"""Seeded synthetic book for a health cover that activates on the first payment.

Writes five parquet tables to data/: policies, schedule, payments, status_events, claims.
Every strength of effect comes from src/config.yaml. Run: python -m src.generate
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "src" / "config.yaml"
DATA_DIR = ROOT / "data"
TABLES = ["policies", "schedule", "payments", "status_events", "claims"]
BENEFITS = ["outpatient", "inpatient", "maternity", "chronic"]


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _choice(rng, mapping: dict, size: int) -> np.ndarray:
    keys = list(mapping.keys())
    p = np.array(list(mapping.values()), dtype=float)
    return rng.choice(np.array(keys, dtype=object), size=size, p=p / p.sum())


def add_months(dates: np.ndarray, k) -> np.ndarray:
    """Add k months to datetime64[D] dates (days of month are kept, all are 28 or less)."""
    months = dates.astype("datetime64[M]")
    offset = dates - months.astype("datetime64[D]")
    return (months + np.asarray(k).astype("timedelta64[M]")).astype("datetime64[D]") + offset


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def age_band(age: np.ndarray) -> np.ndarray:
    return np.select([age < 30, age < 40, age < 50], ["18-29", "30-39", "40-49"], "50-65")


def generate(cfg: dict | None = None) -> dict[str, pd.DataFrame]:
    cfg = cfg or load_config()
    rng = np.random.default_rng(cfg["seed"])
    book, prod = cfg["book"], cfg["product"]
    mix, miss, cure, anti = cfg["portfolio_mix"], cfg["missed_payment"], cfg["cure"], cfg["anti_selection"]
    n = book["n_policies"]
    grace, reinst = prod["grace_days"], prod["reinstatement_days"]
    valuation = np.datetime64(book["valuation_date"], "D")

    # ---------------------------------------------------------------- policies
    n_months = book["n_inception_months"]
    w = (1 + book["monthly_growth"]) ** np.arange(n_months)
    month_idx = rng.choice(n_months, size=n, p=w / w.sum())
    first = np.datetime64(book["first_inception"], "M")
    inception = (first + month_idx.astype("timedelta64[M]")).astype("datetime64[D]") + rng.integers(0, 28, n).astype(
        "timedelta64[D]"
    )
    order = np.argsort(inception, kind="stable")
    inception = inception[order]

    income_type = _choice(rng, mix["income_type"], n)
    channel = _choice(rng, mix["channel"], n)
    region = _choice(rng, mix["region"], n)
    family_size = _choice(rng, mix["family_size"], n).astype(int)
    age = np.clip(np.round(rng.normal(mix["age_mean"], mix["age_sd"], n)), 18, 65).astype(int)

    tier = np.empty(n, dtype=object)
    payment_method = np.empty(n, dtype=object)
    for it in mix["income_type"]:
        m = income_type == it
        tier[m] = _choice(rng, cfg["tier_mix_by_income"][it], m.sum())
        payment_method[m] = _choice(rng, cfg["payment_method_by_income"][it], m.sum())

    deposit_pct = rng.choice(prod["deposit_options"], size=n, p=np.array(prod["deposit_weights"]) / sum(prod["deposit_weights"]))
    n_inst = rng.choice(prod["instalment_options"], size=n, p=np.array(prod["instalment_weights"]) / sum(prod["instalment_weights"]))

    principal = np.array([cfg["tiers"][t]["principal_rate"] for t in tier], dtype=float)
    dependant = np.array([cfg["tiers"][t]["dependant_rate"] for t in tier], dtype=float)
    age_fac = np.array([cfg["age_premium_factor"][b] for b in age_band(age)])
    premium = np.round((principal * age_fac + dependant * (family_size - 1)) / 10) * 10
    deposit_amt = np.round(premium * deposit_pct)
    inst_amt = np.round((premium - deposit_amt) / n_inst)

    proxy = np.array([cfg["income_proxy_kes"][t] for t in income_type], dtype=float)
    proxy = proxy * np.where(region == "Nairobi", cfg["nairobi_income_uplift"], 1.0)
    true_income = proxy * np.exp(rng.normal(0, cfg["income_noise_sd"], n))
    afford = inst_amt / true_income

    btc_p = anti["buy_to_claim_base"] + anti["buy_to_claim_per_10pct_lower_deposit"] * (0.40 - deposit_pct) / 0.10
    buy_to_claim = rng.random(n) < btc_p

    policy_id = np.array([f"P{i:06d}" for i in range(1, n + 1)])
    policies = pd.DataFrame(
        {
            "policy_id": policy_id,
            "inception_date": inception,
            "plan_tier": tier,
            "annual_premium_kes": premium,
            "deposit_pct": deposit_pct,
            "n_instalments": n_inst,
            "channel": channel,
            "payment_method": payment_method,
            "income_type": income_type,
            "region": region,
            "family_size": family_size,
            "principal_age": age,
        }
    )

    # ---------------------------------------------------------------- schedule
    max_n = int(max(prod["instalment_options"]))
    sched_rows = []
    for k in range(0, max_n + 1):
        has = n_inst >= k
        amt = np.where(k == 0, deposit_amt, inst_amt)
        if k > 0:  # last instalment absorbs rounding so the schedule sums to the annual premium
            last = n_inst == k
            amt = np.where(last, premium - deposit_amt - inst_amt * (n_inst - 1), amt)
        sched_rows.append(
            pd.DataFrame(
                {
                    "policy_id": policy_id[has],
                    "instalment_no": k,
                    "due_date": add_months(inception[has], k),
                    "amount_due_kes": amt[has],
                }
            )
        )
    schedule = pd.concat(sched_rows, ignore_index=True)
    due_mat = np.stack([add_months(inception, k) for k in range(0, max_n + 2)], axis=1)  # due/start dates
    amt_mat = np.zeros((n, max_n + 1))
    for k in range(max_n + 1):
        amt_mat[:, k] = np.where(k == 0, deposit_amt, np.where(n_inst == k, premium - deposit_amt - inst_amt * (n_inst - 1), inst_amt))
        amt_mat[:, k] = np.where(n_inst >= k, amt_mat[:, k], 0)

    # ------------------------------------------------- monthly payment and claim process
    cover_months = prod["cover_months"]
    starts = np.stack([add_months(inception, m) for m in range(0, cover_months + 1)], axis=1)  # start of month m+1
    lapsed = np.zeros(n, bool)
    lapse_date = np.full(n, np.datetime64("NaT", "D"), dtype="datetime64[D]")
    susp_start = np.full((n, max_n + 1), np.datetime64("NaT", "D"), dtype="datetime64[D]")
    susp_end = np.full((n, max_n + 1), np.datetime64("NaT", "D"), dtype="datetime64[D]")
    prior_late = np.zeros(n, int)
    last_large_paid = np.full(n, np.datetime64("NaT", "D"), dtype="datetime64[D]")
    used = {b: np.zeros(n) for b in BENEFITS}

    pay_policy, pay_k, pay_date, pay_amt, pay_late = [], [], [], [], []
    ev_policy, ev_date, ev_event = [policy_id], [inception], [np.full(n, "active", dtype=object)]
    claim_frames = []

    # deposit: paid at inception, which activates cover
    pay_policy.append(policy_id); pay_k.append(np.zeros(n, int)); pay_date.append(inception)
    pay_amt.append(deposit_amt); pay_late.append(np.zeros(n, float))

    cl = cfg["claims"]
    wait = cfg["waiting_months"]
    sev_scale = np.array([cfg["tiers"][t]["severity_scale"] for t in tier])
    limits = {b: np.array([cfg["tiers"][t]["limits"][b] for t in tier], dtype=float) for b in BENEFITS}
    age_mult = np.exp(cl["age_freq_per_10y"] * (age - 35) / 10)
    mat_lo, mat_hi = cl["maternity_age_range"]
    exposure_units = {
        "outpatient": 1 + (family_size - 1) * cl["family_child_freq"],
        "inpatient": family_size.astype(float),
        "maternity": ((age >= mat_lo) & (age <= mat_hi) & (family_size >= 2)).astype(float),
        "chronic": (age >= 40) * (1.0 + (family_size >= 2)),
    }

    for m in range(1, cover_months + 1):
        # --- claims with service dates in cover month m
        m_start, m_end = starts[:, m - 1], starts[:, m]
        days_in = (m_end - m_start).astype(int)
        for b in BENEFITS:
            if m <= wait[b]:
                continue
            lam = cl[b]["freq"] * exposure_units[b] * (age_mult if b != "maternity" else 1.0)
            if b in ("outpatient", "inpatient") and m <= anti["early_months"]:
                lam = lam * np.where(buy_to_claim, anti["early_claim_multiplier"], 1.0)
            cnt = rng.poisson(lam)
            idx = np.repeat(np.arange(n), cnt)
            if idx.size == 0:
                continue
            service = m_start[idx] + (rng.random(idx.size) * days_in[idx]).astype(int).astype("timedelta64[D]")
            covered = ~(lapsed[idx] & (service >= lapse_date[idx]))
            for k in (m - 2, m - 1):  # suspension windows from instalments due just before or in this month
                if k < 1 or k > max_n:
                    continue
                s0, s1 = susp_start[idx, k], susp_end[idx, k]
                inside = ~np.isnat(s0) & (service >= s0) & (np.isnat(s1) | (service < s1))
                covered &= ~inside
            idx, service = idx[covered], service[covered]
            if idx.size == 0:
                continue
            sev = rng.lognormal(np.log(cl[b]["median_kes"]), cl[b]["sigma"], idx.size) * sev_scale[idx]
            sev = np.round(sev)
            # apply annual benefit limits in service-date order
            o = np.lexsort((service, idx))
            idx, service, sev = idx[o], service[o], sev[o]
            cum = pd.Series(sev).groupby(idx).cumsum().to_numpy()
            remaining_before = limits[b][idx] - used[b][idx] - (cum - sev)
            amt = np.clip(np.minimum(sev, remaining_before), 0, None)
            np.add.at(used[b], idx, amt)
            keep = amt > 0
            idx, service, amt = idx[keep], service[keep], amt[keep]
            lag = np.maximum(1, np.round(rng.lognormal(np.log(cl["paid_lag_days_median"][b]), 0.5, idx.size))).astype(int)
            paid = service + lag.astype("timedelta64[D]")
            claim_frames.append(pd.DataFrame({"pidx": idx, "service_date": service, "paid_date": paid, "benefit_type": b, "amount_paid_kes": amt}))
            big = amt >= anti["large_claim_kes"]
            if big.any():
                bi, bp = idx[big], paid[big]
                cur = last_large_paid[bi]
                upd = np.isnat(cur) | (bp > cur)
                last_large_paid[bi[upd]] = bp[upd]

        # --- instalment k = m falls due at the end of cover month m
        k = m
        if k > max_n:
            continue
        due = due_mat[:, k]
        live = (n_inst >= k) & ~lapsed
        if not live.any():
            continue
        due_month = due.astype("datetime64[M]").astype(int) % 12 + 1
        large_recent = ~np.isnat(last_large_paid) & (last_large_paid < due) & (
            last_large_paid >= due - np.timedelta64(anti["large_claim_window_days"], "D")
        )
        btc_now = buy_to_claim & (k >= anti["early_months"])
        logit = (
            miss["base_log_odds"]
            + np.array([miss["income_type"][t] for t in income_type])
            + np.array([miss["channel"][c] for c in channel])
            + np.array([miss["payment_method"][p] for p in payment_method])
            + miss["affordability_per_10pct"] * (afford - 0.05) / 0.10
            + miss["age_per_10y"] * (age - 35) / 10
            + miss["prior_late_each"] * np.minimum(prior_late, 3)
            + miss["duration_slope"] * (k - 1)
            + miss["january"] * (due_month == 1)
            + miss["december"] * (due_month == 12)
            + miss["after_large_claim"] * large_recent
            + miss["buy_to_claim_after_m3"] * btc_now
        )
        missed = live & (rng.random(n) < _sigmoid(logit))
        ontime = live & ~missed

        ever = np.where(btc_now, cure["ever_pay_buy_to_claim"], np.where(large_recent, cure["ever_pay_after_large_claim"], cure["ever_pay_base"]))
        ever = ever + np.where(income_type == "salaried", cure["ever_pay_salaried_uplift"], 0.0)
        pays = rng.random(n) < ever
        days = np.ceil(cure["days_weibull_scale"] * rng.weibull(cure["days_weibull_shape"], n)).astype(int)
        days = np.maximum(days, 1)
        cured = missed & pays & (days <= grace + reinst)
        lapse_now = missed & ~cured

        early = rng.integers(0, 4, n)
        pdates = np.where(ontime, due - early.astype("timedelta64[D]"), due + days.astype("timedelta64[D]"))
        paid_mask = ontime | cured
        pay_policy.append(policy_id[live]); pay_k.append(np.full(live.sum(), k))
        pay_date.append(np.where(paid_mask, pdates, np.datetime64("NaT", "D"))[live])
        pay_amt.append(np.where(paid_mask, amt_mat[:, k], 0.0)[live])
        pay_late.append(np.where(ontime, 0.0, np.where(cured, days, np.nan))[live])

        prior_late += cured.astype(int)
        susp = (cured & (days > grace)) | lapse_now
        susp_start[susp, k] = due[susp] + np.timedelta64(grace + 1, "D")
        reinstated = cured & (days > grace)
        susp_end[reinstated, k] = pdates[reinstated]
        lapse_d = due + np.timedelta64(grace + reinst + 1, "D")
        lapse_date[lapse_now] = lapse_d[lapse_now]
        lapsed |= lapse_now

        ev_policy += [policy_id[susp], policy_id[reinstated], policy_id[lapse_now]]
        ev_date += [susp_start[susp, k], pdates[reinstated], lapse_d[lapse_now]]
        ev_event += [np.full(susp.sum(), "suspended", dtype=object), np.full(reinstated.sum(), "reinstated", dtype=object),
                     np.full(lapse_now.sum(), "lapsed", dtype=object)]
        done = paid_mask & (n_inst == k)
        ev_policy.append(policy_id[done]); ev_date.append(pdates[done]); ev_event.append(np.full(done.sum(), "completed", dtype=object))

    payments = pd.DataFrame(
        {
            "policy_id": np.concatenate(pay_policy),
            "instalment_no": np.concatenate(pay_k).astype(int),
            "paid_date": np.concatenate(pay_date).astype("datetime64[D]"),
            "amount_paid_kes": np.concatenate(pay_amt),
            "days_late": np.concatenate(pay_late),
        }
    )
    status_events = pd.DataFrame(
        {"policy_id": np.concatenate(ev_policy), "event_date": np.concatenate(ev_date).astype("datetime64[D]"), "event": np.concatenate(ev_event)}
    )
    claims = pd.concat(claim_frames, ignore_index=True)
    claims["policy_id"] = policy_id[claims.pop("pidx").to_numpy()]

    # ------------------------------------------------- observe only what is known at the valuation date
    pay_due = payments.merge(schedule[["policy_id", "instalment_no", "due_date"]], on=["policy_id", "instalment_no"])
    payments = pay_due[pay_due["due_date"] <= valuation].copy()
    unknown = payments["paid_date"].isna() | (payments["paid_date"] > valuation)
    payments.loc[unknown, ["paid_date", "days_late"]] = [pd.NaT, np.nan]
    payments.loc[unknown, "amount_paid_kes"] = 0.0
    payments = payments.drop(columns="due_date")
    status_events = status_events[status_events["event_date"] <= valuation]
    claims = claims[claims["paid_date"] <= valuation]

    payments = payments.sort_values(["policy_id", "instalment_no"]).reset_index(drop=True)
    ev_rank = {"active": 0, "suspended": 1, "reinstated": 2, "lapsed": 3, "completed": 4}
    status_events = (
        status_events.assign(_r=status_events["event"].map(ev_rank))
        .sort_values(["policy_id", "event_date", "_r"])
        .drop(columns="_r")
        .reset_index(drop=True)
    )
    claims = claims.sort_values(["service_date", "policy_id"]).reset_index(drop=True)
    claims.insert(0, "claim_id", [f"C{i:07d}" for i in range(1, len(claims) + 1)])
    claims = claims[["claim_id", "policy_id", "service_date", "paid_date", "benefit_type", "amount_paid_kes"]]

    for df in (policies, schedule, payments, status_events, claims):
        for c in df.columns:
            if c.endswith("_date"):
                df[c] = pd.to_datetime(df[c]).astype("datetime64[ms]")
    return {"policies": policies, "schedule": schedule, "payments": payments, "status_events": status_events, "claims": claims}


def write(tables: dict[str, pd.DataFrame], out_dir: Path = DATA_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out_dir / f"{name}.parquet", index=False)


def ensure_data(out_dir: Path = DATA_DIR) -> None:
    if not all((out_dir / f"{t}.parquet").exists() for t in TABLES):
        write(generate(), out_dir)


if __name__ == "__main__":
    t = generate()
    write(t)
    for k, v in t.items():
        print(f"{k:14s} {len(v):>8,d} rows")
