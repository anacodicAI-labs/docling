"""Filesystem layout for job uploads and outputs."""

from __future__ import annotations

import re
from pathlib import Path

from paper_extract_api.config import settings

PDF_MAGIC = b"%PDF"
STEM_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_stem(filename: str) -> str:
    stem = Path(filename).stem.strip() or "paper"
    stem = STEM_PATTERN.sub("_", stem).strip("._")
    return stem or "paper"


def is_pdf_bytes(data: bytes) -> bool:
    return len(data) >= 4 and data[:4] == PDF_MAGIC


def job_root(job_id: str) -> Path:
    return settings.storage_root / "jobs" / job_id


def job_uploads_dir(job_id: str) -> Path:
    return job_root(job_id) / "uploads"


def job_output_dir(job_id: str) -> Path:
    return job_root(job_id) / "output"


def ensure_job_dirs(job_id: str) -> tuple[Path, Path]:
    uploads = job_uploads_dir(job_id)
    output = job_output_dir(job_id)
    uploads.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    return uploads, output


def unique_stem(stem: str, used: set[str]) -> str:
    if stem not in used:
        used.add(stem)
        return stem
    index = 2
    while True:
        candidate = f"{stem}-{index}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def paper_output_path(job_id: str, stem: str) -> Path:
    return job_output_dir(job_id) / stem
