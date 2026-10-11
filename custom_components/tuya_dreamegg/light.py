"""Colour and white light for Dreamegg Sunrise Controls.

The official Tuya integration exposes the clock's lamp, but the device
specification carries no ranges for ``colour_data``. Home Assistant therefore
falls back to the legacy 0-255 scale, while the clock uses 0-1000 for both
saturation and value. Through the official entity the lamp can only reach about
a quarter of its brightness and saturation, and its reported state is
mis-scaled. This entity talks to the same datapoints on the correct scale.

The lamp's white light is not in the official specification at all. Its
brightness (DP 6) and colour temperature (DP 7) are written over the LAN and
read from the clock's raw reports; see ``light_transport``.
"""

import json
import logging
from collections.abc import Iterable
from math import isfinite
from typing import Any, override

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
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
    TUYA_RAW_DP_UPDATE,
    WORK_MODE_COLOUR,
)
from .entity import DreameggEntity
from .helpers import has_writable_datapoint, is_supported_device
from .light_transport import (
    BRIGHTNESS_DP_ID,
    COLOUR_TEMPERATURE_DP_ID,
    LIGHT_MODE_COLOUR,
    LIGHT_MODE_DP_ID,
)

_LOGGER = logging.getLogger(__name__)

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

# Nominal ends of the white light. The clock only reports colour temperature as
# 0-1000; the Kelvin range has not been measured, so these are a
# conventional warm-to-cool span, with 0 taken as the warm end as on other Tuya
# lamps. Neither the span nor the direction has been measured on the clock.
WARMEST_KELVIN = 2700
COOLEST_KELVIN = 6500

# Value DP 4 holds while the white light is showing. Not identified yet: no
# capture has caught the clock in that mode. While it is None the integration
# writes only brightness and colour temperature and relies on the clock
# changing mode by itself, as it does to "color" after a colour write.
WHITE_LIGHT_MODE: str | None = None
# Modes DP 4 has been seen to report that are not the white light: a solid
# colour, and three values that appeared with no command sent.
NON_WHITE_LIGHT_MODES = frozenset({LIGHT_MODE_COLOUR, "change", "breath", "sunrise"})

_WATCHED_DATAPOINTS = frozenset({DP_SWITCH_LED, DP_COLOUR_DATA, DP_WORK_MODE})
_WATCHED_RAW_DATAPOINTS = frozenset(
    {LIGHT_MODE_DP_ID, BRIGHTNESS_DP_ID, COLOUR_TEMPERATURE_DP_ID}
)


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


def kelvin_to_device(kelvin: int) -> int:
    """Convert a colour temperature to the clock's 0-1000 value."""
    span = COOLEST_KELVIN - WARMEST_KELVIN
    value = round((kelvin - WARMEST_KELVIN) * DEVICE_MAX / span)
    return max(0, min(DEVICE_MAX, value))


def device_to_kelvin(value: int) -> int:
    """Convert the clock's 0-1000 value to a colour temperature."""
    span = COOLEST_KELVIN - WARMEST_KELVIN
    return round(WARMEST_KELVIN + max(0, min(DEVICE_MAX, value)) * span / DEVICE_MAX)


