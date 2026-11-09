"""Builds the DuckDB database from parquet and runs sql/ in order.

All business metrics are views defined in sql/. Python only loads raw tables and parameters.
"""
from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

from src.generate import DATA_DIR, ROOT, TABLES, ensure_data, load_config

SQL_DIR = ROOT / "sql"
DB_PATH = DATA_DIR / "lab.duckdb"


def sql_files() -> list[Path]:
    return sorted(SQL_DIR.glob("*.sql"))


def _params(cfg: dict) -> pd.DataFrame:
    rows = {
        "valuation_date": cfg["book"]["valuation_date"],
        "grace_days": cfg["product"]["grace_days"],
        "reinstatement_days": cfg["product"]["reinstatement_days"],
        "cover_months": cfg["product"]["cover_months"],
        "runoff_days": cfg["book"]["runoff_days"],
        "large_claim_kes": cfg["anti_selection"]["large_claim_kes"],
        "large_claim_window_days": cfg["anti_selection"]["large_claim_window_days"],
        "expense_ratio": cfg["product"]["expense_ratio"],
        "snapshot_days_before_due": cfg["model"]["snapshot_days_before_due"],
        "call_horizon_days": cfg["model"]["call_horizon_days"],
        "nairobi_income_uplift": cfg["nairobi_income_uplift"],
    }
    return pd.DataFrame({"key": list(rows), "value": [str(v) for v in rows.values()]})


def build(db_path: Path | None = DB_PATH, cfg: dict | None = None) -> duckdb.DuckDBPyConnection:
    """Create (or rebuild) the database. Pass db_path=None for an in-memory database."""
    cfg = cfg or load_config()
    ensure_data()
    if db_path is not None and Path(db_path).exists():
        Path(db_path).unlink()
    con = duckdb.connect(str(db_path) if db_path else ":memory:")
    for t in TABLES:
        p = (DATA_DIR / f"{t}.parquet").as_posix()
        con.execute(f"CREATE TABLE raw_{t} AS SELECT * FROM read_parquet('{p}')")
    con.register("params_df", _params(cfg))
    con.execute("CREATE TABLE params AS SELECT * FROM params_df")
    proxy = pd.DataFrame({"income_type": list(cfg["income_proxy_kes"]), "income_proxy_kes": list(cfg["income_proxy_kes"].values())})
    con.register("proxy_df", proxy)
    con.execute("CREATE TABLE income_proxy AS SELECT * FROM proxy_df")
    for f in sql_files():
        con.execute(f.read_text(encoding="utf-8"))
    return con


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        build().close()
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def view_sql(name: str) -> str:
    """Return the CREATE VIEW statement for a view, as written in sql/."""
    pat = re.compile(rf"CREATE OR REPLACE VIEW {re.escape(name)}\b.*?;", re.S | re.I)
    for f in sql_files():
        m = pat.search(f.read_text(encoding="utf-8"))
        if m:
            return f"-- {f.name}\n{m.group(0)}"
    return f"-- view {name} not found"


if __name__ == "__main__":
    c = build()
    print(c.execute("SELECT table_name, table_type FROM information_schema.tables ORDER BY 1").df().to_string())
