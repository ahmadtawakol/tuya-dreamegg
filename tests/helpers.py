"""Test helpers for Dreamegg Sunrise Controls."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_dreamegg.const import TUYA_DOMAIN

OFFICIAL_ENTRY_ID = "official-tuya-entry"
PRODUCT_ID = "yible1syyda3s5iv"


def dreamegg_device(
    device_id: str = "dreamegg-1",
    name: str = "Bedroom Dreamegg",
    *,
    online: bool = True,
    product_id: str = PRODUCT_ID,
):
    """Return a representative official Tuya Dreamegg device."""
    number_values = {
        "countdown": {"unit": "min", "min": 0, "max": 1440, "scale": 0, "step": 1},
        "backlight": {"min": 0, "max": 100, "scale": 0, "step": 1},
    }
    function = {
        code: SimpleNamespace(values=json.dumps(values))
        for code, values in number_values.items()
    }
    function.update(
        {
            "time_mode": SimpleNamespace(values=json.dumps({"range": ["12h", "24h"]})),
            "stop": SimpleNamespace(values="{}"),
        }
    )
    return SimpleNamespace(
        id=device_id,
        name=name,
        category="bzyd",
        product_id=product_id,
        online=online,
        function=function,
        status_range=dict(function),
        status={
            "countdown": 15,
            "backlight": 80,
            "time_mode": "12h",
            "stop": False,
        },
    )


def official_entry(
    devices: list | None = None,
    *,
    entry_id: str = OFFICIAL_ENTRY_ID,
    title: str = "Smart Life account",
    loaded: bool = True,
) -> tuple[MockConfigEntry, SimpleNamespace]:
    """Return an official Tuya config entry and its manager."""
    manager = SimpleNamespace(
        device_map={device.id: device for device in devices or []},
        send_commands=Mock(),
    )
    entry = MockConfigEntry(
        domain=TUYA_DOMAIN,
        entry_id=entry_id,
        title=title,
        data={},
        state=ConfigEntryState.LOADED if loaded else ConfigEntryState.NOT_LOADED,
    )
    if loaded:
        entry.runtime_data = SimpleNamespace(manager=manager)
    return entry, manager
