# ha-ndlgo-water

Imports water usage and cost from the Nicosia water board portal
(ΣΑΛΑ/NDLGO, https://online.ndlgo.org.cy/portal/) into Home Assistant, and builds a
separate **Νερό** dashboard (`/water-ndlgo`). It does not touch the Energy dashboard.

## What it does
- Logs into the portal API (`POST /api/oraclelogin`; the JWT goes in a `jwt` cookie).
- Reads installations (`/api/wbninst`) and billed periods (`/api/wbnperiods/<inst>`).
- Meters without AMR only have bi-monthly bills, so each period's m³ and € are spread
  evenly over its hours and imported as external statistics:
  - `ndlgo:water_consumption` (m³)
  - `ndlgo:water_cost` (EUR)
- The whole series is rewritten on every run, so re-running is safe.
- Creates or updates the dashboard: a bills table (m³, litres/day, €) plus monthly m³ and € bar graphs.

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in the values
set -a; . ./.env; set +a; .venv/bin/python ndlgo_import.py   # add --dry to only print the bills
```
Cron, daily:
```
40 7 * * * cd /path/ha-ndlgo-water && set -a && . ./.env && set +a && .venv/bin/python ndlgo_import.py >> ndlgo.log 2>&1
```
