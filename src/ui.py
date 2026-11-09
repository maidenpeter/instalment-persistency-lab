"""Shared formatting, page setup, data access and chart theme for every page."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from src import db
from src.generate import load_config

SYNTHETIC_LABEL = "Synthetic portfolio. Illustrative only."

# Neutral palette (validated categorical order, not any insurer's colours).
INK = "#1d2430"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#fcfcfb"
BLUE = "#2a78d6"  # stayers, base case, observed
ORANGE = "#eb6834"  # lapsers, scenario, risk
AQUA = "#1baf7a"
YELLOW = "#eda100"
VIOLET = "#6250d6"
SERIES = [BLUE, ORANGE, AQUA, YELLOW, "#e87ba4", "#008300", VIOLET, "#e34948"]
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SEQ_SCALE = [[i / (len(SEQ_BLUE) - 1), c] for i, c in enumerate(SEQ_BLUE)]

_CSS = """
<style>
  .block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1180px;}
  h1 {font-weight: 650; letter-spacing: -0.01em; font-size: 2.0rem;}
  h2, h3 {font-weight: 600; letter-spacing: -0.005em;}
  .synthetic-banner {font-size: 0.82rem; color: #52514e; background: #eef0f2; border: 1px solid #dfe3e8;
      border-radius: 6px; padding: 0.35rem 0.75rem; display: inline-block; margin-bottom: 0.6rem;}
  .takeaway {color: #1d2430; font-size: 0.95rem; margin: -0.4rem 0 1.4rem 0; padding-left: 0.7rem;
      border-left: 3px solid #c3c2b7;}
  .kpi {background: #ffffff; border: 1px solid #e3e5e8; border-radius: 8px; padding: 1rem 1.1rem; height: 100%;}
  .kpi .label {color: #52514e; font-size: 0.85rem; margin-bottom: 0.25rem;}
  .kpi .value {color: #1d2430; font-size: 1.75rem; font-weight: 650; line-height: 1.15; white-space: nowrap;}
  .kpi .note {color: #6b6a66; font-size: 0.8rem; margin-top: 0.35rem;}
  .lede {font-size: 1.05rem; color: #2b3340; line-height: 1.55; max-width: 60rem;}
  [data-testid="stMetricValue"] {font-size: 1.6rem;}
  @media (max-width: 640px) { .kpi .value {font-size: 1.5rem;} h1 {font-size: 1.6rem;} }
</style>
"""


def _register_template() -> None:
    t = go.layout.Template()
    t.layout = go.Layout(
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13, color=INK),
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


def page(title: str, subtitle: str | None = None) -> None:
    st.set_page_config(page_title=f"{title} | Instalment Persistency Lab", layout="wide", initial_sidebar_state="expanded")
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


def footer() -> None:
    st.divider()
    st.caption(
        f"{SYNTHETIC_LABEL} Every number on this page comes from a seeded synthetic book of "
        "health covers that activate on the first instalment. Product prices, limits and effect sizes are "
        "assumptions listed on the Methods and Assumptions page."
    )
