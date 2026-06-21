"""API integration tests (no Docling conversion)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import paper_extract_api.database as db_module
from paper_extract_api.config import settings
from paper_extract_api.database import Base, get_db
from paper_extract_api.main import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.db"
    storage = tmp_path / "storage"
    storage.mkdir()

    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestSessionLocal = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=test_engine)

    monkeypatch.setattr(db_module, "engine", test_engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(settings, "storage_root", storage)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app, raise_server_exceptions=True) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture()
def sample_pdf(tmp_path: Path) -> Path:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n")
    return pdf


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_job_lifecycle(client: TestClient, sample_pdf: Path) -> None:
    enqueue_mock = AsyncMock(return_value=None)
    meta_mock = patch(
        "paper_extract_api.jobs_service._pdf_metadata",
        return_value={"page_count": 5},
    )
    with meta_mock, patch("paper_extract_worker.tasks.enqueue_process_job", enqueue_mock):
        create = client.post("/api/v1/jobs", json={})
        assert create.status_code == 201
        body = create.json()
        job_id = body["job_id"]
        token = body["token"]

        upload = client.post(
            f"/api/v1/jobs/{job_id}/files",
            headers={"X-Job-Token": token},
            files={"files": ("sample.pdf", sample_pdf.read_bytes(), "application/pdf")},
        )
        assert upload.status_code == 200
        assert upload.json()["total_files"] == 1

        start = client.post(
            f"/api/v1/jobs/{job_id}/start",
            headers={"X-Job-Token": token},
        )
        assert start.status_code == 200
        enqueue_mock.assert_awaited_once_with(job_id)

        status = client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"X-Job-Token": token},
        )
        assert status.status_code == 200
        assert status.json()["progress"]["total"] == 1


def test_upload_requires_token(client: TestClient, sample_pdf: Path) -> None:
    create = client.post("/api/v1/jobs", json={}).json()
    response = client.post(
        f"/api/v1/jobs/{create['job_id']}/files",
        files={"files": ("sample.pdf", sample_pdf.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 401


def test_reject_non_pdf(client: TestClient) -> None:
    create = client.post("/api/v1/jobs", json={}).json()
    response = client.post(
        f"/api/v1/jobs/{create['job_id']}/files",
        headers={"X-Job-Token": create["token"]},
        files={"files": ("bad.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
