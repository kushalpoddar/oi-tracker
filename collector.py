#!/usr/bin/env python3
"""
Standalone OI Data Collector
============================
Run via cron — no browser needed.

Modes:
  --live     Fetch live OI snapshot (every 5 min during market hours)
  --close    Fetch day-end closing OI (run once after 3:30 PM)
  --dayend   Fetch participant-wise OI FII/DII/Pro/Retail (run after 5:30 PM)

Crontab entries:
  */5 9-15 * * 1-5  cd /path/to/oi-tracker && python3 collector.py --live
  35 15 * * 1-5     cd /path/to/oi-tracker && python3 collector.py --close
  30 17 * * 1-5     cd /path/to/oi-tracker && python3 collector.py --dayend
"""

from __future__ import annotations

import sys
import logging
import sqlite3
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import pytz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("collector")

IST = pytz.timezone("Asia/Kolkata")
DB_PATH = Path(__file__).parent / "data" / "oi_tracker.db"
SYMBOLS = ["NIFTY", "BANKNIFTY"]
ATM_RANGE = 10


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    with conn:
        conn.executescript("""
            -- Live 5-min snapshots
            CREATE TABLE IF NOT EXISTS live_oi (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT    NOT NULL,
                strike      REAL    NOT NULL,
                expiry      TEXT    NOT NULL,
                timestamp   TEXT    NOT NULL,
                ce_oi       INTEGER DEFAULT 0,
                ce_chg_oi   INTEGER DEFAULT 0,
                ce_ltp      REAL    DEFAULT 0,
                ce_iv       REAL    DEFAULT 0,
                ce_volume   INTEGER DEFAULT 0,
                pe_oi       INTEGER DEFAULT 0,
                pe_chg_oi   INTEGER DEFAULT 0,
                pe_ltp      REAL    DEFAULT 0,
                pe_iv       REAL    DEFAULT 0,
                pe_volume   INTEGER DEFAULT 0,
                spot        REAL    DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_live_oi_sym_ts
                ON live_oi (symbol, timestamp);
            CREATE INDEX IF NOT EXISTS idx_live_oi_strike
                ON live_oi (symbol, strike, timestamp);

            -- Day-end closing OI (snapshot at 3:30 PM)
            CREATE TABLE IF NOT EXISTS closing_oi (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date  TEXT    NOT NULL,
                symbol      TEXT    NOT NULL,
                strike      REAL    NOT NULL,
                expiry      TEXT    NOT NULL,
                ce_oi       INTEGER DEFAULT 0,
                ce_chg_oi   INTEGER DEFAULT 0,
                ce_ltp      REAL    DEFAULT 0,
                ce_iv       REAL    DEFAULT 0,
                pe_oi       INTEGER DEFAULT 0,
                pe_chg_oi   INTEGER DEFAULT 0,
                pe_ltp      REAL    DEFAULT 0,
                pe_iv       REAL    DEFAULT 0,
                spot        REAL    DEFAULT 0,
                UNIQUE(trade_date, symbol, strike, expiry)
            );

            -- Participant-wise OI (FII/DII/Pro/Retail) day-end
            CREATE TABLE IF NOT EXISTS participant_oi (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date  TEXT    NOT NULL,
                instrument  TEXT    NOT NULL,
                client_long INTEGER DEFAULT 0,
                client_short INTEGER DEFAULT 0,
                dii_long    INTEGER DEFAULT 0,
                dii_short   INTEGER DEFAULT 0,
                fii_long    INTEGER DEFAULT 0,
                fii_short   INTEGER DEFAULT 0,
                pro_long    INTEGER DEFAULT 0,
                pro_short   INTEGER DEFAULT 0,
                UNIQUE(trade_date, instrument)
            );

            -- FII/DII daily cash+FnO activity
            CREATE TABLE IF NOT EXISTS fii_dii_activity (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date  TEXT    NOT NULL,
                category    TEXT    NOT NULL,
                buy_value   REAL    DEFAULT 0,
                sell_value  REAL    DEFAULT 0,
                net_value   REAL    DEFAULT 0,
                UNIQUE(trade_date, category)
            );
        """)
    conn.close()


def fetch_oi_for_symbol(symbol: str, expiry: str | None = None) -> tuple:
    """Fetch OI via pnsea, return (df, expiry_list, spot)."""
    from pnsea import NSE
    nse = NSE()
    df, expiries, spot = nse.options.option_chain(symbol, expiry_date=expiry)
    return df, expiries, float(spot)


def filter_atm_strikes(df: pd.DataFrame, spot: float, n: int = ATM_RANGE) -> pd.DataFrame:
    strikes = sorted(df["strikePrice"].unique())
    if not strikes:
        return df
    atm = min(strikes, key=lambda x: abs(x - spot))
    idx = strikes.index(atm)
    selected = strikes[max(0, idx - n): idx + n + 1]
    return df[df["strikePrice"].isin(selected)].copy()


