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
    # Match on the id, not on the whole row: the list carries extra facts for
    # the console and the phone's job picker (page count, mode, mtime), and
    # adding one must not be a breaking change.
    row = next(j for j in r.json()["jobs"] if j["job_id"] == job_id)
    assert row["pages"] == 0 and row["mode"] == "flag"


def test_status_404_for_unknown_job(client: TestClient):
    assert client.get("/api/jobs/does-not-exist").status_code == 404


def test_status_shape_for_fresh_job(client: TestClient):
    job_id = client.post("/api/jobs").json()["job_id"]
    body = client.get(f"/api/jobs/{job_id}").json()
    assert body["job_id"] == job_id
    assert body["mode"] == "flag"
    assert body["pages"] == []
    assert body["has_document"] is False
    assert body["has_render"] is False


def test_create_job_with_mode(client: TestClient):
    r = client.post("/api/jobs", params={"mode": "patch"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    assert r.json()["mode"] == "patch"
    assert client.get(f"/api/jobs/{job_id}").json()["mode"] == "patch"


def test_create_job_rejects_invalid_mode(client: TestClient):
    r = client.post("/api/jobs", params={"mode": "not-a-mode"})
    assert r.status_code == 400


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


def test_upload_preserves_a_sweep_origin_marker(client: TestClient, tmp_path: Path):
    """A swept close-up and a tapped one are the same kind of file, so the only
    way to tell later which a page's frames came from is the marker the app puts
    in the part's name. Stage 00 copies the saved name into ``ingest.json``'s
    ``source``, so keeping it here is what makes that question answerable."""
    job_id = client.post("/api/jobs").json()["job_id"]
    files = [
        ("files", ("frame_00.jpg", io.BytesIO(b"anchor"), "image/jpeg")),
        ("files", ("frame_01_sweep.jpg", io.BytesIO(b"swept"), "image/jpeg")),
    ]
    r = client.post(f"/api/jobs/{job_id}/pages", files=files)
    assert r.json()["files"] == ["frame_00.jpg", "frame_01_sweep.jpg"]

    raw_dir = tmp_path / job_id / "page_001" / "raw"
    assert (raw_dir / "frame_01_sweep.jpg").read_bytes() == b"swept"


def test_upload_index_is_arrival_order_not_the_client_s_claim(client: TestClient):
    """Only the marker is taken from the uploaded name. The index is the
    server's, so a client cannot renumber a page's frames by naming them."""
    job_id = client.post("/api/jobs").json()["job_id"]
    files = [
        ("files", ("frame_09_sweep.jpg", io.BytesIO(b"a"), "image/jpeg")),
        ("files", ("frame_04_sweep.jpg", io.BytesIO(b"b"), "image/jpeg")),
    ]
    r = client.post(f"/api/jobs/{job_id}/pages", files=files)
    assert r.json()["files"] == ["frame_00_sweep.jpg", "frame_01_sweep.jpg"]


@pytest.mark.parametrize("name", [
    "frame_00_notatag.jpg",     # not on the whitelist
    "frame_00_SWEEP.jpg",       # the whitelist is lowercase
    "frame_00_sweep_extra.jpg",  # more than one trailing segment
    "sweep.jpg",                 # no frame prefix at all
])
def test_upload_drops_an_unrecognised_marker(client: TestClient, name: str):
    """An unknown or malformed marker falls back to the plain name rather than
    reaching the filesystem — the filename comes from a client."""
    job_id = client.post("/api/jobs").json()["job_id"]
    files = [("files", (name, io.BytesIO(b"x"), "image/jpeg"))]
    r = client.post(f"/api/jobs/{job_id}/pages", files=files)
    assert r.json()["files"] == ["frame_00.jpg"]


def test_upload_marker_cannot_escape_the_page_folder(client: TestClient, tmp_path: Path):
    """A filename comes from a client, so a path-shaped one must not become a
    path. Only the marker survives, and the folder is the server's."""
    job_id = client.post("/api/jobs").json()["job_id"]
    files = [("files", ("../../frame_00_sweep.jpg", io.BytesIO(b"x"), "image/jpeg"))]
    r = client.post(f"/api/jobs/{job_id}/pages", files=files)
    assert r.json()["files"] == ["frame_00_sweep.jpg"]
    assert (tmp_path / job_id / "page_001" / "raw" / "frame_00_sweep.jpg").exists()
    assert not (tmp_path.parent / "frame_00_sweep.jpg").exists()


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
