import pytest

from src.db import build


@pytest.fixture(scope="module")
def con():
    c = build(db_path=None)
    yield c
    c.close()


def one(con, q):
    return con.execute(q).fetchone()


def test_exposure_reconciles_to_policy_counts(con):
    n_pol = one(con, "SELECT COUNT(*) FROM policies")[0]
    # every policy is exposed at duration 1 unless its first instalment outcome is not yet known
    exp1 = one(con, "SELECT SUM(exposed) FROM v_exposure_monthly WHERE duration = 1")[0]
    unobserved = one(con, "SELECT COUNT(*) FROM v_policy_survival WHERE duration_observed = 0")[0]
    assert exp1 + unobserved == n_pol
    # exposure months equal the sum of observed durations
    tot = one(con, "SELECT SUM(exposed) FROM v_exposure_monthly")[0]
    dur = one(con, "SELECT SUM(duration_observed) FROM v_policy_survival")[0]
    assert tot == dur
    # exposure falls by lapses and censoring only: E(t+1) = E(t) - lapses(t) - censored at t
    rows = con.execute(
        """
        SELECT d.duration, d.exposed, d.lapses,
               (SELECT COUNT(*) FROM v_policy_survival s WHERE s.duration_observed = d.duration AND s.lapsed = 0) AS censored
        FROM v_lapse_decrements d ORDER BY d.duration
        """
    ).fetchall()
    for (t, e, l, c), (_, e_next, _, _) in zip(rows, rows[1:]):
        assert e_next == e - l - c, t


def test_lapses_reconcile(con):
    lapses_exposure = one(con, "SELECT SUM(lapsed) FROM v_exposure_monthly")[0]
    lapses_events = one(
        con,
        "SELECT COUNT(*) FROM status_events WHERE event = 'lapsed'",
    )[0]
    assert lapses_exposure == lapses_events


def test_rates_between_0_and_1(con):
    bad = one(
        con,
        """SELECT COUNT(*) FROM v_lapse_decrements
           WHERE q < 0 OR q > 1 OR q_lower_95 < 0 OR q_upper_95 > 1 OR q_lower_95 > q OR q_upper_95 < q
              OR persistency < 0 OR persistency > 1""",
    )[0]
    assert bad == 0
    for view, cols in [
        ("v_cohort_persistency", ["q", "persistency"]),
        ("v_segment_decrements", ["q", "persistency"]),
        ("v_grace_cure_rate", ["cured_in_grace", "reinstated", "lapsed"]),
        ("v_premium_written_vs_collected", ["collected_share_of_written", "collected_share_of_due"]),
    ]:
        cond = " OR ".join(f"{c} < 0 OR {c} > 1" for c in cols)
        assert one(con, f"SELECT COUNT(*) FROM {view} WHERE {cond}")[0] == 0, view


def test_persistency_non_increasing(con):
    p = [r[0] for r in con.execute("SELECT persistency FROM v_lapse_decrements ORDER BY duration").fetchall()]
    assert all(a >= b for a, b in zip(p, p[1:]))


def test_collected_never_exceeds_written(con):
    assert one(con, "SELECT COUNT(*) FROM v_policy WHERE collected_kes > annual_premium_kes + 0.01")[0] == 0
    w, c = one(con, "SELECT SUM(written_kes), SUM(collected_kes) FROM v_premium_written_vs_collected")
    assert c <= w


def test_collected_reconciles_to_payments(con):
    a = one(con, "SELECT SUM(collected_kes) FROM v_policy")[0]
    b = one(con, "SELECT SUM(amount_paid_kes) FROM payments")[0]
    assert abs(a - b) < 0.01


def test_cure_shares_sum_to_one(con):
    bad = one(con, "SELECT COUNT(*) FROM v_grace_cure_rate WHERE abs(cured_in_grace + reinstated + lapsed - 1) > 1e-9")[0]
    assert bad == 0


def test_leakage_non_negative_and_bounded(con):
    neg = one(con, "SELECT COUNT(*) FROM v_leakage WHERE leakage_kes < 0")[0]
    assert neg == 0
    leak, claims = one(con, "SELECT SUM(leakage_kes), SUM(claims_paid_kes) FROM v_leakage")
    assert leak <= claims


def test_claims_reconcile(con):
    a = one(con, "SELECT SUM(claims_paid_kes) FROM v_policy")[0]
    b = one(con, "SELECT SUM(amount_paid_kes) FROM claims")[0]
    assert abs(a - b) < 0.01
    # claim frequency view only counts run-off policies and must match the claims table for them
    f = one(con, "SELECT SUM(claims_kes) FROM v_claim_frequency")[0]
    r = one(con, "SELECT SUM(claims_paid_kes) FROM v_policy WHERE is_run_off")[0]
    assert abs(f - r) < 0.01


def test_features_have_no_future_information(con):
    bad = one(
        con,
        """SELECT COUNT(*) FROM v_model_features
           WHERE snapshot_date >= due_date OR snapshot_date > (SELECT valuation_date FROM v_params)""",
    )[0]
    assert bad == 0
