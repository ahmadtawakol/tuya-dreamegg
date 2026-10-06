"""Dreamegg Sunrise Controls integration."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .capture import RawDpCapture
from .const import (
    CONF_TUYA_ENTRY_ID,
    PLATFORMS,
)
from .helpers import is_supported_device
from .services import async_remove_services_if_unused, async_setup_services


@dataclass(slots=True)
class DreameggRuntimeData:
    """Resolve the current official Tuya runtime after account reloads."""

    hass: HomeAssistant
    tuya_entry_id: str
    capture: RawDpCapture = field(init=False)

    def __post_init__(self) -> None:
        """Create the privacy-bounded raw datapoint capture."""
        self.capture = RawDpCapture(self.hass)

    @property
    def manager(self) -> Any | None:
        """Return the currently loaded official Tuya manager."""
        entry = self.hass.config_entries.async_get_entry(self.tuya_entry_id)
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            return None
        manager = getattr(getattr(entry, "runtime_data", None), "manager", None)
        if manager is not None:
            self.capture.attach(manager)
        return manager

    @property
    def device_map(self) -> Mapping[str, Any]:
        """Return the official Tuya device cache."""
        device_map = getattr(self.manager, "device_map", None)
        return device_map if isinstance(device_map, Mapping) else {}

    def device(self, device_id: str) -> Any | None:
        """Return one current device object."""
        return self.device_map.get(device_id)

    def supported_devices(self) -> tuple[Any, ...]:
        """Return supported devices from the current Tuya cache."""
        return tuple(
            device for device in self.device_map.values() if is_supported_device(device)
        )


type DreameggConfigEntry = ConfigEntry[DreameggRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: DreameggConfigEntry) -> bool:
    """Set up Dreamegg controls from an official Tuya account."""
    runtime = DreameggRuntimeData(hass, entry.data[CONF_TUYA_ENTRY_ID])
    if runtime.manager is None:
        raise ConfigEntryNotReady("The official Tuya integration is not loaded")
    if not runtime.supported_devices():
        raise ConfigEntryNotReady("No supported Dreamegg devices were found")

    entry.runtime_data = runtime
    runtime.capture.attach(runtime.manager)
    entry.async_on_unload(runtime.capture.detach)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DreameggConfigEntry) -> bool:
    """Unload Dreamegg controls."""
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        async_remove_services_if_unused(hass, entry.entry_id)
    return unloaded
