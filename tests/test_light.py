"""Tests for the Dreamegg colour light."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from homeassistant.components.light import ColorMode
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_dreamegg import DreameggRuntimeData
from custom_components.tuya_dreamegg import light as light_platform
from custom_components.tuya_dreamegg.const import CONF_TUYA_ENTRY_ID, DOMAIN
from custom_components.tuya_dreamegg.light import (
    brightness_to_device,
    device_to_brightness,
    device_to_kelvin,
    kelvin_to_device,
    parse_colour_data,
)
from custom_components.tuya_dreamegg.light_transport import LampStatus

from .helpers import OFFICIAL_ENTRY_ID, dreamegg_device, official_entry


def _lamp_device(**status):
    """Return a Dreamegg that advertises the lamp datapoints."""
    device = dreamegg_device()
    for code in ("switch_led", "colour_data"):
        device.function[code] = SimpleNamespace(values="{}")
    device.status.update(
        {
            "switch_led": True,
            "colour_data": '{"h":300,"s":1000,"v":210}',
            "work_mode": "scene",
        }
    )
    device.status.update(status)
    return device


async def _setup(hass, device):
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry",
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    entry.runtime_data = DreameggRuntimeData(hass, official.entry_id)
    add_entities = Mock()
    await light_platform.async_setup_entry(hass, entry, add_entities)
    return add_entities, manager


def test_scale_helpers() -> None:
    """Brightness and colour reports use the clock's 0-1000 scale."""
    assert parse_colour_data('{"h":300,"s":1000,"v":210}') == (300, 1000, 210)
    assert parse_colour_data({"h": 190, "s": 1000, "v": 792}) == (190, 1000, 792)
    assert parse_colour_data("not json") is None
    assert parse_colour_data('{"h":1,"s":2}') is None
    assert parse_colour_data('{"h":NaN,"s":2,"v":3}') is None
    assert brightness_to_device(255) == 1000
    assert brightness_to_device(128) == 502
    assert brightness_to_device(1) == 10
    assert device_to_brightness(1000) == 255
    assert device_to_brightness(792) == 202
    assert device_to_brightness(0) == 0
    assert device_to_brightness(1) == 1
    assert kelvin_to_device(2700) == 0
    assert kelvin_to_device(6500) == 1000
    assert kelvin_to_device(3000) == 79
    assert kelvin_to_device(1500) == 0
    assert kelvin_to_device(9000) == 1000
    assert device_to_kelvin(0) == 2700
    assert device_to_kelvin(1000) == 6500
    assert device_to_kelvin(79) == 3000


async def test_state_is_read_on_device_scale(hass) -> None:
    """Reported state is in range, unlike the official entity's."""
    device = _lamp_device(colour_data='{"h":190,"s":1000,"v":792}')
    add_entities, _ = await _setup(hass, device)

    (light,) = add_entities.call_args.args[0]
    assert light.unique_id == f"{device.id}_colour_light"
    assert light.color_mode is ColorMode.HS
    assert light.supported_color_modes == {ColorMode.HS, ColorMode.COLOR_TEMP}
    assert light.min_color_temp_kelvin == 2700
    assert light.max_color_temp_kelvin == 6500
    assert light.is_on is True
    assert light.brightness == 202
    assert light.hs_color == (190.0, 100.0)
    assert light.color_temp_kelvin is None
    assert light.extra_state_attributes == {"light_mode": None}

    device.status["switch_led"] = False
    assert light.is_on is False


async def test_turn_on_sends_full_scale_colour_in_colour_mode(hass) -> None:
    """Full brightness reaches v=1000 and switches the clock to colour mode."""
    device = _lamp_device(switch_led=False)
    add_entities, manager = await _setup(hass, device)
    (light,) = add_entities.call_args.args[0]
    light.hass = hass

    await light.async_turn_on(brightness=255, hs_color=(29.0, 58.0))

    manager.send_commands.assert_called_once_with(
        device.id,
        [
            {"code": "switch_led", "value": True},
            {"code": "work_mode", "value": "colour"},
            {
                "code": "colour_data",
                "value": json.dumps({"h": 29, "s": 580, "v": 1000}),
            },
        ],
    )


