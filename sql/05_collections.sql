-- 05_collections.sql
-- Premium written versus collected, and what happens to missed instalments.

-- Written = annual premium on the schedule at inception. Due to date = scheduled instalments
-- already due at the valuation date. Collected = cash received.
CREATE OR REPLACE VIEW v_premium_written_vs_collected AS
WITH due AS (
    SELECT s.policy_id, SUM(s.amount_due_kes) AS due_to_date_kes
    FROM schedule s CROSS JOIN v_params prm
    WHERE s.due_date <= prm.valuation_date
    GROUP BY s.policy_id
)
SELECT
    p.inception_month,
    COUNT(*)                                                   AS policies,
    SUM(p.annual_premium_kes)                                  AS written_kes,
    SUM(d.due_to_date_kes)                                     AS due_to_date_kes,
    SUM(p.collected_kes)                                       AS collected_kes,
    SUM(CASE WHEN p.is_lapsed THEN p.annual_premium_kes - p.collected_kes ELSE 0 END)
                                                               AS never_collected_on_lapses_kes,
    SUM(p.collected_kes) / SUM(p.annual_premium_kes)           AS collected_share_of_written,
    SUM(p.collected_kes) / SUM(d.due_to_date_kes)              AS collected_share_of_due
FROM v_policy p JOIN due d USING (policy_id)
GROUP BY p.inception_month
ORDER BY p.inception_month;

-- Every instalment after the deposit whose outcome is known at the valuation date.
-- Outcome: on time, cured within grace, reinstated during suspension, or lapsed.
CREATE OR REPLACE VIEW v_instalment_outcomes AS
WITH big AS (
    SELECT c.policy_id, c.paid_date
    FROM claims c CROSS JOIN v_params prm
    WHERE c.amount_paid_kes >= prm.large_claim_kes
)
SELECT
    s.policy_id,
    s.instalment_no,
    s.due_date,
    pay.paid_date,
    pay.days_late,
    p.income_type, p.channel, p.payment_method, p.plan_tier, p.deposit_band,
    CASE WHEN pay.paid_date IS NOT NULL AND pay.days_late = 0 THEN 'On time'
         WHEN pay.paid_date IS NOT NULL AND pay.days_late <= prm.grace_days THEN 'Cured in grace'
         WHEN pay.paid_date IS NOT NULL THEN 'Reinstated'
         ELSE 'Lapsed' END                                                  AS outcome,
    (pay.paid_date IS NULL OR pay.days_late > 0)                            AS missed_due_date,
    EXISTS (SELECT 1 FROM big b WHERE b.policy_id = s.policy_id
              AND b.paid_date < s.due_date
              AND b.paid_date >= s.due_date - prm.large_claim_window_days)  AS large_claim_recent
FROM schedule s
JOIN payments pay USING (policy_id, instalment_no)
JOIN v_policy p USING (policy_id)
CROSS JOIN v_params prm
WHERE s.instalment_no >= 1
  AND s.due_date + prm.grace_days + prm.reinstatement_days + 1 <= prm.valuation_date;

-- Share of missed instalments that cure within grace, by income type and overall.
CREATE OR REPLACE VIEW v_grace_cure_rate AS
SELECT
    COALESCE(income_type, 'All')                                            AS income_type,
    COUNT(*)                                                                AS missed_instalments,
    AVG(CASE WHEN outcome = 'Cured in grace' THEN 1.0 ELSE 0 END)           AS cured_in_grace,
    AVG(CASE WHEN outcome = 'Reinstated' THEN 1.0 ELSE 0 END)               AS reinstated,
    AVG(CASE WHEN outcome = 'Lapsed' THEN 1.0 ELSE 0 END)                   AS lapsed
FROM v_instalment_outcomes
WHERE missed_due_date
GROUP BY GROUPING SETS ((income_type), ())
ORDER BY income_type = 'All', income_type;
