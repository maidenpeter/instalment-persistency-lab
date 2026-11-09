-- 04_cohorts.sql
-- Persistency by inception month and duration, heatmap ready.
-- Within a cohort, persistency to t is the product of (1 - q) up to t, so partly observed
-- cohorts are handled the same way as the decrement table.

CREATE OR REPLACE VIEW v_cohort_persistency AS
WITH c AS (
    SELECT inception_month, duration, CAST(SUM(exposed) AS DOUBLE) AS exposed, CAST(SUM(lapsed) AS DOUBLE) AS lapses
    FROM v_exposure_monthly
    GROUP BY inception_month, duration
), sizes AS (
    SELECT inception_month, COUNT(*) AS cohort_policies FROM v_policy GROUP BY inception_month
)
SELECT
    c.inception_month,
    s.cohort_policies,
    c.duration,
    c.exposed,
    c.lapses,
    c.lapses / c.exposed AS q,
    exp(SUM(ln(greatest(1 - c.lapses / c.exposed, 1e-12)))
        OVER (PARTITION BY c.inception_month ORDER BY c.duration)) AS persistency
FROM c JOIN sizes s USING (inception_month)
ORDER BY c.inception_month, c.duration;
