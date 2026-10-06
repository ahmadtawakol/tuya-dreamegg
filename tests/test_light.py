"""Tests for the Dreamegg colour light."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from homeassistant.components.light import ColorMode
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_dreamegg import DreameggRuntimeData
from custom_components.tuya_dreamegg import light as light_platform
from custom_components.tuya_dreamegg.const import CONF_TUYA_ENTRY_ID, DOMAIN
from custom_components.tuya_dreamegg.light import (
    brightness_to_device,
    device_to_brightness,
    parse_colour_data,
)

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


async def test_state_is_read_on_device_scale(hass) -> None:
    """Reported state is in range, unlike the official entity's."""
    device = _lamp_device(colour_data='{"h":190,"s":1000,"v":792}')
    add_entities, _ = await _setup(hass, device)

    (light,) = add_entities.call_args.args[0]
    assert light.unique_id == f"{device.id}_colour_light"
    assert light.color_mode is ColorMode.HS
    assert light.supported_color_modes == {ColorMode.HS}
    assert light.is_on is True
    assert light.brightness == 202
    assert light.hs_color == (190.0, 100.0)

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
