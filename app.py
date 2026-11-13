import streamlit as st

from src import ui

HOME_SQL = {
    "persistency": "SELECT persistency FROM v_lapse_decrements WHERE duration = 10",
    "claims_to_collected": "SELECT persistency_group, deposit_band, policies, collected_kes, claims_paid_kes, claims_to_collected\n"
                           "FROM v_claims_to_collected ORDER BY persistency_group DESC, deposit_band",
    "leakage": "SELECT SUM(leakage_kes) AS leakage, COUNT(*) AS lapsed, SUM(is_leaking::INT) AS leaking,\n"
               "       (SELECT COUNT(*) FROM v_policy WHERE is_run_off) AS run_off\nFROM v_leakage",
}


def home() -> None:
    ui.page(
        "home",
        "A member pays a 10% deposit, claims in the first few months, then stops paying. This lab follows that story "
        "through a synthetic book of 20,000 health covers: how often it happens, what it costs in claims paid against "
        "premium actually collected, and which product changes stop it.",
    )
    dec = ui.q(HOME_SQL["persistency"])
    ctc = ui.q(HOME_SQL["claims_to_collected"])
    leak = ui.q(HOME_SQL["leakage"])
    allr = ctc[ctc["deposit_band"] == "All"].set_index("persistency_group")
    lapser, stayer = allr.loc["Lapser", "claims_to_collected"], allr.loc["Stayer", "claims_to_collected"]

    c1, c2, c3 = st.columns(3)
    ui.kpi(c1, "Still in force after 10 instalments", ui.pct(dec["persistency"].iloc[0]),
           "Observed book, all deposit sizes. Product of the monthly lapse decrements")
    ui.kpi(c2, "Claims paid per KES 1 collected, lapsers", f"KES {lapser:.2f}", f"Stayers: KES {stayer:.2f}")
    ui.kpi(c3, "Claims in excess of premium, lapsed policies", ui.kes(leak["leakage"].iloc[0], short=True),
           f"{int(leak['leaking'].iloc[0]):,} of {int(leak['lapsed'].iloc[0]):,} lapsed policies claimed more than they paid. "
           f"Counted among the {int(leak['run_off'].iloc[0]):,} policies whose year of cover has ended; younger policies are still running.")
    st.write("")
    band = ctc[ctc["deposit_band"] != "All"]
    ui.plot(ui.ctc_by_deposit_figure(band), 380)
    low = band[(band["persistency_group"] == "Lapser") & (band["deposit_band"] == "10%")]["claims_to_collected"].iloc[0]
    ui.takeaway(
        f"Members who lapse after a 10% deposit were paid {ui.pct(low, 0)} of what they paid in. Members who stay sit near "
        f"{ui.pct(stayer, 0)} whatever the deposit. The gap is the cost of cover that starts before the premium is in."
    )
    ui.show_sql(";\n\n".join(HOME_SQL.values()), ["v_lapse_decrements", "v_claims_to_collected", "v_leakage"])

    st.subheader(":material/auto_stories: The story in six chapters")
    for i, c in enumerate(ui.CHAPTERS, 1):
        left, right = st.columns([0.07, 0.93], vertical_alignment="center")
        left.markdown(f'<div class="kicker" style="font-size:0.95rem">{i:02d}</div>', unsafe_allow_html=True)
        with right:
            st.page_link(c["path"], label=f"**{c['title']}**", icon=c["icon"])
            st.caption(c["teaser"])
    st.page_link(ui.APPENDIX["path"], label=f"Appendix: {ui.APPENDIX['title']}", icon=ui.APPENDIX["icon"])
    st.caption(
        "SQL (DuckDB) computes every business metric, Python generates the data and fits the survival models and simulation, "
        "and R cross-checks the survival estimates."
    )
    ui.footer()


st.logo(str(ui.ASSETS / "mark.svg"), size="large")  # the app name is set beside it in the top bar (src/ui.py)
pages = [st.Page(home, title="Home", icon=":material/home:", default=True)]
pages += [st.Page(c["path"], title=c["nav"], url_path=c["url"], icon=c["icon"]) for c in ui.CHAPTERS]
pages += [st.Page(ui.APPENDIX["path"], title=ui.APPENDIX["nav"], url_path=ui.APPENDIX["url"], icon=ui.APPENDIX["icon"])]
st.navigation(pages, position="top").run()
