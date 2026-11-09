-- 06_anti_selection.sql
-- Claims against premium actually collected, stayers versus lapsers, and the cost of
-- "claim then lapse". Uses run-off policies only (cover ended and claims had time to be paid),
-- so every policy in these views has a final outcome.

CREATE OR REPLACE VIEW v_claims_to_collected AS
SELECT
    persistency_group,
    COALESCE(deposit_band, 'All')                      AS deposit_band,
    COUNT(*)                                           AS policies,
    SUM(collected_kes)                                 AS collected_kes,
    SUM(claims_paid_kes)                               AS claims_paid_kes,
    SUM(claims_paid_kes) / SUM(collected_kes)          AS claims_to_collected,
    AVG(collected_kes)                                 AS avg_collected_kes,
    AVG(claims_paid_kes)                               AS avg_claims_kes,
    AVG(CASE WHEN n_claims > 0 THEN 1.0 ELSE 0 END)    AS share_with_claim
FROM v_policy
WHERE is_run_off
GROUP BY GROUPING SETS ((persistency_group, deposit_band), (persistency_group))
ORDER BY persistency_group DESC, deposit_band;

-- Lapsed policies that had a large claim paid before they lapsed: days from the last
-- large claim payment to the lapse date.
CREATE OR REPLACE VIEW v_claim_then_lapse AS
WITH big AS (
    SELECT c.policy_id, c.paid_date, c.amount_paid_kes, c.benefit_type
    FROM claims c CROSS JOIN v_params prm
    WHERE c.amount_paid_kes >= prm.large_claim_kes
)
SELECT
    p.policy_id, p.plan_tier, p.channel, p.income_type, p.deposit_band, p.lapse_duration,
    arg_max(b.benefit_type, b.paid_date)          AS last_large_claim_benefit,
    MAX(b.paid_date)                              AS last_large_claim_paid,
    p.lapse_date,
    datediff('day', MAX(b.paid_date), p.lapse_date) AS days_claim_to_lapse,
    p.claims_paid_kes,
    p.collected_kes
FROM v_policy p JOIN big b ON b.policy_id = p.policy_id AND b.paid_date <= p.lapse_date
WHERE p.is_lapsed AND p.is_run_off
GROUP BY p.policy_id, p.plan_tier, p.channel, p.income_type, p.deposit_band, p.lapse_duration,
         p.lapse_date, p.claims_paid_kes, p.collected_kes;

-- How the next instalment goes, with and without a large claim settled in the window before it.
CREATE OR REPLACE VIEW v_large_claim_next_instalment AS
SELECT
    CASE WHEN large_claim_recent THEN 'Large claim settled in window' ELSE 'No recent large claim' END AS claim_history,
    COUNT(*)                                                       AS instalments,
    AVG(CASE WHEN missed_due_date THEN 1.0 ELSE 0 END)             AS missed_due_date_rate,
    AVG(CASE WHEN outcome = 'Lapsed' THEN 1.0 ELSE 0 END)          AS lapse_rate
FROM v_instalment_outcomes
GROUP BY 1
ORDER BY 1;

-- Leakage: claims paid in excess of premium collected, on policies that lapsed.
CREATE OR REPLACE VIEW v_leakage AS
SELECT
    policy_id, inception_month, plan_tier, channel, income_type, payment_method, deposit_band,
    region, lapse_duration, annual_premium_kes, collected_kes, claims_paid_kes,
    greatest(claims_paid_kes - collected_kes, 0)                  AS leakage_kes,
    claims_paid_kes > collected_kes                               AS is_leaking
FROM v_policy
WHERE is_lapsed AND is_run_off;

-- Periods without cover: from suspension to reinstatement, or from suspension onwards if the policy lapsed.
CREATE OR REPLACE VIEW v_cover_gaps AS
WITH sus AS (
    SELECT policy_id, event_date AS gap_start FROM status_events WHERE event = 'suspended'
), nxt AS (
    SELECT s.policy_id, s.gap_start,
           arg_min(e.event, e.event_date) AS ended_by,
           MIN(e.event_date)              AS ended_on
    FROM sus s
    LEFT JOIN status_events e
      ON e.policy_id = s.policy_id AND e.event IN ('reinstated', 'lapsed') AND e.event_date > s.gap_start
    GROUP BY s.policy_id, s.gap_start
)
SELECT policy_id, gap_start,
       CASE WHEN ended_by = 'reinstated' THEN ended_on END AS gap_end  -- NULL: cover never resumed
FROM nxt;

-- Covered share of each cover month for run-off policies (1 = covered all month).
CREATE OR REPLACE VIEW v_policy_month_cover AS
WITH months AS (
    SELECT CAST(m AS INTEGER) AS cover_month FROM range(1, 13) AS g(m)
), pm AS (
    SELECT p.policy_id, mo.cover_month,
           CAST(p.inception_date + to_months(mo.cover_month - 1) AS DATE) AS month_start,
           CAST(p.inception_date + to_months(mo.cover_month) AS DATE)     AS month_end
    FROM v_policy p CROSS JOIN months mo
    WHERE p.is_run_off
      AND (p.lapse_date IS NULL OR p.lapse_date > p.inception_date + to_months(mo.cover_month - 1))
)
SELECT pm.policy_id, pm.cover_month, pm.month_start, pm.month_end,
       greatest(0.0, 1.0 - SUM(CASE WHEN g.gap_start IS NULL THEN 0 ELSE greatest(0, datediff('day',
               greatest(g.gap_start, pm.month_start),
               least(COALESCE(g.gap_end, DATE '2999-12-31'), pm.month_end))) END)
           / datediff('day', pm.month_start, pm.month_end))                AS covered_fraction