async def test_turn_on_keeps_unspecified_parts_and_skips_redundant_commands(
    hass,
) -> None:
    """A brightness-only call keeps the colour and sends only what changed."""
    device = _lamp_device(work_mode="colour", colour_data='{"h":0,"s":1000,"v":500}')
    add_entities, manager = await _setup(hass, device)
    (light,) = add_entities.call_args.args[0]
    light.hass = hass

    await light.async_turn_on(brightness=13)

    manager.send_commands.assert_called_once_with(
        device.id,
        [{"code": "colour_data", "value": json.dumps({"h": 0, "s": 1000, "v": 51})}],
    )


def _raw_report(manager, device, dp_id, value) -> None:
    """Emit one raw datapoint report from the clock."""
    manager.mq.emit(
        {
            "protocol": 4,
            "data": {
                "devId": device.id,
                "status": [{"dpId": dp_id, "t": 1_700_000_000_000, "value": value}],
            },
        }
    )


async def _white_setup(hass, status: LampStatus, **device_status):
    device = _lamp_device(**device_status)
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry",
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    runtime = entry.runtime_data = DreameggRuntimeData(hass, official.entry_id)
    runtime.capture.attach(manager)
    add_entities = Mock()
    await light_platform.async_setup_entry(hass, entry, add_entities)
    (light,) = add_entities.call_args.args[0]
    light.hass = hass
    light.entity_id = "light.bedroom_dreamegg_colour_light"
    light.async_write_ha_state = Mock()
    await light.async_added_to_hass()

    async def write(device_id, **request):
        for dp_id, value in (
            (4, status.light_mode),
            (6, status.brightness),
            (7, status.colour_temperature),
        ):
            if value is not None:
                runtime.capture.record_local(device_id, dp_id, value)
        return status

    runtime.light.async_write = AsyncMock(side_effect=write)
    return light, device, manager, runtime


async def test_colour_temperature_is_written_locally_and_read_from_the_clock(
    hass,
) -> None:
    """White uses the LAN transport; state is what the clock read back."""
    light, device, manager, runtime = await _white_setup(
        hass,
        LampStatus(
            switch_led=True, light_mode="mystery", brightness=502, colour_temperature=79
        ),
        switch_led=False,
    )

    await light.async_turn_on(color_temp_kelvin=3000, brightness=128)
    await hass.async_block_till_done()

    runtime.light.async_write.assert_awaited_once_with(
        device.id,
        switch_on=True,
        brightness=502,
        colour_temperature=79,
        light_mode=None,
        leaving_modes=light_platform.NON_WHITE_LIGHT_MODES,
    )
    manager.send_commands.assert_not_called()
    assert light.color_mode is ColorMode.COLOR_TEMP
    assert light.color_temp_kelvin == 3000
    assert light.brightness == 128
    assert light.extra_state_attributes == {"light_mode": "mystery"}


async def test_brightness_only_keeps_white_and_colour_returns_to_hs(hass) -> None:
    """Without a colour the lamp stays as it is; a colour goes back to the cloud."""
    light, device, manager, runtime = await _white_setup(
        hass, LampStatus(switch_led=True, brightness=100, colour_temperature=0)
    )
    await light.async_turn_on(color_temp_kelvin=2700)
    runtime.light.async_write.reset_mock()

    await light.async_turn_on(brightness=26)
    runtime.light.async_write.assert_awaited_once_with(
        device.id,
        switch_on=False,
        brightness=102,
        colour_temperature=None,
        light_mode=None,
        leaving_modes=light_platform.NON_WHITE_LIGHT_MODES,
    )
    manager.send_commands.assert_not_called()
    assert light.color_mode is ColorMode.COLOR_TEMP
    assert light.brightness == 26

    await light.async_turn_on(hs_color=(36.0, 88.0))
    manager.send_commands.assert_called_once()
    assert light.color_mode is ColorMode.HS
    assert light.color_temp_kelvin is None
    assert light.brightness == 54


async def test_white_is_not_claimed_while_the_clock_reports_colour_mode(
    hass, caplog
) -> None:
    """A stored temperature is not white if the clock stays in a colour mode."""
    light, _, _, _ = await _white_setup(
        hass,
        LampStatus(
            switch_led=True, light_mode="color", brightness=400, colour_temperature=0
        ),
    )

    await light.async_turn_on(color_temp_kelvin=2700)
    await light.async_turn_on(color_temp_kelvin=2700)

    assert light.color_mode is ColorMode.HS
    assert caplog.text.count("still reports light mode 'color'") == 1


