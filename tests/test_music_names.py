"""Regression coverage for firmware labels, independent of desktop metadata."""

import json
from pathlib import Path

import pytest

from custom_components.tuya_dreamegg.music import MUSIC_NAMES, VERIFIED_MUSIC_NAMES

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
    assert strings["entity"]["select"]["music_selection"]["state"][code] == label


def test_unverified_desktop_labels_are_not_presented_as_real_sounds() -> None:
    """Keep every valid ID available without relabeling unknown firmware tracks."""
    assert list(MUSIC_NAMES) == [str(value) for value in range(1, 35)]
    for code, name in MUSIC_NAMES.items():
        if code not in VERIFIED_MUSIC_NAMES:
            assert name == f"Sound {code}"
