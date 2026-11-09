import re

import numpy as np
import pandas as pd
import streamlit as st

from src import models as M
from src import simulate as SM
from src import ui
from src.generate import CONFIG_PATH, ROOT

ui.page("Methods and Assumptions", "How every number in this lab is built, what it assumes, and where it is weak.")
cfg = ui.config()

tabs = st.tabs(["Data", "Assumptions", "Definitions", "Survival models", "R cross-check", "Simulator check", "Limitations", "IFRS 17 note"])

# ------------------------------------------------------------- data dictionary
DICT = {
    "policies": {
        "policy_id": "Policy key", "inception_date": "Date cover started (first payment)", "plan_tier": "Starter, Mid or Comprehensive",
        "annual_premium_kes": "Annual premium on the schedule, KES", "deposit_pct": "Deposit as share of annual premium",
        "n_instalments": "Monthly instalments after the deposit", "channel": "online, USSD or agent", "payment_method": "M-Pesa STK, paybill or bank",
        "income_type": "salaried, variable/informal or SME group", "region": "Region of the principal member", "family_size": "Members covered",
        "principal_age": "Age of the principal member at inception",
    },
    "schedule": {"policy_id": "Policy key", "instalment_no": "0 = deposit, then 1 to n", "due_date": "Due date", "amount_due_kes": "Amount due, KES"},
    "payments": {"policy_id": "Policy key", "instalment_no": "Instalment paid", "paid_date": "Date paid, empty if unpaid at valuation",
                 "amount_paid_kes": "Cash received, KES", "days_late": "Days after the due date, 0 if on time"},
    "status_events": {"policy_id": "Policy key", "event_date": "Date of the event", "event": "active, suspended, reinstated, lapsed or completed"},
    "claims": {"claim_id": "Claim key", "policy_id": "Policy key", "service_date": "Date of treatment", "paid_date": "Date the claim was paid",
               "benefit_type": "outpatient, inpatient, maternity or chronic", "amount_paid_kes": "Amount paid, KES"},
}
with tabs[0]:
    counts = ui.q("SELECT 'policies' AS t, COUNT(*) AS n FROM policies UNION ALL SELECT 'schedule', COUNT(*) FROM schedule "
                  "UNION ALL SELECT 'payments', COUNT(*) FROM payments UNION ALL SELECT 'status_events', COUNT(*) FROM status_events "
                  "UNION ALL SELECT 'claims', COUNT(*) FROM claims").set_index("t")["n"]
    st.markdown(
        f"Five tables from a seeded generator (`src/generate.py`, seed {cfg['seed']}), observed at the valuation date "
        f"**{pd.Timestamp(cfg['book']['valuation_date']):%d %B %Y}**: nothing after that date is visible to any query or model."
    )
    for t, cols in DICT.items():
        st.markdown(f"**{t}** ({counts[t]:,} rows)")
        st.dataframe(pd.DataFrame({"Column": list(cols), "Meaning": list(cols.values())}), hide_index=True, use_container_width=True)
    st.markdown("**SQL views** (`sql/01` to `sql/08`, run in order by `src/db.py`)")
    views = ui.q("SELECT table_name FROM information_schema.tables WHERE table_type = 'VIEW' AND table_name LIKE 'v_%' ORDER BY 1")
    st.write(", ".join(f"`{v}`" for v in views["table_name"]))


# ------------------------------------------------------------- assumptions from config comments
def config_rows(path) -> pd.DataFrame:
    rows, stack = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        m = re.match(r"\s*([^:#]+):\s*(.*?)\s*(?:#\s*(.*))?$", line)
        if not m:
            continue
        key, value, note = m.group(1).strip().strip('"'), m.group(2).strip(), (m.group(3) or "").strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path_ = " / ".join([s[1] for s in stack] + [key])
        if value == "":
            stack.append((indent, key))
            if note:
                rows.append({"Assumption": path_, "Value": "", "Note": note})
            continue
        rows.append({"Assumption": path_, "Value": value.strip('"'), "Note": note})
    return pd.DataFrame(rows)


with tabs[1]:
    st.markdown("Every parameter of the synthetic book, read straight from `src/config.yaml` with its comment. "
                "These are assumptions for an illustrative book, not market data or any insurer's experience.")
    st.dataframe(config_rows(CONFIG_PATH), hide_index=True, use_container_width=True, height=620)

