"""Select entities for Dreamegg Sunrise Controls."""

from collections.abc import Iterable
from typing import Any, override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DreameggConfigEntry, DreameggRuntimeData
from .const import (
    DP_MUSIC_SET,
    DP_TIME_MODE,
    DP_WORK_MODE,
    TUYA_DISCOVERY_NEW,
    TUYA_RAW_DP_UPDATE,
)
from .entity import DreameggEntity
from .helpers import datapoint_values, has_writable_datapoint, is_supported_device
from .music import MUSIC_DP_ID, MUSIC_NAMES

TIME_FORMAT = SelectEntityDescription(
    key=DP_TIME_MODE,
    translation_key="time_format",
    icon="mdi:clock-digital",
    entity_category=EntityCategory.CONFIG,
)
WORK_MODE = SelectEntityDescription(
    key=DP_WORK_MODE,
    translation_key="work_mode",
    icon="mdi:theme-light-dark",
    entity_category=EntityCategory.CONFIG,
)
MUSIC_SELECTION = SelectEntityDescription(
    key=DP_MUSIC_SET,
    translation_key="music_selection",
    icon="mdi:music",
)
SELECTS = (TIME_FORMAT, WORK_MODE, MUSIC_SELECTION)

DEFAULT_OPTIONS = {
    DP_TIME_MODE: ["12h", "24h"],
    DP_WORK_MODE: ["scene", "customize_scene", "colour"],
    DP_MUSIC_SET: list(MUSIC_NAMES),
}


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
            else DEFAULT_OPTIONS[description.key]
        )

    @property
    @override
    def current_option(self) -> str | None:
        """Return the current option."""
        value = self._status_value()
        if self.entity_description.key == DP_MUSIC_SET:
            raw_value = self._runtime.capture.latest_value(self._device_id, MUSIC_DP_ID)
            if raw_value is not None:
                value = raw_value
            return str(value) if str(value) in self.options else None
        return value if isinstance(value, str) else None

    @override
    async def async_added_to_hass(self) -> None:
        """Listen to raw music reports omitted by Tuya's reduced HA schema."""
        await super().async_added_to_hass()
        if self.entity_description.key == DP_MUSIC_SET:
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"{TUYA_RAW_DP_UPDATE}_{self._device_id}",
                    self._handle_music_update,
                )
            )

    @callback
    def _handle_music_update(self, dp_id: int) -> None:
        """Update selection only when DP 10 reports a value."""
        if dp_id == MUSIC_DP_ID:
            self.async_write_ha_state()

    @override
    async def async_select_option(self, option: str) -> None:
        """Select an enum option."""
        if option not in self.options:
            raise ServiceValidationError("Unsupported Dreamegg selection")
        await self._async_send_value(option)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DreameggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Dreamegg select entities."""
    runtime = entry.runtime_data
    seen: set[tuple[str, str]] = set()

    @callback
    def async_discover(device_ids: Iterable[str]) -> None:
        entities: list[DreameggSelect] = []
        for device_id in device_ids:
            device = runtime.device(device_id)
            if device is None or not is_supported_device(device):
                continue
            for description in SELECTS:
                unique_key = (device_id, description.key)
                if unique_key in seen or (
                    description.key != DP_MUSIC_SET
                    and not has_writable_datapoint(device, description.key)
                ):
                    continue
                seen.add(unique_key)
                entities.append(DreameggSelect(runtime, device, description))
        if entities:
            async_add_entities(entities)

    async_discover(runtime.device_map)
    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover)
    )
