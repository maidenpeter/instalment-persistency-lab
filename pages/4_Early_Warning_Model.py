import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import models as M
from src import ui

ui.page(
    "Early Warning Model",
    "Who is likely to miss the next instalment, how well the model ranks them, and which in-force members to "
    "call before their next due date.",
)
cfg = ui.config()


@st.cache_resource(show_spinner="Fitting the early warning models on earlier cohorts...")
def early_warning():
    art = ui.artifacts()
    return art["early_warning"] if art else M.fit_early_warning(ui.q(M.FEATURES_SQL), cfg)


ew = early_warning()
g = cfg["product"]["grace_days"]

st.markdown(
    f"**Target.** Will the member fail to pay the next instalment within the {g}-day grace period, so that cover is suspended? "
    f"**Unit.** One row per policy and instalment, with every feature taken {cfg['model']['snapshot_days_before_due']} days before "
    f"the due date. **Split.** Trained on cohorts incepted before {pd.Timestamp(ew.cutoff):%B %Y} "
    f"({ew.train_rows:,} instalments), tested on later cohorts ({ew.test_rows:,} instalments), so the test set is genuinely out of time."
)

# ------------------------------------------------------------- comparison
st.subheader("Logistic regression against gradient boosting")
m = ew.metrics.set_index("model")
c1, c2, c3, c4 = st.columns(4)
ui.kpi(c1, "Test AUC, logistic regression", f"{m.loc['Logistic regression', 'test_auc']:.3f}", "Later cohorts")
ui.kpi(c2, "Test AUC, gradient boosting", f"{m.loc['Gradient boosting', 'test_auc']:.3f}", "Later cohorts")
ui.kpi(c3, "Top-decile lift, chosen model", f"{m.loc[ew.chosen, 'top_decile_lift']:.1f}x", "Miss rate in top 10% vs average")
ui.kpi(c4, "Misses caught in top 30%", ui.pct(m.loc[ew.chosen, "top_3_deciles_capture"]), "Share of all misses")
st.write("")
st.info(f"Model kept: **{ew.chosen}**. {ew.reason}")
tbl = ew.metrics.copy()
tbl.columns = ["Model", "Test AUC", "Train AUC", "Brier score", "Top-decile lift", "Top 30% capture"]
st.dataframe(tbl.style.format({"Test AUC": "{:.3f}", "Train AUC": "{:.3f}", "Brier score": "{:.4f}",
                                "Top-decile lift": "{:.2f}x", "Top 30% capture": "{:.1%}"}), hide_index=True, use_container_width=True)

left, right = st.columns(2)
with left:
    fig = go.Figure()
    mx = max(ew.calibration[n][["mean_predicted", "observed"]].max().max() for n in ew.calibration) * 1.08
    fig.add_trace(go.Scatter(x=[0, mx], y=[0, mx], mode="lines", line=dict(color=ui.MUTED, width=1, dash="dot"), name="Perfect calibration", hoverinfo="skip"))
    for name, color in [("Logistic regression", ui.BLUE), ("Gradient boosting", ui.ORANGE)]:
        cb = ew.calibration[name]
        fig.add_trace(go.Scatter(x=cb["mean_predicted"], y=cb["observed"], mode="lines+markers", name=name, line=dict(color=color, width=2),
                                 marker=dict(size=8), hovertemplate=name + "<br>Predicted %{x:.1%}<br>Observed %{y:.1%}<extra></extra>"))
    fig.update_xaxes(tickformat=".0%", title="Mean predicted probability (test decile)", range=[0, mx])
    fig.update_yaxes(tickformat=".0%", title="Observed miss rate", range=[0, mx])
    fig.update_layout(title="Calibration on later cohorts")
    ui.plot(fig, 380)
    cb = ew.calibration[ew.chosen]
    top = cb.iloc[-1]
    ui.takeaway(f"In the riskiest tenth the {ew.chosen.lower()} predicts {ui.pct(top['mean_predicted'])} and {ui.pct(top['observed'])} actually missed.")