# ------------------------------------------------------------- definitions
with tabs[2]:
    g, r = cfg["product"]["grace_days"], cfg["product"]["reinstatement_days"]
    st.markdown(
        f"""
- **Duration t.** The t-th monthly instalment after the deposit. Instalment t falls due t months after inception.
- **Lapse.** Instalment unpaid {g} days after the due date: cover is suspended. Still unpaid {r} days later: the policy lapses, on day {g + r + 1}.
  The lapse is attributed to the duration of the instalment that went unpaid.
- **Exposure E(t).** Policies in force at the start of duration t whose outcome for instalment t is known at the valuation date
  (due date + {g + r + 1} days has passed). Later durations are censored, not treated as survivals.
- **Crude decrement.** q(t) = lapses at t / E(t), with a 95% Wilson score interval. Persistency to t = product of (1 - q) up to t.
  Paid-up policies stay in the exposure with no lapse risk left, so persistency means still in force.
- **Run-off policy.** Cover ended at least {cfg['book']['runoff_days']} days before the valuation date, so its claims have had time to be paid.
  Claims-to-collected and leakage use run-off policies only.
- **Claims to collected.** Claims paid divided by premium actually received in cash, not premium written or earned.
- **Leakage.** On lapsed run-off policies, claims paid in excess of premium collected: max(claims - collected, 0), summed in KES.
- **Large claim.** A paid claim of KES {cfg['anti_selection']['large_claim_kes']:,} or more.
- **Claim frequency exposure.** Exposure units (members, eligible principals, members over 40) times the share of each cover month the policy was actually on cover.
"""
    )


@st.cache_resource(show_spinner="Fitting the Cox model and testing proportional hazards...")
def cox_fit():
    art = ui.artifacts()
    return art["cox"] if art else M.fit_cox(ui.q(M.SURVIVAL_SQL))


@st.cache_data(show_spinner=False)
def km_python():
    art = ui.artifacts()
    return art["km"] if art else M.km_python_table(ui.q(M.SURVIVAL_SQL))


# ------------------------------------------------------------- survival diagnostics
with tabs[3]:
    cr = cox_fit()
    st.markdown(
        "**Kaplan-Meier.** On these whole-month durations the Kaplan-Meier estimate equals the decrement table's product of (1 - q): "
        "same exposure, same events, same censoring."
    )
    kmp = km_python()
    dec = ui.q("SELECT duration, persistency FROM v_lapse_decrements")
    chk = kmp[kmp["group"] == "All"].merge(dec, on="duration", suffixes=("_km", "_sql"))
    st.caption(f"Largest gap between lifelines Kaplan-Meier and the SQL decrement table: {np.abs(chk['persistency_km'] - chk['persistency_sql']).max():.2e}")

    st.markdown(f"**Cox proportional hazards** (Efron ties, concordance {cr.concordance:.3f}). Hazard ratios above 1 mean faster lapse.")
    s = cr.summary.reset_index().rename(columns={"covariate": "Covariate"})
    s["95% CI"] = [f"{a:.2f} to {b:.2f}" for a, b in zip(s["hr_lower_95"], s["hr_upper_95"])]
    s = s[["Covariate", "hazard_ratio", "95% CI", "p_value"]].rename(columns={"hazard_ratio": "Hazard ratio", "p_value": "p-value"})
    st.dataframe(s.style.format({"Hazard ratio": "{:.3f}", "p-value": "{:.4f}"}), hide_index=True, use_container_width=True)
    st.caption("Reference levels: salaried, online, M-Pesa STK, Starter. Deposit and affordability are per 10 percentage points, age per 10 years.")

    ph = cr.ph_test.reset_index().rename(columns={"index": "Covariate"})
    ph.columns = ["Covariate", "Chi-square", "p-value"]
    fails = ph[ph["p-value"] < 0.05]["Covariate"].tolist()
    st.markdown("**Proportional hazards check** (Schoenfeld residuals against rank of time).")
    st.dataframe(ph.style.format({"Chi-square": "{:.2f}", "p-value": "{:.4f}"}), hide_index=True, use_container_width=True)
    st.warning(
        "Where it fails: " + ", ".join(fails) + ". "
        "The number of instalments breaks proportional hazards by construction: a member on 6 instalments has no lapse risk left after month 6, "
        "so the hazard ratio against a 10-instalment member changes sign over time. Deposit size also fails: its effect is concentrated in the "
        "first months, when members who joined to claim stop paying, and fades after. The single hazard ratios for these two are averages over "
        "the term and should not be read as constant effects. Stratifying by number of instalments, or a time-varying deposit effect, would fix this; "
        "the discrete-time hazard model behind the simulator already handles duration directly."
    )

