"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from paper_extract_api.database import get_db
from paper_extract_api.jobs_service import get_job_or_404, verify_job_token
from paper_extract_api.models import Job


DbSession = Annotated[Session, Depends(get_db)]


def job_auth(
    job_id: str,
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
    x_job_token: Annotated[str | None, Header(alias="X-Job-Token")] = None,
) -> Job:
    job = get_job_or_404(db, job_id)
    token = x_job_token
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    verify_job_token(job, token)
    return job


AuthorizedJob = Annotated[Job, Depends(job_auth)]
