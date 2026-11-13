import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import models as M
from src import ui

ui.page(
    "one",
    "Averages hide people. Pick one policy and follow it through its year: every payment, every claim, every slip, and what the early warning model would have said before each due date.",
)
cfg = ui.config()
g, r = cfg["product"]["grace_days"], cfg["product"]["reinstatement_days"]
valuation = pd.Timestamp(cfg["book"]["valuation_date"])

# ------------------------------------------------------------- choose a policy
EX_SQL = "SELECT label, policy_id FROM v_policy_examples ORDER BY ord"
examples = ui.q(EX_SQL)
options = ["Type a policy ID"] + [f"{lab} ({pid})" for lab, pid in zip(examples["label"], examples["policy_id"])]
by_option = dict(zip(options[1:], examples["policy_id"]))

if "policy_id" not in st.session_state:
    st.session_state["policy_id"] = examples["policy_id"].iloc[0]
    st.session_state["example"] = options[1]


def _pick_example():
    choice = st.session_state["example"]
    if choice in by_option:
        st.session_state["policy_id"] = by_option[choice]


a, b = st.columns([1.4, 1])
a.selectbox("Start from an example", options, key="example", on_change=_pick_example)
b.text_input("Policy ID", key="policy_id", help="P000001 to P020000")
pid = st.session_state["policy_id"].strip().upper()

POLICY_SQL = "SELECT * FROM v_policy WHERE policy_id = ?"
pol = ui.q(POLICY_SQL, (pid,))
if pol.empty:
    st.warning(f"No policy called {pid}. Policy IDs run from P000001 to P020000.")
    st.stop()
p = pol.iloc[0]

# ------------------------------------------------------------- headline
status = p["status_at_valuation"]
if status == "Lapsed":
    status_note = f"Lapsed on {pd.Timestamp(p['lapse_date']):%d %b %Y}, at instalment {int(p['lapse_duration'])}"
elif status == "Paid up":
    status_note = f"All instalments paid by {pd.Timestamp(p['completed_date']):%d %b %Y}"
elif status == "Suspended":
    status_note = "Cover suspended: an instalment is past grace"
else:
    status_note = "In force and paying"
ratio = p["claims_paid_kes"] / p["collected_kes"] if p["collected_kes"] else float("nan")
c1, c2, c3, c4 = st.columns(4)
ui.kpi(c1, "Status at valuation", p["status_at_valuation"], status_note)
ui.kpi(c2, "Premium collected", ui.kes(p["collected_kes"]), f"of {ui.kes(p['annual_premium_kes'])} written ({ui.pct(p['collected_kes'] / p['annual_premium_kes'], 0)})")
ui.kpi(c3, "Claims paid", ui.kes(p["claims_paid_kes"]), f"{int(p['n_claims'])} claims, {int(p['n_large_claims'])} large")
ui.kpi(c4, "Claims per KES 1 collected", f"KES {ratio:.2f}" if ratio == ratio else "n/a",
       "Paid out more than it paid in" if ratio > 1 else "Paid in more than it was paid out")
st.write("")
st.markdown(
    f"**{p['plan_tier']}** plan, family of **{int(p['family_size'])}**, principal aged **{int(p['principal_age'])}**, "
    f"**{p['income_type']}** income, sold **{p['channel']}**, pays by **{p['payment_method']}**, **{p['region']}**. "
    f"Started **{pd.Timestamp(p['inception_date']):%d %B %Y}** on a **{ui.pct(p['deposit_pct'], 0)}** deposit and "
    f"**{int(p['n_instalments'])}** monthly instalments of **{ui.kes(p['instalment_kes'])}**."
)
ui.show_sql(POLICY_SQL.replace("?", f"'{pid}'"), ["v_policy"])

# ------------------------------------------------------------- cash in and out
st.subheader(":material/account_balance_wallet: Cash in and cash out")
CASH_SQL = """
SELECT flow_date, flow, amount_kes, detail, premium_to_date_kes, claims_to_date_kes
FROM v_policy_cashflows
WHERE policy_id = ?
ORDER BY flow_date, flow DESC
"""
EVENTS_SQL = "SELECT event_date, event FROM status_events WHERE policy_id = ? ORDER BY event_date"
cash = ui.q(CASH_SQL, (pid,))
events = ui.q(EVENTS_SQL, (pid,))
start = pd.Timestamp(p["inception_date"])
end = min(pd.Timestamp(p["cover_end_date"]), valuation)
line = pd.concat([pd.DataFrame({"flow_date": [start], "premium_to_date_kes": [0.0], "claims_to_date_kes": [0.0]}),
                  cash[["flow_date", "premium_to_date_kes", "claims_to_date_kes"]],
                  pd.DataFrame({"flow_date": [end], "premium_to_date_kes": [cash["premium_to_date_kes"].iloc[-1] if len(cash) else 0],
                                "claims_to_date_kes": [cash["claims_to_date_kes"].iloc[-1] if len(cash) else 0]})])
