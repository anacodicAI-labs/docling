"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobOptions(BaseModel):
    ocr: bool = False
    ocr_engine: str = "auto"
    ocr_full_page: bool = False
    ocr_lang: list[str] = Field(default_factory=list)
    formulas: bool = False
    code_enrichment: bool = False
    picture_classification: bool = False
    picture_description: bool = False
    device: str = "auto"
    threads: int | None = None
    table_mode: str = "accurate"
    output_format: str = "json"
    images_scale: float = 2.0
    write_element_tree: bool = True
    write_assets: bool = True
    write_links: bool = True
    layout: str = "folder"
    copy_source_pdf: bool = True
    chunk: bool = False
    chunk_tokenizer: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_max_tokens: int | None = None
    chunk_overlap: int = 0


class CreateJobRequest(BaseModel):
    options: JobOptions = Field(default_factory=JobOptions)


class CreateJobResponse(BaseModel):
    job_id: str
    token: str
    status: str
    upload_url: str


class JobFileResponse(BaseModel):
    id: str
    stem: str
    original_filename: str
    status: str
    page_count: int | None = None
    error_message: str | None = None
    duration_seconds: float | None = None
    counts: dict[str, Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JobProgress(BaseModel):
    total: int
    completed: int
    failed: int
    pending: int
    processing: int
    percent: float


class JobEta(BaseModel):
    seconds_remaining: int | None = None
    label: str


class JobResponse(BaseModel):
    job_id: str
    status: str
    options: dict[str, Any]
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    progress: JobProgress
    eta: JobEta
    files: list[JobFileResponse]


class UploadFilesResponse(BaseModel):
    job_id: str
    uploaded: list[str]
    total_files: int
    total_pages: int


class StartJobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]
