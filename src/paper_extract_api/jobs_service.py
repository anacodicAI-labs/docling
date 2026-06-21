"""Job lifecycle business logic."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from paper_extract.converter import _pdf_metadata
from paper_extract_api.config import settings
from paper_extract_api.eta import compute_job_eta
from paper_extract_api.models import FileStatus, Job, JobFile, JobStatus
from paper_extract_api.schemas import (
    CreateJobResponse,
    JobEta,
    JobFileResponse,
    JobProgress,
    JobResponse,
    StartJobResponse,
    UploadFilesResponse,
)
from paper_extract_api.storage import (
    ensure_job_dirs,
    is_pdf_bytes,
    job_uploads_dir,
    sanitize_stem,
    unique_stem,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_job(db: Session, options: dict[str, Any]) -> CreateJobResponse:
    job = Job(
        token=secrets.token_urlsafe(32),
        status=JobStatus.CREATED,
        options=options,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    ensure_job_dirs(job.id)
    return CreateJobResponse(
        job_id=job.id,
        token=job.token,
        status=job.status.value,
        upload_url=f"{settings.api_prefix}/jobs/{job.id}/files",
    )


def get_job_or_404(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


def verify_job_token(job: Job, token: str | None) -> None:
    if token is None or token != job.token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid job token")


def _progress(job: Job) -> JobProgress:
    total = len(job.files)
    completed = sum(1 for f in job.files if f.status == FileStatus.COMPLETED)
    failed = sum(1 for f in job.files if f.status == FileStatus.FAILED)
    processing = sum(1 for f in job.files if f.status == FileStatus.PROCESSING)
    pending = sum(1 for f in job.files if f.status == FileStatus.PENDING)
    percent = (completed / total * 100.0) if total else 0.0
    return JobProgress(
        total=total,
        completed=completed,
        failed=failed,
        pending=pending,
        processing=processing,
        percent=round(percent, 1),
    )


def job_to_response(job: Job) -> JobResponse:
    eta_seconds, eta_label = compute_job_eta(job)
    return JobResponse(
        job_id=job.id,
        status=job.status.value,
        options=job.options,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        progress=_progress(job),
        eta=JobEta(seconds_remaining=eta_seconds, label=eta_label),
        files=[
            JobFileResponse(
                id=f.id,
                stem=f.stem,
                original_filename=f.original_filename,
                status=f.status.value,
                page_count=f.page_count,
                error_message=f.error_message,
                duration_seconds=f.duration_seconds,
                counts=f.counts,
                started_at=f.started_at,
                completed_at=f.completed_at,
            )
            for f in job.files
        ],
    )


async def upload_files(
    db: Session,
    job: Job,
    uploads: list[UploadFile],
) -> UploadFilesResponse:
    if job.status not in {JobStatus.CREATED, JobStatus.UPLOADING}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot upload files while job status is {job.status.value}",
        )

    if not uploads:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")

    if len(job.files) + len(uploads) > settings.max_files_per_job:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {settings.max_files_per_job} files per job",
        )

    uploads_dir = job_uploads_dir(job.id)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    used_stems = {f.stem for f in job.files}
    saved: list[str] = []
    existing_bytes = sum(p.stat().st_size for p in uploads_dir.glob("*.pdf"))
    running_bytes = existing_bytes

    for upload in uploads:
        filename = upload.filename or "paper.pdf"
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Not a PDF filename: {filename}",
            )

        data = await upload.read()
        running_bytes += len(data)
        if running_bytes > settings.max_batch_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Batch exceeds max size of {settings.max_batch_bytes} bytes",
            )
        if len(data) > settings.max_pdf_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{filename} exceeds max size of {settings.max_pdf_bytes} bytes",
            )
        if not is_pdf_bytes(data):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{filename} is not a valid PDF",
            )

        stem = unique_stem(sanitize_stem(filename), used_stems)
        pdf_path = uploads_dir / f"{stem}.pdf"
        pdf_path.write_bytes(data)

        meta = _pdf_metadata(pdf_path)
        job_file = JobFile(
            job_id=job.id,
            stem=stem,
            original_filename=filename,
            page_count=int(meta.get("page_count") or 0) or None,
        )
        db.add(job_file)
        saved.append(stem)

    job.status = JobStatus.UPLOADING
    db.commit()
    db.refresh(job)

    total_pages = sum(f.page_count or 0 for f in job.files)
    return UploadFilesResponse(
        job_id=job.id,
        uploaded=saved,
        total_files=len(job.files),
        total_pages=total_pages,
    )


async def enqueue_job(db: Session, job: Job) -> StartJobResponse:
    if not job.files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload at least one PDF")

    if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
        return StartJobResponse(
            job_id=job.id,
            status=job.status.value,
            message="Job already queued or running",
        )

    job.status = JobStatus.QUEUED
    if job.started_at is None:
        job.started_at = _utcnow()
    db.commit()

    from paper_extract_worker.tasks import enqueue_process_job

    await enqueue_process_job(job.id)

    return StartJobResponse(
        job_id=job.id,
        status=job.status.value,
        message="Job queued for processing",
    )


def refresh_job_status(db: Session, job: Job) -> None:
    if job.status in {JobStatus.CREATED, JobStatus.UPLOADING, JobStatus.QUEUED}:
        return

    if not job.files:
        return

    completed = sum(1 for f in job.files if f.status == FileStatus.COMPLETED)
    failed = sum(1 for f in job.files if f.status == FileStatus.FAILED)
    active = sum(
        1
        for f in job.files
        if f.status in {FileStatus.PENDING, FileStatus.PROCESSING}
    )

    if active:
        job.status = JobStatus.RUNNING
    elif completed == len(job.files):
        job.status = JobStatus.COMPLETED
        job.completed_at = _utcnow()
    elif completed > 0 and failed > 0:
        job.status = JobStatus.PARTIAL
        job.completed_at = _utcnow()
    elif failed == len(job.files):
        job.status = JobStatus.FAILED
        job.completed_at = _utcnow()

    db.commit()