with right:
    lt = ew.lift[ew.chosen]
    fig = go.Figure(go.Bar(x=lt["decile"], y=lt["observed_rate"], marker_color=[ui.ORANGE if d <= 3 else ui.BLUE for d in lt["decile"]],
                           customdata=lt[["lift", "members"]],
                           hovertemplate="Decile %{x}<br>Observed miss rate %{y:.1%}<br>Lift %{customdata[0]:.2f}x<br>%{customdata[1]:,} instalments<extra></extra>"))
    base = (lt["observed_rate"] * lt["members"]).sum() / lt["members"].sum()
    fig.add_hline(y=base, line=dict(color=ui.MUTED, width=1, dash="dot"), annotation_text=f"Average {ui.pct(base)}",
                  annotation_position="top right", annotation_font_color=ui.INK_2)
    fig.update_xaxes(title="Risk decile (1 = highest score)", dtick=1)
    fig.update_yaxes(tickformat=".0%", title="Observed miss rate", rangemode="tozero")
    fig.update_layout(title=f"Lift by decile, {ew.chosen.lower()}")
    ui.plot(fig, 380)
    ui.takeaway(
        f"The top decile misses at {ui.pct(lt.loc[lt['decile'] == 1, 'observed_rate'].iloc[0])}, "
        f"{lt.loc[lt['decile'] == 1, 'lift'].iloc[0]:.1f} times the average; the bottom decile at {ui.pct(lt.loc[lt['decile'] == 10, 'observed_rate'].iloc[0])}."
    )

with st.expander("What drives the logistic regression score"):
    co = ew.coefs.head(12).copy()
    co["Odds ratio per unit (standardised for numeric)"] = np.exp(co["coef"])
    co.columns = ["Feature", "Coefficient", "Odds ratio per unit (standardised for numeric)"]
    st.dataframe(co.style.format({"Coefficient": "{:+.3f}", "Odds ratio per unit (standardised for numeric)": "{:.2f}"}),
                 hide_index=True, use_container_width=True)
    st.caption("Numeric features are standardised, so a coefficient is the change in log odds for one standard deviation. "
               "Categorical features are against Starter, online, salaried and M-Pesa STK.")
ui.show_sql(M.FEATURES_SQL, ["v_model_features"])

# ------------------------------------------------------------- call list
st.subheader("Call list this week")
val = pd.Timestamp(cfg["book"]["valuation_date"])
st.markdown(
    f"In-force members with an instalment due in the {cfg['model']['call_horizon_days']} days after the valuation date "
    f"({val:%d %B %Y}), scored with the {ew.chosen.lower()} using only what is known today."
)
cand = ui.q("SELECT * FROM v_call_candidates")
cand["p_miss_grace"] = M.score(ew, cand)

CURE_SQL = "SELECT lapsed / (reinstated + lapsed) AS p_lapse_given_suspended FROM v_grace_cure_rate WHERE income_type = 'All'"
p_lapse = float(ui.q(CURE_SQL)["p_lapse_given_suspended"].iloc[0])
ctc = ui.q("SELECT claims_to_collected FROM v_claims_to_collected WHERE persistency_group = 'Stayer' AND deposit_band = 'All'")
stayer_ctc = float(ctc["claims_to_collected"].iloc[0])
expense = cfg["product"]["expense_ratio"]

a, b = st.columns(2)
n_calls = a.slider("Members the team can call", 25, min(600, len(cand)), min(200, len(cand)), step=25)
uplift = b.slider("Retention uplift from a call (assumption)", 0.0, 0.5, 0.20, step=0.05, format="%.2f",
                  help="Share of members who would have lapsed but stay because they were called. Not estimated from data.")

