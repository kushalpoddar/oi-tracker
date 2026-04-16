"""
OI Tracker — FastAPI Backend
Thin wrapper around existing DB queries for the React frontend.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

DB_PATH = Path(__file__).parent / "data" / "oi_tracker.db"

app = FastAPI(title="OI Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ── OI Data ──────────────────────────────────────────────────────────────────

@app.get("/api/oi/{symbol}")
def get_oi_table(symbol: str):
    """Main table data: live OI + yesterday close, merged into rows."""
    conn = get_db()
    if conn is None:
        raise HTTPException(404, "Database not found")

    today = date.today().isoformat()

    live_rows = conn.execute("""
        SELECT * FROM live_oi
        WHERE symbol = ?
          AND timestamp >= ?
          AND timestamp = (SELECT MAX(timestamp) FROM live_oi WHERE symbol = ? AND timestamp >= ?)
        ORDER BY strike
    """, [symbol, today, symbol, today]).fetchall()

    old_rows = conn.execute("""
        SELECT * FROM closing_oi
        WHERE symbol = ?
          AND trade_date = (SELECT MAX(trade_date) FROM closing_oi WHERE symbol = ?)
        ORDER BY strike
    """, [symbol, symbol]).fetchall()

    snap_count = conn.execute(
        "SELECT COUNT(DISTINCT timestamp) FROM live_oi WHERE symbol = ? AND timestamp >= ?",
        [symbol, today]
    ).fetchone()[0]

    totals = conn.execute("""
        SELECT
            COALESCE(SUM(ce_oi), 0) as total_ce,
            COALESCE(SUM(pe_oi), 0) as total_pe
        FROM live_oi
        WHERE symbol = ?
          AND timestamp >= ?
          AND timestamp = (SELECT MAX(timestamp) FROM live_oi WHERE symbol = ? AND timestamp >= ?)
    """, [symbol, today, symbol, today]).fetchone()

    conn.close()

    if not live_rows:
        return {"rows": [], "spot": 0, "last_update": None, "snap_count": snap_count,
                "totals": {"total_ce": 0, "total_pe": 0, "pcr": 0}, "old_date": None}

    spot = live_rows[0]["spot"]
    last_update = live_rows[0]["timestamp"]

    old_map = {}
    old_date = None
    for r in old_rows:
        old_map[r["strike"]] = dict(r)
        if old_date is None and "trade_date" in r.keys():
            old_date = r["trade_date"]

    strikes = sorted(set(r["strike"] for r in live_rows))
    atm = min(strikes, key=lambda x: abs(x - spot))

    rows = []
    for lr in live_rows:
        s = lr["strike"]
        o = old_map.get(s, {})
        ce_old = int(o.get("ce_oi", 0))
        ce_live = int(lr["ce_oi"] or 0)
        pe_old = int(o.get("pe_oi", 0))
        pe_live = int(lr["pe_oi"] or 0)
        ce_pct = ((ce_live - ce_old) / ce_old * 100) if ce_old else 0.0
        pe_pct = ((pe_live - pe_old) / pe_old * 100) if pe_old else 0.0
        rows.append({
            "strike": int(s),
            "ce_old": ce_old, "ce_live": ce_live, "ce_pct": round(ce_pct, 1),
            "ce_chg_oi": int(lr["ce_chg_oi"] or 0), "ce_volume": int(lr["ce_volume"] or 0),
            "pe_old": pe_old, "pe_live": pe_live, "pe_pct": round(pe_pct, 1),
            "pe_chg_oi": int(lr["pe_chg_oi"] or 0), "pe_volume": int(lr["pe_volume"] or 0),
            "is_atm": s == atm,
        })

    total_ce = totals[0] if totals else 0
    total_pe = totals[1] if totals else 0
    pcr = total_pe / total_ce if total_ce > 0 else 0

    return {
        "rows": rows,
        "spot": spot,
        "last_update": last_update,
        "snap_count": snap_count,
        "totals": {"total_ce": total_ce, "total_pe": total_pe, "pcr": round(pcr, 2)},
        "old_date": old_date,
    }


@app.get("/api/chart/{symbol}/{strike}")
def get_chart_data(symbol: str, strike: int):
    """Intraday CE + PE OI time-series for a single strike."""
    conn = get_db()
    if conn is None:
        raise HTTPException(404, "Database not found")

    today = date.today().isoformat()
    rows = conn.execute("""
        SELECT timestamp, ce_oi, pe_oi, ce_ltp, pe_ltp, spot
        FROM live_oi
        WHERE symbol = ? AND strike = ? AND timestamp >= ?
        ORDER BY timestamp
    """, [symbol, strike, today]).fetchall()
    conn.close()

    return [dict(r) for r in rows]


@app.get("/api/participants")
def get_participants():
    """Participant-wise OI summary (FII/DII/Pro/Client) for Index Options."""
    conn = get_db()
    if conn is None:
        return {"available": False, "data": [], "trade_date": None}

    try:
        rows = conn.execute("""
            SELECT * FROM participant_oi
            WHERE trade_date = (SELECT MAX(trade_date) FROM participant_oi)
            ORDER BY instrument
        """).fetchall()
    except Exception:
        conn.close()
        return {"available": False, "data": [], "trade_date": None}

    conn.close()

    if not rows:
        return {"available": False, "data": [], "trade_date": None}

    trade_date = rows[0]["trade_date"]

    ce_row = pe_row = None
    for r in rows:
        inst = str(r["instrument"]).strip().upper()
        if "CALL" in inst and "INDEX" in inst:
            ce_row = dict(r)
        elif "PUT" in inst and "INDEX" in inst:
            pe_row = dict(r)

    categories = ["fii", "dii", "pro", "client"]
    participants = []
    for cat in categories:
        long_val = short_val = 0
        if ce_row:
            long_val += int(ce_row.get(f"{cat}_long", 0))
            short_val += int(ce_row.get(f"{cat}_short", 0))
        if pe_row:
            long_val += int(pe_row.get(f"{cat}_long", 0))
            short_val += int(pe_row.get(f"{cat}_short", 0))
        participants.append({
            "name": cat.upper() if cat in ("fii", "dii") else cat.capitalize(),
            "long": long_val,
            "short": short_val,
            "net": long_val - short_val,
        })

    return {"available": True, "data": participants, "trade_date": trade_date}


@app.get("/api/status")
def get_status():
    """App status: current time, snapshot count."""
    conn = get_db()
    snap_count = 0
    if conn:
        today = date.today().isoformat()
        snap_count = conn.execute(
            "SELECT COUNT(DISTINCT timestamp) FROM live_oi WHERE symbol = 'NIFTY' AND timestamp >= ?",
            [today]
        ).fetchone()[0]
        conn.close()

    return {
        "time": datetime.now().strftime("%H:%M:%S"),
        "snap_count": snap_count,
        "symbols": ["NIFTY", "BANKNIFTY"],
    }


# Serve React static build
static_dir = Path(__file__).parent / "frontend" / "dist"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
