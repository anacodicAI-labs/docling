"""Extract PDF hyperlinks (DOIs, URLs) via PyMuPDF as a sidecar."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def extract_pdf_links(pdf_path: Path) -> list[dict[str, Any]]:
    """Return hyperlink annotations with page number and bounding box."""
    import fitz

    doc = fitz.open(str(pdf_path))
    links: list[dict[str, Any]] = []

    for page_index in range(doc.page_count):
        page = doc[page_index]
        for link in page.get_links():
            rect = link.get("from")
            entry: dict[str, Any] = {
                "page_no": page_index + 1,
                "kind": link.get("kind"),
                "uri": link.get("uri"),
                "file": link.get("file"),
                "page": link.get("page"),
                "xref": link.get("xref"),
            }
            if rect is not None:
                entry["bbox"] = {
                    "l": round(rect.x0, 2),
                    "t": round(rect.y0, 2),
                    "r": round(rect.x1, 2),
                    "b": round(rect.y1, 2),
                }
            links.append(entry)

    doc.close()
    return links


def write_links_sidecar(pdf_path: Path, output_path: Path) -> list[dict[str, Any]]:
    links = extract_pdf_links(pdf_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(links, indent=2, ensure_ascii=False), encoding="utf-8")
    return links
