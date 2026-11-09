import numpy as np
import plotly.graph_objects as go
import streamlit as st

from src import ui

ui.page("The Problem", "Cover that starts on the first payment means benefits run ahead of cash.")
cfg = ui.config()
g, r = cfg["product"]["grace_days"], cfg["product"]["reinstatement_days"]

left, right = st.columns([1.05, 1])
with left:
    st.markdown(
        f"""
**The product, in plain words.** A 12-month health cover. The member pays a deposit (from 10% of the annual
premium) and cover starts straight away. The rest is paid in up to 10 monthly instalments. Waiting periods,
exclusions and benefit limits still apply.

**When a payment is missed.** The member has {g} days of grace. After that, cover is suspended. If the
instalment is still unpaid {r} days later, the policy lapses and no further premium is collected.

**Why this changes the risk.** In a pay-upfront annual policy, the insurer holds the full premium before
any claim. Here, on day one the insurer may hold only 10% of the premium while the member can claim
against the full annual limits. A member who claims early and then stops paying has been covered by
premium that was never collected. That is a lapse problem and an anti-selection problem at once.
"""
    )
with right:
    months = np.arange(0, 13)
    paid = np.minimum(0.10 + 0.09 * months, 1.0)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=months, y=np.ones_like(months, dtype=float), name="Annual benefit limit available",
                             mode="lines", line=dict(color=ui.ORANGE, width=2), hovertemplate="Month %{x}: 100% of limit<extra></extra>"))
    fig.add_trace(go.Scatter(x=months, y=paid, name="Premium paid so far (10% deposit, 10 instalments)", mode="lines+markers",
                             line=dict(color=ui.BLUE, width=2, shape="hv"), marker=dict(size=8),
                             hovertemplate="Month %{x}: %{y:.0%} of premium paid<extra></extra>"))
    fig.update_yaxes(tickformat=".0%", range=[0, 1.08], title="Share of annual amount")
    fig.update_xaxes(title="Policy month", dtick=1)
    fig.update_layout(title="Cover available versus premium paid")
    ui.plot(fig, 330)
    ui.takeaway("On day one the member has paid 10% of the premium but can claim against 100% of the annual limits.")

st.subheader("What the synthetic book shows")
dec = ui.q("SELECT duration, exposed, lapses, q, persistency FROM v_lapse_decrements ORDER BY duration")
ctc = ui.q("SELECT persistency_group, policies, collected_kes, claims_paid_kes, claims_to_collected "
           "FROM v_claims_to_collected WHERE deposit_band = 'All'").set_index("persistency_group")
leak = ui.q("SELECT SUM(leakage_kes) AS leakage_kes, COUNT(*) AS lapsed_policies, SUM(is_leaking::INT) AS leaking_policies FROM v_leakage")
p10 = dec.loc[dec["duration"] == 10, "persistency"].iloc[0]

c1, c2, c3 = st.columns(3)
ui.kpi(c1, "Persistency at month 10", ui.pct(p10), f"{ui.pct(1 - p10)} of policies lapse before their 10th instalment")
ui.kpi(c2, "Claims to collected premium, lapsers", ui.pct(ctc.loc["Lapser", "claims_to_collected"]),
       f"Stayers: {ui.pct(ctc.loc['Stayer', 'claims_to_collected'])}")
ui.kpi(c3, "Leakage on lapsed policies", ui.kes(leak["leakage_kes"].iloc[0], short=True),
       f"{int(leak['leaking_policies'].iloc[0]):,} of {int(leak['lapsed_policies'].iloc[0]):,} lapsed policies claimed more than they paid")
st.write("")
ratio = ctc.loc["Lapser", "claims_to_collected"] / ctc.loc["Stayer", "claims_to_collected"]
ui.takeaway(
    f"Members who lapse are paid KES {ctc.loc['Lapser', 'claims_to_collected']:.2f} in claims for every KES 1 they paid in, "
    f"{ratio:.1f} times the rate for members who stay."
)

ui.show_sql(
    """
-- Persistency at month 10
SELECT duration, exposed, lapses, q, persistency FROM v_lapse_decrements ORDER BY duration;

-- Claims to collected premium, stayers versus lapsers (run-off cohorts)
SELECT persistency_group, policies, collected_kes, claims_paid_kes, claims_to_collected
FROM v_claims_to_collected WHERE deposit_band = 'All';

-- Leakage: claims in excess of premium collected on lapsed policies
SELECT SUM(leakage_kes) AS leakage_kes, COUNT(*) AS lapsed_policies, SUM(is_leaking::INT) AS leaking_policies
FROM v_leakage;
""",
    ["v_lapse_decrements", "v_claims_to_collected", "v_leakage"],
)

st.subheader("The three questions")
a, b, c = st.columns(3)
a.markdown("**Who lapses, and when?**  \nLapse decrements by policy duration, cohort and segment, with exposure and confidence intervals. See Persistency Explorer.")
b.markdown("**What does lapse cost?**  \nClaims paid against premium actually collected, split by stayers and lapsers, and leakage in KES. See Anti-Selection and Leakage.")
c.markdown("**Which levers fix it?**  \nDeposit, instalments, grace, waiting periods, benefit release and loading, tested on the fitted models. See Product Levers Simulator.")
ui.footer()