# ------------------------------------------------------------- R cross-check
with tabs[4]:
    rdir = ROOT / "r" / "output"
    if not (rdir / "km_check.csv").exists():
        st.info("Run `python -m src.models export` then `Rscript r/km_cox_check.R` to produce the R outputs.")
    else:
        km_r = pd.read_csv(rdir / "km_check.csv")
        cox_r = pd.read_csv(rdir / "cox_check.csv")
        ph_r = pd.read_csv(rdir / "ph_check.csv")
        st.markdown("`r/km_cox_check.R` refits the Kaplan-Meier curves and the Cox model in R's `survival` package from the same exported data. "
                    "Python (lifelines) and R side by side:")
        kmp = km_python()
        kmj = kmp.merge(km_r, on=["group", "duration"], suffixes=(" Python", " R"))
        kmj["Abs. difference"] = (kmj["persistency Python"] - kmj["persistency R"]).abs()
        a, b = st.columns(2)
        with a:
            st.markdown("**Kaplan-Meier persistency**")
            show = kmj[kmj["group"] == "All"][["duration", "persistency Python", "persistency R", "Abs. difference"]]
            st.dataframe(show.style.format({"persistency Python": "{:.5f}", "persistency R": "{:.5f}", "Abs. difference": "{:.1e}"}),
                         hide_index=True, use_container_width=True)
            ci_gap = max((kmj["lower_95 Python"] - kmj["lower_95 R"]).abs().max(), (kmj["upper_95 Python"] - kmj["upper_95 R"]).abs().max())
            st.caption(f"All groups: largest persistency gap {kmj['Abs. difference'].max():.1e}; largest confidence limit gap {ci_gap:.1e} "
                       "(both use log-log Greenwood intervals).")
        with b:
            st.markdown("**Cox coefficients**")
            cp = cox_fit().summary.reset_index().rename(columns={"covariate": "term"})
            cp["term"] = cp["term"].map(M.r_name)
            cj = cp[["term", "coef"]].merge(cox_r[["term", "coef", "coef_breslow"]], on="term", suffixes=(" Python", " R Efron"))
            cj["Abs. difference"] = (cj["coef Python"] - cj["coef R Efron"]).abs()
            cj = cj.rename(columns={"coef_breslow": "R Breslow"})
            st.dataframe(cj.style.format({"coef Python": "{:+.4f}", "coef R Efron": "{:+.4f}", "R Breslow": "{:+.4f}", "Abs. difference": "{:.1e}"}),
                         hide_index=True, use_container_width=True)
        st.success(
            f"Kaplan-Meier agrees to {kmj['Abs. difference'].max():.0e} and Cox coefficients to {cj['Abs. difference'].max():.0e}. "
            "Both use Efron's method for tied lapse times. Ties matter here: thousands of policies lapse at the same whole-month duration. "
            f"Breslow's approximation, shown for comparison, moves coefficients by up to {(cj['coef R Efron'] - cj['R Breslow']).abs().max():.3f}, mostly towards zero, "
            "which is the known bias of Breslow under heavy ties."
        )
        st.markdown("**Proportional hazards check in R** (`cox.zph`, rank time scale)")
        st.dataframe(ph_r.style.format({"chi_square": "{:.2f}", "p_value": "{:.4f}"}), hide_index=True, use_container_width=True)
        st.caption("R's cox.zph uses a score test against the full model, while lifelines tests one covariate at a time, so the statistics differ. "
                   "Both flag the number of instalments and deposit size; R also flags affordability at the 1% level.")

# ------------------------------------------------------------- simulator back-test
with tabs[5]:
    st.markdown("The simulator replays the run-off sample on each policy's own deposit and instalments, then compares with what the SQL views measured.")

    @st.cache_resource(show_spinner="Running the simulator back-test...")
    def backtest():
        art = ui.artifacts()
        if art:
            return art["backtest"]
        inp = SM.build_inputs(ui.q, cfg)
        return SM.simulate(inp, SM.Scenario(use_book_terms=True, grace_days=cfg["product"]["grace_days"], waiting=dict(cfg["waiting_months"])), n_runs=3)

    bt = backtest()
    ACT_SQL = """
SELECT AVG(CASE WHEN is_lapsed THEN 1.0 ELSE 0 END)                                       AS lapse_rate,
       SUM(claims_paid_kes) / SUM(collected_kes)                                          AS claims_to_collected,
       SUM(CASE WHEN is_lapsed THEN claims_paid_kes END) / SUM(CASE WHEN is_lapsed THEN collected_kes END)          AS ctc_lapsers,
       SUM(CASE WHEN NOT is_lapsed THEN claims_paid_kes END) / SUM(CASE WHEN NOT is_lapsed THEN collected_kes END)  AS ctc_stayers,
       AVG(collected_kes)                                                                 AS collected_per_policy,
       AVG(claims_paid_kes)                                                               AS claims_per_policy,
       (SELECT SUM(leakage_kes) FROM v_leakage) / COUNT(*)                                AS leakage_per_policy
FROM v_policy WHERE is_run_off
"""
    act = ui.q(ACT_SQL).iloc[0]
    rows = [
        ("Lapsed by end of term", act["lapse_rate"], bt["lapse_rate"], "pct"),
        ("Claims to collected", act["claims_to_collected"], bt["claims_to_collected"], "pct"),
        ("Claims to collected, lapsers", act["ctc_lapsers"], bt["ctc_lapsers"], "pct"),
        ("Claims to collected, stayers", act["ctc_stayers"], bt["ctc_stayers"], "pct"),
        ("Premium collected per policy", act["collected_per_policy"], bt["collected_per_policy"], "kes"),
        ("Claims paid per policy", act["claims_per_policy"], bt["claims_per_policy"], "kes"),
        ("Leakage per policy", act["leakage_per_policy"], bt["leakage_per_policy"], "kes"),
    ]
    f = lambda v, u: ui.pct(v) if u == "pct" else ui.kes(v)
    st.dataframe(pd.DataFrame([{"Measure": r[0], "Actual (SQL)": f(r[1], r[3]), "Simulated": f(r[2], r[3]),
                                "Simulated / actual": f"{r[2] / r[1]:.2f}"} for r in rows]), hide_index=True, use_container_width=True)
    st.warning(
        "Persistency, premium collected and total claims back-test well. The simulator understates how much more lapsers claim than stayers, "
        f"so it understates leakage (simulated {bt['leakage_per_policy'] / act['leakage_per_policy']:.0%} of actual). It links claims to lapse only through "
        "what a model can see (claims paid to date, a recent large claim, early-claim overdispersion), not through a member's hidden intent. "
        "Read simulated leakage as a floor, and compare scenarios with each other rather than with the actual book."
    )
    ui.show_sql(ACT_SQL, ["v_policy", "v_leakage"])