class DreameggColourLight(DreameggEntity, LightEntity):
    """The clock's lamp, in colour or white, on the device's own 0-1000 scale."""

    entity_description: LightEntityDescription
    _attr_supported_color_modes = {ColorMode.HS, ColorMode.COLOR_TEMP}
    _attr_min_color_temp_kelvin = WARMEST_KELVIN
    _attr_max_color_temp_kelvin = COOLEST_KELVIN

    # Whether the lamp is showing its white light. Set by a confirmed local
    # white write and by the clock's own light-mode reports; a colour write
    # clears it. It starts False because the mode is only known once reported.
    _white = False
    _warned_mode: str | None = None

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

    def _raw_scaled(self, dp_id: int) -> int | None:
        """Return the latest 0-1000 value the clock reported for a raw datapoint."""
        value = self._runtime.capture.latest_value(self._device_id, dp_id)
        if isinstance(value, str) and value.isdecimal():
            value = int(value)
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 0 <= value <= DEVICE_MAX else None

    def _light_mode(self) -> str | None:
        """Return the light mode the clock last reported on DP 4."""
        value = self._runtime.capture.latest_value(self._device_id, LIGHT_MODE_DP_ID)
        return value if isinstance(value, str) and value else None

    @property
    @override
    def color_mode(self) -> ColorMode:
        """Return whether the lamp is showing white or a colour."""
        return ColorMode.COLOR_TEMP if self._white else ColorMode.HS

    @property
    @override
    def brightness(self) -> int | None:
        """Return the brightness on Home Assistant's 0-255 scale."""
        if self._white and (value := self._raw_scaled(BRIGHTNESS_DP_ID)) is not None:
            return device_to_brightness(value)
        hsv = self._hsv()
        return None if hsv is None else device_to_brightness(hsv[2])

    @property
    @override
    def color_temp_kelvin(self) -> int | None:
        """Return the white light's colour temperature."""
        if not self._white:
            return None
        value = self._raw_scaled(COLOUR_TEMPERATURE_DP_ID)
        return None if value is None else device_to_kelvin(value)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the clock's own light mode, which has no other entity state."""
        return {"light_mode": self._light_mode()}

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
    async def async_added_to_hass(self) -> None:
        """Also follow the raw reports that carry the white light's state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{TUYA_RAW_DP_UPDATE}_{self._device_id}",
                self._handle_raw_update,
            )
        )

    def _follow_light_mode(self, mode: str | None) -> None:
        """Track white versus colour from a light mode the clock reported."""
        if mode is None:
            return
        if WHITE_LIGHT_MODE is not None and mode == WHITE_LIGHT_MODE:
            self._white = True
        elif mode in NON_WHITE_LIGHT_MODES:
            self._white = False

    @callback
    def _handle_raw_update(self, dp_id: int) -> None:
        """Write state when the clock reports a white-light datapoint."""
        if dp_id not in _WATCHED_RAW_DATAPOINTS:
            return
        if dp_id == LIGHT_MODE_DP_ID:
            self._follow_light_mode(self._light_mode())
        self.async_write_ha_state()

    async def _async_turn_on_white(
        self, kelvin: int | None, brightness: int | None
    ) -> None:
        """Set the white light over the LAN and follow what the clock confirms."""
        status = await self._runtime.light.async_write(
            self._device_id,
            switch_on=self._status(DP_SWITCH_LED) is not True,
            brightness=None if brightness is None else brightness_to_device(brightness),
            colour_temperature=None if kelvin is None else kelvin_to_device(kelvin),
            light_mode=WHITE_LIGHT_MODE,
            leaving_modes=NON_WHITE_LIGHT_MODES,
        )
        self._white = True
        self._follow_light_mode(status.light_mode)
        if not self._white and self._warned_mode != status.light_mode:
            self._warned_mode = status.light_mode
            _LOGGER.warning(
                "%s stored the white light settings but still reports light mode "
                "%r, so it is probably not showing white. Use the 'Test light "
                "transport' action to find the white light mode value",
                self.entity_id,
                status.light_mode,
            )
        self.async_write_ha_state()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lamp on, in white for a colour temperature, else in colour.

        A call without a colour keeps whichever of the two the lamp is showing.
        """
        hs_color = kwargs.get(ATTR_HS_COLOR)
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        if kelvin is not None or (self._white and hs_color is None):
            await self._async_turn_on_white(kelvin, kwargs.get(ATTR_BRIGHTNESS))
            return

        hue, saturation, value = self._hsv() or DEFAULT_HSV
        if hs_color is not None:
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
        if self._white:
            self._white = False
            self.async_write_ha_state()

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