FROM pm
LEFT JOIN v_cover_gaps g
  ON g.policy_id = pm.policy_id AND g.gap_start < pm.month_end
 AND COALESCE(g.gap_end, DATE '2999-12-31') > pm.month_start
GROUP BY pm.policy_id, pm.cover_month, pm.month_start, pm.month_end;

-- Claim experience per exposure unit by benefit, cover month and deposit band (run-off book).
-- Exposure units: outpatient = members with dependants weighted 1.15, inpatient = members,
-- maternity = eligible principals, chronic = members aged 40 and over (principal and spouse),
-- each multiplied by the share of the month the policy was actually on cover.
CREATE OR REPLACE VIEW v_claim_frequency AS
WITH active AS (
    SELECT p.policy_id, p.deposit_band, p.plan_tier, c.cover_month, c.covered_fraction,
           1 + (p.family_size - 1) * 1.15                                              AS units_outpatient,
           CAST(p.family_size AS DOUBLE)                                              AS units_inpatient,
           CASE WHEN p.principal_age BETWEEN 20 AND 42 AND p.family_size >= 2 THEN 1.0 ELSE 0 END AS units_maternity,
           CASE WHEN p.principal_age >= 40 THEN 1.0 + (p.family_size >= 2)::INT ELSE 0 END AS units_chronic
    FROM v_policy_month_cover c JOIN v_policy p USING (policy_id)
), claim_month AS (
    SELECT c.policy_id, c.benefit_type, c.amount_paid_kes,
           datediff('month', p.inception_date, c.service_date)
             + CASE WHEN p.inception_date + to_months(datediff('month', p.inception_date, c.service_date))
                         <= c.service_date THEN 1 ELSE 0 END AS cover_month
    FROM claims c JOIN v_policy p USING (policy_id)
    WHERE p.is_run_off
), units AS (
    SELECT policy_id, deposit_band, plan_tier, cover_month, b.benefit_type,
           covered_fraction * CASE b.benefit_type WHEN 'outpatient' THEN units_outpatient WHEN 'inpatient' THEN units_inpatient
                               WHEN 'maternity' THEN units_maternity ELSE units_chronic END AS units
    FROM active
    CROSS JOIN (VALUES ('outpatient'), ('inpatient'), ('maternity'), ('chronic')) AS b(benefit_type)
)
SELECT
    u.benefit_type, u.cover_month, u.deposit_band, u.plan_tier,
    SUM(u.units)                         AS exposure_units,
    COALESCE(SUM(cm.n_claims), 0)        AS n_claims,
    COALESCE(SUM(cm.claims_kes), 0)      AS claims_kes
FROM units u
LEFT JOIN (
    SELECT policy_id, benefit_type, cover_month, COUNT(*) AS n_claims, SUM(amount_paid_kes) AS claims_kes
    FROM claim_month GROUP BY ALL
) cm USING (policy_id, benefit_type, cover_month)
GROUP BY ALL
ORDER BY u.benefit_type, u.cover_month, u.deposit_band, u.plan_tier;

-- Early outpatient and inpatient claim counts per run-off policy, with the covered exposure units,
-- used to measure overdispersion (some members claim far more than a Poisson count allows).
CREATE OR REPLACE VIEW v_early_claim_counts AS
WITH cm AS (
    SELECT c.policy_id, COUNT(*) AS n_claims
    FROM claims c JOIN v_policy p USING (policy_id)
    WHERE p.is_run_off AND c.benefit_type IN ('outpatient', 'inpatient')
      AND c.service_date < p.inception_date + to_months(3)
    GROUP BY c.policy_id
)
SELECT p.policy_id, p.deposit_band, p.family_size,
       SUM(c.covered_fraction * CASE WHEN c.cover_month = 1 THEN 1 ELSE 0 END) AS covered_m1,
       SUM(c.covered_fraction * CASE WHEN c.cover_month IN (2, 3) THEN 1 ELSE 0 END) AS covered_m23,
       COALESCE(MAX(cm.n_claims), 0) AS n_claims
FROM v_policy p
JOIN v_policy_month_cover c USING (policy_id)
LEFT JOIN cm USING (policy_id)
WHERE c.cover_month <= 3
GROUP BY p.policy_id, p.deposit_band, p.family_size;

-- Early claims (cover months 1 to 3) per policy by deposit band: the anti-selection signal.
CREATE OR REPLACE VIEW v_early_claims_by_deposit AS
SELECT
    deposit_band,
    SUM(CASE WHEN cover_month <= 3 THEN n_claims END)
        / SUM(CASE WHEN cover_month <= 3 THEN exposure_units END)  AS early_freq_per_unit,
    SUM(CASE WHEN cover_month BETWEEN 4 AND 10 THEN n_claims END)
        / SUM(CASE WHEN cover_month BETWEEN 4 AND 10 THEN exposure_units END) AS later_freq_per_unit
FROM v_claim_frequency
WHERE benefit_type IN ('outpatient', 'inpatient')
GROUP BY deposit_band
ORDER BY deposit_band;
