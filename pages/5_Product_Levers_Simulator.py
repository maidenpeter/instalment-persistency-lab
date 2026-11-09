from dataclasses import asdict, replace

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import models as M
from src import simulate as SM
from src import ui

ui.page(
    "Product Levers Simulator",
    "Change the product and see what happens to persistency, claims against premium collected, leakage and the "
    "loading needed to break even. Every run uses the models fitted on the synthetic book, not the rules that generated it.",
)
cfg = ui.config()
sim_cfg = cfg["simulator"]


@st.cache_resource(show_spinner="Fitting the simulator inputs...")
def inputs() -> SM.Inputs:
    art = ui.artifacts()
    return art["sim_inputs"] if art else SM.build_inputs(ui.q, cfg)


inp = inputs()
PRE = (ui.artifacts() or {}).get("sim_cache", {})
BASE = SM.base_scenario(cfg)
DEFAULT = SM.default_scenario(cfg)


@st.cache_data(show_spinner=False, max_entries=200)
def run(scn_dict: dict, n_runs: int) -> dict:
    scn = SM.Scenario(**scn_dict)
    hit = PRE.get(("run", SM.key(scn), n_runs))
    return hit if hit is not None else SM.simulate(inp, scn, n_runs=n_runs)


@st.cache_data(show_spinner=False, max_entries=100)
def breakeven(scn_dict: dict) -> float | None:
    scn = SM.Scenario(**scn_dict)
    k = ("breakeven", SM.key(scn))
    return PRE[k] if k in PRE else SM.break_even_loading(inp, scn, n_runs=1)


@st.cache_data(show_spinner=False, max_entries=50)
def deposit_curve(scn_dict: dict) -> pd.DataFrame:
    scn = SM.Scenario(**scn_dict)
    hit = PRE.get(("deposit_curve", SM.key(scn)))
    return hit if hit is not None else SM.deposit_curve(inp, scn)


# ------------------------------------------------------------- levers
with st.form("levers"):
    st.markdown("**Product levers** (opens on an example redesign: 20% deposit, benefits unlock with premium paid)")
    c1, c2, c3 = st.columns(3)
    deposit = c1.slider("Deposit, % of annual premium", 10, 40, int(round(DEFAULT.deposit * 100)), step=5) / 100
    n_inst = c1.slider("Number of monthly instalments", 1, 10, BASE.n_instalments)
    grace = c1.slider("Grace period, days", 0, 30, BASE.grace_days,
                      help=f"Cover is suspended after grace; the policy lapses {cfg['product']['reinstatement_days']} days later if still unpaid.")
    w_op = c2.slider("Waiting period, outpatient (months)", 0, 3, BASE.waiting["outpatient"])
    w_ip = c2.slider("Waiting period, inpatient (months)", 0, 6, BASE.waiting["inpatient"])
    w_mat = c2.slider("Waiting period, maternity (months)", 0, 12, BASE.waiting["maternity"])
    w_chr = c2.slider("Waiting period, chronic (months)", 0, 12, BASE.waiting["chronic"])
    release = c3.radio("Benefit release", ["Full cover from first payment", "Benefits unlock with premium paid"], index=1 if DEFAULT.release == "proportional" else 0,
                       help="Unlocking: each benefit limit is available in proportion to the share of annual premium paid so far.")
    loading = c3.slider("Instalment loading, % of premium", 0, 30, 0, step=1) / 100
    elasticity = c3.slider("Sign-up elasticity to deposit (assumption)", 0.0, 1.0, float(sim_cfg["default_signup_elasticity"]), step=0.05,
                           help="New business volume changes as (deposit / 10%) to the power of minus this number. Not estimated from data.")
    st.form_submit_button("Run scenario", type="primary")

scn = SM.Scenario(deposit=deposit, n_instalments=n_inst, grace_days=grace,
                  waiting={"outpatient": w_op, "inpatient": w_ip, "maternity": w_mat, "chronic": w_chr},
                  release="full" if release.startswith("Full") else "proportional", loading=loading)
n_runs = sim_cfg["n_runs"]
with st.spinner("Simulating..."):
    b = run(asdict(BASE), n_runs)
    s = run(asdict(scn), n_runs)
    be_base = breakeven(asdict(replace(BASE, loading=0.0)))
    be_scn = breakeven(asdict(replace(scn, loading=0.0)))

nb = inp.annual_new_business
sign_b = 1.0
sign_s = SM.signup_factor(scn.deposit, BASE.deposit, elasticity)
book_b = nb * sign_b * b["margin_per_policy"]
book_s = nb * sign_s * s["margin_per_policy"]


def fmt_be(x):
    return "above 100%" if x is None else ui.pct(x)


