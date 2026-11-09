import numpy as np
import pandas as pd
import pytest

from src.generate import generate, load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def t(cfg):
    return generate(cfg)


def test_row_counts(t, cfg):
    pol = t["policies"]
    assert len(pol) == cfg["book"]["n_policies"]
    assert pol["policy_id"].is_unique
    expected_sched = int((pol["n_instalments"] + 1).sum())
    assert len(t["schedule"]) == expected_sched
    assert t["claims"]["claim_id"].is_unique
    assert len(t["claims"]) > 1000


def test_deterministic(t, cfg):
    again = generate(cfg)
    for k in t:
        pd.testing.assert_frame_equal(t[k], again[k])


def test_no_negative_amounts(t):
    assert (t["policies"]["annual_premium_kes"] > 0).all()
    assert (t["schedule"]["amount_due_kes"] > 0).all()
    assert (t["payments"]["amount_paid_kes"] >= 0).all()
    assert (t["claims"]["amount_paid_kes"] > 0).all()
    assert (t["payments"]["days_late"].dropna() >= 0).all()


def test_schedule_sums_to_premium(t):
    s = t["schedule"].groupby("policy_id")["amount_due_kes"].sum()
    p = t["policies"].set_index("policy_id")["annual_premium_kes"]
    assert np.allclose(s.loc[p.index], p)


def test_dates_consistent(t, cfg):
    val = pd.Timestamp(cfg["book"]["valuation_date"])
    pol = t["policies"].set_index("policy_id")
    assert (pol["inception_date"] <= val).all()
    c = t["claims"].join(pol["inception_date"], on="policy_id")
    assert (c["service_date"] >= c["inception_date"]).all()
    assert (c["paid_date"] >= c["service_date"]).all()
    assert (c["paid_date"] <= val).all()
    assert (t["status_events"]["event_date"] <= val).all()
    paid = t["payments"].dropna(subset=["paid_date"])
    assert (paid["paid_date"] <= val).all()
    s = t["schedule"].merge(paid, on=["policy_id", "instalment_no"])
    late = (s["paid_date"] - s["due_date"]).dt.days.clip(lower=0)
    assert (late == s["days_late"]).all()


def test_lapse_rule(t, cfg):
    """Lapse happens exactly grace + reinstatement + 1 days after the missed due date."""
    g, r = cfg["product"]["grace_days"], cfg["product"]["reinstatement_days"]
    ev = t["status_events"]
    lapses = ev[ev["event"] == "lapsed"].set_index("policy_id")["event_date"]
    unpaid = t["payments"][t["payments"]["paid_date"].isna()]
    first_unpaid = unpaid.groupby("policy_id")["instalment_no"].min()
    sched = t["schedule"].set_index(["policy_id", "instalment_no"])["due_date"]
    due = pd.to_datetime(sched.loc[list(zip(lapses.index, first_unpaid.loc[lapses.index]))].to_numpy())
    assert ((pd.to_datetime(lapses.to_numpy()) - due) == pd.Timedelta(days=g + r + 1)).all()
    # no payment is ever late beyond the reinstatement window
    assert t["payments"]["days_late"].max() <= g + r


def test_no_claims_after_lapse(t):
    ev = t["status_events"]
    lapses = ev[ev["event"] == "lapsed"].set_index("policy_id")["event_date"]
    c = t["claims"].join(lapses.rename("lapse_date"), on="policy_id")
    assert not (c["service_date"] >= c["lapse_date"]).any()


def test_waiting_periods(t, cfg):
    pol = t["policies"].set_index("policy_id")
    c = t["claims"].join(pol["inception_date"], on="policy_id")
    for b, months in cfg["waiting_months"].items():
        if months == 0:
            continue
        cb = c[c["benefit_type"] == b]
        earliest = cb["inception_date"] + pd.DateOffset(months=months)
        assert (cb["service_date"] >= earliest).all(), b
