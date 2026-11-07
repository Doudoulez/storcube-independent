"""Independent StorCube integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .hub import StorCubeHub

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub = StorCubeHub(hass, entry, async_get_clientsession(hass))
    try:
        await hub.async_login()
    except Exception as err:
        raise ConfigEntryNotReady(f"StorCube authentication/connection failed: {err}") from err
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = hub
    hub.start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hub: StorCubeHub = hass.data[DOMAIN].pop(entry.entry_id)
    await hub.async_stop()
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return True


