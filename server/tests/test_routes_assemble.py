"""HTTP-level tests for server.routes_assemble (POST /api/jobs/{id}/assemble).

Seeds a minimal Stage-06-shaped page directly on disk (same shape
pipeline/tests/test_stage07_assemble.py builds — one subpage, one block, two
words), so stage07_assemble.run() actually has something real to assemble;
this exercises the real in-process call, not a mocked one.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from pipeline.page_model import Block, Word
from pipeline.stage06_uncertainty import PatchRef, ResolvedPage, UncertaintyResult
from server.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app()
    app.state.jobs_root = tmp_path
    return TestClient(app)


def _seed_page(job_dir: Path, mode: str = "flag") -> None:
    page = job_dir / "page_001"
    (page / "03_dewarp").mkdir(parents=True)
    (page / "06_uncertain").mkdir(parents=True)
    cv2.imwrite(str(page / "03_dewarp" / "single.png"),
                np.full((120, 200, 3), 255, np.uint8))

    words = [
        Word(text="Roma", bbox={"x": 10, "y": 10, "w": 40, "h": 20},
             conf=92.0, decision="keep", block_id=0),
        Word(text="caput", bbox={"x": 60, "y": 10, "w": 40, "h": 20},
             conf=40.0, decision=mode, block_id=0),
    ]
    blocks = [Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": 200, "h": 120},
                     reading_order=0, words=words)]
    resolved = UncertaintyResult(
        mode=mode, threshold=75.0, threshold_raw=80.0, flag_rate_target=0.1,
        conf_floor=45.0, conf_ceiling=75.0, scored_words=2,
        pages=[ResolvedPage(name="single.png", width=200, height=120,
                             blocks=blocks, patches=[])])
    (page / "06_uncertain" / "resolved.json").write_text(
        resolved.model_dump_json(indent=2), encoding="utf-8")


def test_assemble_404_unknown_job(client: TestClient):
    r = client.post("/api/jobs/does-not-exist/assemble")
    assert r.status_code == 404


def test_assemble_400_when_no_pages_ready(client: TestClient):
    job_id = client.post("/api/jobs").json()["job_id"]
    r = client.post(f"/api/jobs/{job_id}/assemble")
    assert r.status_code == 400


def test_assemble_success(client: TestClient, tmp_path: Path):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_page(tmp_path / job_id)

    r = client.post(f"/api/jobs/{job_id}/assemble")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["pages"] == 1
    assert (tmp_path / job_id / "document.json").exists()


def test_assemble_defaults_to_auto_order(client: TestClient, tmp_path: Path):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_page(tmp_path / job_id)
    body = client.post(f"/api/jobs/{job_id}/assemble").json()
    assert body["order_mode"] == "auto"


def test_assemble_order_mode_review_persists(client: TestClient, tmp_path: Path):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_page(tmp_path / job_id)
    r = client.post(f"/api/jobs/{job_id}/assemble?order_mode=review")
    assert r.status_code == 200, r.text
    assert r.json()["order_mode"] == "review"
    import json
    d = json.loads((tmp_path / job_id / "document.json").read_text(encoding="utf-8"))
    assert d["settings"]["order_mode"] == "review"


def test_assemble_rejects_bad_order_mode(client: TestClient, tmp_path: Path):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_page(tmp_path / job_id)
    r = client.post(f"/api/jobs/{job_id}/assemble?order_mode=bogus")
    assert r.status_code == 422


def test_assemble_409_refuses_clobber_without_force(client: TestClient, tmp_path: Path):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_page(tmp_path / job_id)
    client.post(f"/api/jobs/{job_id}/assemble")

    # mark an edit the way the editor's save_document would (normalize_edits
    # sets word.edited when text diverges from text_ocr)
    doc_path = tmp_path / job_id / "document.json"
    doc = doc_path.read_text(encoding="utf-8")
    import json
    d = json.loads(doc)
    d["pages"][0]["blocks"][0]["words"][0]["text"] = "ROMA-EDITED"
    d["pages"][0]["blocks"][0]["words"][0]["edited"] = True
    doc_path.write_text(json.dumps(d), encoding="utf-8")

    r = client.post(f"/api/jobs/{job_id}/assemble")
    assert r.status_code == 409


def test_assemble_force_overwrites_edits(client: TestClient, tmp_path: Path):
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_page(tmp_path / job_id)
    client.post(f"/api/jobs/{job_id}/assemble")

    doc_path = tmp_path / job_id / "document.json"
    import json
    d = json.loads(doc_path.read_text(encoding="utf-8"))
    d["pages"][0]["blocks"][0]["words"][0]["text"] = "ROMA-EDITED"
    d["pages"][0]["blocks"][0]["words"][0]["edited"] = True
    doc_path.write_text(json.dumps(d), encoding="utf-8")

    r = client.post(f"/api/jobs/{job_id}/assemble?force=true")
    assert r.status_code == 200
    reassembled = json.loads(doc_path.read_text(encoding="utf-8"))
    assert reassembled["pages"][0]["blocks"][0]["words"][0]["text"] == "Roma"


# --------------------------------------------------------------------------
# Refreshing one spread, and saying which pages were left out
# --------------------------------------------------------------------------


def _two_spreads_with_an_edit_on_the_first(client: TestClient, tmp_path: Path) -> str:
    import json
    import shutil
    job_id = client.post("/api/jobs").json()["job_id"]
    job = tmp_path / job_id
    _seed_page(job)
    shutil.copytree(job / "page_001", job / "page_002")
    assert client.post(f"/api/jobs/{job_id}/assemble").json()["pages"] == 2
    doc_path = job / "document.json"
    d = json.loads(doc_path.read_text(encoding="utf-8"))
    d["pages"][0]["blocks"][0]["words"][0].update(text="ROMA-EDITED", edited=True)
    doc_path.write_text(json.dumps(d), encoding="utf-8")
    return job_id


def test_refreshing_an_unedited_spread_keeps_the_edits_elsewhere(
        client: TestClient, tmp_path: Path):
    import json
    job_id = _two_spreads_with_an_edit_on_the_first(client, tmp_path)
    r = client.post(f"/api/jobs/{job_id}/assemble?spread=page_002")
    assert r.status_code == 200, r.text
    assert r.json()["refreshed"] == ["page_002"] and r.json()["pages"] == 2
    d = json.loads((tmp_path / job_id / "document.json").read_text(encoding="utf-8"))
    assert d["pages"][0]["blocks"][0]["words"][0]["text"] == "ROMA-EDITED"


def test_refreshing_an_edited_spread_is_409_until_forced(
        client: TestClient, tmp_path: Path):
    import json
    job_id = _two_spreads_with_an_edit_on_the_first(client, tmp_path)
    r = client.post(f"/api/jobs/{job_id}/assemble?spread=page_001")
    assert r.status_code == 409 and "page_001" in r.json()["detail"]
    r = client.post(f"/api/jobs/{job_id}/assemble?spread=page_001&force=true")
    assert r.status_code == 200
    d = json.loads((tmp_path / job_id / "document.json").read_text(encoding="utf-8"))
    assert d["pages"][0]["blocks"][0]["words"][0]["text"] == "Roma"


def test_refresh_rejects_a_name_that_is_not_a_page(client: TestClient, tmp_path: Path):
    job_id = _two_spreads_with_an_edit_on_the_first(client, tmp_path)
    assert client.post(
        f"/api/jobs/{job_id}/assemble?spread=../x").status_code == 400
    # a real page name with nothing to assemble is the client's to fix, not a 500
    assert client.post(
        f"/api/jobs/{job_id}/assemble?spread=page_077").status_code == 400


def test_assemble_names_the_pages_it_left_out(client: TestClient, tmp_path: Path):
    import json
    job_id = client.post("/api/jobs").json()["job_id"]
    job = tmp_path / job_id
    _seed_page(job)
    (job / "page_002" / "raw").mkdir(parents=True)
    (job / "page_002" / "worker.json").write_text(
        json.dumps({"state": "running"}), encoding="utf-8")
    (job / "page_003").mkdir()
    (job / "page_003" / "run_all.json").write_text(
        json.dumps({"ok": False, "failed_stage": "03_dewarp"}), encoding="utf-8")
    r = client.post(f"/api/jobs/{job_id}/assemble").json()
    assert r["not_in_document"] == [
        {"page": "page_002", "why": "still being processed"},
        {"page": "page_003", "why": "failed at 03_dewarp"}]
    assert r["stale"] == []
