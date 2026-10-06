"""Regression coverage for firmware labels, independent of desktop metadata."""

import json
from pathlib import Path

import pytest

from custom_components.tuya_dreamegg.music import MUSIC_NAMES, VERIFIED_MUSIC_NAMES
from custom_components.tuya_dreamegg.schedules import SOUND_NAMES

ROOT = Path(__file__).parents[1]
CAPTURES = json.loads(
    (Path(__file__).parent / "fixtures/music_label_captures.json").read_text()
)


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda item: item["label"])
def test_music_name_matches_native_capture_and_translation(capture) -> None:
    """Display the sound actually observed for the firmware value."""
    strings = json.loads(
        (ROOT / "custom_components/tuya_dreamegg/strings.json").read_text()
    )
    code, label = capture["value"], capture["label"]
    assert VERIFIED_MUSIC_NAMES[code] == label
    assert MUSIC_NAMES[code] == label
    assert SOUND_NAMES[int(code)] == label
    assert strings["entity"]["select"]["music_selection"]["state"][code] == label


def test_native_catalog_covers_every_firmware_sound_id() -> None:
    """The confirmed native catalog contains all 34 values exactly once."""
    assert list(MUSIC_NAMES) == [str(value) for value in range(1, 35)]
    assert len(CAPTURES) == 34
    assert {capture["value"] for capture in CAPTURES} == set(MUSIC_NAMES)
    assert set(VERIFIED_MUSIC_NAMES) == set(MUSIC_NAMES)
