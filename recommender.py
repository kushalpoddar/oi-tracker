#!/usr/bin/env python3
"""
NIFTY/BANKNIFTY Trade Recommender
==================================
One big function: recommend(date, budget) → JSON

Fetches all data for a given date, analyzes OI/participant/IV/PCR,
and outputs ranked trade suggestions for the next trading day.

Usage:
  python recommender.py --date 2026-04-15 --budget 10000
  python recommender.py --backtest --from 2026-03-15 --to 2026-04-15 --budget 10000
"""

from __future__ import annotations

import sys
import json
import math
import logging
import urllib.request
import io
import zipfile
from datetime import datetime, date, timedelta
from typing import Optional

import pandas as pd
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("recommender")

IST = pytz.timezone("Asia/Kolkata")
SYMBOLS = ["NIFTY", "BANKNIFTY"]
LOT_SIZE = {"NIFTY": 75, "BANKNIFTY": 30}
ATM_RANGE = 12

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    "Referer": "https://www.nseindia.com/",
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_option_chain(symbol: str) -> tuple[pd.DataFrame, list[str], float]:
    from pnsea import NSE
    nse = NSE()
    df, expiries, spot = nse.options.option_chain(symbol)
    return df, expiries, float(spot)


def fetch_bhavcopy(target_date: date) -> pd.DataFrame:
    """Download NSE F&O Bhavcopy for a given date. Returns raw DataFrame."""
    date_str = target_date.strftime("%Y%m%d")
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip"
    try:
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            zf = zipfile.ZipFile(io.BytesIO(resp.read()))
            df = pd.read_csv(zf.open(zf.namelist()[0]))
            return df
    except Exception as e:
        logger.debug(f"Bhavcopy for {target_date} failed: {e}")
        return pd.DataFrame()


def bhavcopy_to_option_chain(bhavcopy: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, list[str], float]:
    """
    Convert Bhavcopy rows into the same format as pnsea's option_chain(),
    so the rest of the analysis engine works unchanged.

    Returns (df, expiries, spot) matching fetch_option_chain() signature.
    """
    # IDO = Index Option, IDF = Index Future
    opts = bhavcopy[
        (bhavcopy["TckrSymb"] == symbol) & (bhavcopy["FinInstrmTp"] == "IDO")
    ].copy()

    if opts.empty:
        return pd.DataFrame(), [], 0.0

    spot = float(opts["UndrlygPric"].iloc[0])
    expiries = sorted(opts["XpryDt"].unique())
    nearest_expiry = expiries[0]

    # Use nearest weekly expiry only
    opts = opts[opts["XpryDt"] == nearest_expiry].copy()

    ce = opts[opts["OptnTp"] == "CE"].copy()
    pe = opts[opts["OptnTp"] == "PE"].copy()

    # Build merged strike-level dataframe matching pnsea column names
    ce = ce.rename(columns={
        "StrkPric": "strikePrice",
        "OpnIntrst": "CE_openInterest",
        "ChngInOpnIntrst": "CE_changeinOpenInterest",
        "TtlTradgVol": "CE_totalTradedVolume",
        "ClsPric": "CE_lastPrice",
    })[["strikePrice", "CE_openInterest", "CE_changeinOpenInterest",
        "CE_totalTradedVolume", "CE_lastPrice"]]

    pe = pe.rename(columns={
        "StrkPric": "strikePrice",
        "OpnIntrst": "PE_openInterest",
        "ChngInOpnIntrst": "PE_changeinOpenInterest",
        "TtlTradgVol": "PE_totalTradedVolume",
        "ClsPric": "PE_lastPrice",
    })[["strikePrice", "PE_openInterest", "PE_changeinOpenInterest",
        "PE_totalTradedVolume", "PE_lastPrice"]]

    merged = pd.merge(ce, pe, on="strikePrice", how="outer").fillna(0)

    # Bhavcopy doesn't have IV — estimate from closing prices using simple ATM straddle method
    # IV ≈ straddle_price / spot * sqrt(365/DTE) * 100
    atm_strike = min(merged["strikePrice"].unique(), key=lambda x: abs(x - spot))
    atm_row = merged[merged["strikePrice"] == atm_strike]
    if not atm_row.empty:
        atm_ce_price = float(atm_row["CE_lastPrice"].iloc[0])
        atm_pe_price = float(atm_row["PE_lastPrice"].iloc[0])
        straddle = atm_ce_price + atm_pe_price
        # Approximate DTE from expiry date
        try:
            exp_dt = datetime.strptime(nearest_expiry, "%Y-%m-%d").date()
            dte = max((exp_dt - target_date).days, 1)
        except Exception:
            dte = 5
        estimated_iv = round((straddle / spot) * math.sqrt(365 / dte) * 100, 2)
    else:
        estimated_iv = 15.0

    # Add IV columns (uniform estimate — best we can do without actual IV data)
    merged["CE_impliedVolatility"] = estimated_iv
    merged["PE_impliedVolatility"] = estimated_iv

    for col in ["CE_openInterest", "PE_openInterest", "CE_changeinOpenInterest",
                 "PE_changeinOpenInterest", "CE_totalTradedVolume", "PE_totalTradedVolume"]:
        merged[col] = merged[col].astype(int)

    return merged, expiries, spot


def fetch_historical_spot(bhavcopy: pd.DataFrame, symbol: str) -> dict:
    """Extract spot OHLC from Bhavcopy's underlying price + futures data."""
    # Get underlying from options
    opts = bhavcopy[
        (bhavcopy["TckrSymb"] == symbol) & (bhavcopy["FinInstrmTp"].isin(["IDO", "IDF"]))
    ]
    if opts.empty:
        return {}

    spot = float(opts["UndrlygPric"].iloc[0])

    # Get nearest month futures for OHLC as proxy
    futs = bhavcopy[
        (bhavcopy["TckrSymb"] == symbol) & (bhavcopy["FinInstrmTp"] == "IDF")
    ].sort_values("XpryDt")

    if not futs.empty:
        f = futs.iloc[0]
        return {
            "open": float(f["OpnPric"]),
            "high": float(f["HghPric"]),
            "low": float(f["LwPric"]),
            "close": spot,
            "prev_close": float(f["PrvsClsgPric"]) if f["PrvsClsgPric"] != 0 else spot,
            "change_pct": round((spot - float(f["PrvsClsgPric"])) / max(float(f["PrvsClsgPric"]), 1) * 100, 2),
        }

    return {"open": spot, "high": spot, "low": spot, "close": spot, "prev_close": spot, "change_pct": 0}


