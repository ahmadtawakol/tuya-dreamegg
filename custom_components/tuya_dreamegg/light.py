"""Colour light for Dreamegg Sunrise Controls.

The official Tuya integration exposes the clock's lamp, but the device
specification carries no ranges for ``colour_data``. Home Assistant therefore
falls back to the legacy 0-255 scale, while the clock uses 0-1000 for both
saturation and value. Through the official entity the lamp can only reach about
a quarter of its brightness and saturation, and its reported state is
mis-scaled. This entity talks to the same datapoints on the correct scale.
"""

import json
from collections.abc import Iterable
from math import isfinite
from typing import Any, override

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DreameggConfigEntry, DreameggRuntimeData
from .const import (
    DP_COLOUR_DATA,
    DP_SWITCH_LED,
    DP_WORK_MODE,
    TUYA_DISCOVERY_NEW,
    WORK_MODE_COLOUR,
)
from .entity import DreameggEntity
from .helpers import has_writable_datapoint, is_supported_device

COLOUR_LIGHT = LightEntityDescription(
    key="colour_light",
    translation_key="colour_light",
    icon="mdi:lightbulb-night",
)

# Scale used by the clock for saturation and value.
DEVICE_MAX = 1000
# Lowest value sent while the lamp is on, so 1/255 never rounds to dark.
DEVICE_MIN_VALUE = 10
# Used when the lamp has never reported a colour.
DEFAULT_HSV = (30, 600, DEVICE_MAX)

_WATCHED_DATAPOINTS = frozenset({DP_SWITCH_LED, DP_COLOUR_DATA, DP_WORK_MODE})


def parse_colour_data(value: Any) -> tuple[int, int, int] | None:
    """Return (h, s, v) from a ``colour_data`` report, or None if unusable."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None
    parts = []
    for key in ("h", "s", "v"):
        part = value.get(key)
        if isinstance(part, bool) or not isinstance(part, int | float):
            return None
        if isinstance(part, float) and not isfinite(part):
            return None
        parts.append(int(part))
    hue, saturation, brightness = parts
    return (
        max(0, min(360, hue)),
        max(0, min(DEVICE_MAX, saturation)),
        max(0, min(DEVICE_MAX, brightness)),
    )


def brightness_to_device(brightness: int) -> int:
    """Convert Home Assistant brightness (1-255) to the device value."""
    return max(DEVICE_MIN_VALUE, min(DEVICE_MAX, round(brightness * DEVICE_MAX / 255)))


def device_to_brightness(value: int) -> int:
    """Convert the device value (0-1000) to Home Assistant brightness."""
    if value <= 0:
        return 0
    return max(1, min(255, round(value * 255 / DEVICE_MAX)))


class DreameggColourLight(DreameggEntity, LightEntity):
    """The clock's lamp in colour mode, on the device's own 0-1000 scale."""

    entity_description: LightEntityDescription
    _attr_color_mode = ColorMode.HS
    _attr_supported_color_modes = {ColorMode.HS}

    def _status(self, code: str) -> Any:
        """Return the current value of one datapoint."""
        status = getattr(self.device, "status", None)
        return status.get(code) if isinstance(status, dict) else None

    def _hsv(self) -> tuple[int, int, int] | None:
        """Return the lamp's last reported colour."""
        return parse_colour_data(self._status(DP_COLOUR_DATA))

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the lamp is on."""
        value = self._status(DP_SWITCH_LED)
        return value if isinstance(value, bool) else None

    @property
    @override
    def brightness(self) -> int | None:
        """Return the brightness on Home Assistant's 0-255 scale."""
        hsv = self._hsv()
        return None if hsv is None else device_to_brightness(hsv[2])

    @property
    @override
    def hs_color(self) -> tuple[float, float] | None:
        """Return hue (0-360) and saturation (0-100)."""
        hsv = self._hsv()
        if hsv is None:
            return None
        return (float(hsv[0]), hsv[1] * 100 / DEVICE_MAX)

    @callback
    @override
    def _handle_tuya_update(
        self,
        updated_status_properties: list[str] | None,
        dp_timestamps: dict[str, int] | None,
    ) -> None:
        """Write state when one of the lamp's datapoints changes."""
        if updated_status_properties is None or _WATCHED_DATAPOINTS.intersection(
            updated_status_properties
        ):
            self.async_write_ha_state()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lamp on in colour mode, optionally changing its colour."""
        hue, saturation, value = self._hsv() or DEFAULT_HSV
        if (hs_color := kwargs.get(ATTR_HS_COLOR)) is not None:
            hue = max(0, min(360, round(hs_color[0])))
            saturation = max(0, min(DEVICE_MAX, round(hs_color[1] * DEVICE_MAX / 100)))
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            value = brightness_to_device(brightness)
        value = max(DEVICE_MIN_VALUE, value)

        commands: list[dict[str, Any]] = []
        if self._status(DP_SWITCH_LED) is not True:
            commands.append({"code": DP_SWITCH_LED, "value": True})
        if self._status(DP_WORK_MODE) != WORK_MODE_COLOUR:
            commands.append({"code": DP_WORK_MODE, "value": WORK_MODE_COLOUR})
        commands.append(
            {
                "code": DP_COLOUR_DATA,
                "value": json.dumps({"h": hue, "s": saturation, "v": value}),
            }
        )
        await self._async_send_commands(commands)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lamp off."""
        await self._async_send_commands([{"code": DP_SWITCH_LED, "value": False}])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DreameggConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Dreamegg colour lights."""
    runtime: DreameggRuntimeData = entry.runtime_data
    seen: set[str] = set()

    @callback
    def async_discover(device_ids: Iterable[str]) -> None:
        entities: list[DreameggColourLight] = []
        for device_id in device_ids:
            device = runtime.device(device_id)
            if (
                device is None
                or device_id in seen
                or not is_supported_device(device)
                or not has_writable_datapoint(device, DP_COLOUR_DATA)
                or not has_writable_datapoint(device, DP_SWITCH_LED)
            ):
                continue
            seen.add(device_id)
            entities.append(DreameggColourLight(runtime, device_id, COLOUR_LIGHT))
        if entities:
            async_add_entities(entities)

    async_discover(runtime.device_map)
    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover)
    )
