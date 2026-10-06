"""Decode Dreamegg schedule datapoints from captured Tuya raw reports."""

from base64 import b64decode, b64encode
from binascii import Error as Base64DecodeError
from collections.abc import Mapping
from typing import Any

from .music import VERIFIED_MUSIC_NAMES

SCHEDULE_RECORD_COUNT = 6
SCHEDULE_RECORD_SIZE = 20
SCHEDULE_PAYLOAD_SIZE = SCHEDULE_RECORD_COUNT * SCHEDULE_RECORD_SIZE
ROUTINE_NAMES = (
    "Okay to Wake",
    "First Nap",
    "Play Time",
    "Last Nap",
    "Wind Down",
    "Bed Time",
)
SOUND_NAMES = {int(code): name for code, name in VERIFIED_MUSIC_NAMES.items()}
LIGHT_MODE_NAMES = {2: "Solid Color", 3: "Sunlight", 4: "Sunrise"}


def decode_schedule_payload(value: Any) -> list[dict[str, Any]] | None:
    """Decode the confirmed fields in a six-record schedule payload.

    The payload layout is based on controlled diagnostics. Fields whose
    semantics are still uncertain are returned as raw byte values.
    """
    if not isinstance(value, str):
        return None
    try:
        payload = b64decode(value, validate=True)
    except Base64DecodeError, ValueError:
        return None
    if len(payload) != SCHEDULE_PAYLOAD_SIZE:
        return None

    slots: list[dict[str, Any]] = []
    for index in range(SCHEDULE_RECORD_COUNT):
        start = index * SCHEDULE_RECORD_SIZE
        record = payload[start : start + SCHEDULE_RECORD_SIZE]
        slots.append(
            {
                "slot": index + 1,
                "enabled": bool(record[0]),
                "unknown_1": record[1],
                "light_mode_code": record[2],
                "light_mode_name": LIGHT_MODE_NAMES.get(record[2]),
                "unknown_3_4": list(record[3:5]),
                "light_config": list(record[5:9]),
                "light_brightness_raw": int.from_bytes(record[9:11], "big"),
                "unknown_11": record[11],
                "sound_id": record[12],
                "sound_name": SOUND_NAMES.get(record[12]),
                "volume": record[13],
                "start_minute": int.from_bytes(record[14:16], "big"),
                "duration_minutes": int.from_bytes(record[16:18], "big"),
                "repeat_mask": record[18],
                "special_light_enabled": bool(record[19]),
            }
        )
    return slots


def decode_latest_schedule_reports(
    reports: list[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]] | None]:
    """Decode the latest captured alarm and routine table, when available."""
    latest: dict[int, tuple[int, Any]] = {}
    for report in reports:
        dp_id = report.get("dp_id")
        timestamp = report.get("timestamp")
        if dp_id not in (15, 112) or not isinstance(timestamp, int):
            continue
        previous = latest.get(dp_id)
        if previous is None or timestamp >= previous[0]:
            latest[dp_id] = (timestamp, report.get("value"))

    alarms = decode_schedule_payload(latest[112][1]) if 112 in latest else None
    routines = decode_schedule_payload(latest[15][1]) if 15 in latest else None
    if routines is not None:
        for slot, name in zip(routines, ROUTINE_NAMES, strict=True):
            slot["name"] = name

    return {"alarms": alarms, "routines": routines}


def update_schedule_payload(
    value: Any,
    slot: int,
    changes: Mapping[str, Any],
) -> str:
    """Update confirmed fields in one slot while preserving unknown bytes."""
    payload = _decode_payload(value)
    if not 1 <= slot <= SCHEDULE_RECORD_COUNT:
        raise ValueError("slot must be between 1 and 6")
    if not changes:
        raise ValueError("at least one field must be changed")

    record_start = (slot - 1) * SCHEDULE_RECORD_SIZE
    fields = {
        "enabled": (0, 1, "bool"),
        "light_mode_code": (2, 1, "byte"),
        "light_brightness_raw": (9, 2, "brightness"),
        "sound_id": (12, 1, "byte"),
        "volume": (13, 1, "volume"),
        "start_minute": (14, 2, "start_minute"),
        "duration_minutes": (16, 2, "duration"),
        "repeat_mask": (18, 1, "repeat_mask"),
        "special_light_enabled": (19, 1, "bool"),
    }

    for name, new_value in changes.items():
        if name not in fields:
            raise ValueError(f"unsupported schedule field: {name}")
        offset, width, value_type = fields[name]
        if value_type == "bool":
            if not isinstance(new_value, bool):
                raise ValueError(f"{name} must be a boolean")
            encoded = bytes([int(new_value)])
        else:
            minimum, maximum = {
                "byte": (0, 255),
                "brightness": (0, 1000),
                "volume": (0, 100),
                "start_minute": (0, 1439),
                "duration": (0, 1440),
                "repeat_mask": (0, 127),
            }[value_type]
            if (
                isinstance(new_value, bool)
                or not isinstance(new_value, int)
                or not minimum <= new_value <= maximum
            ):
                raise ValueError(
                    f"{name} must be an integer from {minimum} to {maximum}"
                )
            encoded = new_value.to_bytes(width, "big")
        begin = record_start + offset
        payload[begin : begin + width] = encoded

    return b64encode(payload).decode()


def _decode_payload(value: Any) -> bytearray:
    """Decode and validate one 120-byte schedule payload."""
    if not isinstance(value, str):
        raise ValueError("schedule payload must be base64 text")
    try:
        payload = b64decode(value, validate=True)
    except (Base64DecodeError, ValueError) as error:
        raise ValueError("schedule payload is not valid base64") from error
    if len(payload) != SCHEDULE_PAYLOAD_SIZE:
        raise ValueError("schedule payload must be exactly 120 bytes")
    return bytearray(payload)