# ------------------------------------------------------------- headline comparison
st.subheader("Base case against your scenario")
st.caption(
    f"Base case: {ui.pct(BASE.deposit, 0)} deposit, {BASE.n_instalments} instalments, {BASE.grace_days} days grace, waiting periods "
    f"{BASE.waiting['outpatient']}/{BASE.waiting['inpatient']}/{BASE.waiting['maternity']}/{BASE.waiting['chronic']} months "
    "(outpatient/inpatient/maternity/chronic), full cover from first payment, no loading. "
    f"{len(inp.sample):,} run-off policies x {n_runs} runs, common random numbers."
)
rows = [
    ("Persistency at month 10", ui.pct(b["persistency"][-1]), ui.pct(s["persistency"][-1]), s["persistency"][-1] - b["persistency"][-1], True, "pts"),
    ("Claims to premium collected", ui.pct(b["claims_to_collected"]), ui.pct(s["claims_to_collected"]), s["claims_to_collected"] - b["claims_to_collected"], False, "pts"),
    ("Claims to collected, lapsers", ui.pct(b["ctc_lapsers"]), ui.pct(s["ctc_lapsers"]), s["ctc_lapsers"] - b["ctc_lapsers"], False, "pts"),
    ("Leakage per 1,000 policies", ui.kes(1000 * b["leakage_per_policy"], short=True), ui.kes(1000 * s["leakage_per_policy"], short=True),
     1000 * (s["leakage_per_policy"] - b["leakage_per_policy"]), False, "kes"),
    ("Premium collected per policy", ui.kes(b["collected_per_policy"]), ui.kes(s["collected_per_policy"]), s["collected_per_policy"] - b["collected_per_policy"], True, "kes"),
    ("Margin per policy after claims and expenses", ui.kes(b["margin_per_policy"]), ui.kes(s["margin_per_policy"]), s["margin_per_policy"] - b["margin_per_policy"], True, "kes"),
    ("Loading needed to break even", fmt_be(be_base), fmt_be(be_scn),
     None if be_base is None or be_scn is None else be_scn - be_base, False, "pts"),
    ("New business volume (assumption)", "100.0%", ui.pct(sign_s), sign_s - 1, True, "pts"),
    ("Annual book margin", ui.kes(book_b, short=True), ui.kes(book_s, short=True), book_s - book_b, True, "kes"),
]


def delta(v, good_up, unit):
    if v is None or abs(v) < 1e-9:
        return ""
    good = (v > 0) == good_up
    txt = f"{v * 100:+.1f} pts" if unit == "pts" else f"{'+' if v > 0 else '-'}KES {abs(v):,.0f}"
    return f"{txt}, {'better' if good else 'worse'}"


cmp = pd.DataFrame([{"Measure": r[0], "Base case": r[1], "Scenario": r[2], "Change": delta(r[3], r[4], r[5])} for r in rows])
def _tone(v: str) -> str:
    if v.endswith("better"):
        return "color: #006300; font-weight: 600"
    if v.endswith("worse"):
        return "color: #b42b2b; font-weight: 600"
    return ""


st.dataframe(cmp.style.map(_tone, subset=["Change"]), hide_index=True, use_container_width=True,
             column_config={"Measure": st.column_config.TextColumn(width="large")})
if scn == BASE:
    st.info("The scenario equals the base case. Move the levers and press Run scenario to compare.")
else:
    ui.takeaway(
        f"This scenario moves claims to collected premium from {ui.pct(b['claims_to_collected'])} to {ui.pct(s['claims_to_collected'])} and leakage "
        f"from {ui.kes(b['leakage_per_policy'])} to {ui.kes(s['leakage_per_policy'])} per policy written; the loading needed to break even goes from "
        f"{fmt_be(be_base)} to {fmt_be(be_scn)}."
    )

# ------------------------------------------------------------- charts
left, right = st.columns(2)
with left:
    t = np.arange(1, 11)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t, y=b["persistency"], name="Base case", mode="lines+markers", line=dict(color=ui.BLUE, width=2), marker=dict(size=8),
                             hovertemplate="Base, instalment %{x}: %{y:.1%}<extra></extra>"))
    fig.add_trace(go.Scatter(x=t, y=s["persistency"], name="Scenario", mode="lines+markers", line=dict(color=ui.ORANGE, width=2), marker=dict(size=8),
                             hovertemplate="Scenario, instalment %{x}: %{y:.1%}<extra></extra>"))
    fig.update_yaxes(tickformat=".0%", title="Share still in force", range=[0, 1.02])
    fig.update_xaxes(title="Policy month (instalment number)", dtick=1)
    fig.update_layout(title="Projected persistency")
    ui.plot(fig, 360)
    ui.takeaway(f"Projected persistency at month 10: {ui.pct(b['persistency'][-1])} in the base case, {ui.pct(s['persistency'][-1])} in the scenario.")
