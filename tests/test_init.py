"""Tests for Dreamegg Sunrise Controls setup."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_dreamegg import (
    DreameggRuntimeData,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.tuya_dreamegg.const import (
    CONF_TUYA_ENTRY_ID,
    DOMAIN,
    PLATFORMS,
)

from .helpers import OFFICIAL_ENTRY_ID, dreamegg_device, official_entry


def _custom_entry() -> MockConfigEntry:
    """Return a Dreamegg companion config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id="dreamegg-entry",
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )


async def test_setup_uses_official_runtime_and_forwards_platforms(hass) -> None:
    """Setup stores a dynamic runtime and forwards all entity platforms."""
    official, manager = official_entry([dreamegg_device()])
    official.add_to_hass(hass)
    entry = _custom_entry()
    forward = AsyncMock()

    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        new=forward,
    ):
        assert await async_setup_entry(hass, entry) is True

    assert isinstance(entry.runtime_data, DreameggRuntimeData)
    assert entry.runtime_data.manager is manager
    forward.assert_awaited_once_with(entry, PLATFORMS)


async def test_runtime_follows_official_tuya_reload(hass) -> None:
    """The companion resolves the replacement manager after a Tuya reload."""
    device = dreamegg_device()
    official, manager = official_entry([device])
    official.add_to_hass(hass)
    runtime = DreameggRuntimeData(hass, official.entry_id)
    replacement = SimpleNamespace(
        device_map={device.id: device},
        send_commands=AsyncMock(),
    )

    assert runtime.manager is manager
    official.runtime_data = SimpleNamespace(manager=replacement)
    assert runtime.manager is replacement


@pytest.mark.parametrize("loaded", [False, True])
async def test_setup_retries_without_usable_devices(hass, loaded: bool) -> None:
    """Setup waits for the official account and supported devices."""
    devices = [dreamegg_device(product_id="different-product")] if loaded else []
    official, _ = official_entry(devices, loaded=loaded)
    official.add_to_hass(hass)
    entry = _custom_entry()

    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, entry)


async def test_unload_forwards_all_platforms(hass) -> None:
    """Unload removes the companion platforms."""
    entry = _custom_entry()
    entry.mock_state(hass, ConfigEntryState.LOADED)
    unload = AsyncMock(return_value=True)

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=unload,
    ):
        assert await async_unload_entry(hass, entry) is True

    unload.assert_awaited_once_with(entry, PLATFORMS)
