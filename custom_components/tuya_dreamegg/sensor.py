"""Read-only sensors for raw Dreamegg datapoints."""

from collections.abc import Iterable
from typing import Any, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DreameggConfigEntry, DreameggRuntimeData
from .const import TUYA_DISCOVERY_NEW, TUYA_RAW_DP_UPDATE
from .entity import DreameggEntity
from .helpers import is_supported_device
from .music import VERIFIED_MUSIC_NAMES
from .schedules import ROUTINE_NAMES, decode_schedule_payload

COUNTDOWN_REMAINING_DP_ID = 104

COUNTDOWN_REMAINING = SensorEntityDescription(
    key="countdown_remaining",
    translation_key="countdown_remaining",
    icon="mdi:timer-sand",
    device_class=SensorDeviceClass.DURATION,
    native_unit_of_measurement=UnitOfTime.SECONDS,
    entity_category=EntityCategory.DIAGNOSTIC,
)

RAW_DP_DESCRIPTIONS = {
    6: SensorEntityDescription(
        key="raw_brightness",
        translation_key="raw_brightness",
        icon="mdi:brightness-6",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    7: SensorEntityDescription(
        key="raw_colour_temperature",
        translation_key="raw_colour_temperature",
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    10: SensorEntityDescription(
        key="raw_music_selection",
        translation_key="raw_music_selection",
        icon="mdi:music-note",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    13: SensorEntityDescription(
        key="raw_scene_selection",
        translation_key="raw_scene_selection",
        icon="mdi:palette-swatch",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    14: SensorEntityDescription(
        key="raw_customize_scene_set",
        translation_key="raw_customize_scene_set",
        icon="mdi:code-json",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    102: SensorEntityDescription(
        key="raw_dp_102",
        translation_key="raw_dp_102",
        icon="mdi:help-circle-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
}

SCHEDULE_DP_DESCRIPTIONS = {
    15: SensorEntityDescription(
        key="wake_up_set_enabled_slots",
        translation_key="wake_up_set_enabled_slots",
        icon="mdi:calendar-clock",
    ),
    112: SensorEntityDescription(
        key="alarm_set_enabled_slots",
        translation_key="alarm_set_enabled_slots",
        icon="mdi:alarm",
    ),
}


class DreameggRawSensor(DreameggEntity, SensorEntity):
    """Read-only sensor backed by captured raw datapoints."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        runtime: DreameggRuntimeData,
        device_id: str,
        description: SensorEntityDescription,
        dp_id: int,
    ) -> None:
        """Initialize a raw datapoint sensor."""
        super().__init__(runtime, device_id, description)
        self._dp_id = dp_id

    @property
    @override
    def native_value(self) -> int | float | str | None:
        """Return the latest captured datapoint value."""
        value = self._raw_value()
        if isinstance(value, bool):
            return None
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return value
        if not isinstance(value, int | float):
            return None
        return value

    def _raw_value(self) -> Any:
        """Return the unmodified latest datapoint value."""
        return self._runtime.capture.latest_value(self._device_id, self._dp_id)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Describe the raw datapoint and any known value mapping."""
        attributes: dict[str, Any] = {"dp_id": self._dp_id}
        if self._dp_id == 10 and isinstance(self.native_value, int):
            attributes["music_id"] = self.native_value
            if (name := VERIFIED_MUSIC_NAMES.get(str(self.native_value))) is not None:
                attributes["sound_name"] = name
        elif self._dp_id == 14:
            attributes["format"] = "base64 opaque scene configuration"
        return attributes

    @override
    async def async_added_to_hass(self) -> None:
        """Subscribe to raw datapoint updates."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{TUYA_RAW_DP_UPDATE}_{self._device_id}",
                self._handle_raw_update,
            )
        )

    @callback
    def _handle_raw_update(self, dp_id: int) -> None:
        """Write state for the datapoint this sensor tracks."""
        if dp_id == self._dp_id:
            self.async_write_ha_state()


class DreameggScheduleSensor(DreameggRawSensor):
    """Read-only schedule summary with decoded slot attributes."""

    @property
    @override
    def native_value(self) -> int | None:
        """Return the number of enabled slots in the latest schedule."""
        slots = decode_schedule_payload(self._raw_value())
        if slots is None:
            return None
        return sum(slot["enabled"] for slot in slots)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose decoded schedule records without offering write controls."""
        slots = decode_schedule_payload(self._raw_value())
        if slots is None:
            return None
        if self._dp_id == 15:
            for slot, name in zip(slots, ROUTINE_NAMES, strict=True):
                slot["name"] = name
        return {
            "dp_id": self._dp_id,
            "enabled_slots": sum(slot["enabled"] for slot in slots),
            "slot_count": len(slots),
            "slots": slots,
        }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DreameggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up read-only raw datapoint and schedule sensors."""
    runtime = entry.runtime_data
    seen: set[tuple[str, str]] = set()

    @callback
    def async_discover(device_ids: Iterable[str]) -> None:
        entities: list[DreameggRawSensor] = []
        for device_id in device_ids:
            device = runtime.device(device_id)
            if device is None or not is_supported_device(device):
                continue
            unique_key = (device_id, COUNTDOWN_REMAINING.key)
            if unique_key not in seen:
                seen.add(unique_key)
                entities.append(
                    DreameggRawSensor(
                        runtime,
                        device_id,
                        COUNTDOWN_REMAINING,
                        COUNTDOWN_REMAINING_DP_ID,
                    )
                )
            for dp_id, description in RAW_DP_DESCRIPTIONS.items():
                unique_key = (device_id, description.key)
                if unique_key in seen:
                    continue
                seen.add(unique_key)
                entities.append(
                    DreameggRawSensor(runtime, device_id, description, dp_id)
                )
            for dp_id, description in SCHEDULE_DP_DESCRIPTIONS.items():
                unique_key = (device_id, description.key)
                if unique_key in seen:
                    continue
                seen.add(unique_key)
                entities.append(
                    DreameggScheduleSensor(runtime, device_id, description, dp_id)
                )
        if entities:
            async_add_entities(entities)

    async_discover(runtime.device_map)
    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover)
    )
