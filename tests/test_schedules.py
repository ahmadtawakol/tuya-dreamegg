"""Tests for decoding the captured Dreamegg alarm and routine tables."""

from base64 import b64decode, b64encode

from custom_components.tuya_dreamegg.schedules import (
    decode_latest_schedule_reports,
    decode_schedule_payload,
    update_schedule_payload,
)


def _encode_records(first_record: bytes) -> str:
    """Encode a six-slot table with one populated record."""
    return b64encode(first_record + bytes(20 * 5)).decode()


def test_decode_alarm_record() -> None:
    """Decode known alarm fields and retain unconfirmed bytes verbatim."""
    value = _encode_records(
        bytes.fromhex("01 01 04 00 00 00 00 00 00 03 e8 00 02 5a 01 6a 00 1e 1e 00")
    )

    slots = decode_schedule_payload(value)

    assert slots is not None
    assert len(slots) == 6
    assert slots[0] == {
        "slot": 1,
        "enabled": True,
        "unknown_1": 1,
        "light_mode_code": 4,
        "light_mode_name": "Sunrise",
        "unknown_3_4": [0, 0],
        "light_config": [0, 0, 0, 0],
        "light_brightness_raw": 1000,
        "unknown_11": 0,
        "sound_id": 2,
        "sound_name": "Sea Wave",
        "volume": 90,
        "start_minute": 362,
        "duration_minutes": 30,
        "repeat_mask": 30,
        "special_light_enabled": False,
    }


def test_decode_routine_record() -> None:
    """Decode a routine's time, duration, repeat mask, and light flag."""
    value = _encode_records(
        bytes.fromhex("01 01 03 00 00 00 00 00 00 03 e8 01 20 50 01 68 00 1e 1f 00")
    )

    slots = decode_schedule_payload(value)

    assert slots is not None
    assert slots[0]["start_minute"] == 360
    assert slots[0]["duration_minutes"] == 30
    assert slots[0]["repeat_mask"] == 31
    assert slots[0]["light_mode_name"] == "Sunlight"
    assert slots[0]["sound_id"] == 32
    assert slots[0]["sound_name"] == "Morning"
    assert slots[0]["volume"] == 80
    assert slots[0]["special_light_enabled"] is False


def test_decode_latest_schedule_reports() -> None:
    """Choose the newest report per table and keep table types distinct."""
    older = _encode_records(bytes(20))
    newer_record = bytes.fromhex(
        "01 01 04 00 00 00 00 00 00 03 e8 00 01 64 01 68 00 0f 1f 01"
    )
    newer = _encode_records(newer_record)
    tables = decode_latest_schedule_reports(
        [
            {"dp_id": 112, "timestamp": 1, "value": older},
            {"dp_id": 112, "timestamp": 2, "value": newer},
            {"dp_id": 15, "timestamp": 3, "value": older},
        ]
    )

    assert tables["alarms"] is not None
    assert tables["alarms"][0]["start_minute"] == 360
    assert tables["routines"] is not None
    assert tables["routines"][0]["enabled"] is False
    assert tables["routines"][0]["name"] == "Okay to Wake"


def test_invalid_schedule_payload_is_ignored() -> None:
    """Ignore non-base64 values and payloads of an unexpected size."""
    assert decode_schedule_payload("not-base64!") is None
    assert decode_schedule_payload(b64encode(bytes(20)).decode()) is None


def test_update_schedule_preserves_unmapped_bytes() -> None:
    """Editing known fields leaves every unrecognized table byte unchanged."""
    first = bytes.fromhex("01 01 02 00 f1 03 e8 03 e8 03 e8 01 0f 3c 05 0a 03 0c 7f 01")
    original = first + bytes(range(100))
    encoded = b64encode(original).decode()

    updated = b64decode(
        update_schedule_payload(
            encoded,
            2,
            {
                "enabled": True,
                "start_minute": 570,
                "duration_minutes": 60,
                "repeat_mask": 126,
            },
        )
    )

    assert updated[:20] == original[:20]
    assert updated[20] == 1
    assert updated[34:36] == (570).to_bytes(2, "big")
    assert updated[36:38] == (60).to_bytes(2, "big")
    assert updated[38] == 126
    assert updated[39] == original[39]
    assert updated[40:] == original[40:]


def test_update_schedule_rejects_unsupported_or_out_of_range_fields() -> None:
    """Reject unknown fields and invalid UI values before building a write."""
    encoded = _encode_records(bytes(20))

    try:
        update_schedule_payload(encoded, 1, {"unknown_11": 0})
    except ValueError as error:
        assert "unsupported schedule field" in str(error)
    else:
        raise AssertionError("unsupported fields must be rejected")

    try:
        update_schedule_payload(encoded, 1, {"volume": 101})
    except ValueError as error:
        assert "volume must be an integer" in str(error)
    else:
        raise AssertionError("out-of-range values must be rejected")
