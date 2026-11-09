import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from lifelines import KaplanMeierFitter

from src import queries as Q
from src import ui

ui.page("Persistency Explorer", "Who lapses, and when. Lapse decrements by policy duration, with exposure, confidence intervals and cohort views.")

opts = ui.q(
    "SELECT DISTINCT channel, income_type, plan_tier, deposit_band FROM v_policy"
)
all_values = {lab: sorted(opts[col].unique()) for lab, col in Q.FILTER_COLUMNS.items()}
months = ui.q("SELECT DISTINCT inception_month FROM v_policy ORDER BY 1")["inception_month"].dt.date.tolist()

with st.sidebar:
    st.markdown("**Filters**")
    filters = {lab: st.multiselect(lab, vals, default=vals, key=f"f_{lab}") for lab, vals in all_values.items()}
    cohort = st.select_slider("Inception cohort", options=months, value=(months[0], months[-1]),
                              format_func=lambda d: d.strftime("%b %Y"))
    compare = st.selectbox("Compare curves by", ["Income type", "Channel", "Plan tier", "Deposit band", "Payment method"])

where, params = Q.where_clause(filters, all_values, cohort)
dec = ui.q(Q.DECREMENTS.format(where=where), params)
if dec.empty:
    st.warning("No policies match these filters.")
    st.stop()

n_pol = ui.q(f"SELECT COUNT(*) AS n FROM v_policy_survival WHERE {where}", params)["n"].iloc[0]
p_last = dec["persistency"].iloc[-1]
last_t = int(dec["duration"].iloc[-1])
worst = dec.loc[dec["q"].idxmax()]

c1, c2, c3 = st.columns(3)
ui.kpi(c1, "Policies selected", f"{n_pol:,}", "")
ui.kpi(c2, f"Persistency to instalment {last_t}", ui.pct(p_last), "Product of (1 - q) over durations")
ui.kpi(c3, "Highest monthly lapse rate", ui.pct(worst["q"]), f"At instalment {int(worst['duration'])}")
st.write("")

