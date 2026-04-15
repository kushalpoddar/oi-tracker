"""
OI Tracker — Clean Table View
==============================
One table per index (NIFTY / BANKNIFTY / SENSEX):
  Middle: Strike prices (±10 from ATM)
  Left:   CALL → Old (yesterday close) | Live (latest)
  Right:  PUT  → Old (yesterday close) | Live (latest)
  Click Live → modal with CE + PE OI graph over time (5-min)
"""

from __future__ import annotations

import streamlit as st
import pandas as pd
import altair as alt
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "oi_tracker.db"


# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OI Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .block-container { padding-top: 1rem; max-width: 1200px; }
    .spot-badge {
        display: inline-block; background: #ffd700; color: #000;
        padding: 4px 12px; border-radius: 12px; font-weight: 700; font-size: 14px;
    }

    /* Live OI buttons styled as table cells */
    .stButton > button {
        font-family: 'SF Mono', 'Fira Code', Consolas, monospace !important;
        font-size: 13px !important;
        padding: 6px 0 !important;
        min-height: 0 !important;
        height: auto !important;
        border: 1px solid #333 !important;
        background: transparent !important;
        color: #90caf9 !important;
        transition: background 0.15s;
        width: 100% !important;
    }
    .stButton > button:hover {
        background: #1a2744 !important;
        border-color: #90caf9 !important;
        color: #fff !important;
    }

    /* Tighten vertical spacing between rows */
    [data-testid="stVerticalBlock"] > div { margin-bottom: -0.5rem; }
    [data-testid="column"] > div { display: flex; align-items: center; justify-content: center; }

    /* Table group headers */
    .tbl-group {
        text-align: center; font-size: 14px; font-weight: 700;
        padding: 6px 0; border-bottom: 2px solid #444;
    }
    .tbl-sub {
        text-align: center; font-size: 12px; font-weight: 600;
        padding: 4px 0; color: #aaa; border-bottom: 1px solid #333;
    }
    .tbl-cell {
        text-align: center; padding: 6px 0;
        font-family: 'SF Mono', 'Fira Code', Consolas, monospace; font-size: 13px;
    }
