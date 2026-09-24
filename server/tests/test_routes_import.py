"""The console's Import PDF button: check, then start, then every page is queued.

The client is entered with ``with`` so the app's lifespan runs — without it the
background import task would never be driven and a green test would mean nothing
ran. The worker is a recorder: no pipeline stage runs here, only the importer.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fitz")

from pipeline import pdf_import as PI  # noqa: E402
from pipeline.tests.test_pdf_import import (  # noqa: E402
    DPI, _add_scan_page, _add_text_page, _picture, _scan_pdf)
from server import routes_import as RI  # noqa: E402
from server.app import create_app  # noqa: E402


class RecordingWorker:
    def __init__(self):
        self.enqueued: list[Path] = []

    async def start(self):
        pass

    async def stop(self):
        pass

    def enqueue(self, page_dir: Path) -> None:
        self.enqueued.append(page_dir)


@pytest.fixture
def env(tmp_path: Path):
    app = create_app()
    app.state.jobs_root = tmp_path / "jobs"
    app.state.jobs_root.mkdir()
    app.state.import_staging = tmp_path / "staging"
    app.state.worker = RecordingWorker()
    with TestClient(app) as client:
        yield app, client, tmp_path


def _check(client, pdf: Path, dpi: int = DPI):
    with open(pdf, "rb") as f:
        return client.post(f"/api/imports?dpi={dpi}",
                           files={"file": (pdf.name, f, "application/pdf")})


def _wait(client, token: str, timeout: float = 30.0) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        rec = client.get(f"/api/imports/{token}").json()
        if rec["state"] not in ("checked", "running"):
            return rec
        time.sleep(0.05)
    raise AssertionError(f"import still {rec['state']} after {timeout}s")


def test_check_surveys_the_pdf_and_creates_no_job(env):
    app, client, tmp = env
    pdf, _ = _scan_pdf(tmp)
    r = _check(client, pdf)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["state"] == "checked" and rec["page_count"] == 2 and rec["dpi"] == DPI
    assert [(p["pdf_page"], p["layout"], p["layout_source"]) for p in rec["pages"]] == [
        (1, "spread", "pdf_import_aspect"), (2, "single", "pdf_import_aspect")]
    assert rec["not_scans"] == [] and rec["estimated_bytes"] > 0
    assert "flag" in rec["modes"] and rec["lang_default"]
    assert "pdf_path" not in rec                      # server paths stay server-side
    assert list(app.state.jobs_root.iterdir()) == []  # nothing created yet
    assert (RI.uploads_root(app) / rec["token"] / "book.pdf").exists()


def test_start_publishes_the_job_and_queues_every_page_in_order(env):
    app, client, tmp = env
    pdf, _ = _scan_pdf(tmp)
    token = _check(client, pdf).json()["token"]
    r = client.post(f"/api/imports/{token}/start",
                    json={"mode": "patch", "lang": "deu", "layouts": {"1": "single"}})
    assert r.status_code == 200, r.text
    rec = _wait(client, token)
    assert rec["state"] == "done", rec
    job = app.state.jobs_root / rec["job_id"]
    assert rec["done"] == 2
    assert app.state.worker.enqueued == [job / "page_001", job / "page_002"]
    assert json.loads((job / "job.json").read_text()) == {"mode": "patch", "lang": "deu"}
    lay = [json.loads((job / p / "page_layout.json").read_text())
           for p in ("page_001", "page_002")]
    # the operator's toggle wins on page 1 and says so; page 2 keeps the survey's
    assert [(x["layout"], x["source"]) for x in lay] == [
        ("single", "operator"), ("single", "pdf_import_aspect")]
    assert not (RI.uploads_root(app) / token).exists()     # upload cleaned up
    assert r.json()["state"] == "running"


def test_a_pdf_with_a_page_made_by_software_needs_the_explicit_tick(env):
    app, client, tmp = env
    import fitz
    doc = fitz.open()
    _add_scan_page(doc, _picture(200, 280, 3))
    _add_text_page(doc)
    pdf = tmp / "mixed.pdf"
    doc.save(pdf)
    doc.close()
    rec = _check(client, pdf).json()
    assert rec["not_scans"] == [2]
    r = client.post(f"/api/imports/{rec['token']}/start", json={})
    assert r.status_code == 400 and "not scans" in r.json()["detail"]
    assert client.get(f"/api/imports/{rec['token']}").json()["state"] == "checked"
    client.post(f"/api/imports/{rec['token']}/start", json={"allow_vector": True})
    done = _wait(client, rec["token"])
    assert done["state"] == "done" and len(app.state.worker.enqueued) == 2


@pytest.mark.parametrize("payload,name", [
    (b"<html>not found</html>", "x.pdf"),
    (b"%PDF-1.4 but truncated", "y.pdf"),
    (b"%PDF-1.4", "z.png"),
])
def test_what_is_not_a_readable_pdf_is_refused_and_leaves_nothing(env, payload, name):
    app, client, tmp = env
    r = client.post("/api/imports", files={"file": (name, payload, "application/pdf")})
    assert r.status_code == 400
    root = RI.uploads_root(app)
    assert not root.exists() or list(root.iterdir()) == []
    assert app.state.imports == {}


def test_a_page_number_the_pdf_does_not_have_is_refused(env):
    app, client, tmp = env
    pdf, _ = _scan_pdf(tmp)
    token = _check(client, pdf).json()["token"]
    for bad in ({"3": "single"}, {"x": "single"}, {"1": "sideways"}):
        r = client.post(f"/api/imports/{token}/start", json={"layouts": bad})
        assert r.status_code == 400, bad
    r = client.post(f"/api/imports/{token}/start", json={"mode": "nope"})
    assert r.status_code == 400


def test_only_one_import_renders_at_a_time(env, monkeypatch):
    app, client, tmp = env
    release = threading.Event()
    real = PI.import_pdf

    def slow(*a, **k):
        release.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(RI.PI, "import_pdf", slow)
    pdf, _ = _scan_pdf(tmp)
    first = _check(client, pdf).json()["token"]
    second = _check(client, pdf).json()["token"]
    assert client.post(f"/api/imports/{first}/start", json={}).status_code == 200
    r = client.post(f"/api/imports/{second}/start", json={})
    assert r.status_code == 409
    assert client.delete(f"/api/imports/{first}").status_code == 409  # running
    release.set()
    assert _wait(client, first)["state"] == "done"
    assert client.post(f"/api/imports/{second}/start", json={}).status_code == 200
    assert _wait(client, second)["state"] == "done"
    assert client.post(f"/api/imports/{second}/start", json={}).status_code == 409


def test_a_shutdown_mid_render_cancels_and_publishes_nothing(env, monkeypatch):
    app, client, tmp = env
    real = PI.import_pdf

    def cancel_first(*a, **k):
        RI.cancel_running(app)          # what the lifespan does on shutdown
        return real(*a, **k)

    monkeypatch.setattr(RI.PI, "import_pdf", cancel_first)
    pdf, _ = _scan_pdf(tmp)
    token = _check(client, pdf).json()["token"]
    client.post(f"/api/imports/{token}/start", json={})
    rec = _wait(client, token)
    assert rec["state"] == "failed" and "shut down" in rec["error"]
    assert list(app.state.jobs_root.iterdir()) == []
    assert app.state.worker.enqueued == []


def test_discard_removes_a_checked_upload(env):
    app, client, tmp = env
    pdf, _ = _scan_pdf(tmp)
    token = _check(client, pdf).json()["token"]
    assert client.delete(f"/api/imports/{token}").json()["discarded"] is True
    assert not (RI.uploads_root(app) / token).exists()
    assert client.get(f"/api/imports/{token}").status_code == 404


def test_uploads_never_live_inside_the_importers_staging(env):
    """import_pdf wipes <staging>/<job_id>; no upload may be reachable that way."""
    app, client, tmp = env
    root = RI.uploads_root(app)
    staging = Path(app.state.import_staging)
    assert root.parent == staging.parent and root != staging
    assert staging not in root.parents


def test_the_job_records_the_pdfs_own_name(env):
    app, client, tmp = env
    pdf, _ = _scan_pdf(tmp, name="Спасработы 1983.pdf")
    token = _check(client, pdf).json()["token"]
    client.post(f"/api/imports/{token}/start", json={})
    job = app.state.jobs_root / _wait(client, token)["job_id"]
    assert json.loads((job / "import.json").read_text(encoding="utf-8"))["pdf"] ==         "Спасработы 1983.pdf"


@pytest.mark.parametrize("given,saved", [
    ("../../evil.pdf", "evil.pdf"), (r"a/b\c:d?.pdf", "c_d_.pdf"), (None, "upload.pdf"),
    ("..", "upload.pdf"), ("...pdf", "pdf.pdf")])
def test_an_uploaded_name_cannot_leave_its_folder(given, saved):
    assert RI._safe_name(given) == saved
