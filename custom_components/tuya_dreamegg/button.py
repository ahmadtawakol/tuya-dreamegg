"""Button entities for Dreamegg Sunrise Controls."""

from collections.abc import Iterable
from typing import override

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DreameggConfigEntry, DreameggRuntimeData, is_supported_device
from .const import DP_STOP, TUYA_DISCOVERY_NEW
from .entity import DreameggEntity
from .helpers import has_writable_datapoint

STOP = ButtonEntityDescription(
    key=DP_STOP,
    translation_key="stop",
    icon="mdi:stop-circle-outline",
)


class DreameggStopButton(DreameggEntity, ButtonEntity):
    """Stop the active Dreamegg alarm or playback."""

    entity_description: ButtonEntityDescription

    def __init__(self, runtime: DreameggRuntimeData, device_id: str) -> None:
        """Initialize the stop button."""
        super().__init__(runtime, device_id, STOP)

    @override
    async def async_press(self) -> None:
        """Send the momentary stop command."""
        await self._async_send_value(True)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DreameggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Dreamegg button entities."""
    runtime = entry.runtime_data
    seen: set[str] = set()

    @callback
    def async_discover(device_ids: Iterable[str]) -> None:
        entities: list[DreameggStopButton] = []
        for device_id in device_ids:
            device = runtime.device(device_id)
            if (
                device is None
                or device_id in seen
                or not is_supported_device(device)
                or not has_writable_datapoint(device, STOP.key)
            ):
                continue
            seen.add(device_id)
            entities.append(DreameggStopButton(runtime, device_id))
        if entities:
            async_add_entities(entities)

    async_discover(runtime.device_map)
    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover)
    )
