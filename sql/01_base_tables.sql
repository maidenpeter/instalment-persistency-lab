-- 01_base_tables.sql
-- Typed base views over the raw synthetic tables, the parameter row, and one row per policy.

CREATE OR REPLACE VIEW v_params AS
SELECT
    MAX(CASE WHEN key = 'valuation_date' THEN CAST(value AS DATE) END)             AS valuation_date,
    MAX(CASE WHEN key = 'grace_days' THEN CAST(value AS INTEGER) END)              AS grace_days,
    MAX(CASE WHEN key = 'reinstatement_days' THEN CAST(value AS INTEGER) END)      AS reinstatement_days,
    MAX(CASE WHEN key = 'cover_months' THEN CAST(value AS INTEGER) END)            AS cover_months,
    MAX(CASE WHEN key = 'runoff_days' THEN CAST(value AS INTEGER) END)             AS runoff_days,
    MAX(CASE WHEN key = 'large_claim_kes' THEN CAST(value AS DOUBLE) END)          AS large_claim_kes,
    MAX(CASE WHEN key = 'large_claim_window_days' THEN CAST(value AS INTEGER) END) AS large_claim_window_days,
    MAX(CASE WHEN key = 'expense_ratio' THEN CAST(value AS DOUBLE) END)            AS expense_ratio,
    MAX(CASE WHEN key = 'snapshot_days_before_due' THEN CAST(value AS INTEGER) END) AS snapshot_days,
    MAX(CASE WHEN key = 'call_horizon_days' THEN CAST(value AS INTEGER) END)       AS call_horizon_days,
    MAX(CASE WHEN key = 'nairobi_income_uplift' THEN CAST(value AS DOUBLE) END)    AS nairobi_income_uplift
FROM params;

CREATE OR REPLACE VIEW policies AS
SELECT policy_id, CAST(inception_date AS DATE) AS inception_date, plan_tier, annual_premium_kes,
       deposit_pct, n_instalments, channel, payment_method, income_type, region, family_size, principal_age
FROM raw_policies;

CREATE OR REPLACE VIEW schedule AS
SELECT policy_id, instalment_no, CAST(due_date AS DATE) AS due_date, amount_due_kes
FROM raw_schedule;

CREATE OR REPLACE VIEW payments AS
SELECT policy_id, instalment_no, CAST(paid_date AS DATE) AS paid_date, amount_paid_kes, days_late
FROM raw_payments;

CREATE OR REPLACE VIEW status_events AS
SELECT policy_id, CAST(event_date AS DATE) AS event_date, event
FROM raw_status_events;

CREATE OR REPLACE VIEW claims AS
SELECT claim_id, policy_id, CAST(service_date AS DATE) AS service_date, CAST(paid_date AS DATE) AS paid_date,
       benefit_type, amount_paid_kes
FROM raw_claims;

-- One row per policy: segments, premium written and collected, claims, and the lapse outcome.
-- Lapse duration t is the instalment number (1 to 10) that went unpaid and caused the lapse.
CREATE OR REPLACE VIEW v_policy AS
WITH pay AS (
    SELECT policy_id,
           SUM(amount_paid_kes)                                          AS collected_kes,
           MIN(CASE WHEN paid_date IS NULL THEN instalment_no END)       AS first_unpaid_instalment,
           SUM(CASE WHEN days_late > 0 THEN 1 ELSE 0 END)                AS n_late_payments
    FROM payments GROUP BY policy_id
), ev AS (
    SELECT policy_id,
           MIN(CASE WHEN event = 'lapsed' THEN event_date END)    AS lapse_date,
           MIN(CASE WHEN event = 'completed' THEN event_date END) AS completed_date,
           arg_max(event, event_date)                             AS last_event
    FROM status_events GROUP BY policy_id
), clm AS (
    SELECT c.policy_id,
           COUNT(*)                                                         AS n_claims,
           SUM(c.amount_paid_kes)                                           AS claims_paid_kes,
           SUM(CASE WHEN c.amount_paid_kes >= p.large_claim_kes THEN 1 ELSE 0 END) AS n_large_claims
    FROM claims c CROSS JOIN v_params p GROUP BY c.policy_id
), inst AS (
    SELECT policy_id, amount_due_kes AS instalment_kes FROM schedule WHERE instalment_no = 1
)
SELECT
    p.*,
    CAST(date_trunc('month', p.inception_date) AS DATE)                     AS inception_month,
    CASE WHEN p.deposit_pct < 0.125 THEN '10%'
         WHEN p.deposit_pct < 0.175 THEN '15%'
         WHEN p.deposit_pct < 0.275 THEN '20 to 25%'
         ELSE '30 to 40%' END                                                AS deposit_band,
    CASE WHEN p.principal_age < 30 THEN '18-29' WHEN p.principal_age < 40 THEN '30-39'
         WHEN p.principal_age < 50 THEN '40-49' ELSE '50-65' END              AS age_band,
    i.instalment_kes,
    i.instalment_kes / (ip.income_proxy_kes * CASE WHEN p.region = 'Nairobi' THEN prm.nairobi_income_uplift ELSE 1 END)
                                                                             AS affordability_ratio,
    COALESCE(pay.collected_kes, 0)                                           AS collected_kes,
    COALESCE(pay.n_late_payments, 0)                                         AS n_late_payments,
    COALESCE(clm.n_claims, 0)                                                AS n_claims,
    COALESCE(clm.claims_paid_kes, 0)                                         AS claims_paid_kes,
    COALESCE(clm.n_large_claims, 0)                                          AS n_large_claims,
    ev.lapse_date,
    ev.completed_date,
    ev.lapse_date IS NOT NULL                                                AS is_lapsed,
    CASE WHEN ev.lapse_date IS NOT NULL THEN pay.first_unpaid_instalment END AS lapse_duration,
    CASE WHEN ev.lapse_date IS NOT NULL THEN 'Lapsed'
         WHEN ev.completed_date IS NOT NULL THEN 'Paid up'
         WHEN ev.last_event = 'suspended' THEN 'Suspended'
         ELSE 'Paying' END                                                   AS status_at_valuation,
    CASE WHEN ev.lapse_date IS NOT NULL THEN 'Lapser' ELSE 'Stayer' END      AS persistency_group,
    CAST(p.inception_date + to_months(prm.cover_months) AS DATE)             AS cover_end_date,
    (p.inception_date + to_months(prm.cover_months) + to_days(prm.runoff_days)) <= prm.valuation_date
                                                                             AS is_run_off
FROM policies p
CROSS JOIN v_params prm
JOIN inst i USING (policy_id)
JOIN income_proxy ip USING (income_type)
LEFT JOIN pay USING (policy_id)
LEFT JOIN ev USING (policy_id)
LEFT JOIN clm USING (policy_id);
