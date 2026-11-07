"""Baterway login and WebSocket client, written for this integration."""
from __future__ import annotations

import asyncio
import json
import logging

import aiohttp
import websockets
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_APP_CODE, CONF_DEVICE_IDS, CONF_LOGIN_NAME, CONF_PASSWORD,
    DEFAULT_APP_CODE, DOMAIN, FIRMWARE_URL, HEARTBEAT_SECONDS,
    REST_INTERVAL_SECONDS, SCENE_URL, THRESHOLD_URL, TOKEN_URL, WS_URI,
)

_LOGGER = logging.getLogger(__name__)


class StorCubeHub(DataUpdateCoordinator[dict[str, dict]]):
    """Own the live stream and current readings for configured battery IDs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, session: aiohttp.ClientSession) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self.session = session
        self.device_ids: list[str] = entry.options.get(CONF_DEVICE_IDS, entry.data[CONF_DEVICE_IDS])
        self.token: str | None = None
        self._task: asyncio.Task | None = None
        self._rest_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.module_parent: dict[str, str] = {}
        self.stack_totals: dict[str, dict] = {}
        self._stack_members: dict[str, list[str]] = {}
        self.websocket_connected = False
        self.frames_received = 0
        self.unmatched_frames = 0
        self.last_error_type: str | None = None
        self.last_frame_shape: str | None = None
        self.raw_frames: list[dict | list | str | int | float | bool | None] = []

    async def _async_update_data(self) -> dict[str, dict]:
        """Return the latest pushed values if Home Assistant asks for a refresh."""
        return self.data or {}

    async def async_login(self) -> None:
        payload = {
            "appCode": self.entry.data.get(CONF_APP_CODE, DEFAULT_APP_CODE),
            "loginName": self.entry.data[CONF_LOGIN_NAME],
            "password": self.entry.data[CONF_PASSWORD],
        }
        async with self.session.post(TOKEN_URL, json=payload, timeout=20) as response:
            response.raise_for_status()
            result = await response.json(content_type=None)
        if result.get("code") != 200 or not (result.get("data") or {}).get("token"):
            raise ValueError("Baterway a refusé l’authentification")
        self.token = result["data"]["token"]

    def start(self) -> None:
        self._task = self.entry.async_create_background_task(
            self.hass, self._websocket_loop(), name="storcube_baterway_stream"
        )
        self._rest_task = self.entry.async_create_background_task(
            self.hass, self._rest_loop(), name="storcube_baterway_rest"
        )

    async def async_stop(self) -> None:
        self._stop.set()
        for task in (self._task, self._rest_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    async def _websocket_loop(self) -> None:
        delay = 5
        while not self._stop.is_set():
            try:
                if not self.token:
                    await self.async_login()
                headers = {"Authorization": self.token, "Content-Type": "application/json", "User-Agent": "okhttp/3.12.11"}
                uri = f"{WS_URI}{self.token}"
                # websockets 13+ names this argument additional_headers.
                async with websockets.connect(uri, additional_headers=headers, ping_interval=20, ping_timeout=20) as ws:
                    delay = 5
                    self.websocket_connected = True
                    self.last_error_type = None
                    # Baterway accepts a WebSocket session without a report
                    # subscription, but then sends no battery readings.
                    subscribe = json.dumps({
                        "cmd": "sub",
                        "action": "report",
                        "reportEquip": self.subscription_ids,
                    })
                    await ws.send(subscribe)
                    # Keep compatibility with app/server versions that use
                    # the simpler request documented by the MQTT client.
                    await ws.send(json.dumps({"reportEquip": self.subscription_ids}))
                    heartbeat = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for message in ws:
                            self.frames_received += 1
                            self._handle_message(message)
                    finally:
                        self.websocket_connected = False
                        heartbeat.cancel()
                        try:
                            await heartbeat
                        except asyncio.CancelledError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                self.websocket_connected = False
                self.last_error_type = type(err).__name__
                # Avoid logging the exception text: some websocket errors
                # include the token-bearing connection URL.
                _LOGGER.warning("Flux StorCube interrompu (%s); reconnexion dans %s s", type(err).__name__, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)
                self.token = None

    async def _heartbeat(self, ws) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            # Refresh both the subscription and keepalive; some Baterway
            # sessions acknowledge the socket but silently drop old topics.
            await ws.send(json.dumps({
                "cmd": "sub",
                "action": "report",
                "reportEquip": self.subscription_ids,
            }))
            await ws.send(json.dumps({"reportEquip": self.subscription_ids}))
            await ws.send(json.dumps({"heartbeat": self.subscription_ids}))

    @property
    def subscription_ids(self) -> list[str]:
        """Configured IDs plus modules discovered from the master REST response."""
        return list(dict.fromkeys([*self.device_ids, *self.discovered_device_ids]))

    @property
    def discovered_device_ids(self) -> list[str]:
        return list(dict.fromkeys(device_id for members in self._stack_members.values() for device_id in members))

    async def _api_get(self, url: str, params: dict | None = None) -> dict | None:
        """Make one authenticated Baterway GET, renewing an expired token once."""
        for attempt in range(2):
            if not self.token:
                await self.async_login()
            try:
                async with self.session.get(
                    url,
                    params=params,
                    headers={"Authorization": self.token or "", "Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status in (401, 403) and attempt == 0:
                        self.token = None
                        continue
                    response.raise_for_status()
                    result = await response.json(content_type=None)
            except aiohttp.ClientError:
                raise
            if isinstance(result, dict):
                return result
            return None
        return None

    async def async_set_output_power(self, device_id: str, power: int) -> None:
        """Set target output power using the Baterway endpoint used by batteryMqtt."""
        result = await self._api_get("http://baterway.com/api/slb/equip/set/power", {"equipId": device_id, "power": power})
        if not result or result.get("code") != 200:
            raise ValueError("Baterway a refusé la modification de puissance")
        current = dict(self.data or {})
        current.setdefault(device_id, {})["outputPower"] = power
        self.async_set_updated_data(current)

    async def async_set_threshold(self, device_id: str, threshold: int) -> None:
        """Set reserve threshold using Baterway's threshold endpoint."""
        if not self.token:
            await self.async_login()
        url = "http://baterway.com/api/scene/threshold/set"
        headers = {"Authorization": self.token or "", "Content-Type": "application/json", "appCode": self.entry.data.get(CONF_APP_CODE, DEFAULT_APP_CODE)}
        async with self.session.post(url, json={"reserved": str(threshold), "equipId": device_id}, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as response:
            response.raise_for_status()
            result = await response.json(content_type=None)
        if not isinstance(result, dict) or result.get("code") != 200:
            raise ValueError("Baterway a refusé la modification du seuil")
        current = dict(self.data or {})
        current.setdefault(device_id, {})["reserved"] = threshold
        self.async_set_updated_data(current)

    @staticmethod
    def _response_records(response: dict | None) -> list[dict]:
        """Unwrap common Baterway list and object responses."""
        if not response or response.get("code") not in (None, 200):
            return []
        data = response.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        if isinstance(response.get("list"), list):
            return [item for item in response["list"] if isinstance(item, dict)]
        return []

    async def _rest_loop(self) -> None:
        """Poll configuration, reserve and firmware fields not in the live stream."""
        cycle = 0
        while True:
            try:
                current = dict(self.data or {})
                changed = False
                for master_id in self.device_ids:
                    scene = await self._api_get(SCENE_URL, {"equipId": master_id})
                    scene_records = self._response_records(scene)
                    if scene_records:
                        record = scene_records[0]
                        member_ids = record.get("equipIds") or []
                        if isinstance(member_ids, list):
                            members = [str(item) for item in member_ids if item]
                            self._stack_members[master_id] = members
                            for member_id in members:
                                if self.module_parent.get(member_id) in (None, member_id):
                                    self.module_parent[member_id] = master_id
                        current[master_id] = {**current.get(master_id, {}), **record}
                        changed = True

                    if cycle % 5 == 0:
                        threshold = await self._api_get(THRESHOLD_URL, {"equipId": master_id})
                        if threshold and threshold.get("code") == 200:
                            value = threshold.get("data")
                            if isinstance(value, dict):
                                current[master_id] = {**current.get(master_id, {}), **value}
                                changed = True
                            elif value is not None:
                                current.setdefault(master_id, {})["threshold_value"] = value
                                changed = True

                    if cycle % 10 == 0:
                        firmware = await self._api_get(FIRMWARE_URL, {"equipId": master_id})
                        fw_records = self._response_records(firmware)
                        if fw_records:
                            current.setdefault(master_id, {}).update({f"firmware_{key}": value for key, value in fw_records[0].items()})
                            changed = True

                if changed:
                    self.async_set_updated_data(current)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Lecture REST StorCube en échec (%s)", type(err).__name__)
            cycle += 1
            await asyncio.sleep(REST_INTERVAL_SECONDS)

    def _handle_message(self, message: str | bytes) -> None:
        try:
            payload = json.loads(message)
        except (TypeError, ValueError):
            _LOGGER.debug("Trame StorCube non JSON ignorée")
            return
        self.last_frame_shape = (
            "root_list" if isinstance(payload, dict) and "list" in payload
            else "response_data" if isinstance(payload, dict) and "data" in payload
            else "device_keyed" if isinstance(payload, dict) and any(key in payload for key in self.subscription_ids)
            else "object" if isinstance(payload, dict)
            else type(payload).__name__
        )
        if isinstance(payload, (dict, list)):
            self.raw_frames = [*self.raw_frames[-2:], payload]
        found: dict[str, dict] = {}
        parents: dict[str, str] = {}
        totals: dict[str, dict] = {}

        def collect(node, fallback_id=None, in_requested_stack=False, index=0):
            if isinstance(node, list):
                for item_index, item in enumerate(node, start=1):
                    collect(item, fallback_id, in_requested_stack, item_index)
            elif isinstance(node, dict):
                if isinstance(node.get("list"), list):
                    # The outer object carries stack totals; its list contains
                    # the individual batteries (master plus expansion units).
                    parent_id = fallback_id if fallback_id in self.device_ids else None
                    if parent_id:
                        totals[parent_id] = {
                            key: value for key, value in node.items()
                            if key != "list" and isinstance(value, (str, int, float, bool))
                        }
                    for item_index, item in enumerate(node["list"], start=1):
                        collect(item, parent_id or fallback_id, bool(parent_id), item_index)
                elif "data" in node and isinstance(node["data"], (list, dict)):
                    collect(node["data"], fallback_id, in_requested_stack)
                else:
                    record_fields = {
                        "equipId", "soc", "capacity", "temp", "temperature",
                        "pv1power", "pv2power", "solarPower", "invPower", "power",
                    }
                    if not record_fields.intersection(node):
                        for key, value in node.items():
                            if isinstance(value, (dict, list)):
                                candidate = str(key) if str(key) in self.device_ids else fallback_id
                                collect(value, candidate, candidate in self.device_ids or in_requested_stack)
                        return
                    raw_id = node.get("equipId")
                    equip_id = str(raw_id) if raw_id else (
                        f"{fallback_id}#module{index}" if in_requested_stack and index > 1
                        else str(fallback_id or "")
                    )
                    if equip_id and (equip_id in self.subscription_ids or in_requested_stack):
                        found[equip_id] = node
                        parents[equip_id] = fallback_id if in_requested_stack else equip_id
                    else:
                        # Also handle nested {equipId: {report: {...}}} and
                        # {data: {equipId: {...}}} response variants.
                        for key, value in node.items():
                            if isinstance(value, (dict, list)):
                                candidate = str(key) if str(key) in self.subscription_ids else fallback_id
                                collect(value, candidate, candidate in self.device_ids or in_requested_stack)

        if isinstance(payload, dict):
            if "list" in payload or (payload.get("code") == 200 and "data" in payload):
                default_parent = self.device_ids[0] if len(self.device_ids) == 1 else None
                collect(payload, default_parent, default_parent is not None)
            else:
                for key, value in payload.items():
                    if isinstance(value, (dict, list)):
                        candidate = str(key) if str(key) in self.subscription_ids else None
                        collect(value, candidate or str(key), candidate is not None)
        if not found:
            self.unmatched_frames += 1
            _LOGGER.debug("Trame StorCube reçue mais aucun module reconnu (format=%s)", self.last_frame_shape)
            return
        for module_id, parent_id in parents.items():
            existing_parent = self.module_parent.get(module_id)
            if existing_parent is None or parent_id != module_id:
                self.module_parent[module_id] = parent_id
        self.stack_totals.update(totals)
        current = dict(self.data or {})
        for equip_id, record in found.items():
            current[equip_id] = {**current.get(equip_id, {}), **record}
            current[equip_id]["ws_online"] = True
        self.async_set_updated_data(current)
