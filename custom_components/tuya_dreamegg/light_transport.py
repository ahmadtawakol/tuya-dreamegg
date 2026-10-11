"""Local transport for the lamp datapoints the Tuya cloud session leaves out.

The official Tuya specification for the Sunrise 1+ advertises only
``switch_led``, ``work_mode`` and ``colour_data`` for the lamp. The clock also
has a white light, driven by two datapoints the web panel names
``bright_value`` (DP 6) and ``temp_value`` (DP 7), and it reports its real
light mode on DP 4. None of the three has a cloud command code, so they are
written over the LAN, the same way as Music DP 10, and every write is confirmed
by reading the clock back.
"""

import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import sleep
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .capture import RawDpCapture
from .music_transport import LocalMusicTransport

SWITCH_LED_DP_ID = 3
LIGHT_MODE_DP_ID = 4
COLOUR_DATA_DP_ID = 5
BRIGHTNESS_DP_ID = 6
COLOUR_TEMPERATURE_DP_ID = 7
LAMP_DP_IDS = (
    SWITCH_LED_DP_ID,
    LIGHT_MODE_DP_ID,
    COLOUR_DATA_DP_ID,
    BRIGHTNESS_DP_ID,
    COLOUR_TEMPERATURE_DP_ID,
)

# Light mode the clock reports after a colour_data write.
LIGHT_MODE_COLOUR = "color"

# Scale used by the clock for brightness and colour temperature.
DEVICE_MAX = 1000
# Lowest brightness the clock has been seen to accept and report.
DEVICE_MIN_BRIGHTNESS = 10
# A readback this close to the request counts as confirmed, in case the clock
# rounds. A write the clock ignored still fails unless nothing was changing.
READBACK_TOLERANCE = 10
# One short wait before a second readback, for a clock that applies a change
# just after acknowledging it.
READBACK_RETRY_DELAY = 0.3

LIGHT_MODE_PATTERN = re.compile(r"^[a-z_]{1,24}$")

_KNOWN_CODES = {
    BRIGHTNESS_DP_ID: "bright_value",
    COLOUR_TEMPERATURE_DP_ID: "temp_value",
}


@dataclass(frozen=True, slots=True)
class LampStatus:
    """What the clock itself returned for its lamp datapoints."""

    switch_led: bool | None = None
    light_mode: str | None = None
    colour_data: str | None = None
    brightness: int | None = None
    colour_temperature: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the status as plain response data."""
        return asdict(self)

    def value(self, dp_id: int) -> Any:
        """Return the value of one lamp datapoint."""
        return {
            SWITCH_LED_DP_ID: self.switch_led,
            LIGHT_MODE_DP_ID: self.light_mode,
            COLOUR_DATA_DP_ID: self.colour_data,
            BRIGHTNESS_DP_ID: self.brightness,
            COLOUR_TEMPERATURE_DP_ID: self.colour_temperature,
        }[dp_id]


def parse_lamp_status(status: Any) -> LampStatus | None:
    """Return the lamp datapoints from a LAN status response, if it has any."""
    if not isinstance(status, dict) or not isinstance(status.get("dps"), dict):
        return None
    dps = status["dps"]

    def scaled(dp_id: int) -> int | None:
        value = dps.get(str(dp_id))
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 0 <= value <= DEVICE_MAX else None

    def text(dp_id: int) -> str | None:
        value = dps.get(str(dp_id))
        return value if isinstance(value, str) and value else None

    switch_led = dps.get(str(SWITCH_LED_DP_ID))
    return LampStatus(
        switch_led=switch_led if isinstance(switch_led, bool) else None,
        light_mode=text(LIGHT_MODE_DP_ID),
        colour_data=text(COLOUR_DATA_DP_ID),
        brightness=scaled(BRIGHTNESS_DP_ID),
        colour_temperature=scaled(COLOUR_TEMPERATURE_DP_ID),
    )


def _confirmed(requested: Any, reported: Any) -> bool:
    """Return whether the clock's readback matches what was written."""
    if isinstance(requested, bool) or isinstance(requested, str):
        return reported == requested
    if isinstance(reported, bool) or not isinstance(reported, int):
        return False
    return abs(reported - requested) <= READBACK_TOLERANCE


def _unconfirmed(values: dict[int, Any], status: LampStatus) -> dict[int, Any]:
    """Return the written datapoints the clock did not read back as requested."""
    return {
        dp_id: status.value(dp_id)
        for dp_id, requested in values.items()
        if not _confirmed(requested, status.value(dp_id))
    }


