import streamlit as st

from src import ui


def home() -> None:
    ui.page(
        "Instalment Persistency Lab",
        "A member pays a 10% deposit, claims in the first few months, then stops paying. How often does that happen, "
        "what does it cost in claims paid against premium actually collected, and which product changes stop it?",
    )
    dec = ui.q(HOME_SQL["persistency"])
    ctc = ui.q(HOME_SQL["claims_to_collected"])
    leak = ui.q(HOME_SQL["leakage"])
    allr = ctc[ctc["deposit_band"] == "All"].set_index("persistency_group")
    lapser, stayer = allr.loc["Lapser", "claims_to_collected"], allr.loc["Stayer", "claims_to_collected"]

    c1, c2, c3 = st.columns(3)
    ui.kpi(c1, "Still in force after 10 instalments", ui.pct(dec["persistency"].iloc[0]), "Product of the monthly lapse decrements")
    ui.kpi(c2, "Claims paid per KES 1 collected, lapsers", f"KES {lapser:.2f}", f"Stayers: KES {stayer:.2f}")
    ui.kpi(c3, "Claims in excess of premium, lapsed policies", ui.kes(leak["leakage"].iloc[0], short=True),
           f"{int(leak['leaking'].iloc[0]):,} of {int(leak['lapsed'].iloc[0]):,} lapsed policies claimed more than they paid")
    st.write("")
    band = ctc[ctc["deposit_band"] != "All"]
    ui.plot(ui.ctc_by_deposit_figure(band), 380)
    low = band[(band["persistency_group"] == "Lapser") & (band["deposit_band"] == "10%")]["claims_to_collected"].iloc[0]
    ui.takeaway(
        f"Members who lapse after a 10% deposit were paid {ui.pct(low, 0)} of what they paid in. Members who stay sit near "
        f"{ui.pct(stayer, 0)} whatever the deposit. The gap is the cost of cover that starts before the premium is in."
    )
    ui.show_sql(";\n\n".join(HOME_SQL.values()), ["v_lapse_decrements", "v_claims_to_collected", "v_leakage"])

    st.subheader("Inside the lab")
    cards = [
        ("pages/1_The_Problem.py", "The Problem", "The product structure, and why first-payment activation changes the risk."),
        ("pages/2_Persistency_Explorer.py", "Persistency Explorer", "Lapse decrements by duration with exposure and confidence intervals, cohort heatmap, Kaplan-Meier curves."),
        ("pages/3_Anti_Selection_and_Leakage.py", "Anti-Selection and Leakage", "Claims against premium collected for stayers and lapsers, claim-then-lapse timing, leakage in KES."),
        ("pages/7_Policy_Lookup.py", "Policy Lookup", "Open any single policy and follow it month by month: premium in, claims out, late payments and risk."),
        ("pages/4_Early_Warning_Model.py", "Early Warning Model", "Who will miss the next instalment, how well the model ranks them, and a call list for this week."),
        ("pages/5_Product_Levers_Simulator.py", "Product Levers Simulator", "Deposit, instalments, grace, waiting periods, benefit release and loading, run on the fitted models."),
        ("pages/6_Methods_and_Assumptions.py", "Methods and Assumptions", "Data dictionary, every assumption, model diagnostics, the R cross-check and an IFRS 17 note."),
    ]
    cols = st.columns(3)
    for i, (path, name, desc) in enumerate(cards):
        with cols[i % 3].container(border=True):
            st.page_link(path, label=f"**{name}**")
            st.caption(desc)
    st.caption(
        "SQL (DuckDB) computes every business metric, Python generates the data and fits the survival models and simulation, "
        "and R cross-checks the survival estimates."
    )
    ui.footer()


HOME_SQL = {
    "persistency": "SELECT persistency FROM v_lapse_decrements WHERE duration = 10",
    "claims_to_collected": "SELECT persistency_group, deposit_band, policies, collected_kes, claims_paid_kes, claims_to_collected\n"
                           "FROM v_claims_to_collected ORDER BY persistency_group DESC, deposit_band",
    "leakage": "SELECT SUM(leakage_kes) AS leakage, COUNT(*) AS lapsed, SUM(is_leaking::INT) AS leaking FROM v_leakage",
}


nav = st.navigation(
    [
        st.Page(home, title="Home", default=True),
        st.Page("pages/1_The_Problem.py", title="The Problem", url_path="the-problem"),
        st.Page("pages/2_Persistency_Explorer.py", title="Persistency Explorer", url_path="persistency-explorer"),
        st.Page("pages/3_Anti_Selection_and_Leakage.py", title="Anti-Selection and Leakage", url_path="anti-selection-and-leakage"),
        st.Page("pages/7_Policy_Lookup.py", title="Policy Lookup", url_path="policy-lookup"),
        st.Page("pages/4_Early_Warning_Model.py", title="Early Warning Model", url_path="early-warning-model"),
        st.Page("pages/5_Product_Levers_Simulator.py", title="Product Levers Simulator", url_path="product-levers-simulator"),
        st.Page("pages/6_Methods_and_Assumptions.py", title="Methods and Assumptions", url_path="methods-and-assumptions"),
    ]
)
nav.run()