# ------------------------------------------------------------- limitations
with tabs[6]:
    st.markdown(
        """
- **Synthetic data.** The book is generated from the assumptions on the Assumptions tab. Models recover effects the generator put in; they cannot
  discover effects it left out. With real data, the first job is to test which of these assumptions hold.
- **One product year.** Covers are annual and this lab ends at the first term. Renewal, re-underwriting and lapse-and-rejoin behaviour are not modelled.
- **Income proxy.** Affordability uses an income proxy by income type and region. True income varies around it and the insurer never sees it.
- **Proportional hazards** fails for number of instalments and deposit size (Survival models tab), so their Cox hazard ratios are term averages.
- **Early warning model.** Tested out of time on later cohorts, but those cohorts are still from the same synthetic process. A real deployment needs
  monitoring for drift, and the retention uplift on the call list must be measured with a randomised hold-out, not assumed.
- **Simulator.** Understates leakage (Simulator check tab). Waiting periods shorter than the book's borrow frequencies from later months.
  Grace periods beyond 15 days extrapolate the fitted cure curve. Sign-up elasticity is an assumption, and loadings are assumed not to change sign-ups.
- **Expenses** are a flat share of premium collected. Collection costs per instalment, M-Pesa charges and agent commission clawbacks are not modelled.
- **Claims** are paid claims only. There is no IBNR on run-off policies beyond the 60-day run-off wait, and no claims inflation.
"""
    )

# ------------------------------------------------------------- IFRS 17
with tabs[7]:
    st.markdown("**Discussion note, not an implementation.**")
    st.markdown(
        """
Most annual health covers qualify for the **premium allocation approach (PAA)** under IFRS 17, because the coverage period is one year or less.
Instalment cover changes several things under PAA:

- **Premiums receivable and the liability for remaining coverage (LRC).** Under PAA the LRC starts from premiums received, so on a 10% deposit
  the LRC is small while the insurer is already on risk for the full annual limits. Expected future instalments are cash flows within the
  boundary of the contract only while the insurer can compel payment or the member keeps cover by paying. Expected lapses therefore shrink the
  premium cash flows that can be recognised, and uncollected instalments should not sit in receivables as if certain.
- **Revenue recognition.** PAA insurance revenue is expected premium receipts allocated over the coverage period, usually by the passage of time.
  If expected receipts are reduced for lapse, revenue for the cohort is reduced too. The decrement table on the Persistency Explorer is the natural
  basis for that expected-receipts assumption.
- **Onerous contract test.** PAA assumes contracts are not onerous unless facts and circumstances indicate otherwise. Instalment cohorts with
  low deposits are exactly where facts may indicate otherwise: claims are front-loaded, members who claim early lapse, and premium is never
  collected. A cohort with claims to collected premium near or above 100% after expenses should be tested, and any loss component recognised
  immediately in profit or loss.
- **Grouping.** IFRS 17 groups contracts by portfolio, annual cohort and profitability. Deposit size or instalment plan could be a reasonable
  basis for identifying contracts with a significant possibility of becoming onerous at initial recognition.
- **Liability for incurred claims (LIC).** Claims incurred during cover by members who then lapse are still the insurer's liability and sit in the
  LIC with the usual IBNR and risk adjustment.

This note is for discussion. Recognition, measurement and the boundary of the contract for a specific product need the insurer's own accounting policy and auditor view.
"""
    )
ui.footer()
