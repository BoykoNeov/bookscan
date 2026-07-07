"""HTTP-level tests for server.routes_editor — the job-scoped SPA + its API,
mounted under /jobs/{job_id}/.

Seeds a real assembled document (via stage07_assemble, same seed helper as
test_routes_assemble.py) rather than hand-writing document.json, so these
tests exercise the real load_document/save_document/render_preview functions
lifted from pipeline/editor.py, not a mocked document shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from pipeline.page_model import Block, Word
from pipeline.stage04_layout import load_config
from pipeline.stage06_uncertainty import ResolvedPage, UncertaintyResult
from pipeline import stage07_assemble as S7
from server.app import REPO_ROOT, create_app

CFG = load_config(REPO_ROOT / "config.yaml")


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app()
    app.state.jobs_root = tmp_path
    return TestClient(app)


def _seed_and_assemble(job_dir: Path, cfg: dict) -> None:
    page = job_dir / "page_001"
    (page / "03_dewarp").mkdir(parents=True)
    (page / "06_uncertain").mkdir(parents=True)
    cv2.imwrite(str(page / "03_dewarp" / "single.png"),
                np.full((120, 200, 3), 255, np.uint8))
    words = [Word(text="Roma", bbox={"x": 10, "y": 10, "w": 40, "h": 20},
                   conf=92.0, decision="keep", block_id=0)]
    blocks = [Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": 200, "h": 120},
                     reading_order=0, words=words)]
    resolved = UncertaintyResult(
        mode="flag", threshold=75.0, threshold_raw=80.0, flag_rate_target=0.1,
        conf_floor=45.0, conf_ceiling=75.0, scored_words=1,
        pages=[ResolvedPage(name="single.png", width=200, height=120,
                             blocks=blocks, patches=[])])
    (page / "06_uncertain" / "resolved.json").write_text(
        resolved.model_dump_json(indent=2), encoding="utf-8")
    S7.run(job_dir, cfg)


def _make_job(client: TestClient, tmp_path: Path) -> str:
    job_id = client.post("/api/jobs").json()["job_id"]
    _seed_and_assemble(tmp_path / job_id, CFG)
    return job_id


def test_no_trailing_slash_redirects(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    r = client.get(f"/jobs/{job_id}", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == f"/jobs/{job_id}/"


def test_index_serves_spa_for_known_job(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    r = client.get(f"/jobs/{job_id}/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_index_404_for_unknown_job(client: TestClient):
    r = client.get("/jobs/does-not-exist/")
    assert r.status_code == 404


def test_meta(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    r = client.get(f"/jobs/{job_id}/api/meta")
    assert r.status_code == 200
    assert r.json()["job"] == job_id


def test_get_document(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    r = client.get(f"/jobs/{job_id}/api/document")
    assert r.status_code == 200
    doc = r.json()
    assert doc["pages"][0]["blocks"][0]["words"][0]["text"] == "Roma"


def test_put_document_round_trips_edit(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    doc = client.get(f"/jobs/{job_id}/api/document").json()
    doc["pages"][0]["blocks"][0]["words"][0]["text"] = "Roma-edited"

    r = client.put(f"/jobs/{job_id}/api/document", content=json.dumps(doc))
    assert r.status_code == 200, r.text
    assert r.json()["has_edits"] is True

    reread = client.get(f"/jobs/{job_id}/api/document").json()
    w = reread["pages"][0]["blocks"][0]["words"][0]
    assert w["text"] == "Roma-edited"
    assert w["edited"] is True                # normalize_edits set this server-side
    assert w["text_ocr"] == "Roma"             # provenance untouched


def test_put_document_rejects_malformed_body(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    r = client.put(f"/jobs/{job_id}/api/document", content="not json")
    assert r.status_code == 400


def test_render_then_fetch_html(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    r = client.post(f"/jobs/{job_id}/api/render")
    assert r.status_code == 200
    assert r.json()["href"] == "render/page.html"

    html = client.get(f"/jobs/{job_id}/render/page.html")
    assert html.status_code == 200
    assert b"Roma" in html.content


def test_render_page_404_before_first_render(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    r = client.get(f"/jobs/{job_id}/render/page.html")
    assert r.status_code == 404


def test_get_asset_serves_the_page_image(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    doc = client.get(f"/jobs/{job_id}/api/document").json()
    image_asset = doc["pages"][0]["image_asset"]  # e.g. "document_assets/page_001__single.png"
    assert image_asset.startswith("document_assets/")

    r = client.get(f"/jobs/{job_id}/{image_asset}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_get_asset_rejects_path_traversal(client: TestClient, tmp_path: Path):
    job_id = _make_job(client, tmp_path)
    r = client.get(f"/jobs/{job_id}/document_assets/../../document.json")
    assert r.status_code in (403, 404)
