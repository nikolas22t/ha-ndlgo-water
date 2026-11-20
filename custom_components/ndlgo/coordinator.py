"""Fetches bills and imports them as external long-term statistics."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta, timezone

from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AmrReading, NdlgoAuthError, NdlgoClient, NdlgoError, Period
from .const import DOMAIN, STAT_AMR, STAT_CONSUMPTION, STAT_COST, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class NdlgoData:
    periods: list[Period]
    amr: list[AmrReading]


class NdlgoCoordinator(DataUpdateCoordinator[NdlgoData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=UPDATE_INTERVAL, config_entry=entry)
        self.client = NdlgoClient(
            async_get_clientsession(hass), entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )

    async def _async_update_data(self) -> NdlgoData:
        try:
            periods, amr = await self.client.fetch()
        except NdlgoAuthError as err:
            raise ConfigEntryAuthFailed("Invalid NDLGO credentials") from err
        except NdlgoError as err:
            raise UpdateFailed(f"NDLGO request failed: {err}") from err
        if periods:
            self._import(periods, "m3", STAT_CONSUMPTION, "Water Consumption (NDLGO)",
                         UnitOfVolume.CUBIC_METERS, "volume")
            self._import(periods, "eur", STAT_COST, "Water Cost (NDLGO)", "EUR", None)
        if amr:
            self._import_amr(amr)
        return NdlgoData(periods, amr)

    def _import_amr(self, readings: list[AmrReading]) -> None:
        """Smart-meter readings -> hourly statistic (index readings are differenced)."""
        hours: dict = {}
        prev = None
        for r in readings:
            if r.cumulative:
                if prev is not None and r.value >= prev:
                    hour = r.time.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
                    hours[hour] = hours.get(hour, 0.0) + (r.value - prev)
                prev = r.value
            else:
                hour = r.time.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
                hours[hour] = hours.get(hour, 0.0) + r.value
        self._push(hours, STAT_AMR, "Water Consumption (NDLGO smart meter)", UnitOfVolume.CUBIC_METERS, "volume")

    def _import(self, periods, attr, sid, name, unit, unit_class) -> None:
        """Spread each bill evenly over its hours; whole series rewritten each run."""
        hours = {}
        for p in periods:
            s, e = p.start.astimezone(timezone.utc), p.end.astimezone(timezone.utc)
            n = int((e - s).total_seconds() // 3600)
            if n <= 0:
                continue
            v = getattr(p, attr) / n
            for i in range(n):
                hours[s + timedelta(hours=i)] = v
        self._push(hours, sid, name, unit, unit_class)

    def _push(self, hours, sid, name, unit, unit_class) -> None:
        if not hours:
            return
        total, stats = 0.0, []
        for h in sorted(hours):
            total += hours[h]
            stats.append(StatisticData(start=h, state=round(hours[h], 5), sum=round(total, 4)))
        meta = StatisticMetaData(
            source=DOMAIN, statistic_id=sid, name=name, unit_of_measurement=unit,
            unit_class=unit_class, has_sum=True, mean_type=StatisticMeanType.NONE,
        )
        async_add_external_statistics(self.hass, meta, stats)