class LocalLightTransport:
    """Read and write the hidden lamp datapoints with device-confirmed readback."""

    def __init__(
        self,
        hass: HomeAssistant,
        capture: RawDpCapture,
        device_provider: Callable[[str], Any | None],
        link: LocalMusicTransport,
    ) -> None:
        """Share the Music transport's LAN session factory and lock."""
        self._hass = hass
        self._capture = capture
        self._device_provider = device_provider
        self._link = link

    async def async_read(self, device_id: str) -> LampStatus:
        """Read the lamp datapoints without changing anything."""
        return await self._async_run(device_id, self._read_only)

    async def async_write(
        self,
        device_id: str,
        *,
        switch_on: bool = False,
        brightness: int | None = None,
        colour_temperature: int | None = None,
        light_mode: str | None = None,
        leaving_modes: frozenset[str] = frozenset(),
    ) -> LampStatus:
        """Write white-light datapoints and return the confirmed lamp status.

        ``leaving_modes`` are light modes the write is expected to end. If the
        clock still reports one of them it gets one more moment to switch.
        """
        values = _requested_values(
            switch_on=switch_on,
            brightness=brightness,
            colour_temperature=colour_temperature,
            light_mode=light_mode,
        )
        if not values:
            return await self.async_read(device_id)
        return await self._async_run(
            device_id, lambda clock: self._write(clock, values, leaving_modes)
        )

    async def async_test(
        self,
        device_id: str,
        *,
        brightness: int | None = None,
        colour_temperature: int | None = None,
        light_mode: str | None = None,
        restore: bool = True,
    ) -> dict[str, Any]:
        """Probe the lamp, or write the given values and report what changed.

        Unlike ``async_write`` this never raises for an unconfirmed write: the
        point is to return exactly what the clock reported before and after.
        """
        values = _requested_values(
            switch_on=False,
            brightness=brightness,
            colour_temperature=colour_temperature,
            light_mode=light_mode,
        )
        async with self._link.operation_lock:
            device = self._link_device(device_id)
            result, statuses = await self._hass.async_add_executor_job(
                self._test, device, values, restore
            )
        for status in statuses:
            self._record(device_id, status)
        return result

    def _link_device(self, device_id: str) -> Any:
        """Return the current official Tuya device object."""
        device = self._device_provider(device_id)
        if device is None:
            raise HomeAssistantError("The official Tuya integration is unavailable")
        return device

    async def _async_run(self, device_id: str, operation: Any) -> LampStatus:
        """Run one blocking lamp operation in a single LAN session."""
        async with self._link.operation_lock:
            device = self._link_device(device_id)
            status = await self._hass.async_add_executor_job(
                self._session, device, operation
            )
        self._record(device_id, status)
        return status

    def _record(self, device_id: str, status: LampStatus) -> None:
        """Publish values the clock itself returned, never requested ones."""
        for dp_id in (LIGHT_MODE_DP_ID, BRIGHTNESS_DP_ID, COLOUR_TEMPERATURE_DP_ID):
            if (value := status.value(dp_id)) is not None:
                self._capture.record_local(
                    device_id, dp_id, value, _KNOWN_CODES.get(dp_id)
                )

    def _session(self, device: Any, operation: Any) -> LampStatus:
        """Open a session, run the operation, and always close the session."""
        clock = None
        try:
            clock = self._link.open_clock(device)
            return operation(clock)
        except HomeAssistantError:
            self._link.forget_clock(device.id)
            raise
        except Exception as error:
            self._link.forget_clock(device.id)
            raise HomeAssistantError(
                "Unable to contact the clock on the local network"
            ) from error
        finally:
            if clock is not None:
                clock.close()

    @staticmethod
    def _read_only(clock: Any, required: frozenset[int] = frozenset()) -> LampStatus:
        """Read the lamp, asking for its datapoints by ID if they are left out."""
        status = parse_lamp_status(clock.status())
        if (
            status is None
            or status.brightness is None
            or any(status.value(dp_id) is None for dp_id in required)
        ):
            clock.set_dpsUsed({"1": None} | {str(dp_id): None for dp_id in LAMP_DP_IDS})
            status = parse_lamp_status(clock.status())
        if status is None:
            raise HomeAssistantError("The clock did not return its lamp datapoints")
        return status

    def _read_after_write(
        self, clock: Any, values: dict[int, Any]
    ) -> tuple[LampStatus, dict[int, Any]]:
        """Read back a write, allowing the clock one moment to apply it."""
        status = self._read_only(clock)
        if unconfirmed := _unconfirmed(values, status):
            sleep(READBACK_RETRY_DELAY)
            status = self._read_only(clock)
            unconfirmed = _unconfirmed(values, status)
        return status, unconfirmed

    def _write(
        self, clock: Any, values: dict[int, Any], leaving_modes: frozenset[str]
    ) -> LampStatus:
        """Write only the given lamp datapoints and require their readback."""
        _send(clock, values)
        status, unconfirmed = self._read_after_write(clock, values)
        if not unconfirmed and status.light_mode in leaving_modes:
            sleep(READBACK_RETRY_DELAY)
            status = self._read_only(clock)
            unconfirmed = _unconfirmed(values, status)
        if unconfirmed:
            details = ", ".join(
                f"DP {dp_id} requested {values[dp_id]!r}, reported {reported!r}"
                for dp_id, reported in unconfirmed.items()
            )
            raise HomeAssistantError(
                f"The clock did not confirm the lamp change ({details})"
            )
        return status

    def _test(
        self, device: Any, values: dict[int, Any], restore: bool
    ) -> tuple[dict[str, Any], list[LampStatus]]:
        """Report the lamp before and after a bounded write, then put it back."""
        result: dict[str, Any] = {}
        statuses: list[LampStatus] = []
        clock = None
        try:
            clock = self._link.open_clock(device)
            before = self._read_only(
                clock, frozenset(LAMP_DP_IDS) if restore and values else frozenset()
            )
            statuses.append(before)
            result["before"] = before.as_dict()
            if not values:
                return result, statuses
            if restore:
                missing = [
                    dp_id for dp_id in LAMP_DP_IDS if before.value(dp_id) is None
                ]
                if missing:
                    return result | {
                        "write_attempted": False,
                        "write_verified": False,
                        "missing_baseline_dp_ids": missing,
                        "error_message": "Complete lamp baseline required to restore",
                    }, statuses
            result["written"] = {str(dp_id): value for dp_id, value in values.items()}
            result["write_attempted"] = True
            if restore:
                result["restore_verified"] = False
            try:
                _send(clock, values)
                after, unconfirmed = self._read_after_write(clock, values)
                statuses.append(after)
                result["after"] = after.as_dict()
                result["write_verified"] = not unconfirmed
            finally:
                if restore and (baseline := _restore_values(before, values)):
                    # Restore hidden preferences, the exact RGB preference, then
                    # the original active mode/brightness. Switch state is last
                    # because a colour or mode write may turn an off lamp on.
                    _send(
                        clock,
                        {
                            COLOUR_TEMPERATURE_DP_ID: baseline[
                                COLOUR_TEMPERATURE_DP_ID
                            ],
                            BRIGHTNESS_DP_ID: baseline[BRIGHTNESS_DP_ID],
                        },
                    )
                    _send(clock, {COLOUR_DATA_DP_ID: baseline[COLOUR_DATA_DP_ID]})
                    _send(clock, {LIGHT_MODE_DP_ID: baseline[LIGHT_MODE_DP_ID]})
                    _send(clock, {BRIGHTNESS_DP_ID: baseline[BRIGHTNESS_DP_ID]})
                    _send(clock, {SWITCH_LED_DP_ID: baseline[SWITCH_LED_DP_ID]})
                    restored, unrestored = self._read_after_write(clock, baseline)
                    statuses.append(restored)
                    result["restored"] = restored.as_dict()
                    result["restore_verified"] = not unrestored
                    if unrestored:
                        result["unrestored"] = {
                            str(dp_id): reported
                            for dp_id, reported in unrestored.items()
                        }
            return result, statuses
        except Exception as error:
            self._link.forget_clock(device.id)
            result["error_type"] = type(error).__name__
            if isinstance(error, HomeAssistantError):
                result["error_message"] = str(error)
            return result, statuses
        finally:
            if clock is not None:
                clock.close()


