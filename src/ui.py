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
TAGLINE = "Pay-as-you-go health cover"
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

# Navy and amber palette, matched to the NuruOps gem. Categorical order validated for colour-blind
# separation, chroma and contrast. The only other colour is the small rose signature.
NAVY_BAR = "#0F1117"
GOLD = "#E8960C"
INK = "#1d2430"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e6e4dd"
AXIS = "#c9c6bc"
SURFACE = "#fdfcfa"
PRIMARY = "#3d5a9e"  # navy: stayers, base case, observed
ACCENT = "#c47a06"  # amber: lapsers, scenario, risk
TEAL = "#00998a"
ORCHID = "#b44fc0"
SERIES = [PRIMARY, ACCENT, TEAL, ORCHID]
SEQ_NAVY = ["#eef1f7", "#cdd5e8", "#a3b2d5", "#7489bd", "#4f68a3", "#34497d", "#1f2d52"]
SEQ_SCALE = [[i / (len(SEQ_NAVY) - 1), c] for i, c in enumerate(SEQ_NAVY)]
HIGHLIGHT_ROW = "#fbf1df"
ROSE = "#b5577a"


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


_CSS = """
<style>
  /* top bar: NuruOps navy, gold gem, Garamond app name */
  header[data-testid="stHeader"] {background: #0F1117; height: 4.1rem; border-bottom: 1px solid #2a2d38;}
  header[data-testid="stHeader"]::after {content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 1px;
      background: linear-gradient(90deg, rgba(232,150,12,0) 0%, rgba(232,150,12,.75) 50%, rgba(232,150,12,0) 100%);}
  [data-testid="stToolbar"] {height: 4.1rem; align-items: center;}
  img[data-testid="stHeaderLogo"] {height: 2.6rem !important; max-height: 2.6rem !important; width: auto;}
  /* app name and what it is about: gem spans two rows, name above, tagline below */
  :is([data-testid="stLogoLink"], div:has(> img.stLogo)) {display: grid !important; grid-template-columns: auto auto; grid-template-rows: auto auto;
      column-gap: 0.75rem; row-gap: 0.15rem; align-items: center; text-decoration: none; height: auto !important;}
  :is([data-testid="stLogoLink"], div:has(> img.stLogo)) img {grid-column: 1; grid-row: 1 / span 2;}
  header :is([data-testid="stLogoLink"], div:has(> img.stLogo)) {grid-template-columns: 2.6rem auto;}
  [data-testid="stSidebar"] :is([data-testid="stLogoLink"], div:has(> img.stLogo)) {grid-template-columns: 2.3rem auto;}
  img[data-testid="stSidebarLogo"] {width: 2.3rem !important; height: 2.3rem !important; max-width: none !important;
      max-height: none !important;}
  :is([data-testid="stLogoLink"], div:has(> img.stLogo))::after {content: "Instalment Persistency Lab"; grid-column: 2; grid-row: 1; align-self: end;
      font-family: 'EB Garamond', Garamond, Georgia, serif; font-size: 1.55rem; font-weight: 600; letter-spacing: 0.005em;
      color: #FAFAFA; white-space: nowrap; line-height: 1;}
  :is([data-testid="stLogoLink"], div:has(> img.stLogo))::before {content: "Pay-as-you-go health cover"; grid-column: 2; grid-row: 2; align-self: start;
      font-size: 0.66rem; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase; color: #E8A33A;
      white-space: nowrap; line-height: 1;}
  /* when the menu folds into the light side panel, the name turns dark so it stays readable */
  [data-testid="stSidebar"] :is([data-testid="stLogoLink"], div:has(> img.stLogo))::after {color: #12151d;}
  [data-testid="stSidebar"] :is([data-testid="stLogoLink"], div:has(> img.stLogo))::before {color: #a86a05;}
  a[data-testid="stTopNavLink"] {color: #c9c6bc !important; border-radius: 6px;}
  a[data-testid="stTopNavLink"] p, a[data-testid="stTopNavLink"] span {color: inherit !important; font-size: 0.93rem;}
  a[data-testid="stTopNavLink"]:hover {color: #ffffff !important; background: rgba(255,255,255,0.06) !important;}
  a[data-testid="stTopNavLink"][aria-current="page"] {color: #FFC24B !important; background: rgba(232,150,12,0.12) !important;}
  header [data-testid="stMainMenuButton"] svg, header [data-testid="stExpandSidebarButton"] span,
  header [data-testid="stStatusWidget"], header [data-testid="stStatusWidget"] button {color: #c9c6bc !important; fill: #c9c6bc;}
  @media (max-width: 900px) { :is([data-testid="stLogoLink"], div:has(> img.stLogo))::after {font-size: 1.2rem;} }
  @media (max-width: 640px) { header :is([data-testid="stLogoLink"], div:has(> img.stLogo))::after {content: "IPL";}
      header :is([data-testid="stLogoLink"], div:has(> img.stLogo))::before {letter-spacing: 0.12em;} }

  .block-container {padding-top: 6rem; padding-bottom: 2.5rem; max-width: 1160px;}
  h1 {font-weight: 600; letter-spacing: -0.005em; font-size: 2.7rem; padding-top: 0; padding-bottom: 0.1rem; color: #12151d;}
  h2, h3 {font-weight: 600; color: #12151d;}
  [data-testid="stMarkdownContainer"] h3 {padding-top: 1.3rem; font-size: 1.6rem;}
  .kicker {font-size: 0.76rem; letter-spacing: 0.18em; text-transform: uppercase; font-weight: 700; color: #a86a05;
      margin-bottom: -0.15rem;}
  .kicker::before {content: ""; display: inline-block; width: 22px; height: 1px; background: #c47a06; vertical-align: middle;
      margin-right: 0.6rem;}
  .synthetic {font-size: 0.8rem; color: #6b6a66; margin: -0.2rem 0 0.9rem 0;}
  .lede {font-size: 1.1rem; color: #2b3340; line-height: 1.65; max-width: 60rem;}
  .takeaway {color: #1d2430; font-size: 0.96rem; margin: -0.3rem 0 1.4rem 0; padding-left: 0.85rem;
      border-left: 2px solid #c47a06;}
  .kpi {background: #ffffff; border: 1px solid #e6e4dd; border-top: 2px solid #12151d; border-radius: 4px;
      padding: 1rem 1.15rem; height: 100%; box-shadow: 0 1px 2px rgba(15,17,23,0.04);}
  .kpi .label {color: #52514e; font-size: 0.78rem; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 0.35rem;}
  .kpi .value {font-family: 'EB Garamond', Garamond, Georgia, serif; color: #12151d; font-size: 2.3rem; font-weight: 600;
      line-height: 1.05; white-space: nowrap;}
  .kpi .note {color: #6b6a66; font-size: 0.8rem; margin-top: 0.4rem;}
  .next-up {font-size: 0.76rem; letter-spacing: 0.16em; text-transform: uppercase; color: #a86a05; margin-bottom: 0.1rem;}
  .signature {display: flex; align-items: center; gap: 0.7rem; margin-top: 0.4rem;}
  .signature img {width: 40px; height: 40px;}
  .signature .who {font-size: 0.86rem; color: #2b3340;}
  .signature .who b {color: #8e3a5d; font-weight: 600;}
  .signature .fine {font-size: 0.76rem; color: #6b6a66;}
  [data-testid="stMetricValue"] {font-size: 1.6rem;}
  @media (max-width: 640px) { .kpi .value {font-size: 1.8rem;} h1 {font-size: 2rem;} }
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
        title=dict(font=dict(size=17, color="#12151d", family="'EB Garamond', Garamond, Georgia, serif"), x=0, xanchor="left", y=0.985, yanchor="top", yref="container"),
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
    else:
        st.markdown(f'<div class="kicker">{TAGLINE}, told in {len(CHAPTERS)} chapters</div>', unsafe_allow_html=True)
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


def set_linked(key: str, value) -> None:
    """Set a linked slider's value everywhere it is held (the value, the slider and the number box)."""
    st.session_state[key] = value
    st.session_state[f"{key}__slider"] = value
    st.session_state[f"{key}__box"] = value


def linked_slider(label: str, lo, hi, default, step, key: str, fmt: str | None = None, help: str | None = None):
    """A slider with a number box beside it. Changing either one updates the other.

    The current value lives in st.session_state[key]."""
    if key not in st.session_state:
        set_linked(key, default)
    is_float = isinstance(step, float)
    cast = float if is_float else int

    def _from_slider():
        set_linked(key, cast(st.session_state[f"{key}__slider"]))

    def _from_box():
        v = st.session_state[f"{key}__box"]
        v = lo if v is None else min(max(cast(v), lo), hi)
        set_linked(key, round(v, 4) if is_float else v)

    s_col, b_col = st.columns([3.3, 1.2], vertical_alignment="bottom")
    s_col.slider(label, lo, hi, step=step, key=f"{key}__slider", on_change=_from_slider, format=fmt, help=help)
    b_col.number_input(label, lo, hi, step=step, key=f"{key}__box", on_change=_from_box, label_visibility="collapsed",
                       format="%.2f" if is_float else "%d")
    return st.session_state[key]


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
