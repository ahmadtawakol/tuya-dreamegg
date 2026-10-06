"""Tests for Dreamegg number, select, and button entities."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.number import NumberDeviceClass
from homeassistant.const import UnitOfTime
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_dreamegg import DreameggRuntimeData
from custom_components.tuya_dreamegg import button as button_platform
from custom_components.tuya_dreamegg import number as number_platform
from custom_components.tuya_dreamegg import select as select_platform
from custom_components.tuya_dreamegg.const import (
    CONF_TUYA_ENTRY_ID,
    DOMAIN,
    TUYA_DISCOVERY_NEW,
    TUYA_DOMAIN,
    TUYA_UPDATE_ENTITY,
)

from .helpers import OFFICIAL_ENTRY_ID, dreamegg_device, official_entry


def _custom_entry(hass, official) -> MockConfigEntry:
    """Return a config entry with initialized runtime data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry",
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    entry.runtime_data = DreameggRuntimeData(hass, official.entry_id)
    return entry


async def test_number_entities_read_schema_and_send_commands(hass) -> None:
    """Numbers expose device ranges and send integer datapoints."""
    device = dreamegg_device()
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    entry = _custom_entry(hass, official)
    add_entities = Mock()

    await number_platform.async_setup_entry(hass, entry, add_entities)

    entities = add_entities.call_args.args[0]
    assert len(entities) == 2
    by_key = {entity.entity_description.key: entity for entity in entities}
    countdown = by_key["countdown"]
    backlight = by_key["backlight"]
    assert countdown.native_value == 15
    assert countdown.native_min_value == 0
    assert countdown.native_max_value == 1440
    assert countdown.native_step == 1
    assert countdown.device_class is NumberDeviceClass.DURATION
    assert countdown.native_unit_of_measurement == UnitOfTime.MINUTES
    assert backlight.native_value == 80
    assert backlight.native_max_value == 100
    assert backlight.device_info["identifiers"] == {(TUYA_DOMAIN, device.id)}

    countdown.hass = hass
    backlight.hass = hass
    await countdown.async_set_native_value(30)
    await backlight.async_set_native_value(45)

    assert manager.send_commands.call_args_list == [
        ((device.id, [{"code": "countdown", "value": 30}]),),
        ((device.id, [{"code": "backlight", "value": 45}]),),
    ]


async def test_select_and_button_send_expected_commands(hass) -> None:
    """Time format and stop controls use the documented Tuya values."""
    device = dreamegg_device()
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    entry = _custom_entry(hass, official)
    add_selects = Mock()
    add_buttons = Mock()

    await select_platform.async_setup_entry(hass, entry, add_selects)
    await button_platform.async_setup_entry(hass, entry, add_buttons)
    selects = {
        entity.entity_description.key: entity
        for entity in add_selects.call_args.args[0]
    }
    time_format = selects["time_mode"]
    work_mode = selects["work_mode"]
    stop = add_buttons.call_args.args[0][0]

    assert time_format.options == ["12h", "24h"]
    assert time_format.current_option == "12h"
    assert work_mode.options == ["scene", "customize_scene", "colour"]
    assert work_mode.current_option == "scene"
    time_format.hass = hass
    work_mode.hass = hass
    stop.hass = hass
    await time_format.async_select_option("24h")
    await work_mode.async_select_option("customize_scene")
    await stop.async_press()

    assert manager.send_commands.call_args_list == [
        ((device.id, [{"code": "time_mode", "value": "24h"}]),),
        ((device.id, [{"code": "work_mode", "value": "customize_scene"}]),),
        ((device.id, [{"code": "stop", "value": True}]),),
    ]


async def test_entity_uses_reloaded_manager_and_live_device(hass) -> None:
    """Existing entities survive an official Tuya config-entry reload."""
    device = dreamegg_device()
    official, _ = official_entry([device])
    official.add_to_hass(hass)
    entry = _custom_entry(hass, official)
    add_entities = Mock()
    await number_platform.async_setup_entry(hass, entry, add_entities)
    countdown = next(
        entity
        for entity in add_entities.call_args.args[0]
        if entity.entity_description.key == "countdown"
    )
    replacement_device = dreamegg_device()
    replacement_device.status["countdown"] = 90
    replacement_manager = SimpleNamespace(
        device_map={replacement_device.id: replacement_device},
        send_commands=Mock(),
    )
    official.runtime_data = SimpleNamespace(manager=replacement_manager)

    assert countdown.native_value == 90
    countdown.hass = hass
    await countdown.async_set_native_value(60)
    replacement_manager.send_commands.assert_called_once_with(
        device.id, [{"code": "countdown", "value": 60}]
    )


