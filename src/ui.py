"""Shared formatting, page setup, data access and chart theme for every page."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from src import artifacts as A
from src import db
from src.generate import load_config

SYNTHETIC_LABEL = "Synthetic portfolio. Illustrative only."

# Pink and lavender palette. Categorical order validated for colour-blind separation and contrast.
INK = "#3d1f35"
INK_2 = "#6d4560"
MUTED = "#a07a92"
GRID = "#f6dce8"
AXIS = "#e9bfd3"
SURFACE = "#fffafc"
PRIMARY = "#7357d6"  # violet: stayers, base case, observed
ACCENT = "#e0457b"  # rose: lapsers, scenario, risk
APRICOT = "#d97a1e"
TEAL = "#00998a"
ORCHID = "#b44fc0"
SERIES = [PRIMARY, ACCENT, APRICOT, TEAL, ORCHID]
SEQ_PINK = ["#fde7f0", "#f9c4da", "#f29abd", "#e46a9c", "#c94882", "#9c2f63", "#6b1f45"]
SEQ_SCALE = [[i / (len(SEQ_PINK) - 1), c] for i, c in enumerate(SEQ_PINK)]
HIGHLIGHT_ROW = "#fde7f0"


def rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


_CSS = """
<style>
  .stApp {background: linear-gradient(180deg, #fff8fb 0%, #fff3f8 55%, #f8f1ff 100%);}
  header[data-testid="stHeader"] {background: transparent; height: 2.5rem;}
  .block-container {padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1180px;}
  h1 {font-weight: 700; letter-spacing: -0.01em; font-size: 2.5rem; padding-top: 0.2rem; padding-bottom: 0.35rem;
      background: linear-gradient(90deg, #9c2f63 0%, #c2457f 45%, #6b3fa0 100%);
      -webkit-background-clip: text; background-clip: text; color: transparent !important;}
  h2, h3 {font-weight: 600; color: #7a2d5a;}
  [data-testid="stMarkdownContainer"] h3 {padding-top: 1.4rem;}
  [data-testid="stSidebar"] {background: linear-gradient(180deg, #fde6f0 0%, #f6e4fb 100%);}
  [data-testid="stSidebarNav"] a span {font-size: 0.95rem;}
  [data-testid="stSidebarNav"] a[aria-current="page"] {background: #ffffffb3; border-radius: 999px;}
  .sidebar-brand {font-family: 'Playfair Display', Georgia, serif; font-size: 1.15rem; font-weight: 700; color: #9c2f63;}
  .sidebar-note {font-size: 0.82rem; color: #6d4560;}
  .synthetic-banner {font-size: 0.72rem; letter-spacing: 0.16em; text-transform: uppercase; font-weight: 700;
      color: #b8336a; background: #ffffffcc; border: 1px solid #f3a9c7; border-radius: 999px;
      padding: 0.32rem 0.95rem; display: inline-block; margin-bottom: 0.5rem;}
  .synthetic-banner::before {content: "\\2726"; color: #ec6fa0; margin-right: 0.45rem; letter-spacing: 0;}
  .takeaway {color: #3d1f35; font-size: 0.97rem; margin: -0.3rem 0 1.4rem 0; padding: 0.6rem 0.9rem;
      border-left: 4px solid #ec6fa0; background: #fff0f6cc; border-radius: 0 12px 12px 0;}
  .kpi {background: #ffffff; border: 1px solid #f6cfe0; border-radius: 18px; padding: 1.05rem 1.2rem; height: 100%;
      box-shadow: 0 8px 22px rgba(194, 84, 127, 0.10);}
  .kpi .label {color: #6d4560; font-size: 0.86rem; margin-bottom: 0.2rem; font-weight: 600;}
  .kpi .value {font-family: 'Playfair Display', Georgia, serif; color: #9c2f63; font-size: 2rem; font-weight: 700;
      line-height: 1.15; white-space: nowrap;}
  .kpi .note {color: #8a6a80; font-size: 0.8rem; margin-top: 0.35rem;}
  .lede {font-size: 1.07rem; color: #5b2a48; line-height: 1.6; max-width: 62rem;}
  [data-testid="stExpander"] details {background: #ffffffb3; border-radius: 14px;}
  [data-testid="stVerticalBlockBorderWrapper"] {background: #ffffffb3;}
  .stButton button, .stFormSubmitButton button, .stDownloadButton button {border-radius: 999px; padding-left: 1.2rem; padding-right: 1.2rem;}
  [data-baseweb="tab-list"] button[aria-selected="true"] p {color: #b8336a; font-weight: 700;}
  [data-testid="stMetricValue"] {font-size: 1.6rem;}
  @media (max-width: 640px) { .kpi .value {font-size: 1.6rem;} h1 {font-size: 1.9rem;} }
</style>
"""


def _register_template() -> None:
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="Nunito Sans, system-ui, -apple-system, Segoe UI, sans-serif", size=13, color=INK),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=SURFACE,
        colorway=SERIES,
        margin=dict(l=10, r=10, t=72, b=10),
        xaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, ticks="", title_font=dict(color=INK_2, size=12)),
        yaxis=dict(gridcolor=GRID, linecolor=AXIS, zeroline=False, ticks="", title_font=dict(color=INK_2, size=12)),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0, title_text="", font=dict(size=12)),
        hoverlabel=dict(bgcolor="white", font_size=12, bordercolor=ACCENT),
        title=dict(font=dict(size=15, color="#7a2d5a", family="Playfair Display, Georgia, serif"), x=0, xanchor="left", y=0.985, yanchor="top", yref="container"),
    )
    pio.templates["lab"] = t
    pio.templates.default = "lab"


_register_template()


def page(title: str, subtitle: str | None = None) -> None:
    st.set_page_config(page_title=f"{title} | Instalment Persistency Lab", layout="wide", initial_sidebar_state="auto")
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(f'<div class="synthetic-banner">{SYNTHETIC_LABEL}</div>', unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.markdown(f'<p class="lede">{subtitle}</p>', unsafe_allow_html=True)
    st.sidebar.markdown(f"**Instalment Persistency Lab**  \n{SYNTHETIC_LABEL}")


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
    st.divider()
    st.caption(
        f"{SYNTHETIC_LABEL} Every number on this page comes from a seeded synthetic book of "
        "health covers that activate on the first instalment. Product prices, limits and effect sizes are "
        "assumptions listed on the Methods and Assumptions page."
    )
