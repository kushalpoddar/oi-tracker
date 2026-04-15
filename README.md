# OI Tracker – NSE F&O Dashboard

A Streamlit web app for tracking **Open Interest**, **FII/DII/Pro/Retail participant positions**, and **live 5-minute option chain data** for NIFTY, BANKNIFTY, and SENSEX.

## Features

| Tab | What it shows |
|-----|--------------|
| **Option Chain** | CE/PE OI butterfly chart, PCR gauge, Max Pain, IV, Volume per strike (±8 strikes from ATM) |
| **Day End OI** | FII, DII, Pro, Retail (Client) Long/Short positions for Index Futures, Index CE, Index PE |
| **Live 5-Min** | Intraday OI chart per strike refreshed every 5 min during market hours |
| **FII/DII Flow** | Daily net buy/sell cash + F&O flows over last 30 days |
| **Scheduler** | Status of background data collection + manual refresh button |

## Setup

```bash
cd oi-tracker
pip install -r requirements.txt
streamlit run app.py
```

Open http://localhost:8501

## Data Sources

- **Option Chain**: `https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY`
- **Participant OI**: NSE Reports → F&O Participant wise Open Interest CSV (published ~5–6 PM IST)
- **FII/DII Activity**: `https://www.nseindia.com/api/fiidiiTradeReact`
- **Sensex**: BSE India API

All data is stored locally in `data/oi_tracker.db` (SQLite).

## How Data Collection Works

1. **During market hours (9:15 AM – 3:30 PM IST, Mon–Fri)**: APScheduler runs every 5 minutes to capture option chain OI snapshots for NIFTY and BANKNIFTY.
2. **After market (5:30 PM & 6:30 PM IST)**: Fetches NSE's day-end participant-wise OI report + FII/DII activity.

## Note on NSE Scraping

NSE's public APIs require browser-like headers and a valid cookie session. The app:
- Hits the NSE homepage first to get a valid session cookie
- Sets browser-like User-Agent headers

If you get rate-limited, wait a few minutes and refresh.

## Understanding the Data

- **FII** = Foreign Institutional Investors (hedge funds, pension funds)
- **DII** = Domestic Institutional Investors (MFs, insurance, banks)
- **Pro** = Proprietary traders (broker HFT desks)
- **Client** = Retail investors + HNIs

A high **Put OI** at a strike = strong support level  
A high **Call OI** at a strike = strong resistance level  
**PCR > 1.2** = Bullish sentiment | **PCR < 0.8** = Bearish sentiment
# oi-tracker
