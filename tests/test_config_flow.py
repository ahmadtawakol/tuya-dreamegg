"""Tests for the Dreamegg Sunrise Controls config flow."""

from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_platform

from custom_components.tuya_dreamegg import config_flow
from custom_components.tuya_dreamegg.const import CONF_TUYA_ENTRY_ID, DOMAIN

from .helpers import OFFICIAL_ENTRY_ID, dreamegg_device, official_entry


async def _start_flow(hass, entries: list[MockConfigEntry] | None = None):
    """Start the custom integration user flow."""
    mock_platform(hass, f"{DOMAIN}.config_flow", config_flow, built_in=False)
    with patch.object(
        hass.config_entries,
        "async_entries",
        return_value=entries or [],
    ):
        return await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
        )


async def test_flow_requires_loaded_official_tuya(hass) -> None:
    """The official Tuya integration must be loaded."""
    result = await _start_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "tuya_not_configured"


async def test_flow_requires_supported_device(hass) -> None:
    """An unrelated Tuya account is not offered."""
    unsupported = dreamegg_device(product_id="different-product")
    entry, _ = official_entry([unsupported])

    result = await _start_flow(hass, [entry])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_supported_devices"


async def test_flow_lists_eligible_accounts(hass) -> None:
    """The form lists accounts and the number of supported clocks."""
    entry, _ = official_entry(
        [dreamegg_device(), dreamegg_device("dreamegg-2", "Nursery Dreamegg")]
    )

    result = await _start_flow(hass, [entry])

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["data_schema"]({CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID}) == {
        CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID
    }
    with pytest.raises(vol.Invalid):
        result["data_schema"]({CONF_TUYA_ENTRY_ID: "another-account"})


async def test_flow_creates_credential_free_entry(hass) -> None:
    """The entry stores only the official Tuya config-entry ID."""
    entry, _ = official_entry([dreamegg_device()])
    form = await _start_flow(hass, [entry])

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dreamegg Sunrise Controls"
    assert result["data"] == {CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID}
    assert result["result"].unique_id == OFFICIAL_ENTRY_ID


async def test_flow_rejects_duplicate_account(hass) -> None:
    """Only one companion entry may extend each official Tuya account."""
    entry, _ = official_entry([dreamegg_device()])
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id=OFFICIAL_ENTRY_ID,
        data={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )
    existing.add_to_hass(hass)
    form = await _start_flow(hass, [entry])

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        user_input={CONF_TUYA_ENTRY_ID: OFFICIAL_ENTRY_ID},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
