"""Configuration UI for StorCube Batteries."""
from __future__ import annotations

import asyncio
import logging
import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .const import (
    CONF_APP_CODE, CONF_DEVICE_IDS, CONF_LOGIN_NAME, CONF_PASSWORD,
    DEFAULT_APP_CODE, DOMAIN, TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)
PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _device_ids(raw: str) -> list[str]:
    """Parse IDs separated by commas, semicolons or newlines."""
    return list(dict.fromkeys(part.strip() for part in raw.replace(";", ",").replace("\n", ",").split(",") if part.strip()))


class StorCubeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one account and one or more batteries."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowWithReload:
        return StorCubeOptionsFlow()

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            ids = _device_ids(user_input[CONF_DEVICE_IDS])
            if not ids:
                errors["base"] = "no_device_ids"
            else:
                try:
                    await self._validate(user_input)
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except (CannotConnect, aiohttp.ClientError, TimeoutError):
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("StorCube setup validation failed")
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id("|".join(sorted(ids)))
                    self._abort_if_unique_id_configured()
                    data = {**user_input, CONF_DEVICE_IDS: ids}
                    return self.async_create_entry(title=f"StorCube ({len(ids)} pile(s))", data=data)

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_IDS, default=""): str,
            vol.Required(CONF_LOGIN_NAME): str,
            vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
            vol.Optional(CONF_APP_CODE, default=DEFAULT_APP_CODE): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _validate(self, data: dict) -> None:
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(20):
                async with session.post(TOKEN_URL, json={
                    "appCode": data.get(CONF_APP_CODE, DEFAULT_APP_CODE),
                    "loginName": data[CONF_LOGIN_NAME],
                    "password": data[CONF_PASSWORD],
                }, headers={"Content-Type": "application/json"}) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
        except TimeoutError:
            raise CannotConnect from None
        except aiohttp.ClientError as err:
            raise CannotConnect from err
        if payload.get("code") != 200 or not (payload.get("data") or {}).get("token"):
            raise InvalidAuth


class StorCubeOptionsFlow(OptionsFlowWithReload):
    """Let the user add the slave battery identifier after setup."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current_ids = self.config_entry.options.get(
            CONF_DEVICE_IDS, self.config_entry.data[CONF_DEVICE_IDS]
        )
        if user_input is not None:
            ids = _device_ids(user_input[CONF_DEVICE_IDS])
            if not ids:
                errors["base"] = "no_device_ids"
            else:
                return self.async_create_entry(title="", data={CONF_DEVICE_IDS: ids})

        schema = vol.Schema({
            vol.Required(
                CONF_DEVICE_IDS,
                default=", ".join(current_ids),
            ): str,
        })
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


class CannotConnect(HomeAssistantError):
    """Baterway could not be reached."""


class InvalidAuth(HomeAssistantError):
    """Baterway rejected the credentials."""
