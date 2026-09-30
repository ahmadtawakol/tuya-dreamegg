"""Test helpers for Dreamegg Sunrise Controls."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tuya_dreamegg.const import TUYA_DOMAIN

OFFICIAL_ENTRY_ID = "official-tuya-entry"
PRODUCT_ID = "yible1syyda3s5iv"


class FakeMQ:
    """Minimal raw Tuya MQTT listener registry."""

    def __init__(self) -> None:
        """Initialize the listener set."""
        self.message_listeners: set = set()

    def add_message_listener(self, listener) -> None:
        """Register a raw message listener."""
        self.message_listeners.add(listener)

    def remove_message_listener(self, listener) -> None:
        """Remove a raw message listener."""
        self.message_listeners.discard(listener)

    def emit(self, message: dict) -> None:
        """Emit a raw Tuya MQTT message."""
        for listener in self.message_listeners:
            listener(message)


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
            "work_mode": SimpleNamespace(
                values=json.dumps({"range": ["scene", "customize_scene", "colour"]})
            ),
            "stop": SimpleNamespace(values="{}"),
        }
    )
    return SimpleNamespace(
        id=device_id,
        name=name,
        category="bzyd",
        product_id=product_id,
        product_name="Dreamegg Sunrise 1+",
        online=online,
        function=function,
        status_range=dict(function),
        status={
            "countdown": 15,
            "backlight": 80,
            "time_mode": "12h",
            "work_mode": "scene",
            "stop": False,
        },
        local_strategy={
            2: {"status_code": "work_mode"},
            21: {"status_code": "time_mode"},
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
        mq=FakeMQ(),
        query_scenes=Mock(return_value=[]),
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
