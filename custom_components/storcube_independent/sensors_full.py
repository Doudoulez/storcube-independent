"""StorCube telemetry and Energy dashboard meters."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_DEVICE_IDS, DOMAIN
from .hub import StorCubeHub


def _value(data: dict, *keys: str) -> Any:
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def _number(data: dict, *keys: str) -> float | None:
    try:
        value = _value(data, *keys)
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _channel(data: dict, channel: int) -> float | None:
    return _number(data, f"pv{channel}power", f"totalPv{channel}power", f"solarPower{channel}")


def _solar(data: dict) -> float | None:
    one, two = _channel(data, 1), _channel(data, 2)
    if one is None and two is None:
        return _number(data, "solarPower", "totalPvPower")
    return (one or 0) + (two or 0)


def _battery_power(data: dict) -> float | None:
    direct = _number(data, "batteryPower", "batPower", "chargeDischargePower")
    if direct is not None:
        return direct
    solar = _solar(data)
    output = _number(data, "totalInvPower", "invPower", "outputActualPower")
    return round(solar - output, 1) if solar is not None and output is not None else None


def _online(data: dict) -> str | None:
    value = _value(data, "fgOnline", "online", "ws_online")
    if value is None:
        return None
    return "En ligne" if str(value).lower() in ("1", "true", "online", "on") else "Hors ligne"


def _battery_state(data: dict) -> Any:
    return _value(data, "batteryStatus", "isWork", "battery_state")


def _work_status(data: dict) -> Any:
    return _value(data, "workStatus", "work_status", "runStatus")


def _description(
    key: str, name: str, icon: str, *, unit=None, device_class=None, state_class=None,
) -> SensorEntityDescription:
    return SensorEntityDescription(
        key=key,
        name=name,
        icon=icon,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=state_class,
    )


BATTERY_DESCRIPTIONS = (
    ("soc", _description("soc", "Charge", "mdi:battery-high", unit=PERCENTAGE, device_class=SensorDeviceClass.BATTERY, state_class=SensorStateClass.MEASUREMENT), lambda d: _number(d, "soc", "batterySoc")),
    ("capacity", _description("capacity", "Énergie restante", "mdi:battery-charging", unit=UnitOfEnergy.WATT_HOUR, device_class=SensorDeviceClass.ENERGY_STORAGE, state_class=SensorStateClass.MEASUREMENT), lambda d: _number(d, "capacity", "remainEnergy", "remainingCapacity")),
    ("battery_power", _description("battery_power", "Puissance batterie", "mdi:battery-sync", unit=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT), _battery_power),
    ("pv1", _description("pv1", "Puissance solaire 1", "mdi:solar-power", unit=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT), lambda d: _channel(d, 1)),
    ("pv2", _description("pv2", "Puissance solaire 2", "mdi:solar-power", unit=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT), lambda d: _channel(d, 2)),
    ("solar", _description("solar", "Puissance solaire totale", "mdi:solar-power", unit=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT), _solar),
    ("output", _description("output", "Puissance de sortie", "mdi:flash", unit=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT), lambda d: _number(d, "totalInvPower", "invPower", "outputActualPower")),
    ("setpoint", _description("setpoint", "Consigne de sortie", "mdi:target", unit=UnitOfPower.WATT, device_class=SensorDeviceClass.POWER, state_class=SensorStateClass.MEASUREMENT), lambda d: _number(d, "outputPower", "output_power", "setPower")),
    ("threshold", _description("threshold", "Seuil de décharge", "mdi:battery-arrow-down", unit=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT), lambda d: _number(d, "reserved", "threshold", "threshold_value", "dischargeThreshold")),
    ("reserve", _description("reserve", "Niveau de réserve", "mdi:battery-lock", unit=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT), lambda d: _number(d, "reserved", "reserve", "threshold_value")),
    ("temperature", _description("temperature", "Température batterie", "mdi:thermometer", unit=UnitOfTemperature.CELSIUS, device_class=SensorDeviceClass.TEMPERATURE, state_class=SensorStateClass.MEASUREMENT), lambda d: _number(d, "temp", "temperature", "batteryTemperature")),
    ("battery_status", _description("battery_status", "État batterie", "mdi:battery-check"), _battery_state),
    ("error_code", _description("error_code", "Code d’erreur", "mdi:alert-circle-outline"), lambda d: _value(d, "errorCode", "errCode", "faultCode", "alarmCode", "error_code", "error")),
    ("connection", _description("connection", "État de connexion", "mdi:lan-connect"), _online),
    ("work_status", _description("work_status", "État de fonctionnement", "mdi:power"), _work_status),
    ("system_status", _description("system_status", "État système", "mdi:state-machine"), lambda d: _value(d, "systemStatus", "sysStatus", "systemState", "status")),
    ("operating_mode", _description("operating_mode", "Mode de fonctionnement", "mdi:cog-outline"), lambda d: _value(d, "workMode", "operateMode", "operatingMode", "mode")),
    ("output_type", _description("output_type", "Type de sortie", "mdi:power-plug"), lambda d: _value(d, "outputType", "output_type")),
    ("model", _description("model", "Modèle", "mdi:information-outline"), lambda d: _value(d, "equipModelCode", "equipType", "model", "modelName")),
    ("serial", _description("serial", "Numéro de série", "mdi:barcode"), lambda d: _value(d, "equipId", "serialNumber", "serialNo")),
    ("firmware_version", _description("firmware_version", "Version firmware", "mdi:chip"), lambda d: _value(d, "firmwareVersion", "version", "swVersion", "firmware_lastBigVersion", "firmware_version")),
    ("firmware_update", _description("firmware_update", "État firmware", "mdi:update"), lambda d: _value(d, "firmware_currentBigVersion", "firmware_upgradeAvailable", "upgradeAvailable", "upgrade_available")),
)

_HANDLED_KEYS = {
    "soc", "batterySoc", "capacity", "remainEnergy", "remainingCapacity", "batteryPower", "batPower",
    "chargeDischargePower", "pv1power", "totalPv1power", "solarPower1", "pv2power", "totalPv2power",
    "solarPower2", "solarPower", "totalPvPower", "totalInvPower", "invPower", "outputActualPower",
    "outputPower", "output_power", "setPower", "reserved", "threshold", "threshold_value",
    "dischargeThreshold", "reserve", "temp", "temperature", "batteryTemperature", "batteryStatus",
    "isWork", "battery_state", "errorCode", "errCode", "faultCode", "alarmCode", "error_code", "error",
    "fgOnline", "online", "ws_online", "workStatus", "work_status", "runStatus", "systemStatus",
    "sysStatus", "systemState", "status", "workMode", "operateMode", "operatingMode", "mode",
    "outputType", "output_type", "equipModelCode", "equipType", "model", "modelName", "equipId",
    "serialNumber", "serialNo", "firmwareVersion", "version", "swVersion", "firmware_lastBigVersion",
    "firmware_currentBigVersion", "firmware_upgradeAvailable", "upgradeAvailable", "upgrade_available",
    "equipIds",
}


def _flatten(data: Any, prefix: tuple[str, ...] = ()):
    if isinstance(data, dict):
        for key, value in data.items():
            lower = str(key).lower()
            if any(part in lower for part in ("password", "token", "secret", "login", "email", "phone", "equipid", "serialnumber")):
                continue
            yield from _flatten(value, (*prefix, str(key)))
    elif isinstance(data, (str, int, float, bool)) or data is None:
        if prefix and data is not None:
            yield prefix, data


def _at_path(data: dict, path: tuple[str, ...]):
    value: Any = data
    for part in path:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _aggregate_power(hub: StorCubeHub, metric: str) -> float | None:
    """Sum module power without counting a stack-level API total twice."""
    data = hub.data or {}
    groups = {hub.module_parent.get(device_id, device_id) for device_id in hub.device_ids}
    totals: list[float] = []
    for master_id in groups:
        stack = hub.stack_totals.get(master_id, {})
        if metric == "pv1":
            total = _number(stack, "totalPv1power")
            vals = [_channel(item, 1) for key, item in data.items() if hub.module_parent.get(key, key) == master_id]
        elif metric == "pv2":
            total = _number(stack, "totalPv2power")
            vals = [_channel(item, 2) for key, item in data.items() if hub.module_parent.get(key, key) == master_id]
        elif metric == "solar":
            p1, p2 = _number(stack, "totalPv1power"), _number(stack, "totalPv2power")
            total = (p1 or 0) + (p2 or 0) if p1 is not None or p2 is not None else None
            vals = [_solar(item) for key, item in data.items() if hub.module_parent.get(key, key) == master_id]
        else:
            total = _number(stack, "totalInvPower")
            vals = [_number(item, "totalInvPower", "invPower", "outputActualPower") for key, item in data.items() if hub.module_parent.get(key, key) == master_id]
        if total is not None:
            totals.append(total)
        else:
            totals.extend(value for value in vals if value is not None)
    return round(sum(totals), 1) if totals else None


def _aggregate_battery_power(hub: StorCubeHub) -> float | None:
    data = hub.data or {}
    direct = [_number(item, "batteryPower", "batPower", "chargeDischargePower") for item in data.values()]
    direct = [value for value in direct if value is not None]
    if direct:
        return round(sum(direct), 1)
    solar, output = _aggregate_power(hub, "solar"), _aggregate_power(hub, "output")
    return round(solar - output, 1) if solar is not None and output is not None else None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    hub: StorCubeHub = hass.data[DOMAIN][entry.entry_id]
    known_modules = set(hub.device_ids)

    entities: list[SensorEntity] = []
    for device_id in hub.device_ids:
        entities.extend(BatteryFieldSensor(hub, device_id, description, getter) for _, description, getter in BATTERY_DESCRIPTIONS)
    entities.extend(VirtualFieldSensor(hub, metric) for metric in VIRTUAL_METRICS)
    entities.extend(VirtualEnergySensor(hub, metric) for metric in ENERGY_METRICS)
    async_add_entities(entities)

    @callback
    def add_discovered_module_sensors() -> None:
        """Add the known sensors for modules discovered after platform setup."""
        new_entities: list[SensorEntity] = []
        for device_id in (hub.data or {}):
            if device_id in known_modules:
                continue
            known_modules.add(device_id)
            new_entities.extend(
                BatteryFieldSensor(hub, device_id, description, getter)
                for _, description, getter in BATTERY_DESCRIPTIONS
            )
        if new_entities:
            async_add_entities(new_entities)

    add_discovered_module_sensors()
    entry.async_on_unload(hub.async_add_listener(add_discovered_module_sensors))


class BatteryFieldSensor(CoordinatorEntity[StorCubeHub], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, hub: StorCubeHub, device_id: str, description: SensorEntityDescription, getter) -> None:
        super().__init__(hub)
        self.device_id = device_id
        self.entity_description = description
        self.getter = getter
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self.device_id)}, name=f"Batterie StorCube {self.device_id}", manufacturer="StorCube")

    @property
    def native_value(self):
        return self.getter((self.coordinator.data or {}).get(self.device_id, {}))

    @property
    def available(self) -> bool:
        return super().available and self.device_id in (self.coordinator.data or {})


class RawFieldSensor(CoordinatorEntity[StorCubeHub], SensorEntity):
    """Expose new scalar API fields as entities without waiting for a code update."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: StorCubeHub, device_id: str, path: tuple[str, ...]) -> None:
        super().__init__(hub)
        self.device_id = device_id
        self.path = path
        label = ".".join(path)
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:64] or "field"
        self._attr_name = f"API · {label}"
        self._attr_icon = "mdi:code-json"
        self._attr_unique_id = f"{device_id}_raw_{slug}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self.device_id)}, name=f"Batterie StorCube {self.device_id}", manufacturer="StorCube")

    @property
    def native_value(self):
        value = _at_path((self.coordinator.data or {}).get(self.device_id, {}), self.path)
        return str(value)[:240] if isinstance(value, str) else value

    @property
    def available(self) -> bool:
        return super().available and self.device_id in (self.coordinator.data or {})


