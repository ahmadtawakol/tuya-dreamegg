"""End-to-end test for Dreamegg Sunrise Controls."""

from homeassistant.components.number import SERVICE_SET_VALUE
from homeassistant.components.select import SERVICE_SELECT_OPTION
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_dreamegg.const import (
    CONF_TUYA_ENTRY_ID,
    DOMAIN,
    TUYA_DOMAIN,
    TUYA_UPDATE_ENTITY,
)

from .helpers import OFFICIAL_ENTRY_ID, dreamegg_device, official_entry


async def test_full_setup_commands_updates_and_unload(hass) -> None:
    """The installed integration creates working entities on the Tuya device."""
    device = dreamegg_device()
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    official_device = device_registry.async_get_or_create(
        config_entry_id=official.entry_id,
        identifiers={(TUYA_DOMAIN, device.id)},
        name=device.name,
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry",
        unique_id=OFFICIAL_ENTRY_ID,
        title="Dreamegg Sunrise Controls",
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    entity_ids = {
        "number.bedroom_dreamegg_countdown",
        "number.bedroom_dreamegg_display_brightness",
        "select.bedroom_dreamegg_time_format",
        "button.bedroom_dreamegg_stop",
    }
    assert all(hass.states.get(entity_id) is not None for entity_id in entity_ids)
    entity_registry = er.async_get(hass)
    assert {
        entity_registry.async_get(entity_id).device_id for entity_id in entity_ids
    } == {official_device.id}

    await hass.services.async_call(
        "number",
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: "number.bedroom_dreamegg_countdown", "value": 25},
        blocking=True,
    )
    await hass.services.async_call(
        "select",
        SERVICE_SELECT_OPTION,
        {
            ATTR_ENTITY_ID: "select.bedroom_dreamegg_time_format",
            "option": "24h",
        },
        blocking=True,
    )
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.bedroom_dreamegg_stop"},
        blocking=True,
    )
    assert [call.args[1] for call in manager.send_commands.call_args_list] == [
        [{"code": "countdown", "value": 25}],
        [{"code": "time_mode", "value": "24h"}],
        [{"code": "stop", "value": True}],
    ]

    device.status["countdown"] = 20
    async_dispatcher_send(
        hass,
        f"{TUYA_UPDATE_ENTITY}_{device.id}",
        ["countdown"],
        {},
    )
    await hass.async_block_till_done()
    assert hass.states.get("number.bedroom_dreamegg_countdown").state == "20.0"

    assert await hass.config_entries.async_unload(entry.entry_id) is True
    await hass.async_block_till_done()
    assert all(
        hass.states.get(entity_id).state == STATE_UNAVAILABLE
        for entity_id in entity_ids
    )
    official.mock_state(hass, ConfigEntryState.NOT_LOADED)
