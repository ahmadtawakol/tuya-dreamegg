"""Privacy-bounded capture of Dreamegg raw Tuya datapoint reports."""

from collections import deque
from collections.abc import Mapping
from copy import deepcopy
from threading import Lock
from typing import Any

from .helpers import is_supported_device

DEVICE_REPORT_PROTOCOL = 4
MAX_REPORTS_PER_DEVICE = 200


class RawDpCapture:
    """Capture raw reports only for supported Dreamegg devices in memory."""

    def __init__(self) -> None:
        """Initialize a raw report capture."""
        self._reports: dict[str, deque[dict[str, Any]]] = {}
        self._device_strategies: dict[str, dict[str, Any]] = {}
        self._lock = Lock()
        self._message_source: Any | None = None

    def attach(self, manager: Any | None) -> None:
        """Attach to the current official Tuya MQTT manager if available."""
        device_map = getattr(manager, "device_map", None)
        device_strategies: dict[str, dict[str, Any]] = {}
        if isinstance(device_map, Mapping):
            for device in device_map.values():
                if not is_supported_device(device):
                    continue
                local_strategy = getattr(device, "local_strategy", None)
                strategy = local_strategy if isinstance(local_strategy, Mapping) else {}
                device_strategies[device.id] = {
                    str(dp_id): value for dp_id, value in strategy.items()
                }
        with self._lock:
            self._device_strategies = device_strategies

        source = getattr(manager, "mq", None)
        if source is self._message_source:
            return
        self.detach()
        add_listener = getattr(source, "add_message_listener", None)
        if callable(add_listener):
            add_listener(self._capture_message)
            self._message_source = source

    def detach(self) -> None:
        """Detach from the previously observed Tuya MQTT manager."""
        remove_listener = getattr(self._message_source, "remove_message_listener", None)
        if callable(remove_listener):
            remove_listener(self._capture_message)
        self._message_source = None

    def _capture_message(self, message: dict[str, Any]) -> None:
        """Retain bounded raw reports for supported clocks only."""
        if message.get("protocol") != DEVICE_REPORT_PROTOCOL:
            return
        data = message.get("data")
        if not isinstance(data, Mapping):
            return
        device_id = data.get("devId")
        if not isinstance(device_id, str):
            return
        status = data.get("status")
        if not isinstance(status, list):
            return

        with self._lock:
            normalized_strategy = self._device_strategies.get(device_id)
        if normalized_strategy is None:
            return
        reports: list[dict[str, Any]] = []
        for item in status:
            if not isinstance(item, Mapping) or "dpId" not in item:
                continue
            dp_id = item["dpId"]
            mapping = normalized_strategy.get(str(dp_id))
            reports.append(
                {
                    "dp_id": dp_id,
                    "known_code": (
                        mapping.get("status_code")
                        if isinstance(mapping, Mapping)
                        else None
                    ),
                    "timestamp": item.get("t"),
                    "value": deepcopy(item.get("value")),
                }
            )
        if not reports:
            return
        with self._lock:
            device_reports = self._reports.setdefault(
                device_id, deque(maxlen=MAX_REPORTS_PER_DEVICE)
            )
            device_reports.extend(reports)

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Return a stable copy of the retained raw reports."""
        with self._lock:
            return {
                device_id: deepcopy(list(reports))
                for device_id, reports in self._reports.items()
            }