def fetch_participant_oi(target_date: date) -> pd.DataFrame:
    date_str = target_date.strftime("%d%m%Y")
    urls = [
        f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{date_str}.csv",
        f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{date_str}.csv",
    ]
    for url in urls:
        try:
            req = urllib.request.Request(url, headers=HTTP_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                csv_text = resp.read().decode("utf-8")
                df = pd.read_csv(io.StringIO(csv_text), skiprows=1)
                df.columns = [c.strip() for c in df.columns]
                if not df.empty:
                    return df
        except Exception:
            continue
    return pd.DataFrame()


def fetch_fii_dii() -> pd.DataFrame:
    try:
        import nsepython as nsepy
        return nsepy.nse_fiidii()
    except Exception:
        return pd.DataFrame()


def fetch_spot_price(symbol: str) -> dict:
    """Fetch current/latest spot price and day OHLC."""
    from pnsea import NSE
    nse = NSE()
    index_name = "NIFTY 50" if symbol == "NIFTY" else "NIFTY BANK"
    url = f"https://www.nseindia.com/api/equity-stockIndices?index={index_name.replace(' ', '%20')}"
    try:
        resp = nse.session.get(url)
        data = resp.json()
        if "data" in data and data["data"]:
            d = data["data"][0]
            return {
                "open": float(d.get("open", 0)),
                "high": float(d.get("dayHigh", 0)),
                "low": float(d.get("dayLow", 0)),
                "close": float(d.get("lastPrice", 0)),
                "prev_close": float(d.get("previousClose", 0)),
                "change_pct": float(d.get("pChange", 0)),
            }
    except Exception as e:
        logger.warning(f"Could not fetch spot price for {symbol}: {e}")
    return {}


def fetch_index_history(symbol: str, from_date: date, to_date: date) -> pd.DataFrame:
    """Fetch historical daily OHLC for NIFTY/BANKNIFTY via yfinance."""
    import yfinance as yf

    ticker = "^NSEI" if symbol == "NIFTY" else "^NSEBANK"
    try:
        raw = yf.download(
            ticker,
            start=from_date.strftime("%Y-%m-%d"),
            end=(to_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            progress=False,
        )
        if raw.empty:
            return pd.DataFrame()

        # yfinance returns MultiIndex columns like (Close, ^NSEI); flatten them
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]

        df = pd.DataFrame({
            "date": raw.index,
            "open": raw["Open"].values,
            "high": raw["High"].values,
            "low": raw["Low"].values,
            "close": raw["Close"].values,
        }).reset_index(drop=True)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.warning(f"yfinance fetch failed for {symbol}: {e}")
        return pd.DataFrame()


def get_next_trading_day_price(symbol: str, after_date: date, history_df: pd.DataFrame) -> Optional[dict]:
    """Get the next trading day's OHLC from pre-fetched history."""
    if history_df.empty:
        return None
    after_ts = pd.Timestamp(after_date)
    future = history_df[history_df["date"] > after_ts]
    if future.empty:
        return None
    row = future.iloc[0]
    return {
        "date": row["date"].strftime("%Y-%m-%d"),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
    }


def filter_atm_strikes(df: pd.DataFrame, spot: float, n: int = ATM_RANGE) -> pd.DataFrame:
    strikes = sorted(df["strikePrice"].unique())
    if not strikes:
        return df
    atm = min(strikes, key=lambda x: abs(x - spot))
    idx = strikes.index(atm)
    selected = strikes[max(0, idx - n): idx + n + 1]
    return df[df["strikePrice"].isin(selected)].copy()


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYSIS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def _safe_int(val) -> int:
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return 0


def analyze_participant_oi(p_df: pd.DataFrame) -> dict:
    """Analyze participant positioning for index options."""
    if p_df.empty:
        return {"available": False}

    participants = {"client": "Client", "dii": "DII", "fii": "FII", "pro": "Pro"}
    result = {"available": True, "participants": {}}

    for p_key, p_name in participants.items():
        p_row = None
        for _, row in p_df.iterrows():
            if str(row.iloc[0]).strip().lower() == p_key:
                p_row = row
                break
        if p_row is None:
            continue

        ce_long = _safe_int(p_row.get("Option Index Call Long", 0))
        ce_short = _safe_int(p_row.get("Option Index Call Short", 0))
        pe_long = _safe_int(p_row.get("Option Index Put Long", 0))
        pe_short = _safe_int(p_row.get("Option Index Put Short", 0))
        fut_long = _safe_int(p_row.get("Future Index Long", 0))
        fut_short = _safe_int(p_row.get("Future Index Short", 0))

        total_long = ce_long + pe_long
        total_short = ce_short + pe_short
        net_options = total_long - total_short
        net_futures = fut_long - fut_short

        result["participants"][p_name] = {
            "ce_long": ce_long, "ce_short": ce_short,
            "pe_long": pe_long, "pe_short": pe_short,
            "fut_long": fut_long, "fut_short": fut_short,
            "net_options": net_options,
            "net_futures": net_futures,
            "options_bias": "bullish" if net_options > 0 else "bearish",
            "futures_bias": "bullish" if net_futures > 0 else "bearish",
        }

    fii = result["participants"].get("FII", {})
    if fii:
        result["fii_combined_bias"] = "bullish" if (fii.get("net_futures", 0) + fii.get("net_options", 0)) > 0 else "bearish"
        result["fii_long_short_ratio"] = round(fii["fut_long"] / max(fii["fut_short"], 1) * 100, 1)

    return result


def analyze_option_chain(df: pd.DataFrame, spot: float) -> dict:
    """Analyze the option chain: PCR, max pain, support/resistance, IV."""
    strikes = sorted(df["strikePrice"].unique())
    atm = min(strikes, key=lambda x: abs(x - spot))

    total_ce_oi = int(df["CE_openInterest"].sum())
    total_pe_oi = int(df["PE_openInterest"].sum())
    pcr = round(total_pe_oi / max(total_ce_oi, 1), 2)

    total_ce_chg = int(df["CE_changeinOpenInterest"].sum())
    total_pe_chg = int(df["PE_changeinOpenInterest"].sum())

    total_ce_vol = int(df["CE_totalTradedVolume"].sum())
    total_pe_vol = int(df["PE_totalTradedVolume"].sum())

    # Max OI strikes = key support/resistance
    max_ce_oi_row = df.loc[df["CE_openInterest"].idxmax()]
    max_pe_oi_row = df.loc[df["PE_openInterest"].idxmax()]
    resistance = int(max_ce_oi_row["strikePrice"])
    support = int(max_pe_oi_row["strikePrice"])

    # Max change in OI = where fresh buildup happened today
    max_ce_chg_row = df.loc[df["CE_changeinOpenInterest"].idxmax()]
    max_pe_chg_row = df.loc[df["PE_changeinOpenInterest"].idxmax()]

    # IV analysis - ATM IV is the baseline
    atm_row = df[df["strikePrice"] == atm].iloc[0] if not df[df["strikePrice"] == atm].empty else None
    atm_ce_iv = float(atm_row["CE_impliedVolatility"]) if atm_row is not None else 0
    atm_pe_iv = float(atm_row["PE_impliedVolatility"]) if atm_row is not None else 0
    avg_iv = round((atm_ce_iv + atm_pe_iv) / 2, 2) if (atm_ce_iv + atm_pe_iv) > 0 else 0
    iv_skew = round(atm_pe_iv - atm_ce_iv, 2)

    # Max Pain calculation: strike where option writers lose least
    max_pain = _calculate_max_pain(df, strikes)

    # Top 3 CE and PE OI strikes for support/resistance levels
    top_ce = df.nlargest(3, "CE_openInterest")[["strikePrice", "CE_openInterest"]].to_dict("records")
    top_pe = df.nlargest(3, "PE_openInterest")[["strikePrice", "PE_openInterest"]].to_dict("records")

    # PCR interpretation
    if pcr > 1.5:
        pcr_signal = "extremely_bullish"
    elif pcr > 1.2:
        pcr_signal = "bullish"
    elif pcr > 0.8:
        pcr_signal = "neutral"
    elif pcr > 0.5:
        pcr_signal = "bearish"
    else:
        pcr_signal = "extremely_bearish_may_reverse"

    return {
        "spot": spot,
        "atm": int(atm),
        "pcr": pcr,
        "pcr_signal": pcr_signal,
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "total_ce_chg_oi": total_ce_chg,
        "total_pe_chg_oi": total_pe_chg,
        "total_ce_volume": total_ce_vol,
        "total_pe_volume": total_pe_vol,
        "resistance": resistance,
        "support": support,
        "max_pain": max_pain,
        "fresh_ce_buildup": {"strike": int(max_ce_chg_row["strikePrice"]), "chg_oi": int(max_ce_chg_row["CE_changeinOpenInterest"])},
        "fresh_pe_buildup": {"strike": int(max_pe_chg_row["strikePrice"]), "chg_oi": int(max_pe_chg_row["PE_changeinOpenInterest"])},
        "atm_iv": avg_iv,
        "iv_skew": iv_skew,
        "iv_regime": "high" if avg_iv > 18 else ("low" if avg_iv < 12 else "normal"),
        "top_ce_walls": [{"strike": int(r["strikePrice"]), "oi": int(r["CE_openInterest"])} for r in top_ce],
        "top_pe_walls": [{"strike": int(r["strikePrice"]), "oi": int(r["PE_openInterest"])} for r in top_pe],
    }


def _calculate_max_pain(df: pd.DataFrame, strikes: list) -> int:
    """Max pain = strike where total intrinsic value loss for option buyers is maximum."""
    min_pain = float("inf")
    max_pain_strike = strikes[len(strikes) // 2]

    for s in strikes:
        ce_pain = sum(max(0, s2 - s) * int(row.get("CE_openInterest", 0) or 0) for s2, row in
                       [(row["strikePrice"], row) for _, row in df.iterrows()] if s2 < s)
        # CE buyers lose when market is below their strike
        ce_loss = sum(max(0, strike - s) * int(r["CE_openInterest"] or 0)
                      for _, r in df.iterrows() if (strike := r["strikePrice"]) > s)
        # PE buyers lose when market is above their strike
        pe_loss = sum(max(0, s - strike) * int(r["PE_openInterest"] or 0)
                      for _, r in df.iterrows() if (strike := r["strikePrice"]) < s)
        total_loss = ce_loss + pe_loss
        if total_loss < min_pain:
            min_pain = total_loss
            max_pain_strike = s

    return int(max_pain_strike)


def analyze_fii_dii(fii_df: pd.DataFrame) -> dict:
    if fii_df is None or fii_df.empty:
        return {"available": False}

    result = {"available": True}
    for _, row in fii_df.iterrows():
        cat = str(row.get("category", "")).strip()
        net = float(str(row.get("netValue", 0)).replace(",", "") or 0)
        buy = float(str(row.get("buyValue", 0)).replace(",", "") or 0)
        sell = float(str(row.get("sellValue", 0)).replace(",", "") or 0)

        key = "fii" if "FII" in cat.upper() or "FPI" in cat.upper() else "dii"
        result[key] = {
            "buy_value": buy,
            "sell_value": sell,
            "net_value": net,
            "bias": "bullish" if net > 0 else "bearish",
        }

    return result


def determine_overall_bias(oc: dict, part: dict, fii_dii: dict, price_data: dict) -> dict:
    """
    Combine all signals into an overall market bias with confidence score.

    Signals and weights (v2 — rebalanced from backtest analysis):
      - PCR:                   weight 15   (was over-relying on this)
      - FII options net:       weight 10   (more reliable than futures for daily direction)
      - FII futures:           weight 8    (was 25 — too heavy, same value every day)
      - FII cash:              weight 5    (lagging indicator, low weight)
      - Change in OI pattern:  weight 12   (strong same-day signal)
      - Max pain distance:     weight 10   (market gravitates to max pain near expiry)
      - Support/resistance:    weight 12   (mean reversion near key levels)
      - Price trend (today):   weight 8    (momentum)
      - Mean reversion:        weight 10   (contrarian after big moves)
      - IV regime:             weight 5    (high IV = uncertainty = favor neutral)
    """
    signals = []
    score = 0

    # 1. PCR signal (weight: 15)
    pcr = oc.get("pcr", 1.0)
    if pcr > 1.5:
        pcr_s, pcr_i = 15, "extremely_bullish"
    elif pcr > 1.2:
        pcr_s, pcr_i = 10, "bullish"
    elif pcr > 0.8:
        pcr_s, pcr_i = 0, "neutral"
    elif pcr > 0.5:
        pcr_s, pcr_i = -10, "bearish"
    else:
        pcr_s, pcr_i = 6, "extremely_low_contrarian_bullish"
    score += pcr_s
    signals.append({"signal": "pcr", "value": pcr, "interpretation": pcr_i, "score": pcr_s})

    # 2. FII options positioning (weight: 10) — more granular than binary
    if part.get("available"):
        fii = part.get("participants", {}).get("FII", {})
        if fii:
            net_opt = fii.get("net_options", 0)
            if net_opt > 100000:
                opt_s = 10
            elif net_opt > 30000:
                opt_s = 5
            elif net_opt < -100000:
                opt_s = -10
            elif net_opt < -30000:
                opt_s = -5
            else:
                opt_s = 0
            score += opt_s
            signals.append({"signal": "fii_options_net", "value": net_opt,
                            "interpretation": "bullish" if opt_s > 0 else ("bearish" if opt_s < 0 else "neutral"),
                            "score": opt_s})

            # 3. FII futures (weight: 8 — reduced from 25)
            net_fut = fii.get("net_futures", 0)
            lsr = part.get("fii_long_short_ratio", 50)
            if lsr > 65:
                fut_s = 8
            elif lsr > 50:
                fut_s = 4
            elif lsr < 35:
                fut_s = -8
            elif lsr < 50:
                fut_s = -4
            else:
                fut_s = 0
            score += fut_s
            signals.append({"signal": "fii_futures", "value": net_fut, "lsr": lsr,
                            "interpretation": "bullish" if fut_s > 0 else ("bearish" if fut_s < 0 else "neutral"),
                            "score": fut_s})

    # 4. FII/DII cash (weight: 5 — lagging indicator)
    if fii_dii.get("available"):
        fii_cash = fii_dii.get("fii", {})
        if fii_cash:
            net_val = fii_cash.get("net_value", 0)
            cash_s = 5 if net_val > 500 else (-5 if net_val < -500 else 0)
            score += cash_s
            signals.append({"signal": "fii_cash", "value": net_val,
                            "interpretation": fii_cash.get("bias", "neutral"), "score": cash_s})

    # 5. Change in OI pattern (weight: 12)
    ce_chg = oc.get("total_ce_chg_oi", 0)
    pe_chg = oc.get("total_pe_chg_oi", 0)
    total_chg = abs(ce_chg) + abs(pe_chg)
    if total_chg > 0:
        pe_ratio = pe_chg / total_chg  # >0.6 means more PE writing (bullish)
        ce_ratio = ce_chg / total_chg
        if pe_chg > 0 and ce_chg < 0:
            chg_s, chg_i = 12, "pe_writing_ce_unwinding_bullish"
        elif ce_chg > 0 and pe_chg < 0:
            chg_s, chg_i = -12, "ce_writing_pe_unwinding_bearish"
        elif pe_ratio > 0.6:
            chg_s, chg_i = 6, "more_pe_writing_mildly_bullish"
        elif ce_ratio > 0.6:
            chg_s, chg_i = -6, "more_ce_writing_mildly_bearish"
        else:
            chg_s, chg_i = 0, "balanced"
    else:
        chg_s, chg_i = 0, "no_change"
    score += chg_s
    signals.append({"signal": "chg_oi_pattern", "value": {"ce_chg": ce_chg, "pe_chg": pe_chg},
                     "interpretation": chg_i, "score": chg_s})

    # 6. Max pain magnet (weight: 10) — market tends to pull toward max pain
    spot = oc.get("spot", 0)
    max_pain = oc.get("max_pain", spot)
    if spot > 0 and max_pain > 0:
        mp_dist_pct = (max_pain - spot) / spot * 100
        if mp_dist_pct > 0.5:
            mp_s, mp_i = 10, f"max_pain_above_spot_bullish_pull"
        elif mp_dist_pct > 0.2:
            mp_s, mp_i = 5, f"max_pain_slightly_above"
        elif mp_dist_pct < -0.5:
            mp_s, mp_i = -10, f"max_pain_below_spot_bearish_pull"
        elif mp_dist_pct < -0.2:
            mp_s, mp_i = -5, f"max_pain_slightly_below"
        else:
            mp_s, mp_i = 0, "spot_near_max_pain"
        score += mp_s
        signals.append({"signal": "max_pain_distance", "value": round(mp_dist_pct, 2),
                         "max_pain": max_pain, "interpretation": mp_i, "score": mp_s})

    # 7. Support/resistance proximity (weight: 12)
    support = oc.get("support", 0)
    resistance = oc.get("resistance", 0)
    if spot > 0 and support > 0 and resistance > 0:
        dist_to_support = (spot - support) / spot * 100
        dist_to_resistance = (resistance - spot) / spot * 100
        if dist_to_support < 0.3 and dist_to_support >= 0:
            sr_s, sr_i = 8, "near_support_likely_bounce"
        elif dist_to_support < 0:
            sr_s, sr_i = -6, "below_support_breakdown"
        elif dist_to_resistance < 0.3 and dist_to_resistance >= 0:
            sr_s, sr_i = -8, "near_resistance_likely_rejection"
        elif dist_to_resistance < 0:
            sr_s, sr_i = 6, "above_resistance_breakout"
        else:
            sr_s, sr_i = 0, "mid_range"
        score += sr_s
        signals.append({"signal": "support_resistance", "value": {"support": support, "resistance": resistance,
                         "dist_support_pct": round(dist_to_support, 2), "dist_resistance_pct": round(dist_to_resistance, 2)},
                         "interpretation": sr_i, "score": sr_s})

    # 8. Price trend / momentum (weight: 8)
    if price_data:
        change = price_data.get("change_pct", 0)
        if change > 1.5:
            trend_s = 8
        elif change > 0.5:
            trend_s = 4
        elif change < -1.5:
            trend_s = -8
        elif change < -0.5:
            trend_s = -4
        else:
            trend_s = 0
        score += trend_s
        signals.append({"signal": "price_trend", "value": change,
                         "interpretation": "bullish" if trend_s > 0 else ("bearish" if trend_s < 0 else "flat"),
                         "score": trend_s})

        # 9. Mean reversion (weight: 10) — CONTRARIAN to today's move
        # After a big move, next day tends to partially reverse
        if change > 2.0:
            mr_s, mr_i = -8, "overbought_likely_pullback"
        elif change > 1.0:
            mr_s, mr_i = -4, "extended_may_consolidate"
        elif change < -2.0:
            mr_s, mr_i = 8, "oversold_likely_bounce"
        elif change < -1.0:
            mr_s, mr_i = 4, "extended_down_may_recover"
        else:
            mr_s, mr_i = 0, "normal_range"
        score += mr_s
        signals.append({"signal": "mean_reversion", "value": change, "interpretation": mr_i, "score": mr_s})

    # 10. IV regime (weight: 5) — high IV = uncertainty, mild neutral push
    atm_iv = oc.get("atm_iv", 15)
    if atm_iv > 20:
        iv_s, iv_i = 0, "high_iv_favor_selling"
    elif atm_iv > 16:
        iv_s, iv_i = 0, "normal_iv"
    else:
        iv_s, iv_i = 0, "low_iv_favor_buying"
    # IV doesn't push direction but we track it for strategy selection
    signals.append({"signal": "iv_regime", "value": atm_iv, "interpretation": iv_i, "score": iv_s})

    # Final bias determination — wider neutral band (was ±10, now ±15)
    confidence = min(abs(score), 100)
    if score > 15:
        bias = "bullish"
    elif score < -15:
        bias = "bearish"
    else:
        bias = "neutral"

    return {
        "bias": bias,
        "score": score,
        "confidence": confidence,
        "signals": signals,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BLACK-SCHOLES & GREEKS
# ═══════════════════════════════════════════════════════════════════════════════

def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def black_scholes_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "CE") -> float:
    """Black-Scholes option price. T in years, sigma as decimal (0.15 = 15%)."""
    if T <= 0 or sigma <= 0:
        if option_type == "CE":
            return max(0, S - K)
        return max(0, K - S)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    else:
        return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def probability_itm(S: float, K: float, T: float, sigma: float, option_type: str = "CE") -> float:
    """Probability that option expires in-the-money."""
    if T <= 0 or sigma <= 0:
        if option_type == "CE":
            return 1.0 if S > K else 0.0
        return 1.0 if S < K else 0.0

    d2 = (math.log(S / K) + (-0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    if option_type == "CE":
        return round(_norm_cdf(d2) * 100, 1)
    return round(_norm_cdf(-d2) * 100, 1)


def probability_profit(S: float, K: float, premium: float, T: float, sigma: float, option_type: str = "CE", is_sell: bool = False) -> float:
    """Probability that the trade is profitable."""
    if is_sell:
        # Seller profits if option expires OTM
        if option_type == "CE":
            return 100 - probability_itm(S, K + premium, T, sigma, "CE")
        return 100 - probability_itm(S, K - premium, T, sigma, "PE")
    else:
        # Buyer profits if option is ITM beyond premium
        if option_type == "CE":
            return probability_itm(S, K + premium, T, sigma, "CE")
        return probability_itm(S, K - premium, T, sigma, "PE")


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN RECOMMEND FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def _get_actual_premium(chain_df: pd.DataFrame, strike: float, opt_type: str) -> Optional[float]:
    """Look up the actual closing premium from option chain data."""
    col = f"{opt_type}_lastPrice"
    if col not in chain_df.columns:
        return None
    row = chain_df[chain_df["strikePrice"] == strike]
    if row.empty:
        return None
    val = float(row[col].iloc[0])
    return val if val > 0 else None


def generate_strategies_with_market_prices(
    oc: dict, bias: dict, budget: float, symbol: str, chain_df: pd.DataFrame, target_date: date,
    price_data: dict = None,
) -> list[dict]:
    """
    v2: Always generates ALL strategy types, then ranks them using a composite
    score based on bias direction, confidence, IV regime, and risk/reward.

    Key changes from v1:
    - Neutral strategies (straddle, condor) always generated regardless of bias
    - Directional strategies always generated but ranked lower when bias is weak
    - Stop-loss and target levels added to every trade
    - Confidence-based weighting: low confidence = neutral strategies ranked higher
    """
    price_data = price_data or {}
    strategies = []
    spot = oc["spot"]
    atm = oc["atm"]
    iv = oc["atm_iv"] / 100 if oc["atm_iv"] > 0 else 0.15
    support = oc["support"]
    resistance = oc["resistance"]
    lot = LOT_SIZE.get(symbol, 75)
    overall_bias = bias["bias"]
    confidence = bias["confidence"]
    step = 50 if symbol == "NIFTY" else 100

    nearest_exp = oc.get("nearest_expiry", "unknown")
    try:
        exp_dt = datetime.strptime(nearest_exp, "%Y-%m-%d").date()
        T = max((exp_dt - target_date).days, 1) / 365
        dte = max((exp_dt - target_date).days, 1)
    except Exception:
        T = 5 / 365
        dte = 5
    r = 0.07

    atm_iv = oc.get("atm_iv", 15)
    high_iv = atm_iv > 18
    low_iv = atm_iv < 12

    # Expected daily move from IV (annualized IV → daily σ)
    daily_sigma_pct = iv * 100 / (252 ** 0.5)  # e.g. 15% IV → ~0.95% daily move

    # Bias multiplier: directional strategies boosted when confidence is high
    # Backtest showed directional spreads have 5:1 win/loss ratio — bias them up
    dir_boost = max(confidence / 40, 0.5)  # floor of 0.5 so they always appear
    # Neutral boost: heavily penalized — IC only wins 36% of the time
    neut_boost = max(1.0 - dir_boost * 0.5, 0.2)
    # IV boost: selling strategies get bonus in high IV but capped
    iv_sell_boost = 1.3 if high_iv else (1.0 if not low_iv else 0.7)

    def get_prem(strike, opt_type):
        actual = _get_actual_premium(chain_df, strike, opt_type)
        if actual is not None:
            return actual, "market"
        return black_scholes_price(spot, strike, T, r, iv, opt_type), "bs"

    def add_stoploss(strat: dict, is_debit: bool):
        """Add stop-loss and target levels.

        Backtest learnings (3-month data):
        - Debit spreads: avg win ₹5,700 vs avg loss ₹1,050 → wider targets, tight SL works
        - Credit spreads (IC): held-to-close = ₹-79K loss. Must exit early.
          Tighten SL to 1x credit (was 1.5x) to cut losses faster.
        """
        if is_debit:
            cost = strat.get("net_cost", 0)
            profit = strat.get("max_profit", 0)
            if isinstance(profit, (int, float)) and isinstance(cost, (int, float)) and cost > 0:
                strat["stop_loss"] = round(-cost * 0.65, 0)   # Exit at 65% loss (give room to recover)
                strat["target"] = round(profit * 0.55, 0)     # Book at 55% of max profit
        else:
            credit = strat.get("net_credit", 0)
            loss = strat.get("max_loss", 0)
            if isinstance(loss, (int, float)) and isinstance(credit, (int, float)) and credit > 0:
                strat["stop_loss"] = round(-credit * 1.0, 0)  # Exit at 1x credit (was 1.5x — too loose)
                strat["target"] = round(credit * 0.4, 0)      # Book at 40% of credit (quicker exit)

    # ─── BULLISH STRATEGIES ──────────────────────────────────────────────
    # Bull Call Spread
    buy_k, sell_k = atm, atm + step * 4
    buy_p, buy_src = get_prem(buy_k, "CE")
    sell_p, sell_src = get_prem(sell_k, "CE")
    net_cost = (buy_p - sell_p) * lot
    max_profit = (sell_k - buy_k) * lot - net_cost
    if net_cost > 0 and net_cost <= budget * 1.5:
        wp = probability_itm(spot, buy_k, T, iv, "CE")
        rr = max_profit / max(net_cost, 1)
        base_score = wp * rr
        # 9mo backtest: BCS wins 100% when move >+0.5%, but loses -₹94K on flat days.
        # Only rank highly on strong bullish conviction. On neutral, rank below naked buys.
        if overall_bias == "bullish":
            bull_mult = dir_boost * 1.5
            bcs_score = base_score * bull_mult
        elif overall_bias == "bearish":
            bcs_score = rr * 10 * 0.3
        else:
            bcs_score = rr * 8  # neutral: low rank so naked buy / sit-out wins
        s = {
            "strategy": "bull_call_spread", "bias_required": "bullish",
            "legs": [
                {"action": "buy", "type": "CE", "strike": buy_k, "premium": round(buy_p, 2), "source": buy_src},
                {"action": "sell", "type": "CE", "strike": sell_k, "premium": round(sell_p, 2), "source": sell_src},
            ],
            "lot_size": lot,
            "net_cost": round(net_cost, 0), "max_profit": round(max_profit, 0), "max_loss": round(net_cost, 0),
            "breakeven": round(buy_k + (buy_p - sell_p), 0),
            "risk_reward": f"1:{round(rr, 1)}", "win_probability": round(wp, 1),
            "rank_score": bcs_score,
        }
        add_stoploss(s, True)
        strategies.append(s)

    # Bull Put Spread — REMOVED after 9-month backtest analysis.
    # 79 trades, 56% WR but ₹-42,533 total. Credit spreads win small, lose big.
    # Same pattern as the removed Bear Call Spread.

    # ─── BEARISH STRATEGIES ──────────────────────────────────────────────
    # Bear Put Spread
    buy_k3, sell_k3 = atm, atm - step * 4
    buy_p3, buy_src3 = get_prem(buy_k3, "PE")
    sell_p3, sell_src3 = get_prem(sell_k3, "PE")
    net_cost3 = (buy_p3 - sell_p3) * lot
    max_profit3 = (buy_k3 - sell_k3) * lot - net_cost3
    if net_cost3 > 0 and net_cost3 <= budget * 1.5:
        wp3 = probability_itm(spot, buy_k3, T, iv, "PE")
        rr3 = max_profit3 / max(net_cost3, 1)
        # 9mo backtest: BPS wins 100% when move <-0.5%, but loses -₹82K on flat days.
        # Only rank highly on bearish conviction. On neutral, rank below naked buys.
        if overall_bias == "bearish":
            bear_mult = dir_boost * 1.5
            bps_score = wp3 * rr3 * bear_mult
        elif overall_bias == "bullish":
            bps_score = rr3 * 10 * 0.3
        else:
            bps_score = rr3 * 8  # neutral: low rank so naked buy / sit-out wins
        s3 = {
            "strategy": "bear_put_spread", "bias_required": "bearish",
            "legs": [
                {"action": "buy", "type": "PE", "strike": buy_k3, "premium": round(buy_p3, 2), "source": buy_src3},
                {"action": "sell", "type": "PE", "strike": sell_k3, "premium": round(sell_p3, 2), "source": sell_src3},
            ],
            "lot_size": lot,
            "net_cost": round(net_cost3, 0), "max_profit": round(max_profit3, 0), "max_loss": round(net_cost3, 0),
            "breakeven": round(buy_k3 - (buy_p3 - sell_p3), 0),
            "risk_reward": f"1:{round(rr3, 1)}", "win_probability": round(wp3, 1),
            "rank_score": bps_score,
        }
        add_stoploss(s3, True)
        strategies.append(s3)

    # Bear Call Spread — REMOVED after 9-month backtest analysis.

    # ─── NAKED OPTION BUYS (high-conviction directional plays) ──────────
    # Spreads cap profit at ~₹5-6K even on 3%+ moves. Naked buys capture the full move.
    # CE buy: 16 trades in v5 backtest, 62% WR, ₹+114K — the best strategy when it fires.
    # PE buy: barely triggered in v5 because bearish bias is only 1% of the time.
    #
    # Fix: generate PE buy whenever BPS would rank high (bearish-leaning signals)
    # and CE buy on strong bullish days. Both also trigger on mean reversion.

    today_change = price_data.get("change_pct", 0)

    # Naked PE Buy — triggers on bearish bias OR mean reversion after big up day
    pe_prem, pe_src = get_prem(atm, "PE")
    pe_cost = pe_prem * lot
    if pe_cost > 0 and pe_cost <= budget:
        pe_rr = (spot * 0.02 * lot) / max(pe_cost, 1)
        pe_score = 0
        generate_pe = False

        if overall_bias == "bearish":
            pe_score = pe_rr * 25 * dir_boost
            generate_pe = True
        if today_change > 1.5:
            pe_score = max(pe_score, pe_rr * 18)
            generate_pe = True

        if generate_pe:
            s_pe = {
                "strategy": "pe_buy", "bias_required": "bearish",
                "legs": [
                    {"action": "buy", "type": "PE", "strike": atm, "premium": round(pe_prem, 2), "source": pe_src},
                ],
                "lot_size": lot,
                "net_cost": round(pe_cost, 0), "max_profit": "unlimited",
                "max_loss": round(pe_cost, 0),
                "breakeven": round(atm - pe_prem, 0),
                "rank_score": pe_score,
            }
            add_stoploss(s_pe, True)
            strategies.append(s_pe)

    # Naked CE Buy — triggers on strong bullish bias OR mean reversion after big down day
    ce_prem, ce_src = get_prem(atm, "CE")
    ce_cost = ce_prem * lot
    if ce_cost > 0 and ce_cost <= budget:
        ce_rr = (spot * 0.02 * lot) / max(ce_cost, 1)
        ce_score = 0
        generate_ce = False

        if overall_bias == "bullish" and confidence > 20:
            ce_score = ce_rr * 25 * dir_boost
            generate_ce = True
        if today_change < -1.5:
            ce_score = max(ce_score, ce_rr * 18)
            generate_ce = True

        if generate_ce:
            s_ce = {
                "strategy": "ce_buy", "bias_required": "bullish",
                "legs": [
                    {"action": "buy", "type": "CE", "strike": atm, "premium": round(ce_prem, 2), "source": ce_src},
                ],
                "lot_size": lot,
                "net_cost": round(ce_cost, 0), "max_profit": "unlimited",
                "max_loss": round(ce_cost, 0),
                "breakeven": round(atm + ce_prem, 0),
                "rank_score": ce_score,
            }
            add_stoploss(s_ce, True)
            strategies.append(s_ce)

    # ─── NEUTRAL STRATEGIES ─────────────────────────────────────────────
    # Iron Condor — only generate when expected move is within the wing range.
    # Backtest: IC wins only when move <0.5%, loses badly when >1%.
    # Market moves >0.5% on 74% of days — so IC is rarely the right pick.
    wing_mult = 3 if high_iv else 2
    sell_ce_k = atm + step * 2
    buy_ce_k = sell_ce_k + step * wing_mult
    sell_pe_k = atm - step * 2
    buy_pe_k = sell_pe_k - step * wing_mult
    # Wing width as % of spot — if expected daily move exceeds this, skip IC
    wing_width_pct = (sell_ce_k - atm) / spot * 100
    ic_viable = daily_sigma_pct < wing_width_pct * 0.8  # only if exp. move < 80% of wing width

    sc_p, sc_src = get_prem(sell_ce_k, "CE")
    bc_p, bc_src = get_prem(buy_ce_k, "CE")
    sp_p, sp_src = get_prem(sell_pe_k, "PE")
    bp_p, bp_src = get_prem(buy_pe_k, "PE")
    net_credit_ic = ((sc_p - bc_p) + (sp_p - bp_p)) * lot
    max_loss_ic = (buy_ce_k - sell_ce_k) * lot - net_credit_ic
    if net_credit_ic > 0 and max_loss_ic > 0 and ic_viable:
        ic_rr = net_credit_ic / max(max_loss_ic, 1)
        # Heavily reduced base score (was 50) — IC now ranks below spreads unless
        # market conditions are extremely range-bound
        ic_score = 20 * ic_rr * neut_boost * iv_sell_boost
        s_ic = {
            "strategy": "iron_condor", "bias_required": "neutral",
            "legs": [
                {"action": "sell", "type": "CE", "strike": sell_ce_k, "premium": round(sc_p, 2), "source": sc_src},
                {"action": "buy", "type": "CE", "strike": buy_ce_k, "premium": round(bc_p, 2), "source": bc_src},
                {"action": "sell", "type": "PE", "strike": sell_pe_k, "premium": round(sp_p, 2), "source": sp_src},
                {"action": "buy", "type": "PE", "strike": buy_pe_k, "premium": round(bp_p, 2), "source": bp_src},
            ],
            "lot_size": lot,
            "net_credit": round(net_credit_ic, 0), "max_profit": round(net_credit_ic, 0),
            "max_loss": round(max_loss_ic, 0),
            "upper_breakeven": round(sell_ce_k + (net_credit_ic / lot), 0),
            "lower_breakeven": round(sell_pe_k - (net_credit_ic / lot), 0),
            "expected_daily_move_pct": round(daily_sigma_pct, 2),
            "wing_width_pct": round(wing_width_pct, 2),
            "rank_score": ic_score,
        }
        add_stoploss(s_ic, False)
        strategies.append(s_ic)

    # Short Straddle — only when IV is high AND low expected move
    # Unlimited risk makes this dangerous; keep it but rank very low
    atm_ce_p, atm_ce_src = get_prem(atm, "CE")
    atm_pe_p, atm_pe_src = get_prem(atm, "PE")
    total_prem = (atm_ce_p + atm_pe_p) * lot
    if total_prem > 0 and high_iv and daily_sigma_pct < 1.0:
        straddle_boost = neut_boost * iv_sell_boost * 0.6  # reduced from 1.3
        s_st = {
            "strategy": "short_straddle", "bias_required": "neutral",
            "legs": [
                {"action": "sell", "type": "CE", "strike": atm, "premium": round(atm_ce_p, 2), "source": atm_ce_src},
                {"action": "sell", "type": "PE", "strike": atm, "premium": round(atm_pe_p, 2), "source": atm_pe_src},
            ],
            "lot_size": lot,
            "net_credit": round(total_prem, 0), "max_profit": round(total_prem, 0),
            "max_loss": "unlimited",
            "upper_breakeven": round(atm + (atm_ce_p + atm_pe_p), 0),
            "lower_breakeven": round(atm - (atm_ce_p + atm_pe_p), 0),
            "margin_required": round(lot * spot * 0.15, 0),
            "warning": "unlimited_risk_needs_strict_stop_loss",
            "rank_score": 15 * straddle_boost,  # reduced from 40
        }
        s_st["stop_loss"] = round(-total_prem * 0.8, 0)  # tighter SL: 0.8x credit
        s_st["target"] = round(total_prem * 0.3, 0)       # quicker exit: 30% of credit
        strategies.append(s_st)

    # ─── LONG STRADDLE (volatility play) ────────────────────────────────
    # Market moves >0.5% on 74% of days — long straddle profits from big moves
    # Only viable when IV is NOT already elevated (cheap premiums)
    if total_prem > 0 and not high_iv and total_prem <= budget:
        # Expected move needs to exceed premium paid (as % of spot)
        prem_pct = (atm_ce_p + atm_pe_p) / spot * 100
        if daily_sigma_pct > prem_pct * 0.7:  # expected move covers most of premium
            vol_boost = 1.2 if low_iv else 0.8
            straddle_buy_score = 30 * vol_boost * (daily_sigma_pct / max(prem_pct, 0.01))
            s_ls = {
                "strategy": "long_straddle", "bias_required": "volatile",
                "legs": [
                    {"action": "buy", "type": "CE", "strike": atm, "premium": round(atm_ce_p, 2), "source": atm_ce_src},
                    {"action": "buy", "type": "PE", "strike": atm, "premium": round(atm_pe_p, 2), "source": atm_pe_src},
                ],
                "lot_size": lot,
                "net_cost": round(total_prem, 0), "max_profit": "unlimited",
                "max_loss": round(total_prem, 0),
                "upper_breakeven": round(atm + (atm_ce_p + atm_pe_p), 0),
                "lower_breakeven": round(atm - (atm_ce_p + atm_pe_p), 0),
                "expected_daily_move_pct": round(daily_sigma_pct, 2),
                "premium_pct_of_spot": round(prem_pct, 2),
                "rank_score": straddle_buy_score,
            }
            add_stoploss(s_ls, True)
            strategies.append(s_ls)

    # ─── RANK AND RETURN ─────────────────────────────────────────────────
    strategies.sort(key=lambda s: s.get("rank_score", 0), reverse=True)
    for i, s in enumerate(strategies):
        s["rank"] = i + 1
        s.pop("rank_score", None)

    return strategies


def recommend(target_date: date, budget: float, bhavcopy: pd.DataFrame = None) -> dict:
    """
    THE BIG FUNCTION.
    Fetches everything, analyzes, and outputs a complete recommendation JSON.

    If bhavcopy is provided, uses it for historical option chain + price data.
    Otherwise fetches live data from NSE.
    """
    is_historical = bhavcopy is not None and not bhavcopy.empty
    logger.info(f"Generating recommendations for {target_date}, budget=₹{budget:,.0f} [{'historical' if is_historical else 'live'}]")

    result = {
        "date": target_date.isoformat(),
        "recommendations_for": "next_trading_day",
        "budget": budget,
        "data_source": "bhavcopy" if is_historical else "live",
        "generated_at": datetime.now(IST).isoformat(),
        "symbols": {},
    }

    logger.info("Fetching participant OI...")
    p_df = fetch_participant_oi(target_date)
    participant_analysis = analyze_participant_oi(p_df)

    logger.info("Fetching FII/DII activity...")
    fii_df = fetch_fii_dii()
    fii_dii_analysis = analyze_fii_dii(fii_df)

    result["market_wide"] = {
        "participant_oi": participant_analysis,
        "fii_dii_cash": fii_dii_analysis,
    }

    for symbol in SYMBOLS:
        logger.info(f"Analyzing {symbol}...")

        try:
            if is_historical:
                df, expiries, spot = bhavcopy_to_option_chain(bhavcopy, symbol)
                if df.empty:
                    logger.warning(f"  {symbol}: No bhavcopy option data, skipping")
                    result["symbols"][symbol] = {"error": "no_bhavcopy_data"}
                    continue
                price_data = fetch_historical_spot(bhavcopy, symbol)
                chain_df = df
            else:
                df, expiries, spot = fetch_option_chain(symbol)
                price_data = fetch_spot_price(symbol)
                chain_df = df

            df = filter_atm_strikes(df, spot, ATM_RANGE)

            oc_analysis = analyze_option_chain(df, spot)
            oc_analysis["nearest_expiry"] = expiries[0] if expiries else "unknown"

            bias = determine_overall_bias(oc_analysis, participant_analysis, fii_dii_analysis, price_data)

            # Use market prices for strategies when available
            strategies = generate_strategies_with_market_prices(
                oc_analysis, bias, budget, symbol, chain_df, target_date,
                price_data=price_data,
            )

            # If confidence is too low, recommend sitting out
            MIN_CONFIDENCE_TO_TRADE = 5
            should_trade = bias["confidence"] >= MIN_CONFIDENCE_TO_TRADE
            action = "trade" if should_trade and strategies else "sit_out"

            result["symbols"][symbol] = {
                "price": price_data,
                "option_chain_analysis": oc_analysis,
                "bias": bias,
                "trades": strategies if should_trade else [],
                "action": action,
                "action_reason": (
                    f"confidence too low ({bias['confidence']}), signals conflicting — no trade"
                    if not should_trade else
                    ("trade available" if strategies else "no viable strategies")
                ),
                "summary": {
                    "direction": bias["bias"],
                    "confidence": bias["confidence"],
                    "support": oc_analysis["support"],
                    "resistance": oc_analysis["resistance"],
                    "max_pain": oc_analysis["max_pain"],
                    "pcr": oc_analysis["pcr"],
                    "iv_regime": oc_analysis["iv_regime"],
                    "num_strategies": len(strategies) if should_trade else 0,
                    "top_strategy": strategies[0]["strategy"] if (should_trade and strategies) else "sit_out",
                },
            }

            logger.info(f"  {symbol}: bias={bias['bias']} confidence={bias['confidence']} action={action} strategies={len(strategies)}")

        except Exception as e:
            logger.error(f"  {symbol} failed: {e}")
            result["symbols"][symbol] = {"error": str(e)}

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE OUTCOME EVALUATOR
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_trade(trade: dict, spot_at_entry: float, next_day: dict, lot: int) -> dict:
    """Evaluate a single trade against next day's actual price movement."""
    next_close = next_day["close"]
    next_high = next_day["high"]
    next_low = next_day["low"]
    strategy = trade["strategy"]
    legs = trade.get("legs", [])

    pnl = 0.0
    outcome = "unknown"
    explanation = ""

    if strategy == "bull_call_spread":
        buy_leg = next(l for l in legs if l["action"] == "buy")
        sell_leg = next(l for l in legs if l["action"] == "sell")
        buy_k, sell_k = buy_leg["strike"], sell_leg["strike"]
        net_debit = (buy_leg["premium"] - sell_leg["premium"])
        # At expiry approximation using next-day close
        ce_buy_val = max(0, next_close - buy_k)
        ce_sell_val = max(0, next_close - sell_k)
        spread_val = ce_buy_val - ce_sell_val
        pnl = (spread_val - net_debit) * lot

    elif strategy == "bear_put_spread":
        buy_leg = next(l for l in legs if l["action"] == "buy")
        sell_leg = next(l for l in legs if l["action"] == "sell")
        buy_k, sell_k = buy_leg["strike"], sell_leg["strike"]
        net_debit = (buy_leg["premium"] - sell_leg["premium"])
        pe_buy_val = max(0, buy_k - next_close)
        pe_sell_val = max(0, sell_k - next_close)
        spread_val = pe_buy_val - pe_sell_val
        pnl = (spread_val - net_debit) * lot

    elif strategy == "bull_put_spread":
        sell_leg = next(l for l in legs if l["action"] == "sell")
        buy_leg = next(l for l in legs if l["action"] == "buy")
        net_credit = sell_leg["premium"] - buy_leg["premium"]
        pe_sell_val = max(0, sell_leg["strike"] - next_close)
        pe_buy_val = max(0, buy_leg["strike"] - next_close)
        pnl = (net_credit - (pe_sell_val - pe_buy_val)) * lot

    elif strategy == "bear_call_spread":
        sell_leg = next(l for l in legs if l["action"] == "sell")
        buy_leg = next(l for l in legs if l["action"] == "buy")
        net_credit = sell_leg["premium"] - buy_leg["premium"]
        ce_sell_val = max(0, next_close - sell_leg["strike"])
        ce_buy_val = max(0, next_close - buy_leg["strike"])
        pnl = (net_credit - (ce_sell_val - ce_buy_val)) * lot

    elif strategy == "ce_buy":
        leg = legs[0]
        # Use intraday high to capture the best possible exit for CE buyer
        intrinsic_close = max(0, next_close - leg["strike"])
        intrinsic_high = max(0, next_high - leg["strike"])
        best_intrinsic = max(intrinsic_close, intrinsic_high)
        pnl = (best_intrinsic - leg["premium"]) * lot

    elif strategy == "pe_buy":
        leg = legs[0]
        # Use intraday low to capture the best possible exit for PE buyer
        intrinsic_close = max(0, leg["strike"] - next_close)
        intrinsic_low = max(0, leg["strike"] - next_low)
        best_intrinsic = max(intrinsic_close, intrinsic_low)
        pnl = (best_intrinsic - leg["premium"]) * lot

    elif strategy == "iron_condor":
        sell_ce = next(l for l in legs if l["action"] == "sell" and l["type"] == "CE")
        buy_ce = next(l for l in legs if l["action"] == "buy" and l["type"] == "CE")
        sell_pe = next(l for l in legs if l["action"] == "sell" and l["type"] == "PE")
        buy_pe = next(l for l in legs if l["action"] == "buy" and l["type"] == "PE")
        net_credit = (sell_ce["premium"] - buy_ce["premium"]) + (sell_pe["premium"] - buy_pe["premium"])
        ce_loss = max(0, next_close - sell_ce["strike"]) - max(0, next_close - buy_ce["strike"])
        pe_loss = max(0, sell_pe["strike"] - next_close) - max(0, buy_pe["strike"] - next_close)
        pnl = (net_credit - ce_loss - pe_loss) * lot

    elif strategy == "short_straddle":
        ce_leg = next(l for l in legs if l["type"] == "CE")
        pe_leg = next(l for l in legs if l["type"] == "PE")
        total_prem = ce_leg["premium"] + pe_leg["premium"]
        ce_val = max(0, next_close - ce_leg["strike"])
        pe_val = max(0, pe_leg["strike"] - next_close)
        pnl = (total_prem - ce_val - pe_val) * lot

    elif strategy == "long_straddle":
        ce_leg = next(l for l in legs if l["type"] == "CE")
        pe_leg = next(l for l in legs if l["type"] == "PE")
        total_prem = ce_leg["premium"] + pe_leg["premium"]
        # Use intraday extremes to get best exit (straddle holder would exit at max move)
        move_up = next_high - ce_leg["strike"]
        move_down = pe_leg["strike"] - next_low
        best_intrinsic = max(max(0, move_up), max(0, move_down))
        pnl = (best_intrinsic - total_prem) * lot

    pnl = round(pnl, 0)

    sl = trade.get("stop_loss")
    target = trade.get("target")
    exit_reason = "held_to_close"

    # For credit spreads (IC, short straddle), use intraday P&L at high/low to
    # check SL since the position bleeds quickly on big moves.
    # For debit spreads, use close-based P&L — options retain time value intraday
    # so the actual premium loss is smaller than intrinsic-value calculation suggests.
    if strategy in ("iron_condor", "short_straddle", "bear_call_spread", "bull_put_spread"):
        def _pnl_at_price(price):
            if strategy == "iron_condor":
                sc = next(l for l in legs if l["action"] == "sell" and l["type"] == "CE")
                bc = next(l for l in legs if l["action"] == "buy" and l["type"] == "CE")
                sp = next(l for l in legs if l["action"] == "sell" and l["type"] == "PE")
                bp = next(l for l in legs if l["action"] == "buy" and l["type"] == "PE")
                nc = (sc["premium"] - bc["premium"]) + (sp["premium"] - bp["premium"])
                cl = max(0, price - sc["strike"]) - max(0, price - bc["strike"])
                pl = max(0, sp["strike"] - price) - max(0, bp["strike"] - price)
                return (nc - cl - pl) * lot
            return pnl
        worst_pnl = min(pnl, _pnl_at_price(next_high), _pnl_at_price(next_low))
        best_pnl = max(pnl, _pnl_at_price(next_high), _pnl_at_price(next_low))
        if sl is not None and worst_pnl <= sl:
            pnl = round(sl, 0)
            exit_reason = "stop_loss_hit"
        elif target is not None and best_pnl >= target:
            pnl = round(target, 0)
            exit_reason = "target_hit"
    else:
        # Debit spreads: check SL/target against close P&L only
        if sl is not None and pnl <= sl:
            pnl = round(sl, 0)
            exit_reason = "stop_loss_hit"
        elif target is not None and pnl >= target:
            pnl = round(target, 0)
            exit_reason = "target_hit"

    outcome = "profit" if pnl > 0 else ("loss" if pnl < 0 else "breakeven")

    market_moved = next_close - spot_at_entry
    market_direction = "up" if market_moved > 0 else ("down" if market_moved < 0 else "flat")
    move_pct = round((market_moved / spot_at_entry) * 100, 2)

    return {
        "strategy": strategy,
        "pnl": pnl,
        "outcome": outcome,
        "exit_reason": exit_reason,
        "next_day_close": next_close,
        "market_move": round(market_moved, 2),
        "market_move_pct": move_pct,
        "market_direction": market_direction,
    }


def evaluate_bias(bias: str, next_day: dict, spot: float) -> dict:
    """Check if the predicted bias matched actual market movement."""
    next_close = next_day["close"]
    actual_move = next_close - spot
    actual_pct = round((actual_move / spot) * 100, 2)
    actual_direction = "up" if actual_move > 50 else ("down" if actual_move < -50 else "flat")

    correct = False
    if bias == "bullish" and actual_direction == "up":
        correct = True
    elif bias == "bearish" and actual_direction == "down":
        correct = True
    elif bias == "neutral" and actual_direction == "flat":
        correct = True

    return {
        "predicted_bias": bias,
        "actual_direction": actual_direction,
        "actual_move": round(actual_move, 2),
        "actual_move_pct": actual_pct,
        "bias_correct": correct,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTESTER
# ═══════════════════════════════════════════════════════════════════════════════

def _trade_entry_cost(trade: dict) -> float:
    """Calculate the actual capital needed to enter a trade."""
    # Debit spreads: you pay net_cost upfront
    if "net_cost" in trade and isinstance(trade["net_cost"], (int, float)):
        return abs(trade["net_cost"])
    # Credit spreads: you need margin = max_loss (since you receive credit)
    if "net_credit" in trade:
        ml = trade.get("max_loss", 0)
        if isinstance(ml, (int, float)):
            return abs(ml)
        # Unlimited risk (straddle) — need margin
        mr = trade.get("margin_required", 0)
        if isinstance(mr, (int, float)):
            return abs(mr)
    return float("inf")


def backtest(from_date: date, to_date: date, budget: float) -> dict:
    """
    Realistic backtest: picks only the TOP-RANKED trade that fits within
    the budget for each symbol each day. One trade per symbol per day max.
    """
    logger.info(f"Backtesting from {from_date} to {to_date}, budget=₹{budget:,.0f} [realistic mode]")

    history = {}
    for symbol in SYMBOLS:
        logger.info(f"Fetching {symbol} price history...")
        h = fetch_index_history(symbol, from_date - timedelta(days=5), to_date + timedelta(days=10))
        history[symbol] = h
        if not h.empty:
            logger.info(f"  Got {len(h)} days of {symbol} data")
        else:
            logger.warning(f"  No history for {symbol} — will skip outcome evaluation")

    daily_results = []
    current = from_date
    running_capital = budget
    capital_curve = []

    while current <= to_date:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue

        bhav = fetch_bhavcopy(current)
        if bhav.empty:
            logger.info(f"  {current}: No bhavcopy (holiday?), skipping")
            current += timedelta(days=1)
            continue

        try:
            rec = recommend(current, budget, bhavcopy=bhav)
            day_pnl = 0.0

            for symbol in SYMBOLS:
                sym_data = rec.get("symbols", {}).get(symbol, {})
                if "error" in sym_data or not sym_data.get("trades"):
                    continue

                spot = sym_data.get("option_chain_analysis", {}).get("spot", 0)
                bias_info = sym_data.get("bias", {})
                bias_dir = bias_info.get("bias", "neutral")
                confidence = bias_info.get("confidence", 0)
                lot = LOT_SIZE.get(symbol, 75)
                next_day = get_next_trading_day_price(symbol, current, history.get(symbol, pd.DataFrame()))

                # Skip uncertain days: if confidence < 5, signals are too conflicting
                # to risk capital. Backtest showed conf 0-4 trades are basically coin flips.
                MIN_CONFIDENCE_TO_TRADE = 5
                if confidence < MIN_CONFIDENCE_TO_TRADE:
                    sym_data["picked_trade"] = None
                    sym_data["skipped_reason"] = f"low_confidence ({confidence})"
                    if next_day:
                        sym_data["outcome"] = {
                            "next_trading_day": next_day,
                            "bias_evaluation": evaluate_bias(bias_dir, next_day, spot),
                            "trade_result": None,
                        }
                    continue

                # Pick the best affordable trade (already ranked by score)
                picked_trade = None
                for trade in sym_data["trades"]:
                    cost = _trade_entry_cost(trade)
                    if cost <= budget:
                        picked_trade = trade
                        break

                sym_data["picked_trade"] = picked_trade
                sym_data["skipped_reason"] = None if picked_trade else "no_trade_within_budget"

                if next_day:
                    sym_data["outcome"] = {
                        "next_trading_day": next_day,
                        "bias_evaluation": evaluate_bias(bias_dir, next_day, spot),
                    }

                    if picked_trade:
                        result = evaluate_trade(picked_trade, spot, next_day, lot)
                        sym_data["outcome"]["trade_result"] = result
                        sym_data["outcome"]["entry_cost"] = _trade_entry_cost(picked_trade)
                        day_pnl += result["pnl"]
                    else:
                        sym_data["outcome"]["trade_result"] = None
                else:
                    sym_data["outcome"] = {"error": "next_day_price_not_available"}

            running_capital += day_pnl
            capital_curve.append({
                "date": current.isoformat(),
                "day_pnl": round(day_pnl, 0),
                "running_capital": round(running_capital, 0),
            })
            rec["day_pnl"] = round(day_pnl, 0)
            rec["running_capital"] = round(running_capital, 0)

            daily_results.append(rec)
            logger.info(f"  {current}: P&L=₹{day_pnl:+,.0f}  Capital=₹{running_capital:,.0f}")

        except Exception as e:
            logger.error(f"  {current}: Failed - {e}")

        current += timedelta(days=1)

    stats = _compute_backtest_stats(daily_results, budget)

    return {
        "backtest_period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
        "budget": budget,
        "mode": "realistic_single_trade",
        "statistics": stats,
        "capital_curve": capital_curve,
        "daily_recommendations": daily_results,
    }


def _compute_backtest_stats(results: list[dict], budget: float) -> dict:
    """Compute aggregate stats from realistic single-trade-per-symbol backtest."""
    total_trades = 0
    winning_trades = 0
    losing_trades = 0
    total_pnl = 0.0
    bias_correct = 0
    bias_total = 0
    pnls = []
    costs = []
    by_strategy = {}
    skipped_budget = 0
    skipped_low_conf = 0
    target_exits = 0
    sl_exits = 0
    held_exits = 0

    for rec in results:
        for symbol in SYMBOLS:
            sym_data = rec.get("symbols", {}).get(symbol, {})
            outcome = sym_data.get("outcome", {})
            if "error" in outcome or not outcome:
                continue

            be = outcome.get("bias_evaluation", {})
            if be:
                bias_total += 1
                if be.get("bias_correct"):
                    bias_correct += 1

            tr = outcome.get("trade_result")
            if tr is None:
                skip_reason = sym_data.get("skipped_reason", "")
                if "low_confidence" in str(skip_reason):
                    skipped_low_conf += 1
                else:
                    skipped_budget += 1
                continue

            total_trades += 1
            pnl = tr.get("pnl", 0)
            total_pnl += pnl
            pnls.append(pnl)
            costs.append(outcome.get("entry_cost", 0))

            exit_r = tr.get("exit_reason", "held_to_close")
            if exit_r == "target_hit":
                target_exits += 1
            elif exit_r == "stop_loss_hit":
                sl_exits += 1
            else:
                held_exits += 1

            if pnl > 0:
                winning_trades += 1
            elif pnl < 0:
                losing_trades += 1

            strat = tr["strategy"]
            if strat not in by_strategy:
                by_strategy[strat] = {"wins": 0, "losses": 0, "total_pnl": 0, "count": 0, "costs": []}
            by_strategy[strat]["count"] += 1
            by_strategy[strat]["total_pnl"] += pnl
            by_strategy[strat]["costs"].append(outcome.get("entry_cost", 0))
            if pnl > 0:
                by_strategy[strat]["wins"] += 1
            elif pnl < 0:
                by_strategy[strat]["losses"] += 1

    win_rate = round(winning_trades / max(total_trades, 1) * 100, 1)
    bias_accuracy = round(bias_correct / max(bias_total, 1) * 100, 1)
    avg_pnl = round(total_pnl / max(total_trades, 1), 0)
    avg_win = round(sum(p for p in pnls if p > 0) / max(winning_trades, 1), 0) if winning_trades else 0
    avg_loss = round(sum(p for p in pnls if p < 0) / max(losing_trades, 1), 0) if losing_trades else 0
    avg_cost = round(sum(costs) / max(len(costs), 1), 0)
    roi = round(total_pnl / max(budget, 1) * 100, 1)

    strategy_stats = {}
    for strat, s in by_strategy.items():
        avg_c = round(sum(s["costs"]) / max(s["count"], 1), 0)
        strategy_stats[strat] = {
            "total_trades": s["count"],
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": round(s["wins"] / max(s["count"], 1) * 100, 1),
            "total_pnl": round(s["total_pnl"], 0),
            "avg_pnl": round(s["total_pnl"] / max(s["count"], 1), 0),
            "avg_entry_cost": avg_c,
        }

    # Running P&L for drawdown calculation
    running = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        running += p
        peak = max(peak, running)
        dd = peak - running
        max_dd = max(max_dd, dd)

    return {
        "total_trading_days": len(results),
        "total_trades": total_trades,
        "trades_skipped_low_confidence": skipped_low_conf,
        "trades_skipped_over_budget": skipped_budget,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "breakeven_trades": total_trades - winning_trades - losing_trades,
        "win_rate": win_rate,
        "bias_accuracy": bias_accuracy,
        "bias_correct": bias_correct,
        "bias_total": bias_total,
        "total_pnl": round(total_pnl, 0),
        "roi_on_budget": roi,
        "avg_pnl_per_trade": avg_pnl,
        "avg_entry_cost": avg_cost,
        "avg_winning_trade": avg_win,
        "avg_losing_trade": avg_loss,
        "best_trade": round(max(pnls), 0) if pnls else 0,
        "worst_trade": round(min(pnls), 0) if pnls else 0,
        "max_drawdown": round(max_dd, 0),
        "exit_breakdown": {
            "target_hit": target_exits,
            "stop_loss_hit": sl_exits,
            "held_to_close": held_exits,
        },
        "strategy_breakdown": strategy_stats,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(description="NIFTY/BANKNIFTY Trade Recommender")
    parser.add_argument("--date", type=str, default=None, help="Date to analyze (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--budget", type=float, required=True, help="Budget in INR for trade suggestions.")
    parser.add_argument("--backtest", action="store_true", help="Run backtest mode.")
    parser.add_argument("--from", dest="from_date", type=str, help="Backtest start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", type=str, help="Backtest end date (YYYY-MM-DD)")
    parser.add_argument("--symbol", type=str, default=None, help="Single symbol (NIFTY or BANKNIFTY). Default: both.")
    parser.add_argument("--output", type=str, default=None, help="Output file path. Default: stdout.")

    args = parser.parse_args()

    if args.symbol:
        global SYMBOLS
        SYMBOLS = [args.symbol.upper()]

    if args.backtest:
        if not args.from_date or not args.to_date:
            parser.error("--backtest requires --from and --to dates")
        from_d = date.fromisoformat(args.from_date)
        to_d = date.fromisoformat(args.to_date)
        result = backtest(from_d, to_d, args.budget)
    else:
        target = date.fromisoformat(args.date) if args.date else date.today()
        result = recommend(target, args.budget)

    output = json.dumps(result, indent=2, default=str)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        logger.info(f"Output written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
