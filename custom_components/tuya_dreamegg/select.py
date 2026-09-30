"""Select entities for Dreamegg Sunrise Controls."""

from collections.abc import Iterable
from typing import Any, override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DreameggConfigEntry, DreameggRuntimeData, is_supported_device
from .const import DP_TIME_MODE, TUYA_DISCOVERY_NEW
from .entity import DreameggEntity
from .helpers import datapoint_values, has_writable_datapoint

TIME_FORMAT = SelectEntityDescription(
    key=DP_TIME_MODE,
    translation_key="time_format",
    icon="mdi:clock-digital",
    entity_category=EntityCategory.CONFIG,
)


class DreameggSelect(DreameggEntity, SelectEntity):
    """Writable Dreamegg enum datapoint."""

    entity_description: SelectEntityDescription

    def __init__(
        self,
        runtime: DreameggRuntimeData,
        device: Any,
        description: SelectEntityDescription,
    ) -> None:
        """Initialize a Dreamegg select."""
        super().__init__(runtime, device.id, description)
        value_range = datapoint_values(device, description.key).get("range")
        self._attr_options = (
            [option for option in value_range if isinstance(option, str)]
            if isinstance(value_range, list)
            else ["12h", "24h"]
        )

    @property
    @override
    def current_option(self) -> str | None:
        """Return the current option."""
        value = self._status_value()
        return value if isinstance(value, str) else None

    @override
    async def async_select_option(self, option: str) -> None:
        """Select the time format."""
        await self._async_send_value(option)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DreameggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Dreamegg select entities."""
    runtime = entry.runtime_data
    seen: set[str] = set()

    @callback
    def async_discover(device_ids: Iterable[str]) -> None:
        entities: list[DreameggSelect] = []
        for device_id in device_ids:
            device = runtime.device(device_id)
            if (
                device is None
                or device_id in seen
                or not is_supported_device(device)
                or not has_writable_datapoint(device, TIME_FORMAT.key)
            ):
                continue
            seen.add(device_id)
            entities.append(DreameggSelect(runtime, device, TIME_FORMAT))
        if entities:
            async_add_entities(entities)

    async_discover(runtime.device_map)
    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover)
    )
