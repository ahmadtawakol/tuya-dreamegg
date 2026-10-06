"""Tests for Dreamegg capability diagnostics."""

from base64 import b64encode
from types import SimpleNamespace

from homeassistant.components.diagnostics import REDACTED
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_dreamegg import DreameggRuntimeData
from custom_components.tuya_dreamegg.const import CONF_TUYA_ENTRY_ID, DOMAIN
from custom_components.tuya_dreamegg.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import OFFICIAL_ENTRY_ID, dreamegg_device, official_entry


async def test_diagnostics_capture_raw_reports_and_scenes(hass) -> None:
    """Diagnostics retain supported-device reports and redact identifiers."""
    device = dreamegg_device()
    official, manager = official_entry([device])
    manager.query_scenes.return_value = [
        SimpleNamespace(
            actions=[{"devId": device.id, "code": "switch", "value": True}],
            enabled=True,
            home_id="home-1",
            name="Good morning",
            scene_id="scene-1",
        )
    ]
    official.add_to_hass(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry",
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    runtime = DreameggRuntimeData(hass, official.entry_id)
    entry.runtime_data = runtime
    runtime.capture.attach(manager)
    alarm_table = b64encode(
        bytes.fromhex("01 01 04 00 00 00 00 00 00 03 e8 00 01 64 01 68 00 0f 1f 01")
        + bytes(20 * 5)
    ).decode()

    manager.mq.emit(
        {
            "protocol": 4,
            "data": {
                "devId": device.id,
                "status": [
                    {"dpId": 2, "t": 1_700_000_000_000, "value": "colour"},
                    {
                        "dpId": 10,
                        "t": 1_700_000_000_001,
                        "value": {"alarm": "07:00"},
                    },
                    {
                        "dpId": 112,
                        "t": 1_700_000_000_002,
                        "value": alarm_table,
                    },
                ],
            },
        }
    )
    manager.mq.emit(
        {
            "protocol": 4,
            "data": {
                "devId": "another-device",
                "status": [{"dpId": 99, "value": "private"}],
            },
        }
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert len(diagnostics["devices"]) == 1
    captured = diagnostics["devices"][0]["raw_dp_reports"]
    assert captured == [
        {
            "dp_id": 2,
            "known_code": "work_mode",
            "timestamp": 1_700_000_000_000,
            "value": "colour",
        },
        {
            "dp_id": 10,
            "known_code": None,
            "timestamp": 1_700_000_000_001,
            "value": {"alarm": "07:00"},
        },
        {
            "dp_id": 112,
            "known_code": None,
            "timestamp": 1_700_000_000_002,
            "value": alarm_table,
        },
    ]
    alarm_slots = diagnostics["devices"][0]["schedule_tables"]["alarms"]
    assert alarm_slots is not None
    assert alarm_slots[0]["start_minute"] == 360
    assert alarm_slots[0]["duration_minutes"] == 15
    assert alarm_slots[0]["special_light_enabled"] is True
    assert diagnostics["devices"][0]["device_id"] == REDACTED
    assert diagnostics["tuya_scenes"] == [
        {
            "actions": [{"devId": REDACTED, "code": "switch", "value": True}],
            "enabled": True,
            "home_id": REDACTED,
            "name": "Good morning",
            "scene_id": REDACTED,
        }
    ]
    assert diagnostics["scene_query_error"] is None

    runtime.capture.detach()
    assert not manager.mq.message_listeners