def _requested_values(
    *,
    switch_on: bool,
    brightness: int | None,
    colour_temperature: int | None,
    light_mode: str | None,
) -> dict[int, Any]:
    """Validate a white-light request and return it keyed by datapoint ID."""
    values: dict[int, Any] = {}
    if switch_on:
        values[SWITCH_LED_DP_ID] = True
    if light_mode is not None:
        if not LIGHT_MODE_PATTERN.fullmatch(light_mode):
            raise HomeAssistantError("Unsupported Dreamegg light mode value")
        values[LIGHT_MODE_DP_ID] = light_mode
    if colour_temperature is not None:
        if isinstance(colour_temperature, bool) or not (
            0 <= colour_temperature <= DEVICE_MAX
        ):
            raise HomeAssistantError("Unsupported Dreamegg colour temperature")
        values[COLOUR_TEMPERATURE_DP_ID] = int(colour_temperature)
    if brightness is not None:
        if isinstance(brightness, bool) or not (
            DEVICE_MIN_BRIGHTNESS <= brightness <= DEVICE_MAX
        ):
            raise HomeAssistantError("Unsupported Dreamegg brightness")
        values[BRIGHTNESS_DP_ID] = int(brightness)
    return values


def _restore_values(before: LampStatus, written: dict[int, Any]) -> dict[int, Any]:
    """Return the write that puts the lamp back as a test found it.

    Preserve the original active mode and switch state as well as the stored
    colour, brightness and temperature. Stored colour alone cannot establish
    that the lamp has returned from white to colour mode.
    """
    if not written:
        return {}
    return {dp_id: before.value(dp_id) for dp_id in LAMP_DP_IDS}


def _send(clock: Any, values: dict[int, Any]) -> None:
    """Send one control message containing only the given datapoints."""
    if len(values) == 1:
        ((dp_id, value),) = values.items()
        clock.set_value(dp_id, value)
    else:
        clock.set_multiple_values(
            {str(dp_id): value for dp_id, value in values.items()}
        )
