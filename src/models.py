"""Survival models, early warning classifiers and the fitted pieces used by the simulator.

Data comes from SQL views. Python fits models only; business metrics stay in SQL.
Run `python -m src.models export` to write the CSV used by the R cross-check.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter, KaplanMeierFitter
from lifelines.statistics import proportional_hazard_test
from scipy.optimize import minimize
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from src.generate import ROOT, load_config

R_DIR = ROOT / "r"

# ---------------------------------------------------------------- survival

SURVIVAL_SQL = """
SELECT policy_id, duration_observed AS duration, lapsed, income_type, channel, payment_method, plan_tier,
       deposit_pct, n_instalments, affordability_ratio, principal_age, family_size
FROM v_policy_survival
WHERE duration_observed > 0
"""

REFERENCE = {"income_type": "salaried", "channel": "online", "payment_method": "M-Pesa STK", "plan_tier": "Starter"}


def km_table(df: pd.DataFrame, group: str | None = None) -> pd.DataFrame:
    """Kaplan-Meier persistency with 95% CIs, by group if given."""
    out = []
    groups = [(None, df)] if group is None else df.groupby(group)
    for g, d in groups:
        kmf = KaplanMeierFitter().fit(d["duration"], d["lapsed"])
        sf = kmf.survival_function_.join(kmf.confidence_interval_)
        sf.columns = ["persistency", "lower_95", "upper_95"]
        sf = sf.reset_index().rename(columns={"timeline": "duration"})
        sf["group"] = "All" if g is None else g
        sf["n"] = len(d)
        out.append(sf)
    return pd.concat(out, ignore_index=True)


def km_python_table(df: pd.DataFrame) -> pd.DataFrame:
    """Kaplan-Meier overall and by income type, in the layout the R script writes."""
    km = pd.concat([km_table(df, None), km_table(df, "income_type")], ignore_index=True)
    return km[km["duration"] > 0][["group", "duration", "persistency", "lower_95", "upper_95"]].reset_index(drop=True)


def cox_design(df: pd.DataFrame) -> pd.DataFrame:
    """Design matrix for the Cox model: dummies against reference levels, scaled numerics."""
    X = pd.DataFrame({"duration": df["duration"], "lapsed": df["lapsed"]})
    for col, ref in REFERENCE.items():
        for lvl in sorted(df[col].unique()):
            if lvl != ref:
                X[f"{col}={lvl}"] = (df[col] == lvl).astype(float)
    X["deposit_per_10pts"] = df["deposit_pct"] * 10
    X["n_instalments"] = df["n_instalments"].astype(float)
    X["affordability_per_10pts"] = df["affordability_ratio"] * 10
    X["age_per_10y"] = df["principal_age"] / 10
    X["family_size"] = df["family_size"].astype(float)
    return X


@dataclass
class CoxResult:
    summary: pd.DataFrame
    ph_test: pd.DataFrame
    concordance: float
    model: CoxPHFitter = field(repr=False)


def fit_cox(df: pd.DataFrame) -> CoxResult:
    X = cox_design(df)
    cph = CoxPHFitter()  # Efron tie handling, the same default as R survival::coxph
    cph.fit(X, duration_col="duration", event_col="lapsed")
    s = cph.summary[["coef", "exp(coef)", "exp(coef) lower 95%", "exp(coef) upper 95%", "p"]].copy()
    s.columns = ["coef", "hazard_ratio", "hr_lower_95", "hr_upper_95", "p_value"]
    ph = proportional_hazard_test(cph, X, time_transform="rank").summary[["test_statistic", "p"]]
    ph.columns = ["chi_square", "p_value"]
    return CoxResult(s, ph, cph.concordance_index_, cph)


# ---------------------------------------------------------------- early warning classifier

FEATURES_SQL = """
SELECT * FROM v_model_features WHERE missed_grace IS NOT NULL OR is_future
"""
NUMERIC = [
    "instalment_no", "deposit_pct", "n_instalments", "principal_age", "family_size", "affordability_ratio",
    "prior_late_count", "prev_days_late", "prev_outstanding", "paid_share_to_snapshot", "claims_to_snapshot",
    "log_claims_kes", "large_claim_recent", "is_january", "is_december",
]
CATEGORICAL = ["plan_tier", "channel", "income_type", "payment_method"]


def prep_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["log_claims_kes"] = np.log1p(df["claims_kes_to_snapshot"])
    df["is_january"] = (df["due_month"] == 1).astype(int)
    df["is_december"] = (df["due_month"] == 12).astype(int)
    return df


def _logit_pipeline() -> Pipeline:
    pre = ColumnTransformer([("num", StandardScaler(), NUMERIC), ("cat", OneHotEncoder(drop="first"), CATEGORICAL)])
    return Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=2000, C=1.0))])


def _gbm_pipeline() -> Pipeline:
    pre = ColumnTransformer(
        [("num", "passthrough", NUMERIC), ("cat", OrdinalEncoder(), CATEGORICAL)], verbose_feature_names_out=False
    )
    cat_mask = [False] * len(NUMERIC) + [True] * len(CATEGORICAL)
    clf = HistGradientBoostingClassifier(
        max_iter=250, learning_rate=0.06, max_leaf_nodes=24, min_samples_leaf=80,
        l2_regularization=1.0, categorical_features=cat_mask, random_state=7,
    )
    return Pipeline([("pre", pre), ("clf", clf)])


def calibration_table(y, p, bins: int = 10) -> pd.DataFrame:
    d = pd.DataFrame({"y": y, "p": p})
    d["bin"] = pd.qcut(d["p"].rank(method="first"), bins, labels=False)
    return d.groupby("bin").agg(mean_predicted=("p", "mean"), observed=("y", "mean"), n=("y", "size")).reset_index()


def lift_table(y, p) -> pd.DataFrame:
    d = pd.DataFrame({"y": y, "p": p})
    d["decile"] = 10 - pd.qcut(d["p"].rank(method="first"), 10, labels=False)  # 1 = highest risk
    base = d["y"].mean()
    t = d.groupby("decile").agg(members=("y", "size"), observed_rate=("y", "mean"), mean_score=("p", "mean")).reset_index()
    t["lift"] = t["observed_rate"] / base
    t["cumulative_capture"] = t.sort_values("decile")["observed_rate"].mul(t["members"]).cumsum() / (base * len(d))
    return t


@dataclass
class EarlyWarning:
    chosen: str
    reason: str
    metrics: pd.DataFrame
    calibration: dict
    lift: dict
    train_rows: int
    test_rows: int
    cutoff: str
    model: Pipeline = field(repr=False)
    coefs: pd.DataFrame | None = None


def fit_early_warning(feat: pd.DataFrame, cfg: dict | None = None) -> EarlyWarning:
    cfg = cfg or load_config()
    cutoff = pd.Timestamp(cfg["model"]["train_cutoff_inception"])
    feat = prep_features(feat)
    known = feat[feat["missed_grace"].notna()]
    train = known[pd.to_datetime(known["inception_month"]) < cutoff]
    test = known[pd.to_datetime(known["inception_month"]) >= cutoff]
    Xtr, ytr = train[NUMERIC + CATEGORICAL], train["missed_grace"].astype(int)
    Xte, yte = test[NUMERIC + CATEGORICAL], test["missed_grace"].astype(int)

    models = {"Logistic regression": _logit_pipeline(), "Gradient boosting": _gbm_pipeline()}
    rows, calib, lifts, preds = [], {}, {}, {}
    for name, m in models.items():
        m.fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        preds[name] = p
        lt = lift_table(yte.to_numpy(), p)
        rows.append({
            "model": name,
            "test_auc": roc_auc_score(yte, p),
            "train_auc": roc_auc_score(ytr, m.predict_proba(Xtr)[:, 1]),
            "brier": brier_score_loss(yte, p),
            "top_decile_lift": lt.loc[lt["decile"] == 1, "lift"].iloc[0],
            "top_3_deciles_capture": lt.loc[lt["decile"] == 3, "cumulative_capture"].iloc[0],
        })
        calib[name] = calibration_table(yte.to_numpy(), p)
        lifts[name] = lt
    metrics = pd.DataFrame(rows)
    a_lr = metrics.loc[metrics["model"] == "Logistic regression", "test_auc"].iloc[0]
    a_gb = metrics.loc[metrics["model"] == "Gradient boosting", "test_auc"].iloc[0]
    gain = a_gb - a_lr
    thr = cfg["model"]["gbm_keep_threshold_auc"]
    if gain >= thr:
        chosen, reason = "Gradient boosting", f"Gradient boosting adds {gain:.3f} AUC on the later cohorts, above the {thr:.2f} threshold, so it is kept."
    else:
        chosen = "Logistic regression"
        reason = (
            f"Gradient boosting changes test AUC by {gain:+.3f}, below the {thr:.2f} threshold. "
            "The logistic regression is kept: it is as good, easier to explain and easier to monitor."
        )
    lr = models["Logistic regression"]
    names = lr.named_steps["pre"].get_feature_names_out()
    coefs = pd.DataFrame({"feature": names, "coef": lr.named_steps["clf"].coef_[0]})
    coefs["feature"] = coefs["feature"].str.replace("num__", "").str.replace("cat__", "")
    coefs = coefs.reindex(coefs["coef"].abs().sort_values(ascending=False).index)
    return EarlyWarning(chosen, reason, metrics, calib, lifts, len(train), len(test), str(cutoff.date()), models[chosen], coefs)


def score(ew: EarlyWarning, df: pd.DataFrame) -> np.ndarray:
    d = prep_features(df)
    return ew.model.predict_proba(d[NUMERIC + CATEGORICAL])[:, 1]


# ---------------------------------------------------------------- simulator components

MISS_SQL = """
SELECT instalment_no, deposit_pct, n_instalments, affordability_ratio, principal_age, due_month,
       income_type, channel, payment_method, LEAST(prior_late_count, 3) AS prior_late_count,
       large_claim_recent, ln(1 + claims_kes_to_snapshot) AS log_claims_kes, missed_due
