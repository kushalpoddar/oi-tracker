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
    .block-container { padding-top: 1rem; max-width: 1400px; }
    .spot-badge {
        display: inline-block; background: #ffd700; color: #000;
        padding: 4px 12px; border-radius: 12px; font-weight: 700; font-size: 14px;
    }

    /* OI table: horizontally scrollable on mobile, no wrapping */
    .oi-table-wrap {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        margin-bottom: 1rem;
    }
    .oi-table {
        border-collapse: collapse;
        white-space: nowrap;
        width: 100%;
        min-width: 800px;
        font-family: 'SF Mono', 'Fira Code', Consolas, monospace;
        font-size: 13px;
    }
    .oi-table th {
        position: sticky; top: 0;
        padding: 6px 10px;
        border-bottom: 2px solid #444;
        font-weight: 700;
        text-align: center;
        background: #0e1117;
    }
    .oi-table th.group-ce { color: #ef9a9a; }
    .oi-table th.group-pe { color: #a5d6a7; }
    .oi-table th.group-strike { color: #ffd700; }
    .oi-table th.sub {
        font-size: 12px; font-weight: 600; color: #aaa;
        border-bottom: 1px solid #333;
    }
    .oi-table td {
        padding: 5px 10px;
        text-align: center;
        border-bottom: 1px solid #1a1a1a;
    }
    .oi-table tr.atm-row td { background: #2a2a00; }
    .oi-table .ce { color: #ef9a9a; }
    .oi-table .pe { color: #a5d6a7; }
    .oi-table .dim { opacity: 0.5; }
    .oi-table .strike-cell { color: #e0e0e0; font-weight: 600; }
    .oi-table .strike-atm { color: #ffd700; font-weight: 800; font-size: 15px; }
    .oi-table .up { color: #66BB6A; }
    .oi-table .dn { color: #ef5350; }
    .oi-table .zr { color: #666; }
    .oi-table .live-val a {
        color: #90caf9;
        text-decoration: none;
        cursor: pointer;
    }
    .oi-table .live-val a:hover {
        color: #fff;
        text-decoration: underline;
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


def get_latest_participant_oi() -> pd.DataFrame:
    conn = get_db()
    if conn is None:
        return pd.DataFrame()
    try:
        df = pd.read_sql_query("""
            SELECT * FROM participant_oi
            WHERE trade_date = (SELECT MAX(trade_date) FROM participant_oi)
            ORDER BY instrument
        """, conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def get_closing_oi_totals(symbol: str) -> dict:
    """Get total CE OI, PE OI and PCR from latest live snapshot."""
    conn = get_db()
    if conn is None:
        return {}
    today = date.today().isoformat()
    row = conn.execute("""
        SELECT
            COALESCE(SUM(ce_oi), 0) as total_ce,
            COALESCE(SUM(pe_oi), 0) as total_pe
        FROM live_oi
        WHERE symbol = ?
          AND timestamp >= ?
          AND timestamp = (SELECT MAX(timestamp) FROM live_oi WHERE symbol = ? AND timestamp >= ?)
    """, [symbol, today, symbol, today]).fetchone()
    conn.close()
    if row is None:
        return {}
    total_ce, total_pe = row
    pcr = total_pe / total_ce if total_ce > 0 else 0
    return {"total_ce": total_ce, "total_pe": total_pe, "pcr": pcr}


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
            "strike":     int(s),
            "ce_old":     ce_old,
            "ce_live":    ce_live,
            "ce_pct":     ce_pct,
            "ce_chg_oi":  int(lr.get("ce_chg_oi", 0)),
            "ce_volume":  int(lr.get("ce_volume", 0)),
            "pe_live":    pe_live,
            "pe_old":     pe_old,
            "pe_pct":     pe_pct,
            "pe_chg_oi":  int(lr.get("pe_chg_oi", 0)),
            "pe_volume":  int(lr.get("pe_volume", 0)),
            "is_atm":     s == atm,
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


# ── Participant OI Summary ────────────────────────────────────────────────────

def _format_contracts(val: int) -> str:
    """Format large numbers as K/L for display."""
    abs_val = abs(val)
    sign = "+" if val > 0 else ""
    if abs_val >= 100_000:
        return f"{sign}{val / 100_000:.1f}L"
    if abs_val >= 1_000:
        return f"{sign}{val / 1_000:.0f}K"
    return f"{sign}{val:,}"


def render_participant_summary(p_df: pd.DataFrame):
    """Render combined Index Options (CE+PE) gross OI chart + net contracts."""
    if p_df.empty:
        st.caption("No participant OI data yet. Available after 5:30 PM on trading days.")
        return

    trade_date = p_df["trade_date"].iloc[0]

    # Combine Index Call + Index Put into "Index Options"
    ce_row = None
    pe_row = None
    for _, row in p_df.iterrows():
        inst = str(row["instrument"]).strip().upper()
        if "CALL" in inst and "INDEX" in inst:
            ce_row = row
        elif "PUT" in inst and "INDEX" in inst:
            pe_row = row

    if ce_row is None and pe_row is None:
        st.caption("No index options participant data found.")
        return

    categories = ["Client", "FII", "DII", "Pro"]
    chart_data = []
    net_data = []

    for cat in categories:
        key = cat.lower()
        long_val = 0
        short_val = 0
        if ce_row is not None:
            long_val += int(ce_row.get(f"{key}_long", 0))
            short_val += int(ce_row.get(f"{key}_short", 0))
        if pe_row is not None:
            long_val += int(pe_row.get(f"{key}_long", 0))
            short_val += int(pe_row.get(f"{key}_short", 0))

        chart_data.append({"Participant": cat, "Position": "Long", "Contracts": long_val})
        chart_data.append({"Participant": cat, "Position": "Short", "Contracts": short_val})
        net_data.append({"participant": cat, "net": long_val - short_val})

    cdf = pd.DataFrame(chart_data)

    st.markdown(
        f'<div style="text-align:center; font-size:13px; color:#aaa; margin-bottom:4px;">'
        f'📅 {trade_date} &nbsp;&nbsp; <b>Gross Open Interest — Index Options</b></div>',
        unsafe_allow_html=True,
    )

    chart = alt.Chart(cdf).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        x=alt.X("Participant:N", axis=alt.Axis(labelAngle=0), sort=categories, title=None),
        y=alt.Y("Contracts:Q", title=""),
        color=alt.Color("Position:N", scale=alt.Scale(
            domain=["Long", "Short"],
            range=["#66BB6A", "#ef5350"],
        ), legend=alt.Legend(orient="top")),
        xOffset="Position:N",
        tooltip=[
            alt.Tooltip("Participant:N"),
            alt.Tooltip("Position:N"),
            alt.Tooltip("Contracts:Q", format=","),
        ],
    ).properties(height=260).configure_view(
        strokeWidth=0
    ).configure_axis(
        labelColor="#e0e0e0", titleColor="#e0e0e0",
        gridColor="#222", domainColor="#555",
    ).configure_legend(
        labelColor="#e0e0e0", titleColor="#e0e0e0",
    ).configure(background="#0e1117")

    st.altair_chart(chart, use_container_width=True)

    # Net contracts row below the chart
    net_cols = st.columns(len(net_data))
    for i, nd in enumerate(net_data):
        net = nd["net"]
        color = "#66BB6A" if net > 0 else "#ef5350"
        label = _format_contracts(net)
        with net_cols[i]:
            st.markdown(
                f'<div style="text-align:center;">'
                f'<div style="font-size:12px; color:#aaa;">{nd["participant"]}</div>'
                f'<div style="font-size:16px; font-weight:700; color:{color};">{label}</div>'
                f'<div style="font-size:10px; color:#666;">Net Contracts</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def render_oi_summary(symbol: str, totals: dict):
    """Render Total CE OI, Total PE OI, and PCR as metrics above the table."""
    if not totals:
        return

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Total CE OI", f"{totals['total_ce']:,}")
    with c2:
        st.metric("Total PE OI", f"{totals['total_pe']:,}")
    with c3:
        pcr = totals["pcr"]
        if pcr > 1.2:
            pcr_label = f"{pcr:.2f} 🟢 Bullish"
        elif pcr < 0.8:
            pcr_label = f"{pcr:.2f} 🔴 Bearish"
        else:
            pcr_label = f"{pcr:.2f} ⚪ Neutral"
        st.metric("PCR (Put/Call Ratio)", pcr_label)


# ── Interactive Table with clickable Live cells ──────────────────────────────

def _pct_tag(pct: float) -> str:
    """Format % change with colored arrow for button labels."""
    if pct == 0:
        return ""
    sign = "🟢▲" if pct > 0 else "🔴▼"
    return f"{sign}{abs(pct):.1f}%"


def _chg_fmt(val: int) -> str:
    if val > 0:
        return f"+{val:,}"
    return f"{val:,}"


def _chg_cls(val: int) -> str:
    if val > 0: return "up"
    if val < 0: return "dn"
    return "zr"


def render_oi_table(symbol: str, rows: list[dict]):
    """Render OI as an HTML table (mobile-friendly) + strike picker for charts."""

    html = ['<div class="oi-table-wrap"><table class="oi-table">']

    # Group headers
    html.append('<thead><tr>')
    html.append('<th class="group-ce" colspan="4">CALL (CE)</th>')
    html.append('<th class="group-strike">⬍</th>')
    html.append('<th class="group-pe" colspan="4">PUT (PE)</th>')
    html.append('</tr><tr>')
    for h in ["Vol", "Chg OI", "OI", "Live"]:
        html.append(f'<th class="sub">{h}</th>')
    html.append('<th class="sub" style="color:#ffd700">STRIKE</th>')
    for h in ["Live", "OI", "Chg OI", "Vol"]:
        html.append(f'<th class="sub">{h}</th>')
    html.append('</tr></thead>')

    # Data rows
    html.append('<tbody>')
    for row in rows:
        s = row["strike"]
        tr_cls = ' class="atm-row"' if row["is_atm"] else ""
        strike_cls = "strike-atm" if row["is_atm"] else "strike-cell"
        ce_tag = _pct_tag(row["ce_pct"])
        pe_tag = _pct_tag(row["pe_pct"])

        html.append(f'<tr{tr_cls}>')
        html.append(f'<td class="ce dim">{row["ce_volume"]:,}</td>')
        html.append(f'<td class="{_chg_cls(row["ce_chg_oi"])}">{_chg_fmt(row["ce_chg_oi"])}</td>')
        html.append(f'<td class="ce dim">{row["ce_old"]:,}</td>')
        html.append(f'<td class="live-val"><a href="?chart={symbol}_{s}#oi-chart">{row["ce_live"]:,} {ce_tag}</a></td>')
        html.append(f'<td class="{strike_cls}">{s:,}</td>')
        html.append(f'<td class="live-val"><a href="?chart={symbol}_{s}#oi-chart">{row["pe_live"]:,} {pe_tag}</a></td>')
        html.append(f'<td class="pe dim">{row["pe_old"]:,}</td>')
        html.append(f'<td class="{_chg_cls(row["pe_chg_oi"])}">{_chg_fmt(row["pe_chg_oi"])}</td>')
        html.append(f'<td class="pe dim">{row["pe_volume"]:,}</td>')
        html.append('</tr>')

    html.append('</tbody></table></div>')
    st.markdown('\n'.join(html), unsafe_allow_html=True)

    # Show chart if this symbol's strike was clicked (via query param)
    chart_param = st.query_params.get("chart", "")
    if chart_param.startswith(f"{symbol}_"):
        try:
            clicked_strike = int(chart_param.split("_", 1)[1])
            st.markdown('<div id="oi-chart"></div>', unsafe_allow_html=True)
            st.markdown(f"### 📈 OI Chart — {symbol} {clicked_strike:,}")
            render_strike_chart(symbol, float(clicked_strike))
            if st.button("✕ Close chart", key=f"close_chart_{symbol}"):
                st.query_params.clear()
                st.rerun()
        except (ValueError, IndexError):
            pass


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

    # ── Participant OI Summary (FII/DII/Pro/Client) ──
    p_df = get_latest_participant_oi()
    with st.expander("📊 Participant Positions (FII / DII / Pro / Client)", expanded=True):
        render_participant_summary(p_df)

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

            # OI Totals: Total CE, Total PE, PCR
            totals = get_closing_oi_totals(symbol)
            render_oi_summary(symbol, totals)

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