VIRTUAL_METRICS = (
    "count", "soc", "capacity", "battery_power", "pv1", "pv2", "solar", "output", "setpoint",
    "threshold", "reserve", "temperature", "battery_status", "error_code", "connection", "work_status",
    "system_status", "operating_mode", "output_type", "model", "firmware_version", "firmware_update",
)


class VirtualFieldSensor(CoordinatorEntity[StorCubeHub], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, hub: StorCubeHub, metric: str) -> None:
        super().__init__(hub)
        self.metric = metric
        aliases = {name: (desc.name, desc.icon, desc.native_unit_of_measurement, desc.device_class, desc.state_class) for name, desc, _getter in BATTERY_DESCRIPTIONS}
        if metric == "count":
            title = ("Modules StorCube", "mdi:battery-multiple", None, None, None)
        else:
            desc = next(desc for name, desc, _getter in BATTERY_DESCRIPTIONS if name == metric)
            title = (f"{desc.name} globale", desc.icon, desc.native_unit_of_measurement, desc.device_class, desc.state_class)
        self._attr_name, self._attr_icon, self._attr_native_unit_of_measurement, self._attr_device_class, self._attr_state_class = title
        self._attr_unique_id = f"virtual_{hub.entry.entry_id}_{metric}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"virtual_{self.coordinator.entry.entry_id}")}, name="Batterie virtuelle StorCube", manufacturer="StorCube", model="Agrégation des modules configurés")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        items = list(data.values())
        if self.metric == "count":
            return len(items) or None
        if self.metric == "soc":
            vals = [_number(item, "soc", "batterySoc") for item in items]
            vals = [value for value in vals if value is not None]
            return round(sum(vals) / len(vals), 1) if vals else None
        if self.metric == "capacity":
            vals = [_number(item, "capacity", "remainEnergy", "remainingCapacity") for item in items]
            vals = [value for value in vals if value is not None]
            return round(sum(vals), 1) if vals else None
        if self.metric == "battery_power":
            return _aggregate_battery_power(self.coordinator)
        if self.metric in ("pv1", "pv2", "solar", "output"):
            return self._aggregate_power(self.metric)
        if self.metric == "temperature":
            return self._average("temp", "temperature", "batteryTemperature")
        if self.metric in ("threshold", "reserve"):
            return self._average("reserved", "threshold", "threshold_value", "dischargeThreshold", "reserve")
        if self.metric == "setpoint":
            vals = [_number(data.get(device_id, {}), "outputPower", "output_power", "setPower") for device_id in self.coordinator.device_ids]
            vals = [value for value in vals if value is not None]
            return round(sum(vals), 1) if vals else None
        if self.metric == "connection":
            online = [_online(item) == "En ligne" for item in items]
            if not online:
                return None
            return "En ligne" if all(online) else ("Partielle" if any(online) else "Hors ligne")
        getters = {
            "battery_status": _battery_state,
            "error_code": lambda d: _value(d, "errorCode", "errCode", "faultCode", "alarmCode", "error_code"),
            "work_status": _work_status,
            "system_status": lambda d: _value(d, "systemStatus", "sysStatus", "systemState", "status"),
            "operating_mode": lambda d: _value(d, "workMode", "operateMode", "operatingMode", "mode"),
            "output_type": lambda d: _value(d, "outputType", "output_type"),
            "model": lambda d: _value(d, "equipModelCode", "equipType", "model", "modelName"),
            "firmware_version": lambda d: _value(d, "firmwareVersion", "version", "swVersion", "firmware_lastBigVersion", "firmware_version"),
            "firmware_update": lambda d: _value(d, "firmware_currentBigVersion", "firmware_upgradeAvailable", "upgradeAvailable", "upgrade_available"),
        }
        values = list(dict.fromkeys(str(getters[self.metric](item)) for item in items if getters[self.metric](item) is not None))
        return ", ".join(values) if values else None

    def _average(self, *keys: str) -> float | None:
        vals = [_number(item, *keys) for item in (self.coordinator.data or {}).values()]
        vals = [value for value in vals if value is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def _aggregate_field(self, *keys: str) -> float | None:
        values = [_number(item, *keys) for item in (self.coordinator.data or {}).values()]
        values = [value for value in values if value is not None]
        return round(sum(values), 1) if values else None

    def _aggregate_power(self, metric: str) -> float | None:
        return _aggregate_power(self.coordinator, metric)

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data)


