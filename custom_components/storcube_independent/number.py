"""Writable StorCube settings exposed as Home Assistant numbers."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .hub import StorCubeHub


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: StorCubeHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        StorCubeSettingNumber(hub, device_id, "power")
        for device_id in hub.device_ids
        for _ in (0,)
    )
    async_add_entities(
        StorCubeSettingNumber(hub, device_id, "threshold")
        for device_id in hub.device_ids
        for _ in (0,)
    )


class StorCubeSettingNumber(CoordinatorEntity[StorCubeHub], NumberEntity):
    """Set target output power or battery reserve threshold."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, hub: StorCubeHub, device_id: str, setting: str) -> None:
        super().__init__(hub)
        self.device_id = device_id
        self.setting = setting
        if setting == "power":
            self._attr_name = "Puissance de sortie cible"
            self._attr_icon = "mdi:flash"
            self._attr_native_min_value = 0
            self._attr_native_max_value = 5000
            self._attr_native_step = 10
            self._attr_native_unit_of_measurement = UnitOfPower.WATT
            self._attr_unique_id = f"{device_id}_set_output_power"
        else:
            self._attr_name = "Seuil de décharge / réserve"
            self._attr_icon = "mdi:battery-lock"
            self._attr_native_min_value = 0
            self._attr_native_max_value = 100
            self._attr_native_step = 1
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_unique_id = f"{device_id}_set_threshold"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self.device_id)}, name=f"Batterie StorCube {self.device_id}", manufacturer="StorCube")

    @property
    def native_value(self) -> float | None:
        data = (self.coordinator.data or {}).get(self.device_id, {})
        keys = ("outputPower", "output_power", "setPower") if self.setting == "power" else ("reserved", "threshold", "threshold_value", "dischargeThreshold")
        for key in keys:
            value = data.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    @property
    def available(self) -> bool:
        data = (self.coordinator.data or {}).get(self.device_id)
        if not super().available or data is None:
            return False
        if self.setting == "power":
            output_type = str(data.get("outputType", data.get("output_type", ""))).replace("_", "").lower()
            if output_type in {"elemeter", "electricmeter"}:
                return False
        return True

    async def async_set_native_value(self, value: float) -> None:
        if self.setting == "power":
            data = (self.coordinator.data or {}).get(self.device_id, {})
            output_type = str(data.get("outputType", data.get("output_type", ""))).replace("_", "").lower()
            if output_type in {"elemeter", "electricmeter"}:
                raise HomeAssistantError("La puissance cible est bloquée en mode eleMeter")
            await self.coordinator.async_set_output_power(self.device_id, int(value))
        else:
            await self.coordinator.async_set_threshold(self.device_id, int(value))
