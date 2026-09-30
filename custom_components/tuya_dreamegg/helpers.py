"""Helpers shared by Dreamegg entity platforms."""

import json
from collections.abc import Mapping
from typing import Any

from .const import SUPPORTED_CATEGORY, SUPPORTED_PRODUCT_IDS


def is_supported_device(device: Any) -> bool:
    """Return whether a Tuya device is a supported Dreamegg model."""
    return (
        getattr(device, "category", None) == SUPPORTED_CATEGORY
        and getattr(device, "product_id", None) in SUPPORTED_PRODUCT_IDS
    )


def datapoint_values(device: Any, dpcode: str) -> dict[str, Any]:
    """Return normalized metadata for one Tuya datapoint."""
    for collection_name in ("function", "status_range"):
        collection = getattr(device, collection_name, None)
        if not isinstance(collection, Mapping) or dpcode not in collection:
            continue
        raw_values = getattr(collection[dpcode], "values", None)
        if isinstance(raw_values, str):
            try:
                values = json.loads(raw_values)
            except json.JSONDecodeError:
                continue
        elif isinstance(raw_values, dict):
            values = raw_values
        else:
            continue
        if isinstance(values, dict):
            return values
    return {}


def has_writable_datapoint(device: Any, dpcode: str) -> bool:
    """Return whether the device advertises a writable datapoint."""
    functions = getattr(device, "function", None)
    return isinstance(functions, Mapping) and dpcode in functions