async def test_push_updates_only_write_relevant_entity(hass) -> None:
    """Official Tuya push notifications update only the affected control."""
    device = dreamegg_device()
    official, _ = official_entry([device])
    official.add_to_hass(hass)
    entry = _custom_entry(hass, official)
    add_entities = Mock()
    await number_platform.async_setup_entry(hass, entry, add_entities)
    countdown = next(
        entity
        for entity in add_entities.call_args.args[0]
        if entity.entity_description.key == "countdown"
    )
    countdown.hass = hass
    countdown.async_write_ha_state = Mock()
    await countdown.async_added_to_hass()

    async_dispatcher_send(
        hass,
        f"{TUYA_UPDATE_ENTITY}_{device.id}",
        ["backlight"],
        {},
    )
    countdown.async_write_ha_state.assert_not_called()
    async_dispatcher_send(
        hass,
        f"{TUYA_UPDATE_ENTITY}_{device.id}",
        ["countdown"],
        {},
    )
    countdown.async_write_ha_state.assert_called_once_with()


async def test_new_supported_device_is_discovered(hass) -> None:
    """A clock added to Tuya later receives companion entities."""
    first = dreamegg_device()
    official, manager = official_entry([first])
    official.add_to_hass(hass)
    entry = _custom_entry(hass, official)
    add_entities = Mock()
    await select_platform.async_setup_entry(hass, entry, add_entities)
    assert add_entities.call_count == 1

    second = dreamegg_device("dreamegg-2", "Nursery Dreamegg")
    manager.device_map[second.id] = second
    async_dispatcher_send(hass, TUYA_DISCOVERY_NEW, [second.id])

    assert add_entities.call_count == 2
    assert {
        (entity._device_id, entity.entity_description.key)
        for entity in add_entities.call_args.args[0]
    } == {
        (second.id, "time_mode"),
        (second.id, "work_mode"),
        (second.id, "music_set"),
    }


async def test_music_select_uses_full_product_schema_and_raw_reports(hass) -> None:
    """Music works despite being absent from the reduced HA function schema."""
    device = dreamegg_device()
    assert "music_set" not in device.function
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    entry = _custom_entry(hass, official)
    add_entities = Mock()
    await select_platform.async_setup_entry(hass, entry, add_entities)
    music = next(
        entity
        for entity in add_entities.call_args.args[0]
        if entity.entity_description.key == "music_set"
    )
    assert music.options == [str(value) for value in range(1, 35)]
    assert music.current_option is None
    music.hass = hass
    music.async_write_ha_state = Mock()
    entry.runtime_data.music.async_read = AsyncMock(return_value="18")
    entry.runtime_data.music.async_write = AsyncMock(return_value="10")
    await music.async_added_to_hass()
    manager.mq.emit(
        {
            "protocol": 4,
            "data": {
                "devId": device.id,
                "status": [{"dpId": 10, "t": 1, "value": "18"}],
            },
        }
    )
    await hass.async_block_till_done()
    assert music.current_option == "18"
    with pytest.raises(ServiceValidationError):
        await music.async_select_option("35")
    assert manager.send_commands.call_count == 0
    music.async_write_ha_state.assert_called_once_with()
    await music.async_select_option("10")
    entry.runtime_data.music.async_write.assert_awaited_once_with(device.id, "10")
    manager.send_commands.assert_not_called()
    assert music.current_option == "18"
    device.status["music_set"] = "18"
    manager.mq.emit(
        {
            "protocol": 4,
            "data": {
                "devId": device.id,
                "status": [{"dpId": 10, "t": 2, "value": "10"}],
            },
        }
    )
    await hass.async_block_till_done()
    assert music.current_option == "10"
