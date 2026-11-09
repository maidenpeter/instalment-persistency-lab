-- 09_policy.sql
-- One policy at a time: its instalments, its cash in and out over time, and example policies to look at.

-- Every scheduled instalment with what happened to it, as known at the valuation date.
CREATE OR REPLACE VIEW v_policy_instalments AS
SELECT
    s.policy_id,
    s.instalment_no,
    s.due_date,
    s.amount_due_kes,
    pay.paid_date,
    COALESCE(pay.amount_paid_kes, 0)                                         AS amount_paid_kes,
    pay.days_late,
    CASE
        WHEN s.instalment_no = 0                                             THEN 'Deposit'
        WHEN p.lapse_duration IS NOT NULL AND s.instalment_no > p.lapse_duration THEN 'Not billed after lapse'
        WHEN s.due_date > prm.valuation_date                                 THEN 'Not yet due'
        WHEN pay.paid_date IS NOT NULL AND pay.days_late = 0                 THEN 'On time'
        WHEN pay.paid_date IS NOT NULL AND pay.days_late <= prm.grace_days   THEN 'Late, paid in grace'
        WHEN pay.paid_date IS NOT NULL                                       THEN 'Late, reinstated'
        WHEN p.lapse_duration = s.instalment_no                              THEN 'Unpaid, policy lapsed'
        ELSE 'Due, not yet paid'
    END                                                                      AS outcome
FROM schedule s
JOIN v_policy p USING (policy_id)
LEFT JOIN payments pay USING (policy_id, instalment_no)
CROSS JOIN v_params prm;

-- Premium in and claims out, in date order, with running totals per policy.
CREATE OR REPLACE VIEW v_policy_cashflows AS
WITH flows AS (
    SELECT policy_id, paid_date AS flow_date, 'Premium' AS flow, amount_paid_kes AS amount_kes,
           CASE WHEN instalment_no = 0 THEN 'Deposit' ELSE 'Instalment ' || instalment_no END AS detail
    FROM payments
    WHERE paid_date IS NOT NULL AND amount_paid_kes > 0
    UNION ALL
    SELECT policy_id, paid_date, 'Claim', amount_paid_kes,
           benefit_type || ' claim, treated ' || strftime(service_date, '%d %b %Y')
    FROM claims
)
SELECT
    policy_id, flow_date, flow, amount_kes, detail,
    SUM(CASE WHEN flow = 'Premium' THEN amount_kes ELSE 0 END)
        OVER (PARTITION BY policy_id ORDER BY flow_date, flow DESC ROWS UNBOUNDED PRECEDING) AS premium_to_date_kes,
    SUM(CASE WHEN flow = 'Claim' THEN amount_kes ELSE 0 END)
        OVER (PARTITION BY policy_id ORDER BY flow_date, flow DESC ROWS UNBOUNDED PRECEDING) AS claims_to_date_kes
FROM flows;

-- A few policies worth opening, each picked by a rule rather than by hand.
CREATE OR REPLACE VIEW v_policy_examples AS
SELECT * FROM (
    SELECT 1 AS ord, 'Lapsed after claiming far more than it paid' AS label,
           (SELECT policy_id FROM v_leakage ORDER BY leakage_kes DESC, policy_id LIMIT 1) AS policy_id
    UNION ALL
    SELECT 2, 'Claimed big, then lapsed within weeks',
           (SELECT policy_id FROM v_claim_then_lapse ORDER BY days_claim_to_lapse, claims_paid_kes DESC, policy_id LIMIT 1)
    UNION ALL
    SELECT 3, 'Paid every instalment on time',
           (SELECT p.policy_id FROM v_policy p
            WHERE p.status_at_valuation = 'Paid up' AND p.n_late_payments = 0 AND p.n_claims BETWEEN 3 AND 8
            ORDER BY abs(p.claims_paid_kes - 0.65 * p.collected_kes), p.policy_id LIMIT 1)
    UNION ALL
    SELECT 4, 'Paid late, was suspended, then came back',
           (SELECT i.policy_id FROM v_policy_instalments i JOIN v_policy p USING (policy_id)
            WHERE i.outcome = 'Late, reinstated' AND p.status_at_valuation = 'Paid up'
            ORDER BY i.days_late DESC, i.policy_id LIMIT 1)
    UNION ALL
    SELECT 5, 'In force, last instalment overdue',
           (SELECT policy_id FROM v_call_candidates WHERE prev_outstanding = 1 ORDER BY outstanding_kes DESC, policy_id LIMIT 1)
) ORDER BY ord;