async def test_clock_reports_move_the_lamp_between_white_and_colour(hass) -> None:
    """Reports from the clock's own button are followed without any command."""
    light, device, manager, _ = await _white_setup(
        hass, LampStatus(switch_led=True, brightness=400, colour_temperature=1000)
    )
    await light.async_turn_on(color_temp_kelvin=6500)
    await hass.async_block_till_done()
    assert light.color_mode is ColorMode.COLOR_TEMP

    light.async_write_ha_state.reset_mock()
    _raw_report(manager, device, 6, "800")
    await hass.async_block_till_done()
    assert light.brightness == 204
    light.async_write_ha_state.assert_called_once_with()

    _raw_report(manager, device, 4, "an_unknown_mode")
    await hass.async_block_till_done()
    assert light.color_mode is ColorMode.COLOR_TEMP

    _raw_report(manager, device, 4, "breath")
    await hass.async_block_till_done()
    assert light.color_mode is ColorMode.HS
    assert light.extra_state_attributes == {"light_mode": "breath"}

    light.async_write_ha_state.reset_mock()
    _raw_report(manager, device, 10, "18")
    await hass.async_block_till_done()
    light.async_write_ha_state.assert_not_called()


async def test_installed_light_offers_colour_temperature_through_home_assistant(
    hass,
) -> None:
    """The standard light action reaches the LAN transport and updates state."""
    device = _lamp_device()
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry",
        unique_id=OFFICIAL_ENTRY_ID,
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    entity_id = "light.bedroom_dreamegg_colour_light"

    state = hass.states.get(entity_id)
    assert state.attributes["supported_color_modes"] == ["color_temp", "hs"]
    assert state.attributes["color_mode"] == "hs"
    assert state.attributes["min_color_temp_kelvin"] == 2700
    assert state.attributes["max_color_temp_kelvin"] == 6500
    assert state.attributes["brightness"] == 54

    runtime = entry.runtime_data

    async def write(device_id, **request):
        runtime.capture.record_local(device_id, 6, request["brightness"])
        runtime.capture.record_local(device_id, 7, request["colour_temperature"])
        return LampStatus(
            switch_led=True,
            brightness=request["brightness"],
            colour_temperature=request["colour_temperature"],
        )

    runtime.light.async_write = AsyncMock(side_effect=write)
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": entity_id, "color_temp_kelvin": 2700, "brightness_pct": 5},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert runtime.light.async_write.await_args.kwargs["colour_temperature"] == 0
    assert runtime.light.async_write.await_args.kwargs["brightness"] == 51
    manager.send_commands.assert_not_called()
    state = hass.states.get(entity_id)
    assert state.attributes["color_mode"] == "color_temp"
    assert state.attributes["color_temp_kelvin"] == 2700
    assert state.attributes["brightness"] == 13
    assert state.attributes["light_mode"] is None

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": entity_id, "hs_color": [36, 88]},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["color_mode"] == "hs"
    manager.send_commands.assert_called_once()
    assert await hass.config_entries.async_unload(entry.entry_id) is True
    official.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def test_turn_off_only_switches_the_lamp(hass) -> None:
    """Turning off leaves mode and colour untouched."""
    device = _lamp_device()
    add_entities, manager = await _setup(hass, device)
    (light,) = add_entities.call_args.args[0]
    light.hass = hass

    await light.async_turn_off()

    manager.send_commands.assert_called_once_with(
        device.id, [{"code": "switch_led", "value": False}]
    )


async def test_no_light_without_lamp_datapoints(hass) -> None:
    """Devices that do not advertise the lamp datapoints get no entity."""
    add_entities, _ = await _setup(hass, dreamegg_device())
    add_entities.assert_not_called()


async def test_light_service_call_end_to_end(hass) -> None:
    """The light registers on the Tuya device and obeys light.turn_on."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    from custom_components.tuya_dreamegg.const import TUYA_DOMAIN

    device = _lamp_device(work_mode="colour")
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    official_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=official.entry_id,
        identifiers={(TUYA_DOMAIN, device.id)},
        name=device.name,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry",
        unique_id=OFFICIAL_ENTRY_ID,
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()

    entity_id = "light.bedroom_dreamegg_colour_light"
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"
    assert state.attributes["brightness"] == 54
    assert state.attributes["hs_color"] == (300.0, 100.0)
    assert er.async_get(hass).async_get(entity_id).device_id == official_device.id

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": entity_id, "brightness_pct": 5, "hs_color": [0, 100]},
        blocking=True,
    )

    manager.send_commands.assert_called_once_with(
        device.id,
        [{"code": "colour_data", "value": json.dumps({"h": 0, "s": 1000, "v": 51})}],
    )