# ------------------------------------------------------------- lapse rate by duration
fig = go.Figure()
fig.add_trace(go.Scatter(x=dec["duration"], y=dec["q_upper_95"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
fig.add_trace(go.Scatter(x=dec["duration"], y=dec["q_lower_95"], mode="lines", line=dict(width=0), fill="tonexty",
                         fillcolor=ui.rgba(ui.PRIMARY, 0.15), name="95% CI", hoverinfo="skip"))
fig.add_trace(go.Scatter(x=dec["duration"], y=dec["q"], mode="lines+markers", name="Crude q(t)", line=dict(color=ui.PRIMARY, width=2),
                         marker=dict(size=8), customdata=dec[["exposed", "lapses"]],
                         hovertemplate="Instalment %{x}<br>q = %{y:.1%}<br>Exposed %{customdata[0]:,.0f}, lapses %{customdata[1]:,.0f}<extra></extra>"))
fig.update_yaxes(tickformat=".0%", title="Monthly lapse rate q(t)", rangemode="tozero")
fig.update_xaxes(title="Duration t (instalment number)", dtick=1)
fig.update_layout(title="Monthly lapse rate by duration")
ui.plot(fig, 340)
spike = dec.set_index("duration")["q"]
if 3 in spike.index and 2 in spike.index:
    ui.takeaway(
        f"Lapse rates jump from {ui.pct(spike[2])} at instalment 2 to {ui.pct(spike[3])} at instalment 3, "
        "the point where members who joined to claim, and have now claimed, stop paying."
    )

tabs = st.tabs(["Decrement table", "Cohort heatmap", "Kaplan-Meier curves"])

with tabs[0]:
    tbl = pd.DataFrame({
        "Duration t": dec["duration"].astype(int),
        "Exposed at start of t": dec["exposed"].astype(int),
        "Lapses in t": dec["lapses"].astype(int),
        "q(t)": 100 * dec["q"],
        "95% CI, lower": 100 * dec["q_lower_95"],
        "95% CI, upper": 100 * dec["q_upper_95"],
        "Persistency to end of t": 100 * dec["persistency"],
    })
    peak = int(worst["duration"])
    st.dataframe(
        tbl.style.apply(lambda r: [f"background-color: {ui.HIGHLIGHT_ROW}" if r["Duration t"] == peak else "" for _ in r], axis=1),
        hide_index=True, use_container_width=True,
        column_config={
            "Duration t": st.column_config.NumberColumn(help="The t-th monthly instalment after the deposit"),
            "Exposed at start of t": st.column_config.NumberColumn(format="localized"),
            "Lapses in t": st.column_config.NumberColumn(format="localized"),
            "q(t)": st.column_config.NumberColumn(format="%.1f%%", help="Crude monthly lapse rate: lapses / exposed"),
            "95% CI, lower": st.column_config.NumberColumn(format="%.1f%%"),
            "95% CI, upper": st.column_config.NumberColumn(format="%.1f%%"),
            "Persistency to end of t": st.column_config.ProgressColumn(format="%.1f%%", min_value=0.0, max_value=100.0),
        },
    )
    early = dec.loc[dec["duration"] <= 4, "lapses"].sum() / dec["lapses"].sum()
    ui.takeaway(
        f"{ui.pct(early)} of all lapses happen in the first four instalments. The peak (shaded) is at instalment "
        f"{peak}, where {ui.pct(worst['q'])} of members still in force lapse."
    )
    ui.show_sql(Q.inline(Q.DECREMENTS.format(where=where), params), ["v_exposure_monthly"])

with tabs[1]:
    coh = ui.q(Q.COHORTS.format(where=where), params)
    heat = coh.pivot(index="inception_month", columns="duration", values="persistency").sort_index()
    fig = go.Figure(go.Heatmap(
        z=heat.values, x=[f"t={c}" for c in heat.columns], y=[d.strftime("%b %Y") for d in heat.index],
        colorscale=ui.SEQ_SCALE, zmin=0.4, zmax=1,
        colorbar=dict(title="Persistency", tickformat=".0%"),
        hovertemplate="Cohort %{y}<br>Duration %{x}<br>Persistency %{z:.1%}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", title="Inception month")
    fig.update_xaxes(title="Duration (instalment number)", side="top")
    fig.update_layout(title="")
    ui.plot(fig, 560)
    CAL_SQL = f"""
    SELECT CASE month(inception_month + to_months(duration)) WHEN 1 THEN 'January' WHEN 12 THEN 'December' ELSE 'Other months' END AS due_month,
           SUM(lapsed) / SUM(exposed) AS q
    FROM v_exposure_monthly
    WHERE {where}
    GROUP BY 1
    """
    cal = ui.q(CAL_SQL, params).set_index("due_month")["q"]
    if {"January", "Other months"} <= set(cal.index):
        ui.takeaway(
            f"Blank cells are durations not yet observed at the valuation date. Instalments falling due in January lapse at "
            f"{ui.pct(cal['January'])} against {ui.pct(cal['Other months'])} in other months: school fees show up as diagonal bands."
        )
    ui.show_sql(Q.inline(Q.COHORTS.format(where=where), params) + ";\n\n-- Calendar effect\n" + Q.inline(CAL_SQL, params), ["v_cohort_persistency"])

with tabs[2]:
    group_col = {"Income type": "income_type", "Channel": "channel", "Plan tier": "plan_tier",
                 "Deposit band": "deposit_band", "Payment method": "payment_method"}[compare]
    surv = ui.q(Q.SURVIVAL.format(where=where, group_col=group_col), params)


    @st.cache_data(show_spinner=False)
    def km_curves(df: pd.DataFrame) -> pd.DataFrame:
        out = []
        for g, d in df.groupby("grp"):
            k = KaplanMeierFitter().fit(d["duration_observed"], d["lapsed"])
            s = k.survival_function_.join(k.confidence_interval_)
            s.columns = ["s", "lo", "hi"]
            s = s.reset_index().rename(columns={"timeline": "t"})
            s["grp"], s["n"] = g, len(d)
            out.append(s)
        return pd.concat(out, ignore_index=True)


    km = km_curves(surv)
    fig = go.Figure()
    order = km.groupby("grp")["s"].min().sort_values(ascending=False).index
    colors = {g: ui.SERIES[i % len(ui.SERIES)] for i, g in enumerate(sorted(km["grp"].unique()))}
    for g in order:
        d = km[km["grp"] == g]
        c = colors[g]
        rgb = tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        fig.add_trace(go.Scatter(x=d["t"], y=d["hi"], mode="lines", line=dict(width=0, shape="hv"), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=d["t"], y=d["lo"], mode="lines", line=dict(width=0, shape="hv"), fill="tonexty",
                                 fillcolor=f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.14)", hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=d["t"], y=d["s"], mode="lines", name=f"{g} (n={d['n'].iloc[0]:,})", line=dict(color=c, width=2, shape="hv"),
                                 hovertemplate=f"{g}<br>Instalment %{{x}}<br>Persistency %{{y:.1%}}<extra></extra>"))
    fig.update_yaxes(tickformat=".0%", title="Share still in force", range=[0, 1.02])
    fig.update_xaxes(title="Duration (instalment number)", dtick=1, range=[0, 10.3])
    ui.plot(fig, 420)
    end = km.sort_values("t").groupby("grp").last()["s"].sort_values()
    ui.takeaway(
        f"By {compare.lower()}, {end.index[0]} keeps the fewest members ({ui.pct(end.iloc[0])} in force at the last observed "
        f"duration) and {end.index[-1]} the most ({ui.pct(end.iloc[-1])}). Policies still in force at the valuation date are censored, not counted as lapses."
    )
    ui.show_sql(Q.inline(Q.SURVIVAL.format(where=where, group_col=group_col), params), ["v_policy_survival"])
    st.caption("Kaplan-Meier on these discrete durations gives exactly the same persistency as the decrement table: both are the product of (1 - lapses / exposed).")

ui.footer()
