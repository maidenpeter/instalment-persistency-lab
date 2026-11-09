import streamlit as st

from src import ui


def home() -> None:
    ui.page(
        "Instalment Persistency Lab",
        "Some health covers now start on the first instalment: the member pays a small deposit and the rest "
        "monthly. That widens access. It also lets a member pay a little, claim early and stop paying. "
        "This lab measures who lapses and when, what lapse costs in claims paid against premium actually "
        "collected, and which product levers close the gap.",
    )

    dec = ui.q("SELECT persistency FROM v_lapse_decrements WHERE duration = 10")
    ctc = ui.q("SELECT persistency_group, claims_to_collected FROM v_claims_to_collected WHERE deposit_band = 'All'")
    leak = ui.q("SELECT SUM(leakage_kes) AS leakage FROM v_leakage")
    lapser = ctc.set_index("persistency_group").loc["Lapser", "claims_to_collected"]
    stayer = ctc.set_index("persistency_group").loc["Stayer", "claims_to_collected"]

    c1, c2, c3 = st.columns(3)
    ui.kpi(c1, "Still in force after 10 instalments", ui.pct(dec["persistency"].iloc[0]), "Kaplan-Meier style product of monthly decrements")
    ui.kpi(c2, "Claims paid per KES 1 collected, lapsers", f"KES {lapser:.2f}", f"Stayers: KES {stayer:.2f}")
    ui.kpi(c3, "Claims paid in excess of premium on lapsed policies", ui.kes(leak["leakage"].iloc[0], short=True), "Run-off cohorts only")
    st.write("")

    st.subheader("How to read this lab")
    pages = [
        ("1. The Problem", "The product structure and why first-payment activation changes the risk."),
        ("2. Persistency Explorer", "Lapse decrements by duration with exposure and confidence intervals, cohort heatmap, Kaplan-Meier curves."),
        ("3. Anti-Selection and Leakage", "Claims against premium collected for stayers and lapsers, claim-then-lapse timing, leakage in KES."),
        ("4. Early Warning Model", "Who is likely to miss the next instalment, how well the model ranks them, and a call list for this week."),
        ("5. Product Levers Simulator", "Deposit, instalments, grace, waiting periods, benefit release and loading, simulated on the fitted models."),
        ("6. Methods and Assumptions", "Data dictionary, every assumption, diagnostics, the R cross-check and an IFRS 17 discussion note."),
    ]
    cols = st.columns(2)
    for i, (name, desc) in enumerate(pages):
        cols[i % 2].markdown(f"**{name}**  \n{desc}")

    st.write("")
    st.markdown(
        "Built with SQL (DuckDB) for every business metric, Python for data generation, survival models and "
        "simulation, and R for an independent cross-check of the survival estimates. Use the sidebar to move between pages."
    )
    ui.show_sql(
        "SELECT persistency FROM v_lapse_decrements WHERE duration = 10;\n"
        "SELECT persistency_group, claims_to_collected FROM v_claims_to_collected WHERE deposit_band = 'All';\n"
        "SELECT SUM(leakage_kes) AS leakage FROM v_leakage;",
        ["v_lapse_decrements", "v_claims_to_collected", "v_leakage"],
    )
    ui.footer()


nav = st.navigation(
    [
        st.Page(home, title="Home", default=True),
        st.Page("pages/1_The_Problem.py", title="The Problem", url_path="the-problem"),
        st.Page("pages/2_Persistency_Explorer.py", title="Persistency Explorer", url_path="persistency-explorer"),
        st.Page("pages/3_Anti_Selection_and_Leakage.py", title="Anti-Selection and Leakage", url_path="anti-selection-and-leakage"),
        st.Page("pages/4_Early_Warning_Model.py", title="Early Warning Model", url_path="early-warning-model"),
        st.Page("pages/5_Product_Levers_Simulator.py", title="Product Levers Simulator", url_path="product-levers-simulator"),
        st.Page("pages/6_Methods_and_Assumptions.py", title="Methods and Assumptions", url_path="methods-and-assumptions"),
    ]
)
nav.run()
