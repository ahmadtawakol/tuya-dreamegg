"""Tests for the verified local Music control path."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.tuya_dreamegg.capture import RawDpCapture
from custom_components.tuya_dreamegg.music_transport import LocalMusicTransport

from .helpers import dreamegg_device


def _transport(hass):
    device = dreamegg_device()
    device.local_key = "test-key-one1234"
    capture = RawDpCapture(hass)
    capture.attach(SimpleNamespace(device_map={device.id: device}, mq=None))
    provider = Mock(return_value=device)
    return LocalMusicTransport(hass, capture, provider), device, capture, provider


async def test_local_music_read_write_reuses_endpoint_and_fresh_key(hass) -> None:
    """Only DP 10 is sent, and selection changes only after device readback."""
    transport, device, capture, provider = _transport(hass)
    reader = Mock()
    reader.status.return_value = {"dps": {"10": "18"}}
    writer = Mock()
    writer.status.side_effect = [{"dps": {"10": "18"}}, {"dps": {"10": "10"}}]
    with (
        patch(
            "custom_components.tuya_dreamegg.music_transport.scanner.devices",
            return_value={device.id: {"ip": "192.0.2.2", "version": "3.5"}},
        ) as scan,
        patch(
            "custom_components.tuya_dreamegg.music_transport.tinytuya.Device",
            side_effect=[reader, writer],
        ) as device_class,
    ):
        assert await transport.async_read(device.id) == "18"
        assert capture.latest_value(device.id, 10) == "18"
        device.local_key = "test-key-two1234"
        assert await transport.async_write(device.id, "10") == "10"
    assert capture.latest_value(device.id, 10) == "10"
    assert scan.call_count == 1
    assert scan.call_args.kwargs["wantids"] == (device.id,)
    assert device_class.call_args.kwargs["local_key"] == "test-key-two1234"
    assert provider.call_count == 2
    reader.set_value.assert_not_called()
    writer.set_value.assert_called_once_with(10, "10")
    reader.close.assert_called_once_with()
    writer.close.assert_called_once_with()
    assert capture.snapshot()[device.id][-1]["source"] == "local_readback"


async def test_unconfirmed_music_write_keeps_reported_state(hass) -> None:
    """A command that fails readback never reports the requested value."""
    transport, device, capture, _ = _transport(hass)
    capture.record_local_music(device.id, "18")
    clock = Mock()
    clock.status.return_value = {"dps": {"10": "18"}}
    with (
        patch(
            "custom_components.tuya_dreamegg.music_transport.scanner.devices",
            return_value={device.id: {"ip": "192.0.2.2", "version": "3.5"}},
        ),
        patch(
            "custom_components.tuya_dreamegg.music_transport.tinytuya.Device",
            return_value=clock,
        ),
        pytest.raises(HomeAssistantError, match="did not confirm"),
    ):
        await transport.async_write(device.id, "10")
    assert capture.latest_value(device.id, 10) == "18"
    clock.close.assert_called_once_with()


async def test_discovery_never_targets_another_clock_or_cloud_ip(hass) -> None:
    """Only the requested device ID's LAN advertisement is accepted."""
    transport, device, _, _ = _transport(hass)
    device.ip = "203.0.113.1"
    with (
        patch(
            "custom_components.tuya_dreamegg.music_transport.scanner.devices",
            return_value={"another-device": {"ip": "192.0.2.2", "version": "3.5"}},
        ),
        patch(
            "custom_components.tuya_dreamegg.music_transport.tinytuya.Device"
        ) as device_class,
        pytest.raises(HomeAssistantError, match="not found"),
    ):
        await transport.async_write(device.id, "10")
    device_class.assert_not_called()


async def test_discovery_socket_error_is_a_normal_ha_failure(hass) -> None:
    """A LAN problem marks the select unavailable instead of failing setup."""
    transport, device, _, _ = _transport(hass)
    with (
        patch(
            "custom_components.tuya_dreamegg.music_transport.scanner.devices",
            side_effect=OSError("test UDP failure"),
        ),
        pytest.raises(HomeAssistantError, match="Unable to discover"),
    ):
        await transport.async_read(device.id)
