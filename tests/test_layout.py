"""Layout and checkpoint tests."""

from __future__ import annotations

import json
from pathlib import Path

from paper_extract.layout import (
    is_extraction_complete,
    paper_artifact_paths,
    resolve_paper_output_dir,
)
from paper_extract_api.storage import sanitize_stem, unique_stem


def test_sanitize_stem() -> None:
    assert sanitize_stem("2508.19093v2.pdf") == "2508.19093v2"
    assert sanitize_stem("weird name!!.pdf") == "weird_name"


def test_unique_stem() -> None:
    used: set[str] = set()
    assert unique_stem("paper", used) == "paper"
    assert unique_stem("paper", used) == "paper-2"


def test_folder_layout_paths(tmp_path: Path) -> None:
    base = tmp_path / "output"
    paper_dir = resolve_paper_output_dir(base, "demo", "folder")
    assert paper_dir == base / "demo"
    paths = paper_artifact_paths(paper_dir, "demo")
    assert paths["manifest_json"].name == "demo.manifest.json"


def test_checkpoint_detection(tmp_path: Path) -> None:
    paper_dir = tmp_path / "demo"
    paper_dir.mkdir()
    assert not is_extraction_complete(paper_dir, "demo")

    manifest = paper_dir / "demo.manifest.json"
    manifest.write_text(json.dumps({"counts": {"pages": 1}}), encoding="utf-8")
    assert is_extraction_complete(paper_dir, "demo")
