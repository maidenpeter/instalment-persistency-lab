from src import artifacts as A


def test_artifacts_match_current_sources():
    """Precomputed results must be rebuilt (python -m src.artifacts) after any change to data, SQL or model code."""
    art = A.load()
    assert art is not None, "models/artifacts.pkl is missing or stale: run python -m src.artifacts"
    for k in ["cox", "km", "early_warning", "sim_inputs", "sim_cache", "backtest"]:
        assert k in art


def test_caches_clear_when_sources_change(monkeypatch):
    """A redeploy with new data must not keep serving results cached from the old files."""
    import streamlit as st

    from src import ui

    st.cache_resource.clear()
    calls = []

    @st.cache_data
    def cached():
        calls.append(1)
        return len(calls)

    monkeypatch.setattr(A, "source_stamp", lambda: ("old",))
    ui._refresh_if_sources_changed()
    cached()
    ui._refresh_if_sources_changed()
    assert cached() == 1, "unchanged sources should keep the cache"

    monkeypatch.setattr(A, "source_stamp", lambda: ("new",))
    ui._refresh_if_sources_changed()
    assert cached() == 2, "changed sources should clear the cache"