fig = go.Figure()
fig.add_trace(go.Scatter(x=line["flow_date"], y=line["premium_to_date_kes"], name="Premium collected to date", mode="lines",
                         line=dict(color=ui.PRIMARY, width=2.5, shape="hv"), hovertemplate="%{x|%d %b %Y}<br>Premium to date KES %{y:,.0f}<extra></extra>"))
fig.add_trace(go.Scatter(x=line["flow_date"], y=line["claims_to_date_kes"], name="Claims paid to date", mode="lines",
                         line=dict(color=ui.ACCENT, width=2.5, shape="hv"), hovertemplate="%{x|%d %b %Y}<br>Claims to date KES %{y:,.0f}<extra></extra>"))
cl = cash[cash["flow"] == "Claim"]
if len(cl):
    fig.add_trace(go.Scatter(x=cl["flow_date"], y=cl["claims_to_date_kes"], mode="markers", name="A claim is paid",
                             marker=dict(color=ui.ACCENT, size=(cl["amount_kes"] / cl["amount_kes"].max() * 16 + 8).clip(8, 24),
                                         line=dict(color="white", width=2)),
                             customdata=cl[["amount_kes", "detail"]],
                             hovertemplate="%{x|%d %b %Y}<br>%{customdata[1]}<br>KES %{customdata[0]:,.0f}<extra></extra>"))
EVENT_STYLE = {"suspended": ("Suspended", ui.ORCHID), "reinstated": ("Reinstated", ui.TEAL), "lapsed": ("Lapsed", ui.ACCENT),
               "completed": ("Paid up", ui.PRIMARY)}
shown = events[events["event"].isin(EVENT_STYLE)].reset_index(drop=True)
for i, e in shown.iterrows():
    label, color = EVENT_STYLE[e["event"]]
    fig.add_vline(x=pd.Timestamp(e["event_date"]), line=dict(color=color, width=1.5, dash="dot"))
    fig.add_annotation(x=pd.Timestamp(e["event_date"]), y=1.02 + 0.07 * (i % 2), yref="paper", text=label, showarrow=False,
                       yanchor="bottom", font=dict(size=11, color=color), bgcolor="rgba(255,255,255,0.85)")
fig.update_yaxes(tickformat=",.0f", title="KES, cumulative", rangemode="tozero")
fig.update_xaxes(title="")
fig.update_layout(title="", margin=dict(t=75, b=10), legend=dict(orientation="h", yanchor="top", y=-0.12, x=0))
ui.plot(fig, 430)
if p["is_lapsed"]:
    big = cl[cl["amount_kes"] >= cfg["anti_selection"]["large_claim_kes"]]
    after = ""
    if len(big):
        days = (pd.Timestamp(p["lapse_date"]) - big["flow_date"].max()).days
        after = f" It lapsed {days} days after its last large claim was paid."
    ui.takeaway(f"This member paid in {ui.kes(p['collected_kes'])} and was paid {ui.kes(p['claims_paid_kes'])} in claims before lapsing.{after}")
else:
    ui.takeaway(f"So far this member has paid in {ui.kes(p['collected_kes'])} and been paid {ui.kes(p['claims_paid_kes'])} in claims, "
                f"{ui.pct(ratio, 0)} of what came in." if ratio == ratio else "No premium collected yet.")
ui.show_sql(CASH_SQL.replace("?", f"'{pid}'") + ";\n\n" + EVENTS_SQL.replace("?", f"'{pid}'"), ["v_policy_cashflows"])

# ------------------------------------------------------------- instalment record and risk trend
st.subheader(":material/calendar_month: Instalment by instalment")
INST_SQL = """
SELECT instalment_no, due_date, amount_due_kes, paid_date, amount_paid_kes, days_late, outcome
FROM v_policy_instalments
WHERE policy_id = ?
ORDER BY instalment_no
"""
inst = ui.q(INST_SQL, (pid,))
FEAT_SQL = "SELECT * FROM v_model_features WHERE policy_id = ? ORDER BY instalment_no"
feat = ui.q(FEAT_SQL, (pid,))
PEER_SQL = """
SELECT instalment_no, AVG(missed_grace) AS peer_miss_rate, COUNT(*) AS peer_instalments
FROM v_model_features
WHERE missed_grace IS NOT NULL AND income_type = ? AND plan_tier = ? AND payment_method = ?
GROUP BY instalment_no
ORDER BY instalment_no
"""
peer = ui.q(PEER_SQL, (p["income_type"], p["plan_tier"], p["payment_method"]))

