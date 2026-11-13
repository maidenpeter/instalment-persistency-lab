"""Shared formatting, page setup, data access and chart theme for every page."""
from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from src import artifacts as A
from src import db
from src.generate import load_config

SYNTHETIC_LABEL = "Synthetic portfolio. Illustrative only."
APP_NAME = "Instalment Persistency Lab"
ASSETS = Path(__file__).resolve().parents[1] / "assets"

# The story, in order. Every page belongs to one chapter; Methods is the appendix.
CHAPTERS = [
    {"key": "problem", "path": "pages/1_The_Problem.py", "nav": "The Problem", "url": "the-problem",
     "title": "The problem", "teaser": "Cover that starts on a 10% deposit runs ahead of the cash."},
    {"key": "who", "path": "pages/2_Persistency_Explorer.py", "nav": "Who Lapses", "url": "who-lapses",
     "title": "Who lapses, and when", "teaser": "Lapse rates month by month, by segment and by cohort."},
    {"key": "cost", "path": "pages/3_Anti_Selection_and_Leakage.py", "nav": "What It Costs", "url": "what-it-costs",
     "title": "What lapse costs", "teaser": "Claims paid against premium actually collected, and the leakage in KES."},
    {"key": "one", "path": "pages/7_Policy_Lookup.py", "nav": "One Policy", "url": "one-policy",
     "title": "One policy, start to finish", "teaser": "Follow a single member through a year: paid in, paid out, slipped, lapsed."},
    {"key": "warn", "path": "pages/4_Early_Warning_Model.py", "nav": "Early Warning", "url": "early-warning",
     "title": "Catching it early", "teaser": "Who will miss the next instalment, and who to call this week."},
    {"key": "fix", "path": "pages/5_Product_Levers_Simulator.py", "nav": "Fixing It", "url": "fixing-it",
     "title": "Fixing the product", "teaser": "Deposit, instalments, grace, waiting periods and benefit release, tested."},
]
APPENDIX = {"key": "methods", "path": "pages/6_Methods_and_Assumptions.py", "nav": "Methods", "url": "methods",
            "title": "Methods and assumptions", "teaser": "Data, every assumption, diagnostics and the R cross-check."}

# Neutral palette (validated categorical order). The only colour of its own is the small rose signature.
INK = "#1d2430"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"
PRIMARY = "#2a78d6"  # stayers, base case, observed
ACCENT = "#eb6834"  # lapsers, scenario, risk
TEAL = "#1baf7a"
APRICOT = "#eda100"
ORCHID = "#e87ba4"
SERIES = [PRIMARY, ACCENT, TEAL, APRICOT, ORCHID]
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQ_SCALE = [[i / (len(SEQ_BLUE) - 1), c] for i, c in enumerate(SEQ_BLUE)]
HIGHLIGHT_ROW = "#fdf0ea"
ROSE = "#b5577a"


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


_CSS = """
<style>
  .block-container {padding-top: 5.2rem; padding-bottom: 2.5rem; max-width: 1160px;}
  h1 {font-weight: 600; letter-spacing: -0.01em; font-size: 2.35rem; padding-top: 0; padding-bottom: 0.15rem;}
  h2, h3 {font-weight: 600;}
  [data-testid="stMarkdownContainer"] h3 {padding-top: 1.3rem;}
  .kicker {font-size: 0.78rem; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 600; color: #b5577a;
      margin-bottom: -0.2rem;}
  .synthetic {font-size: 0.8rem; color: #6b6a66; margin: -0.2rem 0 0.9rem 0;}
  .lede {font-size: 1.07rem; color: #2b3340; line-height: 1.6; max-width: 62rem;}
  .takeaway {color: #1d2430; font-size: 0.96rem; margin: -0.3rem 0 1.4rem 0; padding-left: 0.8rem;
      border-left: 3px solid #c3c2b7;}
  .kpi {background: #ffffff; border: 1px solid #e3e5e8; border-radius: 10px; padding: 1rem 1.1rem; height: 100%;}
  .kpi .label {color: #52514e; font-size: 0.85rem; margin-bottom: 0.25rem;}
  .kpi .value {color: #1d2430; font-size: 1.8rem; font-weight: 600; line-height: 1.15; white-space: nowrap;}
  .kpi .note {color: #6b6a66; font-size: 0.8rem; margin-top: 0.35rem;}
  .next-up {font-size: 0.8rem; letter-spacing: 0.12em; text-transform: uppercase; color: #6b6a66; margin-bottom: 0.1rem;}
  .signature {display: flex; align-items: center; gap: 0.7rem; margin-top: 0.4rem;}
  .signature img {width: 40px; height: 40px;}
  .signature .who {font-size: 0.86rem; color: #2b3340;}
  .signature .who b {color: #8e3a5d; font-weight: 600;}
  .signature .fine {font-size: 0.76rem; color: #6b6a66;}
  [data-testid="stMetricValue"] {font-size: 1.6rem;}
  @media (max-width: 640px) { .kpi .value {font-size: 1.5rem;} h1 {font-size: 1.85rem;} }
</style>
"""


