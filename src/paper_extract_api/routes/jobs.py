"""Job CRUD and processing endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from paper_extract_api.deps import AuthorizedJob, DbSession
from paper_extract_api.jobs_service import (
    create_job,
    enqueue_job,
    job_to_response,
    upload_files,
)
from paper_extract_api.schemas import (
    CreateJobRequest,
    CreateJobResponse,
    JobResponse,
    StartJobResponse,
    UploadFilesResponse,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=CreateJobResponse, status_code=201)
def create_job_route(body: CreateJobRequest, db: DbSession) -> CreateJobResponse:
    return create_job(db, body.options.model_dump())


@router.post("/{job_id}/files", response_model=UploadFilesResponse)
async def upload_job_files_route(
    job: AuthorizedJob,
    db: DbSession,
    files: Annotated[list[UploadFile], File()],
) -> UploadFilesResponse:
    return await upload_files(db, job, files)


@router.post("/{job_id}/start", response_model=StartJobResponse)
async def start_job_route(job: AuthorizedJob, db: DbSession) -> StartJobResponse:
    return await enqueue_job(db, job)


@router.get("/{job_id}", response_model=JobResponse)
def get_job_route(job: AuthorizedJob, db: DbSession) -> JobResponse:
    from paper_extract_api.jobs_service import refresh_job_status

    refresh_job_status(db, job)
    db.refresh(job)
    return job_to_response(job)
