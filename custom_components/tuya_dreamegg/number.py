"""Number entities for Dreamegg Sunrise Controls."""

from collections.abc import Iterable
from typing import Any, override

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DreameggConfigEntry, DreameggRuntimeData, is_supported_device
from .const import DP_BACKLIGHT, DP_COUNTDOWN, TUYA_DISCOVERY_NEW
from .entity import DreameggEntity
from .helpers import datapoint_values, has_writable_datapoint

NUMBERS = (
    NumberEntityDescription(
        key=DP_COUNTDOWN,
        translation_key="countdown",
        icon="mdi:timer-outline",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.SLIDER,
    ),
    NumberEntityDescription(
        key=DP_BACKLIGHT,
        translation_key="display_brightness",
        icon="mdi:brightness-6",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.SLIDER,
    ),
)

DEFAULT_BOUNDS = {
    DP_COUNTDOWN: (0.0, 1440.0, 1.0),
    DP_BACKLIGHT: (0.0, 100.0, 1.0),
}


class DreameggNumber(DreameggEntity, NumberEntity):
    """Writable Dreamegg numeric datapoint."""

    entity_description: NumberEntityDescription

    def __init__(
        self,
        runtime: DreameggRuntimeData,
        device: Any,
        description: NumberEntityDescription,
    ) -> None:
        """Initialize a Dreamegg number."""
        super().__init__(runtime, device.id, description)
        values = datapoint_values(device, description.key)
        self._scale = int(values.get("scale", 0))
        divisor = 10**self._scale
        default_min, default_max, default_step = DEFAULT_BOUNDS[description.key]
        self._attr_native_min_value = _scaled_number(
            values.get("min"), divisor, default_min
        )
        self._attr_native_max_value = _scaled_number(
            values.get("max"), divisor, default_max
        )
        self._attr_native_step = _scaled_number(
            values.get("step"), divisor, default_step
        )

    @property
    @override
    def native_value(self) -> float | None:
        """Return the current value."""
        value = self._status_value()
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value) / 10**self._scale

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the numeric datapoint."""
        await self._async_send_value(round(value * 10**self._scale))


def _scaled_number(value: Any, divisor: int, default: float) -> float:
    """Scale numeric Tuya metadata with a safe default."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value) / divisor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DreameggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Dreamegg number entities."""
    runtime = entry.runtime_data
    seen: set[tuple[str, str]] = set()

    @callback
    def async_discover(device_ids: Iterable[str]) -> None:
        entities: list[DreameggNumber] = []
        for device_id in device_ids:
            device = runtime.device(device_id)
            if device is None or not is_supported_device(device):
                continue
            for description in NUMBERS:
                unique_key = (device_id, description.key)
                if unique_key in seen or not has_writable_datapoint(
                    device, description.key
                ):
                    continue
                seen.add(unique_key)
                entities.append(DreameggNumber(runtime, device, description))
        if entities:
            async_add_entities(entities)

    async_discover(runtime.device_map)
    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover)
    )
