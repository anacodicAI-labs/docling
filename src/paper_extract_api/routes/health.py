"""Health and readiness endpoints."""

from __future__ import annotations

from pathlib import Path

import redis
from fastapi import APIRouter
from sqlalchemy import text

from paper_extract_api.config import settings
from paper_extract_api.database import SessionLocal
from paper_extract_api.schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
def ready() -> ReadyResponse:
    checks: dict[str, str] = {}

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"

    try:
        client = redis.from_url(settings.redis_url)
        client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    storage = settings.storage_root
    try:
        storage.mkdir(parents=True, exist_ok=True)
        probe = storage / ".ready_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks["storage"] = "ok"
    except Exception as exc:
        checks["storage"] = f"error: {exc}"

    hf_cache = Path(__file__).resolve().parents[2] / ".cache" / "huggingface"
    checks["hf_cache"] = "ok" if hf_cache.exists() else "missing (models download on first run)"

    overall = "ok" if all(v == "ok" or v.startswith("missing") for k, v in checks.items() if k != "hf_cache") else "degraded"
    if checks.get("database") != "ok" or checks.get("redis") != "ok" or checks.get("storage") != "ok":
        overall = "error"

    return ReadyResponse(status=overall, checks=checks)
