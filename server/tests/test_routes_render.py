"""HTTP-level tests for server.routes_render (POST/GET .../render, .../render/pdf).

Stubs ``asyncio.create_subprocess_exec`` (same technique as test_worker.py)
rather than actually running ``pipeline.stage08_render`` — that needs
Playwright/Chromium installed and is exercised for real by the slow e2e test
in test_worker_e2e.py. These tests cover the route's own logic: preconditions,
argv, error propagation, and the PDF download path.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app()
    app.state.jobs_root = tmp_path
    return TestClient(app)


def _seed_document(job_dir: Path) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "document.json").write_text("{}", encoding="utf-8")


def _stub_success(monkeypatch, wrote_pdf: bool = True) -> dict:
    """Fakes a successful stage08_render subprocess: writes the same
    render/{page.html,page.pdf,meta.json} shape the real stage writes, keyed
    off the job_dir passed as the subprocess's last positional arg."""
    captured: dict = {}

    class _FakeProc:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        job_dir = Path(args[-1])
        render_dir = job_dir / "render"
        render_dir.mkdir(parents=True, exist_ok=True)
        (render_dir / "page.html").write_text("<html></html>", encoding="utf-8")
        if wrote_pdf:
            (render_dir / "page.pdf").write_bytes(b"%PDF-1.4 fake")
        (render_dir / "meta.json").write_text(json.dumps({
            "params": {"pages": 1, "words": 5, "figures": 0, "mode": "flag",
                       "wrote_pdf": wrote_pdf},
        }), encoding="utf-8")
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return captured


def test_render_404_unknown_job(client: TestClient):
    r = client.post("/api/jobs/does-not-exist/render")
    assert r.status_code == 404


def test_render_400_without_document(client: TestClient):
    job_id = client.post("/api/jobs").json()["job_id"]
    r = client.post(f"/api/jobs/{job_id}/render")
    assert r.status_code == 400


def test_render_success(client: TestClient, tmp_path: Path, monkeypatch):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_document(tmp_path / job_id)
    captured = _stub_success(monkeypatch)

    r = client.post(f"/api/jobs/{job_id}/render")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["wrote_pdf"] is True
    assert body["pdf_href"] == "render/pdf"
    assert body["pages"] == 1

    args = captured["args"]
    assert "pipeline.stage08_render" in args
    assert args[-1] == str(tmp_path / job_id)


def test_render_success_without_pdf(client: TestClient, tmp_path: Path, monkeypatch):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_document(tmp_path / job_id)
    _stub_success(monkeypatch, wrote_pdf=False)

    r = client.post(f"/api/jobs/{job_id}/render")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wrote_pdf"] is False
    assert body["pdf_href"] is None


def test_render_500_on_subprocess_failure(client: TestClient, tmp_path: Path, monkeypatch):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_document(tmp_path / job_id)

    class _FakeFailedProc:
        returncode = 1

        async def communicate(self):
            return b"", b"boom: missing document_assets"

    async def fake_exec(*args, **kwargs):
        return _FakeFailedProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    r = client.post(f"/api/jobs/{job_id}/render")
    assert r.status_code == 500
    assert "boom: missing document_assets" in r.text


def test_get_pdf_404_before_render(client: TestClient):
    job_id = client.post("/api/jobs").json()["job_id"]
    r = client.get(f"/api/jobs/{job_id}/render/pdf")
    assert r.status_code == 404


def test_get_pdf_serves_file_after_render(client: TestClient, tmp_path: Path, monkeypatch):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_document(tmp_path / job_id)
    _stub_success(monkeypatch)
    client.post(f"/api/jobs/{job_id}/render")

    r = client.get(f"/api/jobs/{job_id}/render/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content == b"%PDF-1.4 fake"
