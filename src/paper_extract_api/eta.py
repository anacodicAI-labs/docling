"""ETA estimation for jobs."""

from __future__ import annotations

from paper_extract_api.config import settings
from paper_extract_api.models import FileStatus, Job, JobFile


def estimate_file_seconds(page_count: int | None) -> float:
    pages = page_count or 1
    return max(settings.eta_minimum_seconds, pages * settings.eta_seconds_per_page)


def compute_job_eta(job: Job) -> tuple[int | None, str]:
    incomplete = [
        f
        for f in job.files
        if f.status in {FileStatus.PENDING, FileStatus.PROCESSING, FileStatus.FAILED}
    ]
    if not incomplete:
        return 0, "Complete"

    remaining = sum(estimate_file_seconds(f.page_count) for f in incomplete)
    seconds = int(round(remaining))

    if any(f.status == FileStatus.PROCESSING for f in job.files):
        return seconds, f"About {seconds // 60} min {seconds % 60} sec remaining"
    if any(f.status == FileStatus.COMPLETED for f in job.files):
        return seconds, f"About {seconds // 60} min {seconds % 60} sec remaining"
    return seconds, "Estimating…"
