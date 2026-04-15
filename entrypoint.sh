#!/bin/bash
set -e

APP_DIR="/app"
LOG_FILE="$APP_DIR/data/cron.log"

mkdir -p "$APP_DIR/data"

# Write cron jobs (IST times: market 9:15–15:30 Mon–Fri)
cat > /etc/cron.d/oi-collector <<CRON
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
TZ=Asia/Kolkata

# Live OI every 5 min during market hours
*/5 9-15 * * 1-5 cd $APP_DIR && python collector.py --live >> $LOG_FILE 2>&1

# Closing OI at 3:35 PM
35 15 * * 1-5 cd $APP_DIR && python collector.py --close >> $LOG_FILE 2>&1

# Day-end participant OI at 5:30 PM and 6:30 PM (retry)
30 17,18 * * 1-5 cd $APP_DIR && python collector.py --dayend >> $LOG_FILE 2>&1

CRON

chmod 0644 /etc/cron.d/oi-collector
crontab /etc/cron.d/oi-collector

# Start cron daemon in background
cron

echo "$(date) — Cron started, launching Streamlit..."

# Run Streamlit in foreground
exec streamlit run app.py \
    --server.port=8501 \
    --server.address=0.0.0.0 \
    --server.headless=true