with right:
    cats = ["Premium collected", "Claims paid", "Expenses", "Margin"]
    vals_b = [b["collected_per_policy"], b["claims_per_policy"], inp.expense_ratio * b["collected_per_policy"], b["margin_per_policy"]]
    vals_s = [s["collected_per_policy"], s["claims_per_policy"], inp.expense_ratio * s["collected_per_policy"], s["margin_per_policy"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(x=cats, y=vals_b, name="Base case", marker_color=ui.BLUE, hovertemplate="Base, %{x}: KES %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Bar(x=cats, y=vals_s, name="Scenario", marker_color=ui.ORANGE, hovertemplate="Scenario, %{x}: KES %{y:,.0f}<extra></extra>"))
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08, title="Per policy written, KES")
    fig.update_yaxes(tickformat=",.0f", title="KES per policy")
    ui.plot(fig, 360)
    ui.takeaway(f"Margin per policy written: {ui.kes(b['margin_per_policy'])} base, {ui.kes(s['margin_per_policy'])} scenario, "
                f"after a {ui.pct(inp.expense_ratio, 0)} expense load on collected premium.")

st.subheader("Conversion trade-off")
with st.spinner("Tracing the deposit curve..."):
    dc = deposit_curve(asdict(replace(scn, deposit=BASE.deposit)))
dc["signups"] = [SM.signup_factor(d, BASE.deposit, elasticity) for d in dc["deposit"]]
dc["book_margin"] = nb * dc["signups"] * dc["margin_per_policy"]
fig = go.Figure()
fig.add_trace(go.Scatter(x=dc["deposit"], y=dc["book_margin"], mode="lines+markers", name="Annual book margin", line=dict(color=ui.BLUE, width=2),
                         marker=dict(size=8), customdata=dc[["signups", "margin_per_policy"]],
                         hovertemplate="Deposit %{x:.0%}<br>Book margin KES %{y:,.0f}<br>Sign-ups %{customdata[0]:.0%} of base<br>"
                                       "Margin per policy KES %{customdata[1]:,.0f}<extra></extra>"))
fig.add_hline(y=0, line=dict(color=ui.MUTED, width=1, dash="dot"))
fig.update_xaxes(tickformat=".0%", title="Deposit, % of annual premium (other levers as set above)")
fig.update_yaxes(tickformat=",.0f", title="KES per year")
fig.update_layout(title=f"Annual book margin against deposit, at sign-up elasticity {elasticity:.2f}")
ui.plot(fig, 360)
best = dc.loc[dc["book_margin"].idxmax()]
ui.takeaway(
    f"With {int(nb):,} new policies a year at a 10% deposit and an elasticity of {elasticity:.2f}, the book margin peaks at a "
    f"{ui.pct(best['deposit'], 0)} deposit ({ui.kes(best['book_margin'], short=True)} a year). A higher deposit cuts leakage per policy but sells fewer policies."
)

with st.expander("How the simulator works, and the fitted inputs it uses"):
    mm = inp.miss
    st.markdown(
        f"""
1. **Sample.** {len(inp.sample):,} policies drawn from the run-off book keep their own age, family, tier, income type, channel, payment method and income proxy.
   Prices and instalments are reset to the scenario's deposit, number of instalments and loading.
2. **Missed due dates** come from a discrete-time hazard model (logistic regression on every instalment, AUC {mm.auc:.3f}). It responds to deposit size, number of instalments,
   affordability (instalment over income proxy), instalment number, calendar month, prior late payments, a recent large claim and claims paid to date.
3. **Time to pay after a miss** comes from a mixture cure model fitted to days late, with lapses censored at the {cfg['product']['grace_days'] + cfg['product']['reinstatement_days']}-day window:
   {ui.pct(inp.cure_normal.pi)} of missed instalments are ever paid ({ui.pct(inp.cure_large.pi)} after a large claim), Weibull shape {inp.cure_normal.shape:.2f}, scale {inp.cure_normal.scale:.1f} days.
   A grace period beyond {cfg['product']['grace_days']} days extrapolates this curve.
4. **Claims** use observed frequency per covered exposure unit by benefit and cover month. Months 1 to 3 carry an anti-selection relativity fitted against deposit size
   (intercept {inp.early_rel[0]:.2f}, slope {inp.early_rel[1]:.2f} per unit of deposit share) and a gamma frailty with variance {inp.early_dispersion:.2f}
   fitted to the overdispersion of early claim counts. Claim sizes are resampled from observed claims by benefit and tier, then capped by limits
   and, under the unlocking rule, by the share of premium paid.
5. **Months inside the book's waiting period** have no observed claims; if you shorten a waiting period, those months borrow the frequency of the first months with claims.
6. **Break-even loading** is where premium collected, net of the {ui.pct(inp.expense_ratio, 0)} expense ratio, equals claims paid, found by interpolation on a grid of loadings.
   A loading also raises the instalment, so it feeds back into affordability and lapse.
"""
    )
    st.code(SM.SAMPLE_SQL.strip() + ";\n\n" + SM.FREQ_SQL.strip() + ";\n\n" + M.MISS_SQL.strip() + ";\n\n" + M.CURE_SQL.strip() + ";", language="sql")
st.caption("The simulator is checked against the actual book on the Methods and Assumptions page. Treat outputs as directional: they depend on the stated assumptions.")
ui.footer()
