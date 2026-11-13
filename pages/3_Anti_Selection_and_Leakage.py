import plotly.graph_objects as go
import streamlit as st

from src import ui

ui.page(
    "cost",
    "Lapse on its own is lost premium. It gets expensive when the members who lapse are the ones who claimed. This chapter sets what stayers and lapsers were paid against what they actually paid in. Run-off cohorts only, so every policy here has a final outcome.",
)

# ------------------------------------------------------------- claims to collected
CTC_SQL = """
SELECT persistency_group, deposit_band, policies, collected_kes, claims_paid_kes,
       claims_to_collected, avg_collected_kes, avg_claims_kes, share_with_claim
FROM v_claims_to_collected
ORDER BY persistency_group DESC, deposit_band
"""
ctc = ui.q(CTC_SQL)
allr = ctc[ctc["deposit_band"] == "All"].set_index("persistency_group")
L, S = allr.loc["Lapser"], allr.loc["Stayer"]

c1, c2, c3, c4 = st.columns(4)
ui.kpi(c1, "Claims to collected, stayers", ui.pct(S["claims_to_collected"]), f"{int(S['policies']):,} policies")
ui.kpi(c2, "Claims to collected, lapsers", ui.pct(L["claims_to_collected"]), f"{int(L['policies']):,} policies")
ui.kpi(c3, "Average paid in by a lapser", ui.kes(L["avg_collected_kes"]), f"Stayer: {ui.kes(S['avg_collected_kes'])}")
ui.kpi(c4, "Average claims paid to a lapser", ui.kes(L["avg_claims_kes"]), f"Stayer: {ui.kes(S['avg_claims_kes'])}")
st.write("")

band = ctc[ctc["deposit_band"] != "All"]
ui.plot(ui.ctc_by_deposit_figure(band), 400)
low = band[(band["persistency_group"] == "Lapser") & (band["deposit_band"] == "10%")]["claims_to_collected"].iloc[0]
high = band[(band["persistency_group"] == "Lapser") & (band["deposit_band"] == "30 to 40%")]["claims_to_collected"].iloc[0]
ui.takeaway(
    f"Lapsers who paid a 10% deposit were paid {ui.pct(low, 0)} of what they paid in, against {ui.pct(high, 0)} for lapsers "
    f"on a 30 to 40% deposit. Stayers sit near {ui.pct(S['claims_to_collected'], 0)} across the board."
)
ui.show_sql(CTC_SQL, ["v_claims_to_collected"])

st.write("")
tabs = st.tabs([':material/event_busy: When members lapse', ':material/medical_services: Claim, then lapse', ':material/vertical_align_top: Front-loaded claims', ':material/water_drop: Leakage by segment'])

with tabs[0]:
    DUR_SQL = """
    SELECT lapse_duration,
           COUNT(*)                      AS lapsed_policies,
           AVG(collected_kes)            AS avg_collected_kes,
           AVG(claims_paid_kes)          AS avg_claims_kes,
           SUM(leakage_kes)              AS leakage_kes,
           AVG(is_leaking::INT)          AS share_leaking
    FROM v_leakage
    GROUP BY lapse_duration
    ORDER BY lapse_duration
    """
    dur = ui.q(DUR_SQL)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=dur["lapse_duration"], y=dur["avg_collected_kes"], name="Premium collected per policy", marker_color=ui.PRIMARY,
                         hovertemplate="Lapsed at instalment %{x}<br>Collected KES %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Bar(x=dur["lapse_duration"], y=dur["avg_claims_kes"], name="Claims paid per policy", marker_color=ui.ACCENT,
                         hovertemplate="Lapsed at instalment %{x}<br>Claims KES %{y:,.0f}<extra></extra>"))
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(title="KES per lapsed policy", tickformat=",.0f")
    fig.update_xaxes(title="Instalment at which the policy lapsed", dtick=1)
    ui.plot(fig, 360)
    worst = dur.loc[(dur["avg_claims_kes"] / dur["avg_collected_kes"]).idxmax()]
    ui.takeaway(
        f"Members who lapse at instalment {int(worst['lapse_duration'])} paid in {ui.kes(worst['avg_collected_kes'])} on average and were "
        f"paid {ui.kes(worst['avg_claims_kes'])} in claims, {worst['avg_claims_kes'] / worst['avg_collected_kes']:.1f} times what they paid."
    )
    ui.show_sql(DUR_SQL, ["v_leakage"])

