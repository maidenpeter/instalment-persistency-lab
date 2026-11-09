-- 07_segments.sql
-- Lapse decrements by segment, long format: one row per dimension, segment and duration.

CREATE OR REPLACE VIEW v_segment_decrements AS
WITH long AS (
    SELECT 'Channel' AS dimension, channel AS segment, duration, exposed, lapsed FROM v_exposure_monthly
    UNION ALL SELECT 'Income type', income_type, duration, exposed, lapsed FROM v_exposure_monthly
    UNION ALL SELECT 'Plan tier', plan_tier, duration, exposed, lapsed FROM v_exposure_monthly
    UNION ALL SELECT 'Deposit band', deposit_band, duration, exposed, lapsed FROM v_exposure_monthly
    UNION ALL SELECT 'Payment method', payment_method, duration, exposed, lapsed FROM v_exposure_monthly
), agg AS (
    SELECT dimension, segment, duration, SUM(exposed) AS exposed, SUM(lapsed) AS lapses
    FROM long GROUP BY ALL
)
SELECT
    dimension, segment, duration, exposed, lapses,
    lapses / exposed AS q,
    exp(SUM(ln(greatest(1 - lapses / exposed, 1e-12)))
        OVER (PARTITION BY dimension, segment ORDER BY duration)) AS persistency
FROM agg
ORDER BY dimension, segment, duration;

-- One row per segment: exposure, lapses, average monthly lapse rate and persistency to month 10.
CREATE OR REPLACE VIEW v_segment_lapse AS
SELECT
    dimension,
    segment,
    SUM(exposed)                                  AS exposure_months,
    SUM(lapses)                                   AS lapses,
    SUM(lapses) / SUM(exposed)                    AS avg_monthly_lapse_rate,
    MIN(persistency)                              AS persistency_to_last_duration,
    MAX(CASE WHEN duration = 10 THEN persistency END) AS persistency_m10
FROM v_segment_decrements
GROUP BY dimension, segment
ORDER BY dimension, persistency_m10;
