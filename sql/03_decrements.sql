-- 03_decrements.sql
-- Crude monthly lapse decrements by duration: q_t = lapses in month t / exposed at start of t.
-- 95% Wilson score intervals, and persistency to the end of t as the product of (1 - q).

CREATE OR REPLACE VIEW v_lapse_decrements AS
WITH d AS (
    SELECT duration, CAST(SUM(exposed) AS DOUBLE) AS exposed, CAST(SUM(lapsed) AS DOUBLE) AS lapses
    FROM v_exposure_monthly
    GROUP BY duration
), q AS (
    SELECT duration, exposed, lapses, lapses / exposed AS q, CAST(1.96 AS DOUBLE) AS z FROM d
)
SELECT
    duration,
    exposed,
    lapses,
    q,
    (q + z * z / (2 * exposed) - z * sqrt(q * (1 - q) / exposed + z * z / (4 * exposed * exposed)))
        / (1 + z * z / exposed)                                               AS q_lower_95,
    (q + z * z / (2 * exposed) + z * sqrt(q * (1 - q) / exposed + z * z / (4 * exposed * exposed)))
        / (1 + z * z / exposed)                                               AS q_upper_95,
    exp(SUM(ln(greatest(1 - q, 1e-12))) OVER (ORDER BY duration))            AS persistency
FROM q
ORDER BY duration;
