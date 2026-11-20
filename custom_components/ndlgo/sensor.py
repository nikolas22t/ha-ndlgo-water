"""Sensors for the latest NDLGO water bill."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfVolume
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([
        NdlgoSensor(c, entry, "last_bill_volume", "m3", UnitOfVolume.CUBIC_METERS, SensorDeviceClass.WATER),
        NdlgoSensor(c, entry, "last_bill_cost", "eur", "EUR", SensorDeviceClass.MONETARY),
        NdlgoDailySensor(c, entry),
        NdlgoAmrSensor(c, entry),
    ])


class _Base(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="NDLGO Water",
            manufacturer="Nicosia District Local Government Organisation", entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _last(self):
        p = self.coordinator.data.periods if self.coordinator.data else None
        return p[-1] if p else None

    @property
    def extra_state_attributes(self):
        p = self._last
        return p and {"period_start": p.start.date().isoformat(), "period_end": p.end.date().isoformat(),
                      "installation": p.installation}


class NdlgoSensor(_Base):
    def __init__(self, coordinator, entry, key, attr, unit, device_class):
        super().__init__(coordinator, entry, key)
        self._attrv = attr
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class

    @property
    def native_value(self):
        return getattr(self._last, self._attrv) if self._last else None


class NdlgoDailySensor(_Base):
    _attr_native_unit_of_measurement = "L/d"
    _attr_icon = "mdi:water"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "last_bill_daily")

    @property
    def native_value(self):
        p = self._last
        days = p and (p.end - p.start).days
        return round(p.m3 / days * 1000) if days else None


class NdlgoAmrSensor(_Base):
    """Latest smart-meter (AMR) value; unavailable until the meter has AMR data."""
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "smart_meter_reading")

    @property
    def available(self):
        return super().available and bool(self.coordinator.data and self.coordinator.data.amr)

    @property
    def _amr(self):
        return self.coordinator.data.amr if self.coordinator.data else []

    @property
    def native_value(self):
        a = self._amr
        if not a:
            return None
        if a[-1].cumulative:
            return a[-1].value
        return round(sum(r.value for r in a), 3)

    @property
    def extra_state_attributes(self):
        a = self._amr
        return a and {"last_reading_time": a[-1].time.isoformat(), "readings": len(a),
                      "kind": "meter_index" if a[-1].cumulative else "summed_interval_usage"}
