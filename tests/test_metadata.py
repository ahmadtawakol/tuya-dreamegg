"""Tests for HACS and Home Assistant metadata."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "tuya_dreamegg"


def _load_json(path: Path) -> dict:
    """Load a JSON object."""
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def test_manifest_and_hacs_versions_match() -> None:
    """Package metadata declares a stable installable version."""
    manifest = _load_json(INTEGRATION / "manifest.json")
    hacs = _load_json(ROOT / "hacs.json")

    assert manifest["domain"] == "tuya_dreamegg"
    assert manifest["version"] == "0.2.0"
    assert manifest["after_dependencies"] == ["tuya"]
    assert hacs["homeassistant"] == "2026.9.0"


def test_english_translation_matches_source_strings() -> None:
    """The checked-in English translation is synchronized."""
    assert _load_json(INTEGRATION / "translations" / "en.json") == _load_json(
        INTEGRATION / "strings.json"
    )


def test_readme_documents_hacs_and_manual_installation() -> None:
    """Users can install and remove the integration safely."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Custom repositories" in readme
    assert "custom_components/tuya_dreamegg" in readme
    assert "Removal" in readme