</style>
""", unsafe_allow_html=True)

SYMBOLS = ["NIFTY", "BANKNIFTY"]


# ── DB queries ────────────────────────────────────────────────────────────────

def get_db():
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(str(DB_PATH))


def get_latest_live(symbol: str) -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    today = date.today().isoformat()
    df = pd.read_sql_query("""
        SELECT * FROM live_oi
        WHERE symbol = ?
          AND timestamp >= ?
          AND timestamp = (SELECT MAX(timestamp) FROM live_oi WHERE symbol = ? AND timestamp >= ?)
        ORDER BY strike
    """, conn, params=[symbol, today, symbol, today])
    conn.close()
    return df


def get_yesterday_close(symbol: str) -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    df = pd.read_sql_query("""
        SELECT * FROM closing_oi
        WHERE symbol = ?
          AND trade_date = (SELECT MAX(trade_date) FROM closing_oi WHERE symbol = ?)
        ORDER BY strike
    """, conn, params=[symbol, symbol])
    conn.close()
    return df


def get_strike_timeseries(symbol: str, strike: float) -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    today = date.today().isoformat()
    df = pd.read_sql_query("""
        SELECT timestamp, ce_oi, pe_oi, ce_ltp, pe_ltp, spot
        FROM live_oi
        WHERE symbol = ? AND strike = ? AND timestamp >= ?
        ORDER BY timestamp
    """, conn, params=[symbol, strike, today])
    conn.close()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def get_all_timestamps_today(symbol: str) -> list:
    conn = get_db()
    if conn is None:
        return []
    today = date.today().isoformat()
    rows = conn.execute("""
        SELECT DISTINCT timestamp FROM live_oi
        WHERE symbol = ? AND timestamp >= ?
        ORDER BY timestamp
    """, [symbol, today]).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_snapshot_count(symbol: str) -> int:
    conn = get_db()
    if conn is None:
        return 0
    today = date.today().isoformat()
    count = conn.execute(
        "SELECT COUNT(DISTINCT timestamp) FROM live_oi WHERE symbol = ? AND timestamp >= ?",
        [symbol, today]
    ).fetchone()[0]
    conn.close()
    return count


# ── Build row data for interactive table ──────────────────────────────────────

def build_row_data(live_df: pd.DataFrame, old_df: pd.DataFrame, spot: float) -> list[dict]:
    """Build list of row dicts for the interactive table."""
    if live_df.empty:
        return []

    old_map = old_df.set_index("strike").to_dict("index") if not old_df.empty else {}
    strikes = sorted(live_df["strike"].unique())
    atm = min(strikes, key=lambda x: abs(x - spot))

    rows = []
    for s in strikes:
        lr = live_df[live_df["strike"] == s].iloc[0]
        o = old_map.get(s, {})
        ce_old = int(o.get("ce_oi", 0))
        ce_live = int(lr.get("ce_oi", 0))
        pe_old = int(o.get("pe_oi", 0))
        pe_live = int(lr.get("pe_oi", 0))
        ce_pct = ((ce_live - ce_old) / ce_old * 100) if ce_old else 0.0
        pe_pct = ((pe_live - pe_old) / pe_old * 100) if pe_old else 0.0
        rows.append({
            "strike":   int(s),
            "ce_old":   ce_old,
            "ce_live":  ce_live,
            "ce_pct":   ce_pct,
            "pe_live":  pe_live,
            "pe_old":   pe_old,
            "pe_pct":   pe_pct,
            "is_atm":   s == atm,
        })
    return rows


# ── OI Time-Series Chart (Modal) ─────────────────────────────────────────────

def render_strike_chart(symbol: str, strike: float):
    """Render CE + PE OI time-series chart for a strike."""
    ts_df = get_strike_timeseries(symbol, strike)

    if ts_df.empty:
        st.info(f"No intraday data for {symbol} {int(strike)} yet.")
        return

    # CE chart
    ce_chart = alt.Chart(ts_df).mark_area(
        color="#ef5350", opacity=0.3, line={"color": "#ef5350", "strokeWidth": 2}
    ).encode(
        x=alt.X("timestamp:T", title="Time", axis=alt.Axis(format="%H:%M")),
        y=alt.Y("ce_oi:Q", title="CE Open Interest"),
        tooltip=[
            alt.Tooltip("timestamp:T", title="Time", format="%H:%M"),
            alt.Tooltip("ce_oi:Q", title="CE OI", format=","),
        ],
    ).properties(height=200, title=f"CALL OI — {symbol} {int(strike)}")

    # PE chart
    pe_chart = alt.Chart(ts_df).mark_area(
        color="#66bb6a", opacity=0.3, line={"color": "#66bb6a", "strokeWidth": 2}
    ).encode(
        x=alt.X("timestamp:T", title="Time", axis=alt.Axis(format="%H:%M")),
        y=alt.Y("pe_oi:Q", title="PE Open Interest"),
        tooltip=[
            alt.Tooltip("timestamp:T", title="Time", format="%H:%M"),
            alt.Tooltip("pe_oi:Q", title="PE OI", format=","),
        ],
    ).properties(height=200, title=f"PUT OI — {symbol} {int(strike)}")

    combined = alt.vconcat(
        ce_chart, pe_chart
    ).resolve_scale(x="shared").configure_view(  # type: ignore[attr-defined]
        strokeWidth=0
    ).configure_axis(
        labelColor="#e0e0e0", titleColor="#e0e0e0",
        gridColor="#222", domainColor="#555",
    ).configure_title(
        color="#e0e0e0"
    ).configure(background="#0e1117")

    st.altair_chart(combined, use_container_width=True)


# ── Interactive Table with clickable Live cells ──────────────────────────────

def _pct_tag(pct: float) -> str:
    """Format % change as a compact string for button labels."""
    if pct == 0:
        return ""
    sign = "▲" if pct > 0 else "▼"
    return f"{sign}{abs(pct):.1f}%"


def render_oi_table(symbol: str, rows: list[dict]):
    """Render the OI table row-by-row. Live cells are buttons that open a chart dialog."""

    # ── Level-1 group headers: CALL | STRIKE | PUT ──
    g1, g2, g3 = st.columns([2, 1, 2])
    g1.markdown('<div class="tbl-group" style="color:#ef9a9a">CALL (CE)</div>', unsafe_allow_html=True)
    g2.markdown('<div class="tbl-group" style="color:#ffd700">⬍</div>', unsafe_allow_html=True)
    g3.markdown('<div class="tbl-group" style="color:#a5d6a7">PUT (PE)</div>', unsafe_allow_html=True)

    # ── Level-2 sub-headers: Old | Live | STRIKE | Live | Old ──
    h1, h2, h3, h4, h5 = st.columns([1, 1, 1, 1, 1])
    h1.markdown('<div class="tbl-sub">Old</div>', unsafe_allow_html=True)
    h2.markdown('<div class="tbl-sub">Live 🔍</div>', unsafe_allow_html=True)
    h3.markdown('<div class="tbl-sub" style="color:#ffd700">STRIKE</div>', unsafe_allow_html=True)
    h4.markdown('<div class="tbl-sub">Live 🔍</div>', unsafe_allow_html=True)
    h5.markdown('<div class="tbl-sub">Old</div>', unsafe_allow_html=True)

    # ── Data rows ──
    for row in rows:
        s = row["strike"]
        atm_bg = "background-color:#2a2a00;" if row["is_atm"] else ""

        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])

        with c1:
            st.markdown(
                f'<div class="tbl-cell" style="color:#ef9a9a; opacity:0.5; {atm_bg}">{row["ce_old"]:,}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            ce_tag = _pct_tag(row["ce_pct"])
            if st.button(f'{row["ce_live"]:,}  {ce_tag}', key=f"ce_{symbol}_{s}", use_container_width=True):
                show_chart_dialog(symbol, s)
        with c3:
            clr = "#ffd700" if row["is_atm"] else "#e0e0e0"
            wt = "800" if row["is_atm"] else "600"
            sz = "15px" if row["is_atm"] else "13px"
            st.markdown(
                f'<div class="tbl-cell" style="color:{clr}; font-weight:{wt}; font-size:{sz}; {atm_bg}">{s:,}</div>',
                unsafe_allow_html=True,
            )
        with c4:
            pe_tag = _pct_tag(row["pe_pct"])
            if st.button(f'{row["pe_live"]:,}  {pe_tag}', key=f"pe_{symbol}_{s}", use_container_width=True):
                show_chart_dialog(symbol, s)
        with c5:
            st.markdown(
                f'<div class="tbl-cell" style="color:#a5d6a7; opacity:0.5; {atm_bg}">{row["pe_old"]:,}</div>',
                unsafe_allow_html=True,
            )


@st.dialog("📈 OI Intraday Chart", width="large")  # type: ignore[attr-defined]
def show_chart_dialog(symbol: str, strike: int):
    """Modal dialog showing CE + PE OI time-series for a strike."""
    render_strike_chart(symbol, float(strike))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    st.title("📊 OI Tracker")

    # Status bar
    col_s1, col_s2, col_s3 = st.columns([1, 1, 1])
    with col_s1:
        now = datetime.now()
        st.markdown(f"🕐 **{now.strftime('%H:%M:%S')}** IST")
    with col_s2:
        snap_count = get_snapshot_count("NIFTY")
        st.markdown(f"📸 **{snap_count}** snapshots today")
    with col_s3:
        if st.button("🔄 Refresh"):
            st.rerun()

    st.divider()

    # Tabs per symbol
    tabs = st.tabs(SYMBOLS)

    for i, symbol in enumerate(SYMBOLS):
        with tabs[i]:
            live_df = get_latest_live(symbol)
            old_df = get_yesterday_close(symbol)

            if live_df.empty:
                st.warning(
                    f"No live data for **{symbol}** yet today.\n\n"
                    "**To start collecting**, run in a terminal:\n"
                    "```\npython3 collector.py --live\n```\n"
                    "Or wait for the cron job to kick in (every 5 min, Mon–Fri, 9:15–3:30)."
                )

                # Show a quick live fetch button
                if st.button(f"⚡ Fetch {symbol} Now", key=f"fetch_{symbol}"):
                    with st.spinner(f"Fetching {symbol}..."):
                        import subprocess
                        result = subprocess.run(
                            ["python3", "collector.py", "--live"],
                            capture_output=True, text=True, cwd=str(Path(__file__).parent)
                        )
                        if result.returncode == 0:
                            st.success("Data collected! Refreshing...")
                            st.rerun()
                        else:
                            st.error(f"Error: {result.stderr}")
                continue

            spot = float(live_df["spot"].iloc[0])
            last_ts = live_df["timestamp"].iloc[0]

            col_info1, col_info2, col_info3 = st.columns([1, 1, 1])
            with col_info1:
                st.markdown(f'<span class="spot-badge">SPOT: ₹{spot:,.2f}</span>', unsafe_allow_html=True)
            with col_info2:
                st.markdown(f"**Last update:** {last_ts}")
            with col_info3:
                if old_df.empty:
                    st.caption("No previous close data yet")
                else:
                    old_date = old_df["trade_date"].iloc[0] if "trade_date" in old_df.columns else "?"
                    st.caption(f"Old = close of {old_date}")

            # Render interactive table
            rows = build_row_data(live_df, old_df, spot)
            if not rows:
                st.info("No data to display.")
                continue

            render_oi_table(symbol, rows)


if __name__ == "__main__":
    main()