OUTCOME_COLOR = {"On time": ui.TEAL, "Late, paid in grace": ui.PRIMARY, "Late, reinstated": ui.ORCHID,
                 "Unpaid, policy lapsed": ui.ACCENT, "Due, not yet paid": ui.ACCENT}
left, right = st.columns(2)
with left:
    rec = inst[(inst["instalment_no"] >= 1) & inst["outcome"].isin(OUTCOME_COLOR)].copy()
    rec["bar_days"] = rec["days_late"].fillna(g + r + 1).clip(lower=0.6)
    fig = go.Figure()
    for outcome, color in OUTCOME_COLOR.items():
        d = rec[rec["outcome"] == outcome]
        if len(d):
            fig.add_trace(go.Bar(x=d["instalment_no"], y=d["bar_days"], name=outcome, marker_color=color,
                                 customdata=d[["due_date", "amount_due_kes"]],
                                 hovertemplate=f"Instalment %{{x}}: {outcome}<br>Due %{{customdata[0]|%d %b %Y}}<br>"
                                               "KES %{customdata[1]:,.0f}<extra></extra>"))
    fig.add_hline(y=g, line=dict(color=ui.MUTED, width=1, dash="dot"), annotation_text=f"Grace ends, day {g}",
                  annotation_position="top left", annotation_font_color=ui.INK_2)
    fig.add_hline(y=g + r + 1, line=dict(color=ui.ACCENT, width=1, dash="dot"), annotation_text=f"Lapse, day {g + r + 1}",
                  annotation_position="top left", annotation_font_color=ui.ACCENT)
    fig.update_layout(title="Days late on each instalment", bargap=0.35, barmode="overlay",
                      legend=dict(orientation="h", yanchor="top", y=-0.22, x=0), margin=dict(t=50, b=10))
    fig.update_xaxes(title="Instalment", dtick=1, range=[0.4, int(p["n_instalments"]) + 0.6])
    fig.update_yaxes(title="Days after due date", range=[0, g + r + 8])
    ui.plot(fig, 400)
    late = rec[rec["outcome"] != "On time"]
    ui.takeaway(f"{len(rec) - len(late)} of {len(rec)} instalments due so far were paid on time." if len(rec) else "No instalments have fallen due yet.")
with right:
    if len(feat):
        ew = ui.early_warning_model()
        feat = feat.assign(score=M.score(ew, feat))
        fig = go.Figure()
        if len(peer):
            fig.add_trace(go.Scatter(x=peer["instalment_no"], y=peer["peer_miss_rate"], name="Similar members, actual miss rate",
                                     mode="lines", line=dict(color=ui.MUTED, width=2, dash="dot"),
                                     hovertemplate="Instalment %{x}<br>Similar members missed %{y:.1%}<extra></extra>"))
        fig.add_trace(go.Scatter(x=feat["instalment_no"], y=feat["score"], name="This member, predicted risk",
                                 mode="lines+markers", line=dict(color=ui.ACCENT, width=2.5), marker=dict(size=9, line=dict(color="white", width=2)),
                                 customdata=feat[["snapshot_date"]],
                                 hovertemplate="Instalment %{x}<br>Risk of missing grace %{y:.1%}<br>Scored on %{customdata[0]|%d %b %Y}<extra></extra>"))
        missed = feat[feat["missed_grace"] == 1]
        if len(missed):
            fig.add_trace(go.Scatter(x=missed["instalment_no"], y=missed["score"], mode="markers", name="Then missed grace",
                                     marker=dict(symbol="x", size=13, color=ui.INK, line=dict(width=1)),
                                     hovertemplate="Instalment %{x}: missed grace<extra></extra>"))
        fig.update_layout(title="Early warning risk before each due date",
                          legend=dict(orientation="h", yanchor="top", y=-0.22, x=0), margin=dict(t=50, b=10))
        fig.update_yaxes(tickformat=".0%", title="Probability of missing grace", rangemode="tozero")
        fig.update_xaxes(title="Instalment", dtick=1, range=[0.4, int(p["n_instalments"]) + 0.6])
        ui.plot(fig, 400)
        top = feat.loc[feat["score"].idxmax()]
        ui.takeaway(
            f"Risk peaked at {ui.pct(top['score'])} before instalment {int(top['instalment_no'])}, scored "
            f"{cfg['model']['snapshot_days_before_due']} days ahead using only what was known then. "
            f"The dotted line is what similar members ({p['income_type']}, {p['plan_tier']}, {p['payment_method']}) actually did."
        )
    else:
        st.info("No instalments have been scored for this policy yet.")

