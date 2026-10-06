"""Diagnostics for Dreamegg Sunrise Controls."""

import json
from collections.abc import Mapping
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DreameggConfigEntry
from .schedules import decode_latest_schedule_reports

TO_REDACT = {
    "asset_id",
    "devId",
    "device_id",
    "home_id",
    "id",
    "ip",
    "local_key",
    "scene_id",
    "uuid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DreameggConfigEntry
) -> dict[str, Any]:
    """Return capability and app-feature investigation data."""
    runtime = entry.runtime_data
    manager = runtime.manager
    runtime.capture.attach(manager)

    scenes: list[dict[str, Any]] = []
    scene_error: str | None = None
    query_scenes = getattr(manager, "query_scenes", None)
    if callable(query_scenes):
        try:
            scenes = [
                {
                    "actions": getattr(scene, "actions", []),
                    "enabled": getattr(scene, "enabled", None),
                    "home_id": getattr(scene, "home_id", None),
                    "name": getattr(scene, "name", None),
                    "scene_id": getattr(scene, "scene_id", None),
                }
                for scene in await hass.async_add_executor_job(query_scenes)
            ]
        except Exception as error:
            scene_error = type(error).__name__

    captured = runtime.capture.snapshot()
    devices = [
        {
            "device_id": device.id,
            "function": _serialize_specification(getattr(device, "function", {})),
            "local_strategy": getattr(device, "local_strategy", {}),
            "name": getattr(device, "name", None),
            "product_id": getattr(device, "product_id", None),
            "product_name": getattr(device, "product_name", None),
            "raw_dp_reports": captured.get(device.id, []),
            "schedule_tables": decode_latest_schedule_reports(
                captured.get(device.id, [])
            ),
            "status": getattr(device, "status", {}),
            "status_range": _serialize_specification(
                getattr(device, "status_range", {})
            ),
        }
        for device in runtime.supported_devices()
    ]
    return async_redact_data(
        {
            "capture": {
                "note": (
                    "Raw reports are held in memory only and include supported "
                    "Dreamegg devices only."
                ),
                "report_limit_per_device": 200,
            },
            "devices": devices,
            "scene_query_error": scene_error,
            "tuya_scenes": scenes,
        },
        TO_REDACT,
    )


def _serialize_specification(specification: Any) -> dict[str, Any]:
    """Normalize Tuya function and status metadata."""
    if not isinstance(specification, Mapping):
        return {}
    result: dict[str, Any] = {}
    for code, item in specification.items():
        values = getattr(item, "values", {})
        if isinstance(values, str):
            try:
                values = json.loads(values)
            except json.JSONDecodeError:
                pass
        result[str(code)] = {
            "type": getattr(item, "type", None),
            "values": values,
        }
    return result
