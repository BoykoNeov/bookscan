"""HTTP-level tests for server.routes_jobs via FastAPI's TestClient.

The app's real config.yaml is loaded (create_app() does that at import), but
jobs_root is swapped to an isolated tmp_path per test so nothing touches the
real jobs/ dir. No pipeline stage runs here — Step 2 only writes uploaded
bytes to <page>/raw/; wiring the worker onto this endpoint is Step 3.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app()
    app.state.jobs_root = tmp_path
    return TestClient(app)


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_create_and_list_job(client: TestClient):
    job_id = client.post("/api/jobs").json()["job_id"]

    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert {"job_id": job_id} in r.json()["jobs"]


def test_status_404_for_unknown_job(client: TestClient):
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_status_shape_for_fresh_job(client: TestClient):
    job_id = client.post("/api/jobs").json()["job_id"]
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["job_id"] == job_id
    assert body["pages"] == []
    assert body["has_document"] is False
    assert body["has_render"] is False


def test_upload_writes_raw_frames(client: TestClient, tmp_path: Path):
    job_id = client.post("/api/jobs").json()["job_id"]
    files = [
        ("files", ("anchor.jpg", io.BytesIO(b"fake-jpeg-bytes"), "image/jpeg")),
        ("files", ("closeup.png", io.BytesIO(b"fake-png-bytes"), "image/png")),
    ]
    r = client.post(f"/api/jobs/{job_id}/pages", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == "page_001"
    assert body["files"] == ["frame_00.jpg", "frame_01.png"]

    raw_dir = tmp_path / job_id / "page_001" / "raw"
    assert (raw_dir / "frame_00.jpg").read_bytes() == b"fake-jpeg-bytes"
    assert (raw_dir / "frame_01.png").read_bytes() == b"fake-png-bytes"


def test_upload_second_page_increments(client: TestClient):
    job_id = client.post("/api/jobs").json()["job_id"]
    one_file = [("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg"))]
    client.post(f"/api/jobs/{job_id}/pages", files=one_file)
    r = client.post(f"/api/jobs/{job_id}/pages", files=one_file)
    assert r.json()["page"] == "page_002"


def test_upload_rejects_bad_extension(client: TestClient):
    job_id = client.post("/api/jobs").json()["job_id"]
    files = [("files", ("doc.txt", io.BytesIO(b"x"), "text/plain"))]
    r = client.post(f"/api/jobs/{job_id}/pages", files=files)
    assert r.status_code == 400


def test_upload_rejects_unknown_job(client: TestClient):
    files = [("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg"))]
    r = client.post("/api/jobs/does-not-exist/pages", files=files)
    assert r.status_code == 404