def _data_uri(name: str) -> str:
    import base64

    return "data:image/svg+xml;base64," + base64.b64encode((ASSETS / name).read_bytes()).decode()


def _chapter(key: str) -> tuple[dict, int | None]:
    for i, c in enumerate(CHAPTERS, 1):
        if c["key"] == key:
            return c, i
    if key == APPENDIX["key"]:
        return APPENDIX, None
    return {"key": "home", "title": APP_NAME, "path": None}, None


def _register_template() -> None:
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="'Source Sans Pro', 'Source Sans 3', system-ui, -apple-system, Segoe UI, sans-serif", size=13, color=INK),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=SURFACE,
        colorway=SERIES,
        margin=dict(l=10, r=10, t=72, b=10),
        xaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, ticks="", title_font=dict(color=INK_2, size=12)),
        yaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, ticks="", title_font=dict(color=INK_2, size=12)),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, title_text="", font=dict(size=12)),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor=AXIS),
        title=dict(font=dict(size=14, color=INK), x=0, xanchor="left", y=0.985, yanchor="top", yref="container"),
    )
    pio.templates["lab"] = t
    pio.templates.default = "lab"


_register_template()


def page(key: str, lede: str | None = None) -> None:
    """Page frame: chapter label, title at the top, synthetic label, and an optional lede."""
    chapter, n = _chapter(key)
    st.session_state["_page_key"] = key
    title = f"{chapter['title']} | {APP_NAME}" if key != "home" else APP_NAME
    st.set_page_config(page_title=title, page_icon=str(ASSETS / "mark.svg"), layout="wide", initial_sidebar_state="collapsed")
    st.markdown(_CSS, unsafe_allow_html=True)
    if n:
        st.markdown(f'<div class="kicker">Chapter {n} of {len(CHAPTERS)}</div>', unsafe_allow_html=True)
    elif key == "methods":
        st.markdown('<div class="kicker">Appendix</div>', unsafe_allow_html=True)
    st.title(chapter["title"])
    st.markdown(f'<div class="synthetic">{SYNTHETIC_LABEL}</div>', unsafe_allow_html=True)
    if lede:
        st.markdown(f'<p class="lede">{lede}</p>', unsafe_allow_html=True)


@st.cache_resource(show_spinner="Building the synthetic book and SQL views...")
def _connection():
    return db.build(db_path=None)


@st.cache_data(show_spinner=False)
def q(sql: str, params: tuple | None = None):
    """Run SQL against the DuckDB views and return a DataFrame (cached per query)."""
    con = _connection().cursor()
    return con.execute(sql, list(params) if params else None).df()


@st.cache_resource(show_spinner=False)
def artifacts() -> dict | None:
    """Precomputed model results, or None if they do not match the current sources."""
    return A.load()


