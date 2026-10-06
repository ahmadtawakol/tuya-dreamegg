"""Tests for bounded Music DP 10 transport diagnostics."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from tuya_sharing.exceptions import ApiRequestException

from custom_components.tuya_dreamegg.const import (
    CONF_TUYA_ENTRY_ID,
    DOMAIN,
    TUYA_DOMAIN,
)
from custom_components.tuya_dreamegg.services import (
    TEST_MUSIC_TRANSPORT,
    _test_cloud,
    _test_local,
)

from .helpers import OFFICIAL_ENTRY_ID, dreamegg_device, official_entry


def test_cloud_diagnostic_returns_error_and_exact_numeric_payload() -> None:
    """No schema validation blocks the requested dpId experiment locally."""
    manager = SimpleNamespace(customer_api=SimpleNamespace(post=Mock()))
    manager.customer_api.post.return_value = {"success": True, "result": True}
    assert _test_cloud(manager, "clock-id", "dp_id", "18") == {
        "accepted": True,
        "command_result": True,
    }
    manager.customer_api.post.assert_called_once_with(
        "/v1.1/m/thing/clock-id/commands",
        None,
        {"commands": [{"dpId": 10, "value": "18"}]},
    )
    manager.customer_api.post.return_value = {"success": True, "result": False}
    assert _test_cloud(manager, "clock-id", "dp_id", "18") == {
        "accepted": False,
        "command_result": False,
    }
    manager.customer_api.post.side_effect = ApiRequestException(
        error_code="2008", error_message="Command not supported"
    )
    assert _test_cloud(manager, "clock-id", "code", "18") == {
        "accepted": False,
        "error_code": "2008",
        "error_message": "Command not supported",
    }


def test_local_write_reads_back_and_restores_original_track() -> None:
    """Only DP 10 is changed, and it is restored even during a test."""
    device = SimpleNamespace(id="clock-id", local_key="test-only-key123")
    clock = Mock()
    clock.status.side_effect = [
        {"dps": {"10": "18"}},
        {"dps": {"10": "10"}},
        {"dps": {"10": "18"}},
    ]
    with (
        patch(
            "custom_components.tuya_dreamegg.services.scanner.devices",
            return_value={device.id: {"ip": "192.0.2.2", "version": "3.3"}},
        ) as scan,
        patch(
            "custom_components.tuya_dreamegg.services.tinytuya.Device",
            return_value=clock,
        ),
    ):
        result = _test_local(device, "local_test", "10")
    assert result["write_verified"] is True
    assert result["restore_verified"] is True
    assert result["music_before"] == result["music_restored"] == "18"
    assert [call.args for call in clock.set_value.call_args_list] == [
        (10, "10"),
        (10, "18"),
    ]
    assert scan.call_args.kwargs["wantids"] == ("clock-id",)
    clock.close.assert_called_once_with()


def test_local_probe_requests_missing_music_without_a_write() -> None:
    """Devices that initially report only DP 1 receive a targeted status query."""
    device = SimpleNamespace(id="clock-id", local_key="test-only-key123")
    clock = Mock()
    clock.status.side_effect = [{"dps": {"1": False}}, {"dps": {"10": "18"}}]
    with (
        patch(
            "custom_components.tuya_dreamegg.services.scanner.devices",
            return_value={device.id: {"ip": "192.0.2.2", "version": "3.3"}},
        ),
        patch(
            "custom_components.tuya_dreamegg.services.tinytuya.Device",
            return_value=clock,
        ),
    ):
        result = _test_local(device, "local_probe", "10")
    assert result["music_before"] == "18"
    clock.set_dpsUsed.assert_called_once_with({"1": None, "10": None})
    clock.set_value.assert_not_called()


def test_local_write_restores_even_if_verification_fails() -> None:
    """A readback exception cannot skip the baseline restore command."""
    device = SimpleNamespace(id="clock-id", local_key="test-only-key123")
    clock = Mock()
    clock.status.side_effect = [
        {"dps": {"10": "18"}},
        OSError("test readback failure"),
        {"dps": {"10": "18"}},
    ]
    with (
        patch(
            "custom_components.tuya_dreamegg.services.scanner.devices",
            return_value={device.id: {"ip": "192.0.2.2", "version": "3.3"}},
        ),
        patch(
            "custom_components.tuya_dreamegg.services.tinytuya.Device",
            return_value=clock,
        ),
    ):
        result = _test_local(device, "local_test", "10")
    assert result["restore_verified"] is True
    assert result["error_type"] == "OSError"
    assert clock.set_value.call_args_list[-1].args == (10, "18")


async def test_action_uses_loaded_account_and_unregisters_on_unload(hass) -> None:
    """The installed action uses only a supported registry device's manager."""
    device = dreamegg_device()
    official, manager = official_entry([device])
    manager.customer_api = SimpleNamespace(post=Mock(return_value={"success": True}))
    official.add_to_hass(hass)
    registry_device = dr.async_get(hass).async_get_or_create(
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
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.services.async_call(
        DOMAIN,
        TEST_MUSIC_TRANSPORT,
        {"device_id": registry_device.id, "transport": "dp_id", "option": "18"},
        blocking=True,
        return_response=True,
    )
    assert result == {
        "transport": "dp_id",
        "dp_id": 10,
        "option": "18",
        "accepted": True,
    }
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            TEST_MUSIC_TRANSPORT,
            {"device_id": "missing", "transport": "dp_id"},
            blocking=True,
            return_response=True,
        )
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, TEST_MUSIC_TRANSPORT)
