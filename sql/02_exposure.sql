-- 02_exposure.sql
-- Policy-month exposure at the start of each policy duration month.
-- Duration t is the t-th monthly instalment after the deposit (t = 1 to the longest instalment plan).
-- A policy is exposed at t if it has not lapsed at an earlier duration and the outcome of
-- instalment t is known by the valuation date: due date + grace + reinstatement window has passed.
-- Paid-up policies stay in the exposure (in force, with no lapse risk left), so persistency means
-- "still in force", not "still paying".

CREATE OR REPLACE VIEW v_duration_grid AS
SELECT CAST(t AS INTEGER) AS duration
FROM range(1, (SELECT MAX(n_instalments) FROM policies) + 1) AS g(t);

CREATE OR REPLACE VIEW v_exposure_monthly AS
SELECT
    p.policy_id,
    g.duration,
    p.inception_month,
    p.plan_tier,
    p.channel,
    p.income_type,
    p.payment_method,
    p.deposit_band,
    p.deposit_pct,
    p.n_instalments,
    p.age_band,
    p.region,
    1                                                         AS exposed,
    CASE WHEN p.lapse_duration = g.duration THEN 1 ELSE 0 END AS lapsed
FROM v_policy p
CROSS JOIN v_duration_grid g
CROSS JOIN v_params prm
WHERE (p.lapse_duration IS NULL OR p.lapse_duration >= g.duration)
  AND p.inception_date + to_months(g.duration) + to_days(prm.grace_days + prm.reinstatement_days + 1)
      <= prm.valuation_date;

-- Policy-level survival record for Kaplan-Meier and Cox models (same definitions as the exposure).
CREATE OR REPLACE VIEW v_policy_survival AS
SELECT
    p.policy_id, p.inception_month, p.plan_tier, p.channel, p.income_type, p.payment_method,
    p.deposit_band, p.deposit_pct, p.n_instalments, p.age_band, p.principal_age, p.family_size,
    p.region, p.affordability_ratio, p.annual_premium_kes,
    COALESCE(MAX(e.duration), 0)  AS duration_observed,
    COALESCE(MAX(e.lapsed), 0)    AS lapsed
FROM v_policy p
LEFT JOIN v_exposure_monthly e USING (policy_id)
GROUP BY ALL;
