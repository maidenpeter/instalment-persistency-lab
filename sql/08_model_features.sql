-- 08_model_features.sql
-- Person-period features for the early warning model: one row per policy and instalment.
-- Every feature is taken at a snapshot date before the due date (due date minus the snapshot
-- days, and never after the valuation date), so nothing from the future leaks in.
-- Targets: missed_due (not paid by the due date) and missed_grace (not paid within grace).

CREATE OR REPLACE VIEW v_model_features AS
WITH base AS (
    SELECT
        s.policy_id, s.instalment_no, s.due_date, s.amount_due_kes,
        least(s.due_date - prm.snapshot_days, prm.valuation_date) AS snapshot_date,
        prm.valuation_date, prm.grace_days, prm.large_claim_kes, prm.large_claim_window_days,
        prm.call_horizon_days
    FROM schedule s
    JOIN v_policy p USING (policy_id)
    CROSS JOIN v_params prm
    WHERE s.instalment_no >= 1
      AND (p.lapse_duration IS NULL OR s.instalment_no <= p.lapse_duration)
      AND s.due_date <= prm.valuation_date + prm.call_horizon_days
), hist AS (
    SELECT
        b.policy_id, b.instalment_no,
        SUM(CASE WHEN pr.instalment_no < b.instalment_no AND pr.paid_date < b.snapshot_date
                  AND pr.days_late > 0 THEN 1 ELSE 0 END)                         AS prior_late_count,
        MAX(CASE WHEN pr.instalment_no = b.instalment_no - 1 AND pr.paid_date < b.snapshot_date
                 THEN pr.days_late END)                                           AS prev_days_late,
        MAX(CASE WHEN pr.instalment_no = b.instalment_no - 1
                  AND (pr.paid_date IS NULL OR pr.paid_date >= b.snapshot_date) THEN 1 ELSE 0 END)
                                                                                  AS prev_outstanding,
        SUM(CASE WHEN pr.paid_date < b.snapshot_date THEN pr.amount_paid_kes ELSE 0 END) AS collected_to_snapshot
    FROM base b JOIN payments pr ON pr.policy_id = b.policy_id AND pr.instalment_no < b.instalment_no
    GROUP BY b.policy_id, b.instalment_no
), clm AS (
    SELECT
        b.policy_id, b.instalment_no,
        COUNT(c.claim_id)                                                         AS claims_to_snapshot,
        COALESCE(SUM(c.amount_paid_kes), 0)                                       AS claims_kes_to_snapshot,
        MAX(CASE WHEN c.amount_paid_kes >= b.large_claim_kes
                  AND c.paid_date >= b.due_date - b.large_claim_window_days THEN 1 ELSE 0 END) AS large_claim_recent
    FROM base b LEFT JOIN claims c ON c.policy_id = b.policy_id AND c.paid_date < b.snapshot_date
    GROUP BY b.policy_id, b.instalment_no
)
SELECT
    b.policy_id, b.instalment_no, b.due_date, b.snapshot_date, b.amount_due_kes,
    p.inception_month, p.plan_tier, p.channel, p.income_type, p.payment_method, p.region,
    p.deposit_pct, p.n_instalments, p.principal_age, p.family_size, p.affordability_ratio,
    p.annual_premium_kes,
    month(b.due_date)                                   AS due_month,
    COALESCE(h.prior_late_count, 0)                     AS prior_late_count,
    COALESCE(h.prev_days_late, 0)                       AS prev_days_late,
    COALESCE(h.prev_outstanding, 0)                     AS prev_outstanding,
    COALESCE(h.collected_to_snapshot, 0) / p.annual_premium_kes AS paid_share_to_snapshot,
    COALESCE(c.claims_to_snapshot, 0)                   AS claims_to_snapshot,
    COALESCE(c.claims_kes_to_snapshot, 0)               AS claims_kes_to_snapshot,
    COALESCE(c.large_claim_recent, 0)                   AS large_claim_recent,
    pay.paid_date,
    pay.days_late,
    -- outcomes, only where they are known at the valuation date
    CASE WHEN b.due_date + 1 <= b.valuation_date
         THEN CAST(pay.paid_date IS NULL OR pay.paid_date > b.due_date AS INTEGER) END        AS missed_due,
    CASE WHEN b.due_date + b.grace_days + 1 <= b.valuation_date
         THEN CAST(pay.paid_date IS NULL OR pay.days_late > b.grace_days AS INTEGER) END     AS missed_grace,
    b.due_date > b.valuation_date                       AS is_future
FROM base b
JOIN v_policy p USING (policy_id)
LEFT JOIN hist h USING (policy_id, instalment_no)
LEFT JOIN clm c USING (policy_id, instalment_no)
LEFT JOIN payments pay USING (policy_id, instalment_no);

-- In-force members with an instalment falling due in the call horizon after the valuation date.
CREATE OR REPLACE VIEW v_call_candidates AS
WITH remaining AS (
    SELECT s.policy_id, SUM(s.amount_due_kes) AS outstanding_kes
    FROM schedule s CROSS JOIN v_params prm
    WHERE s.due_date > prm.valuation_date
    GROUP BY s.policy_id
)
SELECT f.*, r.outstanding_kes, p.status_at_valuation
FROM v_model_features f
JOIN v_policy p USING (policy_id)
JOIN remaining r USING (policy_id)
WHERE f.is_future AND NOT p.is_lapsed;