ENERGY_METRICS = ("charge", "discharge", "solar_1", "solar_2", "solar_total", "output")
ENERGY_NAMES = {
    "charge": "Énergie chargée dans la batterie",
    "discharge": "Énergie déchargée de la batterie",
    "solar_1": "Énergie solaire 1",
    "solar_2": "Énergie solaire 2",
    "solar_total": "Énergie solaire totale",
    "output": "Énergie vers onduleur",
}


class VirtualEnergySensor(CoordinatorEntity[StorCubeHub], RestoreSensor):
    """Restore-safe kWh counters for Home Assistant's Energy dashboard."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hub: StorCubeHub, metric: str) -> None:
        super().__init__(hub)
        self.metric = metric
        self._attr_name = ENERGY_NAMES[metric]
        self._attr_icon = "mdi:battery-charging" if metric == "charge" else "mdi:battery-arrow-down" if metric == "discharge" else "mdi:solar-power" if metric.startswith("solar") else "mdi:flash"
        self._attr_unique_id = f"virtual_{hub.entry.entry_id}_energy_{metric}"
        self._total = 0.0
        self._last_power: float | None = None
        self._last_time: datetime | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, f"virtual_{self.coordinator.entry.entry_id}")}, name="Batterie virtuelle StorCube", manufacturer="StorCube", model="Agrégation des modules configurés")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last and last.native_value is not None:
            try:
                self._total = float(last.native_value)
            except (TypeError, ValueError):
                self._total = 0.0

    def _power(self) -> float | None:
        if self.metric == "charge":
            value = _aggregate_battery_power(self.coordinator)
            return max(value, 0) if value is not None else None
        if self.metric == "discharge":
            value = _aggregate_battery_power(self.coordinator)
            return max(-value, 0) if value is not None else None
        if self.metric == "solar_1":
            return _aggregate_power(self.coordinator, "pv1")
        if self.metric == "solar_2":
            return _aggregate_power(self.coordinator, "pv2")
        if self.metric == "solar_total":
            return _aggregate_power(self.coordinator, "solar")
        return _aggregate_power(self.coordinator, "output")

    @callback
    def _handle_coordinator_update(self) -> None:
        power = self._power()
        now = dt_util.utcnow()
        if power is not None and power >= 0:
            if self._last_power is not None and self._last_time is not None:
                hours = (now - self._last_time).total_seconds() / 3600
                if 0 < hours < 0.25:
                    self._total += ((self._last_power + power) / 2) * hours / 1000
            self._last_power = power
            self._last_time = now
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float:
        return round(self._total, 5)

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data)