show = pd.DataFrame({
    "Instalment": ["Deposit" if n == 0 else str(n) for n in inst["instalment_no"]],
    "Due": pd.to_datetime(inst["due_date"]).dt.strftime("%d %b %Y"),
    "Due (KES)": inst["amount_due_kes"].map("{:,.0f}".format),
    "Paid": pd.to_datetime(inst["paid_date"]).dt.strftime("%d %b %Y").fillna(""),
    "Paid (KES)": [f"{v:,.0f}" if v else "" for v in inst["amount_paid_kes"]],
    "Days late": [f"{int(d)}" if pd.notna(d) else "" for d in inst["days_late"]],
    "What happened": inst["outcome"],
})
st.dataframe(show, hide_index=True, use_container_width=True)
ui.show_sql(INST_SQL.replace("?", f"'{pid}'") + ";\n\n" + FEAT_SQL.replace("?", f"'{pid}'") + ";\n\n-- Similar members\n" + PEER_SQL,
            ["v_policy_instalments", "v_model_features"])

# ------------------------------------------------------------- claims and peers
left, right = st.columns([1.3, 1])
with left:
    st.subheader(":material/medical_services: Claims")
    CLAIMS_SQL = """
SELECT claim_id, service_date, paid_date, benefit_type, amount_paid_kes
FROM claims
WHERE policy_id = ?
ORDER BY service_date
"""
    clm = ui.q(CLAIMS_SQL, (pid,))
    if clm.empty:
        st.markdown("No claims paid on this policy.")
    else:
        st.dataframe(
            clm.rename(columns={"claim_id": "Claim", "service_date": "Treated", "paid_date": "Paid", "benefit_type": "Benefit",
                                "amount_paid_kes": "Amount (KES)"}),
            hide_index=True, use_container_width=True, height=min(38 + 35 * len(clm), 360),
            column_config={"Treated": st.column_config.DateColumn(format="D MMM YYYY"), "Paid": st.column_config.DateColumn(format="D MMM YYYY"),
                           "Amount (KES)": st.column_config.NumberColumn(format="localized")},
        )
    ui.show_sql(CLAIMS_SQL.replace("?", f"'{pid}'"))
with right:
    st.subheader(":material/groups: Against similar policies")
    PEERS_SQL = """
SELECT
    COUNT(*)                                                         AS policies,
    AVG(CASE WHEN is_lapsed THEN 1.0 ELSE 0 END)                     AS lapse_rate,
    SUM(claims_paid_kes) / SUM(collected_kes)                        AS claims_to_collected,
    AVG(collected_kes)                                               AS avg_collected_kes,
    AVG(claims_paid_kes)                                             AS avg_claims_kes
FROM v_policy
WHERE is_run_off AND plan_tier = ? AND income_type = ? AND deposit_band = ?
"""
    pr = ui.q(PEERS_SQL, (p["plan_tier"], p["income_type"], p["deposit_band"])).iloc[0]
    st.caption(f"Run-off policies on the same plan ({p['plan_tier']}), income type ({p['income_type']}) and deposit band ({p['deposit_band']}).")
    comp = pd.DataFrame({
        "Measure": ["Policies compared", "Lapsed by end of term", "Claims per KES 1 collected", "Premium collected", "Claims paid"],
        "This policy": ["1", "Yes" if p["is_lapsed"] else "No", f"KES {ratio:.2f}" if ratio == ratio else "n/a",
                        ui.kes(p["collected_kes"]), ui.kes(p["claims_paid_kes"])],
        "Similar policies": [f"{int(pr['policies']):,}", ui.pct(pr["lapse_rate"]), f"KES {pr['claims_to_collected']:.2f}",
                             ui.kes(pr["avg_collected_kes"]) + " avg", ui.kes(pr["avg_claims_kes"]) + " avg"],
    })
    st.dataframe(comp, hide_index=True, use_container_width=True)
    ui.show_sql(PEERS_SQL, ["v_policy"])

ui.show_sql(EX_SQL, ["v_policy_examples"], label="How the example policies are chosen")
ui.footer()