@st.cache_resource(show_spinner="Fitting the early warning models on earlier cohorts...")
def early_warning_model():
    """The chosen early warning model: precomputed if available, otherwise fitted now."""
    art = artifacts()
    if art:
        return art["early_warning"]
    from src import models as M

    return M.fit_early_warning(q(M.FEATURES_SQL), config())


@st.cache_data(show_spinner=False)
def config() -> dict:
    return load_config()


def show_sql(sql: str, views: list[str] | None = None, label: str = "See the SQL") -> None:
    with st.expander(label):
        st.code(sql.strip(), language="sql")
        for v in views or []:
            st.caption(f"View definition: {v}")
            st.code(db.view_sql(v), language="sql")


def takeaway(text: str) -> None:
    st.markdown(f'<p class="takeaway">{text}</p>', unsafe_allow_html=True)


def kpi(col, label: str, value: str, note: str = "") -> None:
    col.markdown(
        f'<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div>'
        f'<div class="note">{note}</div></div>',
        unsafe_allow_html=True,
    )


def kes(x: float, short: bool = False) -> str:
    if x is None:
        return "n/a"
    if short and abs(x) >= 1e6:
        return f"KES {x / 1e6:,.1f}m"
    return f"KES {x:,.0f}"


def pct(x: float, dp: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{dp}f}%"


def plot(fig, height: int = 380) -> None:
    fig.update_layout(height=height)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def ctc_by_deposit_figure(band) -> go.Figure:
    """Claims per KES collected, stayers against lapsers, by deposit band (rows from v_claims_to_collected)."""
    fig = go.Figure()
    for grp, color in [("Stayer", PRIMARY), ("Lapser", ACCENT)]:
        d = band[band["persistency_group"] == grp]
        fig.add_trace(go.Bar(x=d["deposit_band"], y=d["claims_to_collected"], name=f"{grp}s", marker_color=color,
                             text=[pct(v, 0) for v in d["claims_to_collected"]], textposition="outside",
                             customdata=d[["policies", "collected_kes", "claims_paid_kes"]],
                             hovertemplate=f"{grp}s, deposit %{{x}}<br>Claims / collected %{{y:.1%}}<br>"
                                           "Policies %{customdata[0]:,}<br>Collected KES %{customdata[1]:,.0f}<br>"
                                           "Claims KES %{customdata[2]:,.0f}<extra></extra>"))
    fig.add_hline(y=1.0, line=dict(color=MUTED, width=1, dash="dot"), annotation_text="Claims equal premium collected",
                  annotation_position="top left", annotation_font_color=INK_2)
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08, title="Claims paid per KES of premium collected, by deposit size")
    fig.update_yaxes(tickformat=".0%", title="Claims / premium collected", rangemode="tozero")
    fig.update_xaxes(title="Deposit as share of annual premium", type="category")
    return fig


def footer() -> None:
    """Next chapter in the story, then the signature."""
    key = st.session_state.get("_page_key", "home")
    _, n = _chapter(key)
    st.divider()
    nxt = None
    if key == "home":
        nxt, label = CHAPTERS[0], f"Start the story: Chapter 1, {CHAPTERS[0]['title']}"
    elif n is not None and n < len(CHAPTERS):
        nxt, label = CHAPTERS[n], f"Chapter {n + 1}: {CHAPTERS[n]['title']}"
    elif n == len(CHAPTERS):
        nxt, label = APPENDIX, f"Appendix: {APPENDIX['title']}"
    if nxt:
        with st.container(border=True):
            st.markdown('<div class="next-up">Next</div>', unsafe_allow_html=True)
            st.page_link(nxt["path"], label=f"**{label}**", icon=":material/arrow_forward:")
            st.caption(nxt["teaser"])
    sig = _data_uri("signature.svg")
    st.markdown(
        f'<div class="signature"><img src="{sig}" alt="MP monogram"><div>'
        f'<div class="who">Made by <b>Marion Peter</b></div>'
        f'<div class="fine">{SYNTHETIC_LABEL} Every number comes from a seeded synthetic book; '
        f'the assumptions are listed in the appendix.</div></div></div>',
        unsafe_allow_html=True,
    )
