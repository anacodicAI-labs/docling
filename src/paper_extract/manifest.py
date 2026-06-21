"""Build a small manifest summarizing an extraction run."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ExtractionManifest:
    source_pdf: str
    stem: str
    output_dir: str
    docling_json: str
    artifacts_dir: str
    links_json: str
    assets_dir: str
    element_tree_txt: str
    image_mode: str
    counts: dict[str, int] = field(default_factory=dict)
    pdf_metadata: dict[str, Any] = field(default_factory=dict)
    extracted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
