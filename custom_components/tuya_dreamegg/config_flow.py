"""Config flow for Dreamegg Sunrise Controls."""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState

from .const import CONF_TUYA_ENTRY_ID, DOMAIN, TUYA_DOMAIN
from .helpers import is_supported_device


class DreameggConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure controls backed by an official Tuya account."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize transient account choices."""
        self._loaded_tuya = False
        self._accounts: dict[str, str] = {}

    def _eligible_accounts(self) -> tuple[bool, dict[str, str]]:
        """Return loaded Tuya accounts containing supported devices."""
        loaded_tuya = False
        accounts: dict[str, str] = {}
        for entry in self.hass.config_entries.async_entries(TUYA_DOMAIN):
            if entry.state is not ConfigEntryState.LOADED:
                continue
            manager = getattr(getattr(entry, "runtime_data", None), "manager", None)
            device_map = getattr(manager, "device_map", None)
            if not isinstance(device_map, Mapping):
                continue
            loaded_tuya = True
            count = sum(is_supported_device(device) for device in device_map.values())
            if count:
                suffix = "device" if count == 1 else "devices"
                accounts[entry.entry_id] = f"{entry.title} ({count} {suffix})"
        return loaded_tuya, accounts

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select the official Tuya account to extend."""
        if not self._accounts:
            self._loaded_tuya, self._accounts = self._eligible_accounts()
        if not self._loaded_tuya:
            return self.async_abort(reason="tuya_not_configured")
        if not self._accounts:
            return self.async_abort(reason="no_supported_devices")

        if user_input is not None:
            tuya_entry_id = user_input[CONF_TUYA_ENTRY_ID]
            await self.async_set_unique_id(tuya_entry_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Dreamegg Sunrise Controls",
                data={CONF_TUYA_ENTRY_ID: tuya_entry_id},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_TUYA_ENTRY_ID): vol.In(self._accounts)}
            ),
        )
