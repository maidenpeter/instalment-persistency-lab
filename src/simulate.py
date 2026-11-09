"""Product lever simulation on the fitted models.

Each scenario re-runs a sample of run-off policies through twelve cover months:
  * missed due dates from the fitted discrete-time hazard model (logistic regression),
  * time to pay after a miss from the fitted mixture cure curve (separate curve after a large claim),
  * claim counts from observed frequency per exposure unit by benefit and cover month, with the
    early-month anti-selection loading fitted against deposit size,
  * claim sizes resampled from observed claims by benefit and tier, capped by limits and, if chosen,
    by benefits released in proportion to premium paid.
Common random numbers are used so differences between scenarios are not noise.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from src import models as M

BENEFITS = ["outpatient", "inpatient", "maternity", "chronic"]
MONTH_DAYS = 30.0

SAMPLE_SQL = """
SELECT p.policy_id, p.plan_tier, p.income_type, p.channel, p.payment_method, p.principal_age, p.family_size,
       p.annual_premium_kes, p.deposit_pct, p.n_instalments, p.inception_date,
       p.instalment_kes / p.affordability_ratio                                    AS income_proxy_kes,
       1 + (p.family_size - 1) * 1.15                                              AS units_outpatient,
       CAST(p.family_size AS DOUBLE)                                              AS units_inpatient,
       CASE WHEN p.principal_age BETWEEN 20 AND 42 AND p.family_size >= 2 THEN 1.0 ELSE 0 END AS units_maternity,
       CASE WHEN p.principal_age >= 40 THEN 1.0 + (p.family_size >= 2)::INT ELSE 0 END AS units_chronic
FROM v_policy p
WHERE p.is_run_off
ORDER BY p.policy_id
"""

FREQ_SQL = """
SELECT benefit_type, cover_month, deposit_band,
       SUM(n_claims) AS n_claims, SUM(exposure_units) AS exposure_units
