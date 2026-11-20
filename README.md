# ha-ndlgo-water

[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

Home Assistant integration for the Nicosia water board portal
(ΣΑΛΑ/NDLGO, https://online.ndlgo.org.cy/portal/). Imports your billed water usage and cost
as long-term statistics, usable in the Energy dashboard (Water) and statistics graphs.

## Install (HACS)
1. HACS → ⋮ → **Custom repositories** → add `https://github.com/nikolas22t/ha-ndlgo-water`, type **Integration**.
2. Search **NDLGO Water**, download, restart Home Assistant.
3. Settings → Devices & services → **Add integration** → *NDLGO Water* → enter your portal username/password.

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nikolas22t&repository=ha-ndlgo-water&category=integration)

Manual: copy `custom_components/ndlgo` into your `config/custom_components/`.

## What you get
- Statistics `ndlgo:water_consumption` (m³) and `ndlgo:water_cost` (EUR), refreshed every 12 h.
  Meters without AMR only have bi-monthly bills, so each bill is spread evenly over its hours.
  Add `ndlgo:water_consumption` under Energy → Water consumption.
- Sensors: last bill volume, last bill cost, last bill daily average (L/day), with period attributes.

## Standalone script (optional)
`ndlgo_import.py` does the same import from outside HA over the websocket API and also builds a
**Νερό** dashboard (`/water-ndlgo`). Don't run it alongside the integration.

### What the script does
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
