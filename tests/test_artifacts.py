from src import artifacts as A


def test_artifacts_match_current_sources():
    """Precomputed results must be rebuilt (python -m src.artifacts) after any change to data, SQL or model code."""
    art = A.load()
    assert art is not None, "models/artifacts.pkl is missing or stale: run python -m src.artifacts"
    for k in ["cox", "km", "early_warning", "sim_inputs", "sim_cache", "backtest"]:
        assert k in art
