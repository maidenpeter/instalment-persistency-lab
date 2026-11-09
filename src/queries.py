"""SQL templates for filtered versions of the headline views. Filters are bound as parameters."""
from __future__ import annotations

FILTER_COLUMNS = {
    "Channel": "channel",
    "Income type": "income_type",
    "Plan tier": "plan_tier",
    "Deposit band": "deposit_band",
}

DECREMENTS = """
WITH d AS (
    SELECT duration, CAST(SUM(exposed) AS DOUBLE) AS exposed, CAST(SUM(lapsed) AS DOUBLE) AS lapses
    FROM v_exposure_monthly
    WHERE {where}
    GROUP BY duration
), q AS (
    SELECT duration, exposed, lapses, lapses / exposed AS q, CAST(1.96 AS DOUBLE) AS z FROM d
)
SELECT
    duration,
    exposed,
    lapses,
    q,
    (q + z*z/(2*exposed) - z*sqrt(q*(1-q)/exposed + z*z/(4*exposed*exposed))) / (1 + z*z/exposed) AS q_lower_95,
    (q + z*z/(2*exposed) + z*sqrt(q*(1-q)/exposed + z*z/(4*exposed*exposed))) / (1 + z*z/exposed) AS q_upper_95,
    exp(SUM(ln(greatest(1 - q, 1e-12))) OVER (ORDER BY duration)) AS persistency
FROM q
ORDER BY duration
"""

COHORTS = """
WITH c AS (
    SELECT inception_month, duration, CAST(SUM(exposed) AS DOUBLE) AS exposed, CAST(SUM(lapsed) AS DOUBLE) AS lapses
    FROM v_exposure_monthly
    WHERE {where}
    GROUP BY inception_month, duration
)
SELECT
    inception_month,
    duration,
    exposed,
    lapses,
    exp(SUM(ln(greatest(1 - lapses / exposed, 1e-12)))
        OVER (PARTITION BY inception_month ORDER BY duration)) AS persistency
FROM c
ORDER BY inception_month, duration
"""

SURVIVAL = """
SELECT policy_id, duration_observed, lapsed, {group_col} AS grp
FROM v_policy_survival
WHERE {where} AND duration_observed > 0
"""


def where_clause(filters: dict[str, list], all_values: dict[str, list], cohort_range=None) -> tuple[str, tuple]:
    parts, params = [], []
    for label, col in FILTER_COLUMNS.items():
        sel = filters.get(label) or []
        if sel and set(sel) != set(all_values[label]):
            parts.append(f"{col} IN ({', '.join('?' for _ in sel)})")
            params.extend(sel)
    if cohort_range is not None:
        parts.append("inception_month BETWEEN ? AND ?")
        params.extend([cohort_range[0], cohort_range[1]])
    return (" AND ".join(parts) or "TRUE"), tuple(params)


def inline(sql: str, params: tuple) -> str:
    """Show the query with its parameters filled in, for the 'See the SQL' expander."""
    out = sql
    for p in params:
        out = out.replace("?", f"'{p}'", 1)
    return out