FROM v_claim_frequency
GROUP BY ALL
"""

SEVERITY_SQL = """
SELECT c.benefit_type, p.plan_tier, c.amount_paid_kes
FROM claims c JOIN v_policy p USING (policy_id)
WHERE p.is_run_off
"""

BAND_MID = {"10%": 0.10, "15%": 0.15, "20 to 25%": 0.225, "30 to 40%": 0.35}


@dataclass
class Scenario:
    deposit: float = 0.10
    n_instalments: int = 10
    grace_days: int = 15
    waiting: dict = field(default_factory=lambda: {"outpatient": 0, "inpatient": 1, "maternity": 10, "chronic": 3})
    release: str = "full"  # "full" or "proportional"
    loading: float = 0.0
    use_book_terms: bool = False  # back-test: each policy keeps its own deposit and instalments


@dataclass
class Inputs:
    sample: pd.DataFrame
    miss: M.MissModel
    cure_normal: M.CureCurve
    cure_large: M.CureCurve
    freq: np.ndarray  # [benefit, cover_month 1..12] claims per exposure unit (pooled)
    early_rel: tuple  # (intercept, slope) of early relativity against deposit share
    early_rel_pooled: float
    severity: dict  # (benefit, tier) -> np.ndarray
    limits: dict  # tier -> benefit -> limit
    reinstatement_days: int
    large_claim_kes: float
    expense_ratio: float
    annual_new_business: float
    early_dispersion: float  # gamma frailty variance on early outpatient and inpatient claim counts
    cover_months: int = 12


def build_inputs(q, cfg: dict) -> Inputs:
    """q is a function that runs SQL and returns a DataFrame."""
    sample_all = q(SAMPLE_SQL)
    n = min(cfg["simulator"]["sample_size"], len(sample_all))
    sample = sample_all.sample(n=n, random_state=cfg["seed"]).reset_index(drop=True)

    miss = M.fit_miss_model(q(M.MISS_SQL))
    window = cfg["product"]["grace_days"] + cfg["product"]["reinstatement_days"]
    cd = q(M.CURE_SQL)
    cure_n = M.fit_cure(cd[~cd["large_claim_recent"]], window)
    cure_l = M.fit_cure(cd[cd["large_claim_recent"]], window)

    f = q(FREQ_SQL)
    freq = np.zeros((len(BENEFITS), 12))
    pooled = f.groupby(["benefit_type", "cover_month"])[["n_claims", "exposure_units"]].sum()
    for i, b in enumerate(BENEFITS):
        rates = np.array([
            pooled.loc[(b, m), "n_claims"] / pooled.loc[(b, m), "exposure_units"] if (b, m) in pooled.index and pooled.loc[(b, m), "exposure_units"] > 0 else 0.0
            for m in range(1, 13)
        ])
        # months inside the book's waiting period have no data: borrow the first months with claims
        observed = np.nonzero(rates > 0)[0]
        if observed.size:
            first = observed[0]
            fill = rates[first: first + 3].mean()
            rates[:first] = fill
        freq[i] = rates

    # early (months 1 to 3) relativity by deposit band, outpatient and inpatient, months with cover available in the book
    e = f[(f["benefit_type"].isin(["outpatient", "inpatient"])) & (f["cover_month"].between(2, 3))]
    later = f[(f["benefit_type"].isin(["outpatient", "inpatient"])) & (f["cover_month"].between(6, 10))]
    eb = e.groupby("deposit_band")[["n_claims", "exposure_units"]].sum()
    lb = later.groupby("deposit_band")[["n_claims", "exposure_units"]].sum()
    rel = (eb["n_claims"] / eb["exposure_units"]) / (lb["n_claims"] / lb["exposure_units"])
    x = np.array([BAND_MID[b] for b in rel.index])
    w = eb["exposure_units"].to_numpy()
    slope, intercept = np.polyfit(x, rel.to_numpy(), 1, w=np.sqrt(w))
    pooled_rel = (eb["n_claims"].sum() / eb["exposure_units"].sum()) / (lb["n_claims"].sum() / lb["exposure_units"].sum())

    # overdispersion of early claim counts: Var(N) = mu + phi * mu^2, method of moments
    ec = q("SELECT deposit_band, family_size, covered_m1, covered_m23, n_claims FROM v_early_claim_counts")
    u_op = 1 + (ec["family_size"] - 1) * 1.15
    u_ip = ec["family_size"].astype(float)
    band_rel = ec["deposit_band"].map(lambda b: max(intercept + slope * BAND_MID[b], 0.5) / pooled_rel)
    mu = (freq[0, 0] * u_op * ec["covered_m1"]
          + (freq[0, 1:3].mean() * u_op + freq[1, 1:3].mean() * u_ip) * ec["covered_m23"]) * band_rel
    mu = mu * ec["n_claims"].sum() / mu.sum()
    phi = float(max(((ec["n_claims"] - mu) ** 2 - mu).sum() / (mu ** 2).sum(), 1e-6))

    sev = q(SEVERITY_SQL)
    severity = {(b, t): g["amount_paid_kes"].to_numpy() for (b, t), g in sev.groupby(["benefit_type", "plan_tier"])}
    limits = {t: cfg["tiers"][t]["limits"] for t in cfg["tiers"]}
    nb = q("SELECT COUNT(*) AS n FROM v_policy WHERE inception_month >= "
           "(SELECT MAX(inception_month) FROM v_policy) - INTERVAL 11 MONTH")["n"].iloc[0]
    return Inputs(
        sample=sample, miss=miss, cure_normal=cure_n, cure_large=cure_l, freq=freq,
        early_rel=(float(intercept), float(slope)), early_rel_pooled=float(pooled_rel), severity=severity,
        limits=limits, reinstatement_days=cfg["product"]["reinstatement_days"],
        large_claim_kes=cfg["anti_selection"]["large_claim_kes"], expense_ratio=cfg["product"]["expense_ratio"],
        annual_new_business=float(nb), early_dispersion=phi,
    )


def _overlap(a0, a1, b0, b1):
    return np.clip(np.minimum(a1, b1) - np.maximum(a0, b0), 0, None)


def simulate(inp: Inputs, scn: Scenario, n_runs: int = 2, seed: int = 11) -> dict:
    s = inp.sample
    S = len(s)
    R = inp.reinstatement_days
    G = scn.grace_days
    dep = s["deposit_pct"].to_numpy() if scn.use_book_terms else np.full(S, scn.deposit)
    n_inst = s["n_instalments"].to_numpy() if scn.use_book_terms else np.full(S, scn.n_instalments)
    premium = s["annual_premium_kes"].to_numpy() * (1 + scn.loading)
    deposit = premium * dep
    inst = (premium - deposit) / n_inst
    afford = inst / s["income_proxy_kes"].to_numpy()
    tiers = s["plan_tier"].to_numpy()
    units = np.stack([s[f"units_{b}"].to_numpy() for b in BENEFITS])
    limits = np.stack([np.array([inp.limits[t][b] for t in tiers], dtype=float) for b in BENEFITS])
    inc_month = pd.to_datetime(s["inception_date"]).dt.month.to_numpy()
    a, b_ = inp.early_rel
    early_mult = np.clip(a + b_ * dep, 0.5, None) / inp.early_rel_pooled

    base_X = {
        "deposit_pct": dep, "n_instalments": n_inst.astype(float), "affordability_ratio": afford,
        "principal_age": s["principal_age"].to_numpy(float), "income_type": s["income_type"].to_numpy(),
        "channel": s["channel"].to_numpy(), "payment_method": s["payment_method"].to_numpy(),
    }

    curves, results = [], []
    for run in range(n_runs):
        rng_pay = np.random.default_rng([seed, run, 1])
        rng_clm = np.random.default_rng([seed, run, 2])
        alive = np.ones(S, bool)
        lapse_k = np.zeros(S, int)
        collected = deposit.copy()
        prior_late = np.zeros(S)
        claims_b = np.zeros((len(BENEFITS), S))
        cover = np.ones((S, inp.cover_months + 2))  # cover fraction per month (index = month)
        large_next = np.zeros((S, inp.cover_months + 2), bool)
        persist = []
        U_miss = rng_pay.random((inp.cover_months, S))
        U_pay = rng_pay.random((inp.cover_months, S))
        U_days = rng_pay.random((inp.cover_months, S))
        U_cnt = rng_clm.random((inp.cover_months, len(BENEFITS), S))
        phi = inp.early_dispersion
        frailty = rng_pay.gamma(1 / phi, phi, S)  # some members claim far more early on
        for m in range(1, inp.cover_months + 1):
            claims_before = claims_b.sum(axis=0)  # claims to date, known before this month's due date
            frac = cover[:, m]
            paid_share = collected / premium
            for i, b in enumerate(BENEFITS):
                if m <= scn.waiting[b]:
                    continue
                lam = inp.freq[i, m - 1] * units[i] * frac
                if b in ("outpatient", "inpatient") and m <= 3:
                    lam = lam * early_mult * frailty
                cnt = _poisson_inv(U_cnt[m - 1, i], lam)
                idx = np.repeat(np.arange(S), cnt)
                if idx.size == 0:
                    continue
                amt = np.empty(idx.size)
                for t in np.unique(tiers[idx]):
                    sel = tiers[idx] == t
                    pool = inp.severity.get((b, t))
                    amt[sel] = rng_clm.choice(pool, sel.sum()) if pool is not None and pool.size else 0.0
                per_pol = np.bincount(idx, weights=amt, minlength=S)
                cap = limits[i] if scn.release == "full" else limits[i] * paid_share
                room = np.clip(cap - claims_b[i], 0, None)
                paid = np.minimum(per_pol, room)
                claims_b[i] += paid
                big = np.bincount(idx, weights=(amt >= inp.large_claim_kes).astype(float), minlength=S) > 0
                large_next[big & (paid > 0), m + 1] = True

            k = m
            due = alive & (k <= n_inst)
            if due.any():
                cal = (inc_month + k - 1) % 12 + 1
                X = dict(base_X, instalment_no=np.full(S, float(k)), prior_late_count=np.minimum(prior_late, 3),
                         large_claim_recent=large_next[:, m].astype(float), log_claims_kes=np.log1p(claims_before),
                         is_january=(cal == 1).astype(float), is_december=(cal == 12).astype(float))
                p = 1 / (1 + np.exp(-inp.miss.logit(X)))
                missed = due & (U_miss[m - 1] < p)
                ontime = due & ~missed
                collected[ontime] += inst[ontime]
                pi = np.where(large_next[:, m], inp.cure_large.pi, inp.cure_normal.pi)
                shape = np.where(large_next[:, m], inp.cure_large.shape, inp.cure_normal.shape)
                scale = np.where(large_next[:, m], inp.cure_large.scale, inp.cure_normal.scale)
                days = np.maximum(1, np.ceil(scale * (-np.log(1 - U_days[m - 1])) ** (1 / shape)))
                pays = U_pay[m - 1] < pi
                cured = missed & pays & (days <= G + R)
                lapsed_now = missed & ~cured
                collected[cured] += inst[cured]
                prior_late[cured] += 1
                # cover gap after the due date at the start of month k + 1
                gap_end = np.where(cured, days, 1e9)
                gap_start = np.full(S, float(G))
                for j, (d0, d1) in enumerate([(0, MONTH_DAYS), (MONTH_DAYS, 2 * MONTH_DAYS)]):
                    mo = k + 1 + j
                    if mo <= inp.cover_months:
                        lost = _overlap(gap_start, gap_end, d0, d1) / MONTH_DAYS
                        cover[missed, mo] = np.clip(cover[missed, mo] - lost[missed], 0, 1)
                cover[lapsed_now, min(k + 3, inp.cover_months + 1):] = 0
                alive &= ~lapsed_now
                lapse_k[lapsed_now] = k
            if m <= 10:
                persist.append(alive.mean())

        claims = claims_b.sum(axis=0)
        lapsed = lapse_k > 0
        leak = np.clip(claims - collected, 0, None) * lapsed
        curves.append(persist)
        results.append({
            "collected": collected.sum(), "claims": claims.sum(),
            "collected_lapsed": collected[lapsed].sum(), "claims_lapsed": claims[lapsed].sum(),
            "collected_stay": collected[~lapsed].sum(), "claims_stay": claims[~lapsed].sum(),
            "leakage": leak.sum(), "lapse_rate": lapsed.mean(), "written": premium.sum(),
        })
    r = pd.DataFrame(results).mean()
    S_ = float(S)
    out = {
        "persistency": np.mean(curves, axis=0),
        "claims_to_collected": r["claims"] / r["collected"],
        "ctc_lapsers": r["claims_lapsed"] / max(r["collected_lapsed"], 1),
        "ctc_stayers": r["claims_stay"] / max(r["collected_stay"], 1),
        "collected_per_policy": r["collected"] / S_,
        "claims_per_policy": r["claims"] / S_,
        "leakage_per_policy": r["leakage"] / S_,
        "written_per_policy": r["written"] / S_,
        "lapse_rate": r["lapse_rate"],
    }
    out["margin_per_policy"] = out["collected_per_policy"] * (1 - inp.expense_ratio) - out["claims_per_policy"]
    return out


def _poisson_inv(u: np.ndarray, lam: np.ndarray) -> np.ndarray:
    """Poisson draws by inverse CDF from fixed uniforms (keeps random numbers common across scenarios)."""
    k = np.zeros(u.shape, int)
    p = np.exp(-lam)
    c = p.copy()
    active = u > c
    i = 0
    while active.any() and i < 50:
        i += 1
        p = np.where(active, p * lam / i, p)
        c = np.where(active, c + p, c)
        k = np.where(active, i, k)
        active = active & (u > c)
    return k


def break_even_loading(inp: Inputs, scn: Scenario, n_runs: int = 1) -> float | None:
    """Loading at which premium collected, net of expenses, just covers claims (linear interpolation on a grid)."""
    grid = np.array([-0.3, -0.15, 0.0, 0.15, 0.3, 0.5, 0.75, 1.0])
    margins = np.array([simulate(inp, replace(scn, loading=float(L)), n_runs)["margin_per_policy"] for L in grid])
    for i in range(len(grid) - 1):
        if margins[i] <= 0 <= margins[i + 1] or margins[i] >= 0 >= margins[i + 1]:
            L0, L1, m0, m1 = grid[i], grid[i + 1], margins[i], margins[i + 1]
            return float(L0 - m0 * (L1 - L0) / (m1 - m0))
    return None


def signup_factor(deposit: float, base_deposit: float, elasticity: float) -> float:
    """Relative new business volume: (deposit / base deposit) ^ (-elasticity). An explicit assumption."""
    return float((deposit / base_deposit) ** (-elasticity))


def base_scenario(cfg: dict) -> Scenario:
    """Current product: the configured deposit and instalments, full cover from the first payment, no loading."""
    s = cfg["simulator"]
    return Scenario(deposit=s["base_deposit"], n_instalments=s["base_instalments"],
                    grace_days=cfg["product"]["grace_days"], waiting=dict(cfg["waiting_months"]))


def default_scenario(cfg: dict) -> Scenario:
    """Example redesign the simulator page opens on: 20% deposit, benefits unlock with premium paid."""
    return replace(base_scenario(cfg), deposit=0.20, release="proportional")


def key(scn: Scenario) -> str:
    import json
    from dataclasses import asdict

    return json.dumps(asdict(scn), sort_keys=True)


DEPOSIT_GRID = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]


def deposit_curve(inp: Inputs, scn: Scenario) -> pd.DataFrame:
    """Margin and leakage per policy across deposit sizes, other levers held at the scenario."""
    rows = []
    for d in DEPOSIT_GRID:
        o = simulate(inp, replace(scn, deposit=d), n_runs=1)
        rows.append({"deposit": d, "margin_per_policy": o["margin_per_policy"], "leakage_per_policy": o["leakage_per_policy"]})
    return pd.DataFrame(rows)
