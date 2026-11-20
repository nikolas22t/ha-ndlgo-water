"""Constants for the NDLGO Water integration."""
from datetime import timedelta

DOMAIN = "ndlgo"
API = "https://online.ndlgo.org.cy/api/"
TZ_NAME = "Europe/Nicosia"
UPDATE_INTERVAL = timedelta(hours=12)
STAT_CONSUMPTION = f"{DOMAIN}:water_consumption"
STAT_COST = f"{DOMAIN}:water_cost"