FROM v_model_features
WHERE missed_due IS NOT NULL
"""
MISS_NUMERIC = ["instalment_no", "deposit_pct", "n_instalments", "affordability_ratio", "principal_age",
                "prior_late_count", "large_claim_recent", "log_claims_kes", "is_january", "is_december"]
MISS_CATEGORICAL = ["income_type", "channel", "payment_method"]


@dataclass
class MissModel:
    intercept: float
    coef: dict  # feature name -> coefficient on the raw (unscaled) scale
    levels: dict  # categorical -> {level: coefficient}
    auc: float

    def logit(self, X: dict) -> np.ndarray:
        z = np.full(len(next(iter(X.values()))), self.intercept, dtype=float)
        for k, b in self.coef.items():
            z += b * X[k]
        for col, lv in self.levels.items():
            z += pd.Series(X[col]).map(lv).fillna(0.0).to_numpy()
        return z


def fit_miss_model(df: pd.DataFrame) -> MissModel:
    """Discrete-time hazard of missing a due date (person-period logistic regression)."""
    d = df.copy()
    d["is_january"] = (d["due_month"] == 1).astype(int)
    d["is_december"] = (d["due_month"] == 12).astype(int)
    X = d[MISS_NUMERIC].astype(float)
    dummies = {}
    for col in MISS_CATEGORICAL:
        levels = sorted(d[col].unique())
        ref = REFERENCE[col]
        for lv in levels:
            if lv != ref:
                X[f"{col}={lv}"] = (d[col] == lv).astype(float)
                dummies[f"{col}={lv}"] = (col, lv)
    mu, sd = X.mean(), X.std().replace(0, 1)
    clf = LogisticRegression(max_iter=3000, C=10.0).fit((X - mu) / sd, d["missed_due"].astype(int))
    beta = clf.coef_[0] / sd.to_numpy()
    intercept = clf.intercept_[0] - float((beta * mu.to_numpy()).sum())
    coef, levels = {}, {c: {} for c in MISS_CATEGORICAL}
    for name, b in zip(X.columns, beta):
        if name in dummies:
            col, lv = dummies[name]
            levels[col][lv] = float(b)
        else:
            coef[name] = float(b)
    auc = roc_auc_score(d["missed_due"].astype(int), clf.predict_proba((X - mu) / sd)[:, 1])
    return MissModel(float(intercept), coef, levels, float(auc))


CURE_SQL = """
SELECT days_late, outcome, large_claim_recent
FROM v_instalment_outcomes
WHERE missed_due_date
"""


@dataclass
class CureCurve:
    """Mixture cure model for days from due date to payment: P(paid by day d) = pi * Weibull CDF(d)."""
    pi: float
    shape: float
    scale: float
    window: int
    n: int

    def paid_by(self, d) -> np.ndarray:
        d = np.asarray(d, dtype=float)
        return self.pi * (1 - np.exp(-(np.maximum(d, 0) / self.scale) ** self.shape))


def fit_cure(df: pd.DataFrame, window: int) -> CureCurve:
    paid = df.loc[df["outcome"] != "Lapsed", "days_late"].to_numpy(float)
    n_cens = int((df["outcome"] == "Lapsed").sum())

    def nll(theta):
        pi = 1 / (1 + np.exp(-theta[0]))
        k, lam = np.exp(theta[1]), np.exp(theta[2])
        F = lambda x: 1 - np.exp(-(x / lam) ** k)
        # payment days are whole days: probability mass on (d-1, d]
        mass = np.clip(F(paid) - F(paid - 1), 1e-12, None)
        ll = np.log(pi) * len(paid) + np.log(mass).sum() + n_cens * np.log(1 - pi + pi * (1 - F(window)))
        return -ll

    res = minimize(nll, x0=[0.5, 0.0, np.log(10.0)], method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-6, "fatol": 1e-6})
    pi = 1 / (1 + np.exp(-res.x[0]))
    return CureCurve(float(pi), float(np.exp(res.x[1])), float(np.exp(res.x[2])), window, len(df))


# ---------------------------------------------------------------- export for R

def r_name(term: str) -> str:
    """Syntactic column name shared by the Python export and the R script."""
    return re.sub(r"[^0-9a-zA-Z]+", "_", term).strip("_")


def export_for_r(con) -> Path:
    out = R_DIR / "input"
    out.mkdir(parents=True, exist_ok=True)
    df = con.execute(SURVIVAL_SQL).df()
    X = cox_design(df)
    X.columns = [r_name(c) for c in X.columns]
    X.insert(0, "income_type", df["income_type"].to_numpy())
    X.to_csv(out / "survival_data.csv", index=False)
    return out / "survival_data.csv"


def python_reference_outputs(con, cox: CoxResult | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """KM and Cox estimates in the same layout the R script writes."""
    df = con.execute(SURVIVAL_SQL).df()
    km = pd.concat([km_table(df, None), km_table(df, "income_type")], ignore_index=True)
    km = km[km["duration"] > 0][["group", "duration", "persistency", "lower_95", "upper_95"]]
    cox = cox or fit_cox(df)
    c = cox.summary.reset_index().rename(columns={"covariate": "term"})
    c["term"] = c["term"].map(r_name)
    return km.reset_index(drop=True), c


if __name__ == "__main__":
    from src.db import build

    con = build(db_path=None)
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        print("wrote", export_for_r(con))
    else:
        df = con.execute(SURVIVAL_SQL).df()
        print(km_table(df).tail(3))
        cr = fit_cox(df)
        print(cr.summary.round(3)); print(cr.ph_test.round(4)); print("C =", round(cr.concordance, 3))
        ew = fit_early_warning(con.execute(FEATURES_SQL).df())
        print(ew.metrics.round(3)); print(ew.reason)
        mm = fit_miss_model(con.execute(MISS_SQL).df())
        print(mm)
        cfg = load_config()
        w = cfg["product"]["grace_days"] + cfg["product"]["reinstatement_days"]
        cd = con.execute(CURE_SQL).df()
        print(fit_cure(cd, w))
        print(fit_cure(cd[cd["large_claim_recent"]], w))
