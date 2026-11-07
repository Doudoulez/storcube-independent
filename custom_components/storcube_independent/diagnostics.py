"""Privacy-preserving diagnostics for StorCube cloud frames."""
from __future__ import annotations

import re

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .hub import StorCubeHub

_SAFE_VALUE_FIELDS = {
    "soc",
    "capacity",
    "temp",
    "temperature",
    "pv1power",
    "pv2power",
    "solarPower",
    "totalPv1power",
    "totalPv2power",
    "invPower",
    "totalInvPower",
    "power",
    "fgOnline",
    "isWork",
    "equipType",
    "version",
}

_SENSITIVE_KEY_PARTS = (
    "password", "passwd", "token", "secret", "login", "email", "phone",
    "equipid", "deviceid", "serial", "mac", "account", "userid",
)


def _redact(value, secrets: set[str], depth: int = 0):
    """Keep raw report fields while removing IDs and credential-like values."""
    if depth > 12:
        return "<depth-limit>"
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower().replace("_", "")
            if any(part.replace("_", "") in key_lower for part in _SENSITIVE_KEY_PARTS):
                continue
            # The server sometimes uses a numeric serial as an object key.
            if re.fullmatch(r"\d{8,}", key_text):
                continue
            safe[key_text] = _redact(item, secrets, depth + 1)
        return safe
    if isinstance(value, list):
        return [_redact(item, secrets, depth + 1) for item in value[:100]]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "<redacted>")
        return redacted[:500]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(type(value).__name__)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return received sensor fields without account or serial identifiers."""
    hub: StorCubeHub = hass.data[DOMAIN][entry.entry_id]
    received = hub.data or {}
    secrets = {
        *hub.device_ids,
        str(entry.data.get("login_name", "")),
        str(entry.data.get("password", "")),
        str(hub.token or ""),
    }
    batteries: dict[str, dict] = {}

    for index, payload in enumerate(received.values(), start=1):
        if not isinstance(payload, dict):
            continue
        batteries[f"battery_{index}"] = _redact(payload, secrets)

    return {
        "configured_battery_count": len(hub.device_ids),
        "received_battery_count": len(batteries),
        "discovered_module_count": len(hub.module_parent),
        "websocket_connected": hub.websocket_connected,
        "frames_received": hub.frames_received,
        "unmatched_frames": hub.unmatched_frames,
        "last_error_type": hub.last_error_type,
        "last_frame_shape": hub.last_frame_shape,
        "data_received": bool(batteries),
        "batteries": batteries,
        "recent_raw_frames": [_redact(frame, secrets) for frame in hub.raw_frames],
        "stack_totals": {
            f"stack_{index}": {
                key: value for key, value in totals.items()
                if key in _SAFE_VALUE_FIELDS
                and isinstance(value, (str, int, float, bool, type(None)))
            }
            for index, totals in enumerate(hub.stack_totals.values(), start=1)
        },
    }