with tabs[1]:
    left, right = st.columns(2)
    NEXT_SQL = "SELECT claim_history, instalments, missed_due_date_rate, lapse_rate FROM v_large_claim_next_instalment"
    nxt = ui.q(NEXT_SQL).set_index("claim_history")
    with left:
        fig = go.Figure()
        for metric, name, color in [("missed_due_date_rate", "Missed the due date", ui.PRIMARY), ("lapse_rate", "Lapsed on that instalment", ui.ACCENT)]:
            fig.add_trace(go.Bar(x=nxt.index, y=nxt[metric], name=name, marker_color=color, text=[ui.pct(v) for v in nxt[metric]],
                                 textposition="outside", hovertemplate="%{x}<br>" + name + ": %{y:.1%}<extra></extra>"))
        fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08, title="The next instalment after a large claim")
        fig.update_yaxes(tickformat=".0%", rangemode="tozero")
        ui.plot(fig, 360)
        a = nxt.loc["Large claim settled in window", "lapse_rate"]
        b = nxt.loc["No recent large claim", "lapse_rate"]
        cfg = ui.config()
        ui.takeaway(
            f"After a claim of KES {cfg['anti_selection']['large_claim_kes']:,} or more is settled, {ui.pct(a)} of next instalments end in lapse, "
            f"{a / b:.1f} times the {ui.pct(b)} rate otherwise."
        )
    TIMING_SQL = """
    SELECT days_claim_to_lapse, last_large_claim_benefit, claims_paid_kes, collected_kes
    FROM v_claim_then_lapse
    """
    tim = ui.q(TIMING_SQL)
    with right:
        fig = go.Figure(go.Histogram(x=tim["days_claim_to_lapse"], xbins=dict(start=0, end=tim["days_claim_to_lapse"].max() + 15, size=15),
                                     marker=dict(color=ui.ACCENT, line=dict(color=ui.SURFACE, width=2)),
                                     hovertemplate="%{x} days<br>%{y} policies<extra></extra>"))
        fig.update_layout(title="Days from last large claim payment to lapse", bargap=0.05)
        fig.update_xaxes(title="Days")
        fig.update_yaxes(title="Lapsed policies")
        ui.plot(fig, 360)
        within = (tim["days_claim_to_lapse"] <= 90).mean()
        ui.takeaway(
            f"{len(tim):,} lapsed policies had a large claim before lapsing; {ui.pct(within)} lapsed within 90 days of that claim being paid "
            f"(median {tim['days_claim_to_lapse'].median():.0f} days, of which 46 are the grace and reinstatement window)."
        )
    ui.show_sql(NEXT_SQL + ";\n\n" + TIMING_SQL, ["v_large_claim_next_instalment", "v_instalment_outcomes", "v_claim_then_lapse"])

with tabs[2]:
    EARLY_SQL = "SELECT deposit_band, early_freq_per_unit, later_freq_per_unit FROM v_early_claims_by_deposit"
    early = ui.q(EARLY_SQL)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=early["deposit_band"], y=early["early_freq_per_unit"], name="Cover months 1 to 3", marker_color=ui.ACCENT,
                         hovertemplate="Deposit %{x}<br>%{y:.3f} claims per member-month<extra></extra>"))
    fig.add_trace(go.Bar(x=early["deposit_band"], y=early["later_freq_per_unit"], name="Cover months 4 to 10", marker_color=ui.PRIMARY,
                         hovertemplate="Deposit %{x}<br>%{y:.3f} claims per member-month<extra></extra>"))
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08, title="Outpatient and inpatient claim frequency per member-month")
    fig.update_yaxes(title="Claims per member-month", rangemode="tozero")
    fig.update_xaxes(title="Deposit as share of annual premium", type="category")
    ui.plot(fig, 340)
    e = early.set_index("deposit_band")
    ui.takeaway(
        f"In the first three months, members on a 10% deposit claim {e.loc['10%', 'early_freq_per_unit'] / e.loc['30 to 40%', 'early_freq_per_unit']:.2f} "
        f"times as often as members on a 30 to 40% deposit. From month 4 the gap closes, because many of the early claimers have lapsed."
    )
    ui.show_sql(EARLY_SQL, ["v_early_claims_by_deposit", "v_claim_frequency"])

with tabs[3]:
    dim = st.radio("Segment by", ["Channel", "Income type", "Plan tier", "Deposit band", "Payment method"], horizontal=True)
    col = {"Channel": "channel", "Income type": "income_type", "Plan tier": "plan_tier", "Deposit band": "deposit_band",
           "Payment method": "payment_method"}[dim]
    SEG_SQL = f"""
    SELECT l.{col} AS segment,
           SUM(l.leakage_kes)                                   AS leakage_kes,
           COUNT(*)                                             AS lapsed_policies,
           AVG(l.is_leaking::INT)                               AS share_leaking,
           SUM(l.leakage_kes) / w.written_kes                   AS leakage_share_of_written
    FROM v_leakage l
    JOIN (SELECT {col}, SUM(annual_premium_kes) AS written_kes FROM v_policy WHERE is_run_off GROUP BY {col}) w USING ({col})
    GROUP BY l.{col}, w.written_kes
    ORDER BY leakage_share_of_written DESC
    """
    seg = ui.q(SEG_SQL)
    total_leak = seg["leakage_kes"].sum()
    fig = go.Figure(go.Bar(
        y=seg["segment"], x=seg["leakage_share_of_written"], orientation="h", marker_color=ui.ACCENT,
        text=[f"{ui.pct(v)}  ({ui.kes(k, short=True)})" for v, k in zip(seg["leakage_share_of_written"], seg["leakage_kes"])],
        textposition="outside", customdata=seg[["leakage_kes", "lapsed_policies", "share_leaking"]],
        hovertemplate="%{y}<br>Leakage %{x:.1%} of written premium<br>KES %{customdata[0]:,.0f}<br>"
                      "%{customdata[1]:,} lapsed policies, %{customdata[2]:.0%} leaking<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", title="", type="category")
    fig.update_xaxes(tickformat=".0%", title="Leakage as share of written premium", range=[0, seg["leakage_share_of_written"].max() * 1.45])
    fig.update_layout(title=f"Claims in excess of premium collected on lapsed policies, by {dim.lower()}")
    ui.plot(fig, 120 + 48 * len(seg))
    top = seg.iloc[0]
    ui.takeaway(
        f"Total leakage in the run-off book is {ui.kes(total_leak)}. {top['segment']} leaks the most relative to its size: "
        f"{ui.pct(top['leakage_share_of_written'])} of written premium."
    )
    ui.show_sql(SEG_SQL, ["v_leakage"])

ui.footer()
