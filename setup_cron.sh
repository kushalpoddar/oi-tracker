#!/bin/bash
# Setup cron jobs for OI Tracker data collection
# Run this once: bash setup_cron.sh

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"

echo "Setting up cron for OI Tracker"
echo "  Directory: $DIR"
echo "  Python: $PYTHON"
echo ""

# Build cron entries
CRON_LIVE="*/5 9-15 * * 1-5 cd $DIR && $PYTHON collector.py --live >> $DIR/data/cron.log 2>&1"
CRON_CLOSE="35 15 * * 1-5 cd $DIR && $PYTHON collector.py --close >> $DIR/data/cron.log 2>&1"
CRON_DAYEND="30 17,18 * * 1-5 cd $DIR && $PYTHON collector.py --dayend >> $DIR/data/cron.log 2>&1"

# Remove old OI tracker entries, add new ones
(crontab -l 2>/dev/null | grep -v "collector.py"; echo "$CRON_LIVE"; echo "$CRON_CLOSE"; echo "$CRON_DAYEND") | crontab -

echo "Cron jobs installed:"
echo ""
crontab -l | grep "collector.py"
echo ""
echo "Schedule:"
echo "  LIVE:    Every 5 min, Mon-Fri, 9:00-15:59 IST"
echo "  CLOSE:   3:35 PM Mon-Fri (day-end closing snapshot)"
echo "  DAYEND:  5:30 PM & 6:30 PM Mon-Fri (FII/DII + participant OI)"
echo ""
echo "Logs: $DIR/data/cron.log"
echo "Done!"
