"""
OI Tracker — FastAPI Backend
Thin wrapper around existing DB queries for the React frontend.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
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


def _parse_expiry_date(expiry_str: str) -> date | None:
    """Parse '21-Apr-2026' into a date object."""
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(expiry_str, fmt).date()
        except ValueError:
            continue
    return None


def _compute_levels(rows: list[dict], spot: float) -> dict:
    """Derive support, resistance, and max pain from OI data."""
    if not rows:
        return {"resistance": [], "support": [], "max_pain": None}

    spot_int = int(spot)

    ce_above = sorted(
        [r for r in rows if r["strike"] >= spot_int and r["ce_live"] > 0],
        key=lambda r: r["ce_live"], reverse=True,
    )
    resistance = [
        {"strike": r["strike"], "oi": r["ce_live"], "chg_oi": r["ce_chg_oi"]}
        for r in ce_above[:3]
    ]
    resistance.sort(key=lambda r: r["strike"])

    pe_below = sorted(
        [r for r in rows if r["strike"] <= spot_int and r["pe_live"] > 0],
        key=lambda r: r["pe_live"], reverse=True,
    )
    support = [
        {"strike": r["strike"], "oi": r["pe_live"], "chg_oi": r["pe_chg_oi"]}
        for r in pe_below[:3]
    ]
    support.sort(key=lambda r: r["strike"], reverse=True)

    all_strikes = [r["strike"] for r in rows]
    max_pain_strike = None
    min_pain = float("inf")
    for test_strike in all_strikes:
        pain = 0
        for r in rows:
            ce_itm = max(test_strike - r["strike"], 0) * r["ce_live"]
            pe_itm = max(r["strike"] - test_strike, 0) * r["pe_live"]
            pain += ce_itm + pe_itm
        if pain < min_pain:
            min_pain = pain
            max_pain_strike = test_strike

    return {
        "resistance": resistance,
        "support": support,
        "max_pain": max_pain_strike,
    }


# ── OI Data ──────────────────────────────────────────────────────────────────

@app.get("/api/expiries/{symbol}")
def get_expiries(symbol: str):
    """Return available expiry dates for the symbol from live data."""
    conn = get_db()
    if conn is None:
        raise HTTPException(404, "Database not found")

    today = date.today().isoformat()
    rows = conn.execute("""
        SELECT DISTINCT expiry FROM live_oi
        WHERE symbol = ? AND timestamp >= ?
        ORDER BY expiry
    """, [symbol, today]).fetchall()

    if not rows:
        rows = conn.execute("""
            SELECT DISTINCT expiry FROM live_oi
            WHERE symbol = ?
              AND timestamp = (SELECT MAX(timestamp) FROM live_oi WHERE symbol = ?)
            ORDER BY expiry
        """, [symbol, symbol]).fetchall()

    conn.close()

    expiries = []
    for r in rows:
        exp_str = r["expiry"]
        exp_date = _parse_expiry_date(exp_str)
        if exp_date:
            dte = (exp_date - date.today()).days
            expiries.append({"label": exp_str, "dte": max(dte, 0)})

    expiries.sort(key=lambda e: e["dte"])
    return {"expiries": expiries}


@app.get("/api/oi/{symbol}")
def get_oi_table(symbol: str, expiry: Optional[str] = Query(None)):
    """Main table data: live OI + yesterday close, merged into rows."""
    conn = get_db()
    if conn is None:
        raise HTTPException(404, "Database not found")

    today = date.today().isoformat()

    if not expiry:
        row = conn.execute("""
            SELECT expiry FROM live_oi
            WHERE symbol = ? AND timestamp >= ?
            ORDER BY expiry LIMIT 1
        """, [symbol, today]).fetchone()
        if not row:
            row = conn.execute("""
                SELECT expiry FROM live_oi
                WHERE symbol = ?
                  AND timestamp = (SELECT MAX(timestamp) FROM live_oi WHERE symbol = ?)
                ORDER BY expiry LIMIT 1
            """, [symbol, symbol]).fetchone()
        if row:
            expiry = row["expiry"]

    expiry_filter = ""
    params_extra = []
    if expiry:
        expiry_filter = " AND expiry = ?"
        params_extra = [expiry]

    live_rows = conn.execute(f"""
        SELECT * FROM live_oi
        WHERE symbol = ?
          AND timestamp >= ?
          AND timestamp = (
            SELECT MAX(timestamp) FROM live_oi
            WHERE symbol = ? AND timestamp >= ? {expiry_filter}
          )
          {expiry_filter}
        ORDER BY strike
    """, [symbol, today, symbol, today] + params_extra + params_extra).fetchall()

    old_rows = conn.execute(f"""
        SELECT * FROM closing_oi
        WHERE symbol = ?
          AND trade_date = (SELECT MAX(trade_date) FROM closing_oi WHERE symbol = ?)
          {expiry_filter}
        ORDER BY strike
    """, [symbol, symbol] + params_extra).fetchall()

    snap_count = conn.execute(
        "SELECT COUNT(DISTINCT timestamp) FROM live_oi WHERE symbol = ? AND timestamp >= ?",
        [symbol, today]
    ).fetchone()[0]

    totals = conn.execute(f"""
        SELECT
            COALESCE(SUM(ce_oi), 0) as total_ce,
            COALESCE(SUM(pe_oi), 0) as total_pe
        FROM live_oi
        WHERE symbol = ?
          AND timestamp >= ?
          AND timestamp = (
            SELECT MAX(timestamp) FROM live_oi
            WHERE symbol = ? AND timestamp >= ? {expiry_filter}
          )
          {expiry_filter}
    """, [symbol, today, symbol, today] + params_extra + params_extra).fetchone()

    current_expiry = None
    if live_rows:
        current_expiry = live_rows[0]["expiry"]
    conn.close()

    if not live_rows:
        return {"rows": [], "spot": 0, "last_update": None, "snap_count": snap_count,
                "totals": {"total_ce": 0, "total_pe": 0, "pcr": 0}, "old_date": None,
                "expiry": None, "dte": None}

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

    dte = None
    if current_expiry:
        exp_date = _parse_expiry_date(current_expiry)
        if exp_date:
            dte = max((exp_date - date.today()).days, 0)

    levels = _compute_levels(rows, spot)

    return {
        "rows": rows,
        "spot": spot,
        "last_update": last_update,
        "snap_count": snap_count,
        "totals": {"total_ce": total_ce, "total_pe": total_pe, "pcr": round(pcr, 2)},
        "old_date": old_date,
        "expiry": current_expiry,
        "dte": dte,
        "levels": levels,
    }


@app.get("/api/chart/{symbol}/{strike}")
def get_chart_data(symbol: str, strike: int, expiry: Optional[str] = Query(None)):
    """Intraday CE + PE OI time-series for a single strike."""
    conn = get_db()
    if conn is None:
        raise HTTPException(404, "Database not found")

    today = date.today().isoformat()

    if not expiry:
        row = conn.execute("""
            SELECT expiry FROM live_oi
            WHERE symbol = ? AND strike = ? AND timestamp >= ?
            ORDER BY expiry LIMIT 1
        """, [symbol, strike, today]).fetchone()
        if row:
            expiry = row["expiry"]

    expiry_filter = " AND expiry = ?" if expiry else ""
    params = [symbol, strike, today] + ([expiry] if expiry else [])

    rows = conn.execute(f"""
        SELECT timestamp, ce_oi, pe_oi, ce_ltp, pe_ltp, spot
        FROM live_oi
        WHERE symbol = ? AND strike = ? AND timestamp >= ?
        {expiry_filter}
        ORDER BY timestamp
    """, params).fetchall()
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
        ce_long = int(ce_row.get(f"{cat}_long", 0)) if ce_row else 0
        ce_short = int(ce_row.get(f"{cat}_short", 0)) if ce_row else 0
        pe_long = int(pe_row.get(f"{cat}_long", 0)) if pe_row else 0
        pe_short = int(pe_row.get(f"{cat}_short", 0)) if pe_row else 0
        participants.append({
            "name": cat.upper() if cat in ("fii", "dii") else cat.capitalize(),
            "ce_long": ce_long, "ce_short": ce_short,
            "pe_long": pe_long, "pe_short": pe_short,
            "long": ce_long + pe_long,
            "short": ce_short + pe_short,
            "net": (ce_long + pe_long) - (ce_short + pe_short),
        })

    return {"available": True, "data": participants, "trade_date": trade_date}


@app.get("/api/futures/{symbol}")
def get_futures(symbol: str):
    """Fetch nearest-month futures price for the symbol."""
    try:
        from pnsea import NSE
        nse = NSE()
        raw = nse.session.get(
            "https://www.nseindia.com/api/liveEquity-derivatives?index=nse50_fut",
            timeout=10,
        )
        for item in raw.json().get("data", []):
            if item.get("underlying") == symbol and item.get("instrumentType") == "FUTIDX":
                spot = item.get("underlyingValue", 0)
                fut = item.get("lastPrice", 0)
                premium = round(fut - spot, 2) if spot and fut else 0
                return {
                    "available": True,
                    "price": fut,
                    "change": item.get("change", 0),
                    "pct_change": item.get("pChange", 0),
                    "open": item.get("openPrice", 0),
                    "high": item.get("highPrice", 0),
                    "low": item.get("lowPrice", 0),
                    "oi": item.get("openInterest", 0),
                    "volume": item.get("volume", 0),
                    "expiry": item.get("expiryDate", ""),
                    "premium": premium,
                }
    except Exception:
        pass
    return {"available": False}


@app.get("/api/vix")
def get_vix():
    """Fetch India VIX from NSE."""
    try:
        from pnsea import NSE
        nse = NSE()
        raw = nse.session.get(
            "https://www.nseindia.com/api/allIndices", timeout=10
        )
        for item in raw.json().get("data", []):
            if item.get("indexSymbol") == "INDIA VIX":
                return {
                    "available": True,
                    "value": item.get("last", 0),
                    "change": item.get("variation", 0),
                    "pct_change": item.get("percentChange", 0),
                    "open": item.get("open", 0),
                    "high": item.get("high", 0),
                    "low": item.get("low", 0),
                    "prev_close": item.get("previousClose", 0),
                }
    except Exception:
        pass
    return {"available": False}


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
