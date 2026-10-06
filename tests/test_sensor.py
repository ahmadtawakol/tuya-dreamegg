"""Tests for Dreamegg raw sensors."""

from base64 import b64encode
from unittest.mock import Mock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTime
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_dreamegg import DreameggRuntimeData
from custom_components.tuya_dreamegg import sensor as sensor_platform
from custom_components.tuya_dreamegg.const import (
    CONF_TUYA_ENTRY_ID,
    DOMAIN,
    TUYA_DOMAIN,
    TUYA_RAW_DP_UPDATE,
)

from .helpers import OFFICIAL_ENTRY_ID, dreamegg_device, official_entry


async def test_countdown_remaining_sensor_tracks_raw_dp(hass) -> None:
    """The read-only sensor displays the countdown in seconds."""
    device = dreamegg_device()
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry",
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    entry.runtime_data = DreameggRuntimeData(hass, official.entry_id)
    add_entities = Mock()

    await sensor_platform.async_setup_entry(hass, entry, add_entities)

    sensor = add_entities.call_args.args[0][0]
    assert sensor.native_value is None
    assert sensor.device_class is SensorDeviceClass.DURATION
    assert sensor.native_unit_of_measurement == UnitOfTime.SECONDS
    assert sensor.device_info["identifiers"] == {(TUYA_DOMAIN, device.id)}

    sensor.hass = hass
    sensor.async_write_ha_state = Mock()
    await sensor.async_added_to_hass()
    entry.runtime_data.capture.attach(manager)
    manager.mq.emit(
        {
            "protocol": 4,
            "data": {
                "devId": device.id,
                "status": [{"dpId": 104, "t": 1_700_000_000_000, "value": 600}],
            },
        }
    )
    await hass.async_block_till_done()

    assert sensor.native_value == 600
    sensor.async_write_ha_state.assert_called_once_with()
    async_dispatcher_send(
        hass,
        f"{TUYA_RAW_DP_UPDATE}_{device.id}",
        15,
    )
    sensor.async_write_ha_state.assert_called_once_with()


async def test_web_mapped_raw_datapoints_and_schedules_are_read_only_sensors(
    hass,
) -> None:
    """Tuya Web datapoints appear as raw readings, not guessed write controls."""
    device = dreamegg_device()
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry-raw",
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    entry.runtime_data = DreameggRuntimeData(hass, official.entry_id)
    add_entities = Mock()

    await sensor_platform.async_setup_entry(hass, entry, add_entities)
    entities = add_entities.call_args.args[0]
    raw_sensors = {entity._dp_id: entity for entity in entities}
    assert {6, 7, 10, 13, 14, 15, 102, 104, 112} <= raw_sensors.keys()
    assert raw_sensors[6].native_unit_of_measurement is None
    assert raw_sensors[7].native_unit_of_measurement is None

    for sensor in entities:
        sensor.hass = hass
        sensor.async_write_ha_state = Mock()
        await sensor.async_added_to_hass()

    manager.mq.emit(
        {
            "protocol": 4,
            "data": {
                "devId": device.id,
                "status": [
                    {"dpId": 6, "t": 1_700_000_000_000, "value": 130},
                    {"dpId": 7, "t": 1_700_000_000_001, "value": 20},
                    {"dpId": 10, "t": 1_700_000_000_002, "value": "32"},
                    {"dpId": 13, "t": 1_700_000_000_003, "value": 1},
                    {
                        "dpId": 14,
                        "t": 1_700_000_000_004,
                        "value": b64encode(b"scene-config").decode(),
                    },
                    {"dpId": 15, "t": 1_700_000_000_005, "value": _schedule_payload()},
                    {"dpId": 102, "t": 1_700_000_000_006, "value": "1"},
                    {"dpId": 112, "t": 1_700_000_000_007, "value": _schedule_payload()},
                    {"dpId": 104, "t": 1_700_000_000_008, "value": 60},
                ],
            },
        }
    )
    await hass.async_block_till_done()

    assert raw_sensors[6].native_value == 130
    assert raw_sensors[7].native_value == 20
    assert raw_sensors[10].native_value == 32
    assert raw_sensors[10].extra_state_attributes["sound_name"] == "Morning"
    manager.mq.emit(
        {
            "protocol": 4,
            "data": {
                "devId": device.id,
                "status": [{"dpId": 10, "t": 1_700_000_000_009, "value": "10"}],
            },
        }
    )
    await hass.async_block_till_done()
    assert raw_sensors[10].extra_state_attributes["sound_name"] == "Rainstorm"
    assert raw_sensors[13].native_value == 1
    assert raw_sensors[14].native_value == b64encode(b"scene-config").decode()
    assert raw_sensors[102].native_value == 1
    assert raw_sensors[15].native_value == 2
    assert raw_sensors[15].extra_state_attributes["slots"][0]["name"] == "Okay to Wake"
    assert raw_sensors[112].native_value == 2
    for sensor in entities:
        assert sensor.async_write_ha_state.call_count == (
            2 if sensor._dp_id == 10 else 1
        )


def _schedule_payload() -> str:
    """Return a minimal valid schedule payload with two enabled slots."""
    payload = bytearray(120)
    payload[0] = 1
    payload[20] = 1
    return b64encode(payload).decode()
