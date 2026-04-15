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

    # Participant-wise OI CSV
    try:
        import nsepython as nsepy
        date_str = datetime.now(IST).strftime("%d%b%Y").upper()
        p_df = nsepy.get_fao_participant_oi(date_str)
        if p_df is not None and not p_df.empty:
            for _, row in p_df.iterrows():
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
                        str(row.iloc[0]) if len(row) > 0 else "",
                        int(row.iloc[1]) if len(row) > 1 else 0,
                        int(row.iloc[2]) if len(row) > 2 else 0,
                        int(row.iloc[3]) if len(row) > 3 else 0,
                        int(row.iloc[4]) if len(row) > 4 else 0,
                        int(row.iloc[5]) if len(row) > 5 else 0,
                        int(row.iloc[6]) if len(row) > 6 else 0,
                        int(row.iloc[7]) if len(row) > 7 else 0,
                        int(row.iloc[8]) if len(row) > 8 else 0,
                    ))
            logger.info("  Participant OI saved")
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
