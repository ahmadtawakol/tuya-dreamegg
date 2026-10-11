"""Tests for the local white-light transport."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.tuya_dreamegg.capture import RawDpCapture
from custom_components.tuya_dreamegg.light_transport import (
    LampStatus,
    LocalLightTransport,
    parse_lamp_status,
)
from custom_components.tuya_dreamegg.music_transport import LocalMusicTransport

from .helpers import dreamegg_device

SCAN = "custom_components.tuya_dreamegg.music_transport.scanner.devices"
DEVICE = "custom_components.tuya_dreamegg.music_transport.tinytuya.Device"
NO_WAIT = patch(
    "custom_components.tuya_dreamegg.light_transport.READBACK_RETRY_DELAY", 0
)
COLOUR = {"3": True, "4": "color", "5": "002403700239", "6": 569, "7": 500}
WHITE = {"3": True, "4": "mystery", "5": "002403700239", "6": 400, "7": 0}


def _transports(hass):
    device = dreamegg_device()
    device.local_key = "test-key-one1234"
    capture = RawDpCapture(hass)
    capture.attach(SimpleNamespace(device_map={device.id: device}, mq=None))
    provider = Mock(return_value=device)
    music = LocalMusicTransport(hass, capture, provider)
    light = LocalLightTransport(hass, capture, provider, music)
    return light, music, device, capture


def _lan(device, *clocks):
    return (
        patch(SCAN, return_value={device.id: {"ip": "192.0.2.2", "version": "3.5"}}),
        patch(DEVICE, side_effect=list(clocks)),
    )


def test_lamp_status_ignores_out_of_range_and_wrongly_typed_values() -> None:
    """Only values the clock could really hold are reported."""
    assert parse_lamp_status({"dps": COLOUR}) == LampStatus(
        switch_led=True,
        light_mode="color",
        colour_data="002403700239",
        brightness=569,
        colour_temperature=500,
    )
    assert parse_lamp_status({"dps": {"6": True, "7": 1001, "4": ""}}) == LampStatus()
    assert parse_lamp_status({"Error": "timeout"}) is None


async def test_white_write_is_one_message_confirmed_by_readback(hass) -> None:
    """Only the requested lamp datapoints are sent, in a single control message."""
    light, _, device, capture = _transports(hass)
    clock = Mock()
    clock.status.return_value = {"dps": WHITE}
    scan, device_class = _lan(device, clock)
    with scan, device_class:
        status = await light.async_write(
            device.id, switch_on=True, brightness=400, colour_temperature=0
        )
    assert status.brightness == 400
    assert status.colour_temperature == 0
    clock.set_multiple_values.assert_called_once_with({"3": True, "7": 0, "6": 400})
    clock.set_value.assert_not_called()
    clock.close.assert_called_once_with()
    assert capture.latest_value(device.id, 4) == "mystery"
    assert capture.latest_value(device.id, 6) == 400
    assert capture.latest_value(device.id, 7) == 0
    assert capture.snapshot()[device.id][-1]["source"] == "local_readback"


async def test_single_value_write_and_rounding_tolerance(hass) -> None:
    """A clock that rounds within one percent still confirms the write."""
    light, _, device, _ = _transports(hass)
    clock = Mock()
    clock.status.return_value = {"dps": WHITE | {"6": 405}}
    scan, device_class = _lan(device, clock)
    with scan, device_class:
        status = await light.async_write(device.id, brightness=400)
    assert status.brightness == 405
    clock.set_value.assert_called_once_with(6, 400)
    clock.set_multiple_values.assert_not_called()


async def test_unconfirmed_white_write_fails_and_keeps_reported_state(hass) -> None:
    """A write the clock ignores is an error, and no requested value is recorded."""
    light, _, device, capture = _transports(hass)
    clock = Mock()
    clock.status.return_value = {"dps": COLOUR}
    scan, device_class = _lan(device, clock)
    with (
        scan,
        device_class,
        NO_WAIT,
        pytest.raises(HomeAssistantError, match="DP 7 requested 0, reported 500"),
    ):
        await light.async_write(device.id, colour_temperature=0)
    assert clock.status.call_count == 2
    assert capture.latest_value(device.id, 7) is None
    clock.close.assert_called_once_with()


async def test_write_waits_once_for_the_light_mode_to_leave_colour(hass) -> None:
    """A mode that changes just after the acknowledgement is still picked up."""
    light, _, device, _ = _transports(hass)
    clock = Mock()
    clock.status.side_effect = [
        {"dps": WHITE | {"4": "color"}},
        {"dps": WHITE},
    ]
    scan, device_class = _lan(device, clock)
    with scan, device_class, NO_WAIT:
        status = await light.async_write(
            device.id,
            brightness=400,
            colour_temperature=0,
            leaving_modes=frozenset({"color"}),
        )
    assert status.light_mode == "mystery"


async def test_read_requests_hidden_datapoints_and_never_writes(hass) -> None:
    """A status reply without the lamp datapoints is followed by a targeted query."""
    light, _, device, _ = _transports(hass)
    clock = Mock()
    clock.status.side_effect = [{"dps": {"1": False}}, {"dps": COLOUR}]
    scan, device_class = _lan(device, clock)
    with scan, device_class:
        status = await light.async_read(device.id)
    assert status.light_mode == "color"
    clock.set_dpsUsed.assert_called_once_with(
        {"1": None, "3": None, "4": None, "5": None, "6": None, "7": None}
    )
    clock.set_value.assert_not_called()
    clock.set_multiple_values.assert_not_called()


async def test_light_and_music_share_one_discovered_endpoint(hass) -> None:
    """Both transports use the same LAN endpoint cache and session lock."""
    light, music, device, _ = _transports(hass)
    music_clock = Mock()
    music_clock.status.return_value = {"dps": {"10": "18"}}
    light_clock = Mock()
    light_clock.status.return_value = {"dps": COLOUR}
    scan, device_class = _lan(device, music_clock, light_clock)
    with scan as scanned, device_class:
        assert await music.async_read(device.id) == "18"
        assert (await light.async_read(device.id)).brightness == 569
    assert scanned.call_count == 1
    assert light._link.operation_lock is music.operation_lock


async def test_invalid_requests_never_reach_the_clock(hass) -> None:
    """Out-of-range values and odd mode strings are refused before any session."""
    light, _, device, _ = _transports(hass)
    with patch(DEVICE) as device_class:
        for request in (
            {"brightness": 9},
            {"brightness": 1001},
            {"colour_temperature": -1},
            {"light_mode": "White Light"},
        ):
            with pytest.raises(HomeAssistantError, match="Unsupported"):
                await light.async_write(device.id, **request)
    device_class.assert_not_called()


async def test_test_reports_before_and_after_then_restores_the_colour(hass) -> None:
    """A lamp showing a colour is put back by rewriting that exact colour."""
    light, _, device, capture = _transports(hass)
    clock = Mock()
    clock.status.side_effect = [{"dps": COLOUR}, {"dps": WHITE}, {"dps": COLOUR}]
    scan, device_class = _lan(device, clock)
    with scan, device_class:
        result = await light.async_test(device.id, brightness=400, colour_temperature=0)
    assert result["before"]["light_mode"] == "color"
    assert result["after"]["light_mode"] == "mystery"
    assert result["written"] == {"7": 0, "6": 400}
    assert result["write_verified"] is True
    assert result["restore_verified"] is True
    assert result["restored"] == result["before"]
    assert [call.args for call in clock.set_multiple_values.call_args_list] == [
        ({"7": 0, "6": 400},),
        ({"7": 500, "6": 569},),
    ]
    assert [call.args for call in clock.set_value.call_args_list] == [
        (5, "002403700239"),
        (4, "color"),
        (6, 569),
        (3, True),
    ]
    assert capture.latest_value(device.id, 4) == "color"
    clock.close.assert_called_once_with()


async def test_test_restores_previous_white_values_and_survives_errors(hass) -> None:
    """A lamp not showing a colour gets its changed values back, even on error."""
    light, _, device, _ = _transports(hass)
    clock = Mock()
    clock.status.side_effect = [
        {"dps": WHITE},
        OSError("test readback failure"),
        {"dps": WHITE},
    ]
    scan, device_class = _lan(device, clock)
    with scan, device_class:
        result = await light.async_test(device.id, colour_temperature=900)
    assert result["restore_verified"] is True
    assert result["error_type"] == "OSError"
    assert [call.args for call in clock.set_value.call_args_list] == [
        (7, 900),
        (5, "002403700239"),
        (4, "mystery"),
        (6, 400),
        (3, True),
    ]
    clock.set_multiple_values.assert_called_once_with({"7": 0, "6": 400})


async def test_probe_and_unrestored_test(hass) -> None:
    """A probe only reads; restore can be switched off for a test."""
    light, _, device, _ = _transports(hass)
    probe = Mock()
    probe.status.return_value = {"dps": COLOUR}
    kept = Mock()
    kept.status.side_effect = [{"dps": COLOUR}, {"dps": COLOUR | {"4": "white"}}]
    scan, device_class = _lan(device, probe, kept)
    with scan, device_class:
        assert await light.async_test(device.id) == {
            "before": parse_lamp_status({"dps": COLOUR}).as_dict()
        }
        result = await light.async_test(device.id, light_mode="white", restore=False)
    probe.set_value.assert_not_called()
    kept.set_value.assert_called_once_with(4, "white")
    assert result["write_verified"] is True
    assert "restored" not in result


async def test_final_mode_wait_read_must_still_confirm_the_request(hass) -> None:
    """A mode change cannot hide drift in the final brightness readback."""
    light, _, device, capture = _transports(hass)
    clock = Mock()
    clock.status.side_effect = [
        {"dps": WHITE | {"4": "color"}},
        {"dps": WHITE | {"6": 700}},
    ]
    scan, device_class = _lan(device, clock)
    with (
        scan,
        device_class,
        NO_WAIT,
        pytest.raises(HomeAssistantError, match="DP 6 requested 400, reported 700"),
    ):
        await light.async_write(
            device.id,
            brightness=400,
            colour_temperature=0,
            leaving_modes=frozenset({"color"}),
        )
    assert capture.latest_value(device.id, 6) is None


@pytest.mark.parametrize("missing_dp", ["3", "4", "5", "6", "7"])
async def test_restore_enabled_test_refuses_incomplete_baseline(
    hass, missing_dp
) -> None:
    """No field is changed if the diagnostic cannot restore the entire lamp."""
    light, _, device, _ = _transports(hass)
    clock = Mock()
    clock.status.return_value = {
        "dps": {dp: value for dp, value in COLOUR.items() if dp != missing_dp}
    }
    scan, device_class = _lan(device, clock)
    with scan, device_class:
        result = await light.async_test(device.id, colour_temperature=0)
    assert result["write_attempted"] is False
    assert int(missing_dp) in result["missing_baseline_dp_ids"]
    clock.set_value.assert_not_called()
    clock.set_multiple_values.assert_not_called()


async def test_restore_checks_active_mode_not_only_cached_colour(hass) -> None:
    """Unchanged stored RGB cannot falsely prove that white mode was restored."""
    light, _, device, _ = _transports(hass)
    clock = Mock()
    wrong_mode = COLOUR | {"4": "mystery"}
    clock.status.side_effect = [
        {"dps": COLOUR},
        {"dps": WHITE},
        {"dps": wrong_mode},
        {"dps": wrong_mode},
    ]
    scan, device_class = _lan(device, clock)
    with scan, device_class, NO_WAIT:
        result = await light.async_test(device.id, colour_temperature=0)
    assert result["restore_verified"] is False
    assert result["unrestored"] == {"4": "mystery"}


async def test_restore_preserves_original_off_switch(hass) -> None:
    """A mode/colour rewrite cannot leave an originally off lamp switched on."""
    light, _, device, _ = _transports(hass)
    clock = Mock()
    off_baseline = COLOUR | {"3": False}
    clock.status.side_effect = [
        {"dps": off_baseline},
        {"dps": WHITE},
        {"dps": off_baseline},
    ]
    scan, device_class = _lan(device, clock)
    with scan, device_class:
        result = await light.async_test(device.id, colour_temperature=0)
    assert clock.set_value.call_args_list[-1].args == (3, False)
    assert result["restore_verified"] is True