con = ui._connection().cursor()
con.register("scores", cand[["policy_id", "instalment_no", "p_miss_grace"]])
CALL_SQL = f"""
WITH scored AS (
    SELECT c.policy_id, c.plan_tier, c.income_type, c.channel, c.payment_method, c.due_date, c.amount_due_kes,
           c.outstanding_kes, c.prev_outstanding, s.p_miss_grace,
           s.p_miss_grace * {p_lapse:.6f}                         AS p_lapse,
           s.p_miss_grace * {p_lapse:.6f} * c.outstanding_kes     AS premium_at_risk_kes
    FROM v_call_candidates c JOIN scores s USING (policy_id, instalment_no)
)
SELECT *, ROW_NUMBER() OVER (ORDER BY premium_at_risk_kes DESC) AS call_rank
FROM scored
ORDER BY call_rank
"""
calls = con.execute(CALL_SQL).df()
top = calls.head(n_calls)
SUM_SQL = f"""
SELECT COUNT(*)                                        AS members,
       SUM(premium_at_risk_kes)                        AS premium_at_risk_kes,
       SUM(premium_at_risk_kes) * {uplift:.4f}         AS premium_retained_kes,
       SUM(premium_at_risk_kes) * {uplift:.4f} * (1 - {stayer_ctc:.4f} - {expense:.4f}) AS margin_retained_kes
FROM ({CALL_SQL}) t
WHERE call_rank <= {n_calls}
"""
s = con.execute(SUM_SQL).df().iloc[0]
c1, c2, c3 = st.columns(3)
ui.kpi(c1, f"Premium at risk, top {n_calls} members", ui.kes(s["premium_at_risk_kes"]), f"Of {ui.kes(calls['premium_at_risk_kes'].sum())} across all {len(calls):,} due")
ui.kpi(c2, "Expected premium retained", ui.kes(s["premium_retained_kes"]), f"At a {ui.pct(uplift, 0)} retention uplift")
ui.kpi(c3, "Expected margin retained", ui.kes(s["margin_retained_kes"]),
       f"After stayer claims ({ui.pct(stayer_ctc, 0)}) and expenses ({ui.pct(expense, 0)})")
st.write("")
ui.takeaway(
    f"Calling the top {n_calls} of {len(calls):,} members due this week covers {ui.pct(s['premium_at_risk_kes'] / calls['premium_at_risk_kes'].sum())} "
    "of the premium at risk. Retained premium is not profit: kept members keep claiming, so the margin line nets off expected claims and expenses."
)
show = top[["call_rank", "policy_id", "p_miss_grace", "premium_at_risk_kes", "due_date", "amount_due_kes", "prev_outstanding",
            "outstanding_kes", "plan_tier", "income_type", "channel", "payment_method"]].copy()
show["prev_outstanding"] = np.where(show["prev_outstanding"] == 1, "Yes", "No")
show.columns = ["Rank", "Policy", "P(miss grace)", "Premium at risk (KES)", "Next due", "Instalment (KES)", "Last instalment unpaid",
                "Premium still due (KES)", "Tier", "Income type", "Channel", "Pays by"]
show["P(miss grace)"] = 100 * show["P(miss grace)"]
max_p = float(show["P(miss grace)"].max())
st.dataframe(
    show, hide_index=True, use_container_width=True, height=420,
    column_config={
        "Rank": st.column_config.NumberColumn(width="small"),
        "Next due": st.column_config.DateColumn(format="D MMM YYYY"),
        "Instalment (KES)": st.column_config.NumberColumn(format="localized"),
        "Premium still due (KES)": st.column_config.NumberColumn(format="localized"),
        "P(miss grace)": st.column_config.ProgressColumn(format="%.1f%%", min_value=0.0, max_value=max_p,
                                                         help="Probability the next instalment is not paid within grace"),
        "Premium at risk (KES)": st.column_config.NumberColumn(format="localized"),
    },
)
st.download_button("Download call list (CSV)", show.rename(columns={"P(miss grace)": "P(miss grace) %"}).to_csv(index=False).encode("utf-8"),
                   "call_list.csv", "text/csv")
ui.show_sql(CALL_SQL + ";\n\n-- Probability a suspended instalment ends in lapse\n" + CURE_SQL + ";\n\n-- Totals for the chosen call volume\n" + SUM_SQL,
            ["v_call_candidates", "v_grace_cure_rate"])
st.caption("Premium at risk = P(miss grace) x P(lapse | suspended) x premium still due. The retention uplift is an assumption "
           "until a contact trial measures it; a randomised hold-out group is the way to estimate it honestly.")
ui.footer()
