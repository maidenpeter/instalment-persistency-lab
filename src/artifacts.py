"""Precomputed model results, so every page loads quickly.

`python -m src.artifacts` fits every model once and saves the results to models/artifacts.pkl.
The file carries a fingerprint of the config, data, SQL and model code. If anything changes,
the fingerprint no longer matches and the app fits the models live instead, so results are
never stale. tests/test_artifacts.py fails until the file is rebuilt.
"""
from __future__ import annotations

import hashlib
import pickle
from dataclasses import asdict, replace
from pathlib import Path

from src import models as M
from src import simulate as SM
from src.generate import ROOT, load_config

ARTIFACT_PATH = ROOT / "models" / "artifacts.pkl"
FINGERPRINT_FILES = ["src/config.yaml", "src/generate.py", "src/db.py", "src/models.py", "src/simulate.py"]


def source_paths() -> list[Path]:
    """Config, data, SQL and model code: everything the saved results depend on."""
    return [ROOT / f for f in FINGERPRINT_FILES] + sorted((ROOT / "sql").glob("*.sql")) + sorted((ROOT / "data").glob("*.parquet"))


def source_stamp() -> tuple:
    """Cheap change check on the source files (name, size, modified time), for cache invalidation."""
    return tuple((p.name, s.st_size, s.st_mtime_ns) for p in source_paths() for s in [p.stat()])


def fingerprint() -> str:
    h = hashlib.sha256()
    for p in source_paths():
        data = p.read_bytes()
        if p.suffix != ".parquet":
            data = data.replace(b"\r\n", b"\n")  # same hash on Windows and Linux checkouts
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(data)
    return h.hexdigest()


def build(q, cfg: dict | None = None) -> dict:
    """q runs SQL and returns a DataFrame."""
    cfg = cfg or load_config()
    surv = q(M.SURVIVAL_SQL)
    cox = M.fit_cox(surv)
    cox = replace(cox, model=None)  # keep the tables, not the fitted object
    km = M.km_python_table(surv)
    ew = M.fit_early_warning(q(M.FEATURES_SQL), cfg)

    inp = SM.build_inputs(q, cfg)
    base, default = SM.base_scenario(cfg), SM.default_scenario(cfg)
    n_runs = cfg["simulator"]["n_runs"]
    sim = {}
    for scn in (base, default):
        sim[("run", SM.key(scn), n_runs)] = SM.simulate(inp, scn, n_runs=n_runs)
        sim[("breakeven", SM.key(replace(scn, loading=0.0)))] = SM.break_even_loading(inp, replace(scn, loading=0.0), n_runs=1)
    sim[("deposit_curve", SM.key(replace(default, deposit=base.deposit)))] = SM.deposit_curve(inp, replace(default, deposit=base.deposit))
    backtest = SM.simulate(inp, SM.Scenario(use_book_terms=True, grace_days=cfg["product"]["grace_days"],
                                            waiting=dict(cfg["waiting_months"])), n_runs=3)
    return {"fingerprint": fingerprint(), "cox": cox, "km": km, "early_warning": ew, "sim_inputs": inp,
            "sim_cache": sim, "backtest": backtest}


def save(art: dict, path: Path = ARTIFACT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(art, f, protocol=pickle.HIGHEST_PROTOCOL)


def load(path: Path = ARTIFACT_PATH) -> dict | None:
    """Return the saved results if they match the current sources, else None."""
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            art = pickle.load(f)
    except Exception:
        return None
    return art if art.get("fingerprint") == fingerprint() else None


if __name__ == "__main__":
    import time

    from src.db import build as build_db

    t = time.time()
    con = build_db(db_path=None)
    art = build(lambda s: con.execute(s).df())
    save(art)
    print(f"saved {ARTIFACT_PATH.relative_to(ROOT)} ({ARTIFACT_PATH.stat().st_size / 1e6:.1f} MB) in {time.time() - t:.0f}s")
    print("scenario keys:", [k[0] for k in art["sim_cache"]])
    print(asdict(SM.default_scenario(load_config())))