# ---------------------------------------------------------------------------
# --live: 5-min snapshot
# ---------------------------------------------------------------------------

def collect_live():
    now = datetime.now(IST)
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Collecting live OI at {ts}")

    conn = get_db()

    for symbol in SYMBOLS:
        try:
            df, expiries, spot = fetch_oi_for_symbol(symbol)
            expiry = expiries[0] if expiries else ""
            df = filter_atm_strikes(df, spot, ATM_RANGE)

            records = []
            for _, row in df.iterrows():
                records.append((
                    symbol,
                    float(row["strikePrice"]),
                    expiry,
                    ts,
                    int(row.get("CE_openInterest", 0) or 0),
                    int(row.get("CE_changeinOpenInterest", 0) or 0),
                    float(row.get("CE_lastPrice", 0) or 0),
                    float(row.get("CE_impliedVolatility", 0) or 0),
                    int(row.get("CE_totalTradedVolume", 0) or 0),
                    int(row.get("PE_openInterest", 0) or 0),
                    int(row.get("PE_changeinOpenInterest", 0) or 0),
                    float(row.get("PE_lastPrice", 0) or 0),
                    float(row.get("PE_impliedVolatility", 0) or 0),
                    int(row.get("PE_totalTradedVolume", 0) or 0),
                    spot,
                ))

            with conn:
                conn.executemany("""
                    INSERT INTO live_oi
                        (symbol, strike, expiry, timestamp,
                         ce_oi, ce_chg_oi, ce_ltp, ce_iv, ce_volume,
                         pe_oi, pe_chg_oi, pe_ltp, pe_iv, pe_volume, spot)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, records)

            logger.info(f"  {symbol}: {len(records)} strikes saved (spot={spot:.0f})")

        except Exception as e:
            logger.error(f"  {symbol} failed: {e}")

    conn.close()


# ---------------------------------------------------------------------------
# --close: day-end closing snapshot at 3:30 PM
# ---------------------------------------------------------------------------

def collect_closing():
    today = date.today().isoformat()
    logger.info(f"Collecting closing OI for {today}")

    conn = get_db()

    for symbol in SYMBOLS:
        try:
            df, expiries, spot = fetch_oi_for_symbol(symbol)
            expiry = expiries[0] if expiries else ""
            df = filter_atm_strikes(df, spot, ATM_RANGE)

            for _, row in df.iterrows():
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO closing_oi
                            (trade_date, symbol, strike, expiry,
                             ce_oi, ce_chg_oi, ce_ltp, ce_iv,
                             pe_oi, pe_chg_oi, pe_ltp, pe_iv, spot)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        today, symbol,
                        float(row["strikePrice"]),
                        expiry,
                        int(row.get("CE_openInterest", 0) or 0),
                        int(row.get("CE_changeinOpenInterest", 0) or 0),
                        float(row.get("CE_lastPrice", 0) or 0),
                        float(row.get("CE_impliedVolatility", 0) or 0),
                        int(row.get("PE_openInterest", 0) or 0),
                        int(row.get("PE_changeinOpenInterest", 0) or 0),
                        float(row.get("PE_lastPrice", 0) or 0),
                        float(row.get("PE_impliedVolatility", 0) or 0),
                        spot,
                    ))

            logger.info(f"  {symbol}: closing OI saved")

        except Exception as e:
            logger.error(f"  {symbol} failed: {e}")

    conn.close()


# ---------------------------------------------------------------------------
# Participant-wise OI CSV fetcher
# ---------------------------------------------------------------------------

def fetch_participant_oi_csv() -> pd.DataFrame | None:
    """Fetch participant-wise OI CSV from NSE archives and return normalized rows."""
    import io
    import urllib.request

    now = datetime.now(IST)
    date_ddmmyyyy = now.strftime("%d%m%Y")

    urls = [
        f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{date_ddmmyyyy}.csv",
        f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{date_ddmmyyyy}.csv",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/csv,text/html,application/xhtml+xml,*/*",
        "Referer": "https://www.nseindia.com/",
    }

    for url in urls:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                csv_text = resp.read().decode("utf-8")
                # Skip the first title row, use row 2 as header
                df = pd.read_csv(io.StringIO(csv_text), skiprows=1)
                df.columns = [c.strip() for c in df.columns]
                if not df.empty:
                    logger.info(f"  Fetched participant OI from {url}")
                    return df
        except Exception as e:
            logger.debug(f"  {url} failed: {e}")
            continue

    return None


def _safe_int(val) -> int:
    """Convert a value to int, stripping commas and handling non-numeric gracefully."""
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0


def normalize_participant_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pivot the NSE participant OI CSV from:
        Rows: Client, DII, FII, Pro  |  Cols: Future Index Long, Future Index Short, ...
    Into:
        Rows: Index Futures, Index Call Options, ...  |  Cols: client_long, client_short, fii_long, ...
    """
    # CSV columns: Client Type, Future Index Long, Future Index Short,
    # Future Stock Long, Future Stock Short, Option Index Call Long,
    # Option Index Put Long, Option Index Call Short, Option Index Put Short,
    # Option Stock Call Long, Option Stock Put Long, Option Stock Call Short,
    # Option Stock Put Short, Total Long Contracts, Total Short Contracts

    instruments = {
        "Index Futures":       ("Future Index Long",       "Future Index Short"),
        "Index Call Options":  ("Option Index Call Long",  "Option Index Call Short"),
        "Index Put Options":   ("Option Index Put Long",   "Option Index Put Short"),
        "Stock Futures":       ("Future Stock Long",       "Future Stock Short"),
        "Stock Call Options":  ("Option Stock Call Long",  "Option Stock Call Short"),
        "Stock Put Options":   ("Option Stock Put Long",   "Option Stock Put Short"),
    }

    participant_map = {"client": "client", "dii": "dii", "fii": "fii", "pro": "pro"}

    # Build lookup: participant name → row
    p_rows = {}
    for _, row in df.iterrows():
        name = str(row.iloc[0]).strip().lower()
        if name in participant_map:
            p_rows[name] = row

    if not p_rows:
        return pd.DataFrame()

    result = []
    for inst_name, (long_col, short_col) in instruments.items():
        row_data = {"instrument": inst_name}
        for p_key, prefix in participant_map.items():
            if p_key not in p_rows:
                continue
            p_row = p_rows[p_key]
            row_data[f"{prefix}_long"] = _safe_int(p_row.get(long_col, 0))
            row_data[f"{prefix}_short"] = _safe_int(p_row.get(short_col, 0))
        result.append(row_data)

    return pd.DataFrame(result) if result else pd.DataFrame()


# ---------------------------------------------------------------------------
# --dayend: participant OI + FII/DII activity (after 5:30 PM)
# ---------------------------------------------------------------------------

def collect_dayend():
    today = date.today().isoformat()
    logger.info(f"Collecting day-end participant data for {today}")

    conn = get_db()

    # FII/DII activity via nsepython
    try:
        import nsepython as nsepy
        fii_df = nsepy.nse_fiidii()
        if fii_df is not None and not fii_df.empty:
            for _, row in fii_df.iterrows():
                buy = float(str(row.get("buyValue", 0)).replace(",", "") or 0)
                sell = float(str(row.get("sellValue", 0)).replace(",", "") or 0)
                net = float(str(row.get("netValue", 0)).replace(",", "") or 0)
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO fii_dii_activity
                            (trade_date, category, buy_value, sell_value, net_value)
                        VALUES (?,?,?,?,?)
                    """, (str(row.get("date", today)), str(row.get("category", "")), buy, sell, net))
            logger.info("  FII/DII activity saved")
    except Exception as e:
        logger.error(f"  FII/DII failed: {e}")

    # Participant-wise OI CSV from NSE archives
    try:
        p_df = fetch_participant_oi_csv()
        if p_df is not None and not p_df.empty:
            p_df = normalize_participant_df(p_df)
            for _, row in p_df.iterrows():
                instrument = str(row.get("instrument", "")).strip()
                if not instrument:
                    continue
                with conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO participant_oi
                            (trade_date, instrument,
                             client_long, client_short,
                             dii_long, dii_short,
                             fii_long, fii_short,
                             pro_long, pro_short)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                    """, (
                        today,
                        instrument,
                        _safe_int(row.get("client_long", 0)),
                        _safe_int(row.get("client_short", 0)),
                        _safe_int(row.get("dii_long", 0)),
                        _safe_int(row.get("dii_short", 0)),
                        _safe_int(row.get("fii_long", 0)),
                        _safe_int(row.get("fii_short", 0)),
                        _safe_int(row.get("pro_long", 0)),
                        _safe_int(row.get("pro_short", 0)),
                    ))
            logger.info("  Participant OI saved")
        else:
            logger.warning("  Participant OI CSV not available yet (published ~5-6 PM IST)")
    except Exception as e:
        logger.error(f"  Participant OI failed: {e}")

    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()

    if len(sys.argv) < 2:
        print("Usage: python3 collector.py --live | --close | --dayend | --all")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "--live":
        collect_live()
    elif mode == "--close":
        collect_closing()
    elif mode == "--dayend":
        collect_dayend()
    elif mode == "--all":
        collect_live()
        collect_closing()
        collect_dayend()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
