"""Background job processing with crash-safe resume."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from paper_extract import extract_paper_pdf, is_extraction_complete
from paper_extract_api.config import settings
from paper_extract_api.database import SessionLocal
from paper_extract_api.jobs_service import refresh_job_status
from paper_extract_api.models import FileStatus, Job, JobFile, JobStatus
from paper_extract_api.storage import job_output_dir, job_uploads_dir, paper_output_path
from paper_extract.layout import clear_partial_outputs

log = logging.getLogger(__name__)

_arq_pool = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_job(db: Session, job_id: str) -> Job | None:
    return db.get(Job, job_id)


def _recover_interrupted_files(job: Job) -> None:
    for job_file in job.files:
        if job_file.status == FileStatus.PROCESSING:
            job_file.status = FileStatus.PENDING
            job_file.started_at = None


def _process_single_file(db: Session, job: Job, job_file: JobFile) -> None:
    uploads_dir = job_uploads_dir(job.id)
    pdf_path = uploads_dir / f"{job_file.stem}.pdf"
    if not pdf_path.is_file():
        job_file.status = FileStatus.FAILED
        job_file.error_message = f"Upload missing: {pdf_path.name}"
        job_file.completed_at = _utcnow()
        return

    output_root = job_output_dir(job.id)
    paper_dir = paper_output_path(job.id, job_file.stem)
    options = job.options or {}

    if is_extraction_complete(paper_dir, job_file.stem):
        log.info("Checkpoint skip job=%s stem=%s", job.id, job_file.stem)
        manifest_path = paper_dir / f"{job_file.stem}.manifest.json"
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        job_file.status = FileStatus.COMPLETED
        job_file.counts = manifest.get("counts")
        job_file.error_message = None
        job_file.completed_at = _utcnow()
        return

    job_file.status = FileStatus.PROCESSING
    job_file.started_at = _utcnow()
    job_file.error_message = None
    db.commit()

    clear_partial_outputs(paper_dir, job_file.stem)
    started = time.perf_counter()

    try:
        result = extract_paper_pdf(
            pdf_path,
            output_dir=output_root,
            layout=options.get("layout", settings.default_layout),
            copy_source_pdf=options.get("copy_source_pdf", settings.copy_source_pdf),
            skip_if_complete=False,
            ocr=bool(options.get("ocr", False)),
            formulas=bool(options.get("formulas", False)),
            images_scale=float(options.get("images_scale", 2.0)),
            write_element_tree=bool(options.get("write_element_tree", True)),
            write_assets=bool(options.get("write_assets", True)),
            write_links=bool(options.get("write_links", True)),
        )
        job_file.status = FileStatus.COMPLETED
        job_file.counts = result.manifest.counts
        job_file.duration_seconds = round(time.perf_counter() - started, 2)
        job_file.completed_at = _utcnow()
        log.info(
            "Completed job=%s stem=%s in %.2fs",
            job.id,
            job_file.stem,
            job_file.duration_seconds,
        )
    except Exception as exc:
        log.exception("Failed job=%s stem=%s", job.id, job_file.stem)
        job_file.status = FileStatus.FAILED
        job_file.error_message = str(exc)
        job_file.duration_seconds = round(time.perf_counter() - started, 2)
        job_file.completed_at = _utcnow()
        clear_partial_outputs(paper_dir, job_file.stem)


async def process_job(_ctx, job_id: str) -> dict:
    """Process all pending/failed files in a job (idempotent, resumable)."""
    with SessionLocal() as db:
        job = _load_job(db, job_id)
        if job is None:
            log.error("Job not found: %s", job_id)
            return {"job_id": job_id, "status": "missing"}

        job.status = JobStatus.RUNNING
        _recover_interrupted_files(job)
        db.commit()
        db.refresh(job)

        for job_file in job.files:
            if job_file.status not in {FileStatus.PENDING, FileStatus.FAILED}:
                continue
            _process_single_file(db, job, job_file)
            db.commit()

        refresh_job_status(db, job)
        db.refresh(job)
        return {"job_id": job_id, "status": job.status.value}


async def get_arq_pool():
    global _arq_pool
    if _arq_pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings

        _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _arq_pool


async def enqueue_process_job(job_id: str) -> None:
    pool = await get_arq_pool()
    await pool.enqueue_job("process_job", job_id, _queue_name=settings.arq_queue_name)


async def worker_startup(_ctx) -> None:
    from paper_extract_api.database import init_db

    init_db()
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    log.info("Worker started; storage=%s", settings.storage_root)
