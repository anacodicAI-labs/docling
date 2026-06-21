"""Output layout helpers and extraction checkpoint detection."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Literal

OutputLayout = Literal["flat", "folder"]


def resolve_paper_output_dir(
    base_output_dir: Path,
    stem: str,
    layout: OutputLayout = "flat",
) -> Path:
    """Return the directory where a single paper's artifacts are written."""
    base = base_output_dir.expanduser().resolve()
    if layout == "folder":
        return base / stem
    return base


def paper_artifact_paths(output_dir: Path, stem: str) -> dict[str, Path]:
    """Predictable artifact paths for a paper inside *output_dir*."""
    return {
        "docling_json": output_dir / f"{stem}.docling.json",
        "artifacts_dir": output_dir / f"{stem}_artifacts",
        "links_json": output_dir / f"{stem}.links.json",
        "assets_dir": output_dir / f"{stem}.assets",
        "element_tree_txt": output_dir / f"{stem}.elements.txt",
        "manifest_json": output_dir / f"{stem}.manifest.json",
        "source_pdf": output_dir / f"{stem}.pdf",
    }


def is_extraction_complete(output_dir: Path, stem: str) -> bool:
    """True when a valid manifest exists (checkpoint for crash resume)."""
    manifest_path = output_dir / f"{stem}.manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    counts = data.get("counts")
    return isinstance(counts, dict) and "pages" in counts


def clear_partial_outputs(output_dir: Path, stem: str) -> None:
    """Remove incomplete artifacts before retrying a failed file."""
    paths = paper_artifact_paths(output_dir, stem)
    for key, path in paths.items():
        if key == "source_pdf":
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)
