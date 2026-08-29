"""The page inspector: what it shows, and the two things it must never do.

The endpoints are read-only over the immutable per-page trace, so the tests that
matter most are the negative ones — that serving an artifact cannot be talked
into leaving the page directory, and that looking at a page does not modify it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from server.app import create_app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"paths:\n  jobs: {json.dumps(str(tmp_path / 'jobs'))}\n",
                   encoding="utf-8")
    app = create_app(cfg)
    with TestClient(app) as c:
        yield c


def _page(client, job="j1", page="page_001") -> Path:
    root = client.app.state.jobs_root
    d = root / job / page
    (d / "debug").mkdir(parents=True, exist_ok=True)
    (root / job / "job.json").write_text(json.dumps({"mode": "flag"}), encoding="utf-8")
    return d


def _png(path: Path, w=400, h=300) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.full((h, w, 3), 180, np.uint8)).save(path)


# --------------------------------------------------------------------------
# It shows the page's story
# --------------------------------------------------------------------------


def test_inspect_lists_only_the_overlays_that_exist(client):
    d = _page(client)
    _png(d / "debug" / "02_split.png")
    _png(d / "debug" / "04_layout.png")
    r = client.get("/api/jobs/j1/pages/page_001/inspect")
    assert r.status_code == 200
    paths = [o["path"] for o in r.json()["overlays"]]
    assert paths == ["debug/02_split.png", "debug/04_layout.png"]


def test_inspect_counts_why_each_closeup_was_rejected(client):
    """The rejection FAMILY is the operator-actionable fact, not the raw note.

    317 close-ups over one book collapsed to four families; a list of 311 notes
    would have told nobody anything.
    """
    d = _page(client)
    (d / "01_fuse").mkdir()
    (d / "01_fuse" / "fuse.json").write_text(json.dumps({
        "method": "sharpest", "n_frames": 4, "anchor_source": "frame_00.png",
        "closeups": [
            {"matched": False, "note": "only 5 inliers (need 8)"},
            {"matched": False, "note": "only 6 inliers (need 8)"},
            {"matched": True, "note": "ok"},
        ]}), encoding="utf-8")
    fu = client.get("/api/jobs/j1/pages/page_001/inspect").json()["fuse"]
    assert fu["closeups_used"] == 1 and fu["closeups_total"] == 3
    assert fu["rejections"] == {"only 5 inliers": 1, "only 6 inliers": 1}


def test_words_are_returned_in_reading_order_with_their_verdict(client):
    d = _page(client)
    (d / "06_uncertain").mkdir()
    (d / "06_uncertain" / "resolved.json").write_text(json.dumps({
        "mode": "flag", "threshold": 50.0, "pages": [{
            "name": "left.png", "width": 100, "height": 200,
            "counts": {"keep": 1, "flag": 1},
            "blocks": [
                {"id": 1, "type": "paragraph", "reading_order": 1,
                 "bbox": {"x": 0, "y": 50, "w": 10, "h": 10},
                 "words": [{"text": "second", "conf": 90.0, "decision": "keep",
                            "bbox": {"x": 0, "y": 50, "w": 10, "h": 10}}]},
                {"id": 0, "type": "heading", "reading_order": 0,
                 "bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
                 "words": [{"text": "first", "conf": 12.0, "decision": "flag",
                            "bbox": {"x": 0, "y": 0, "w": 10, "h": 10}}]},
            ]}]}), encoding="utf-8")
    d_ = client.get("/api/jobs/j1/pages/page_001/words").json()
    sub = d_["pages"][0]
    assert [b["reading_order"] for b in sub["blocks"]] == [0, 1]
    assert sub["blocks"][0]["words"][0]["decision"] == "flag"
    # The boxes belong to the DEWARPED image, not the split one.
    assert sub["image"] == "03_dewarp/left.png"


def test_a_page_with_no_stage06_says_so_rather_than_500(client):
    _page(client)
    assert client.get("/api/jobs/j1/pages/page_001/words").status_code == 404


def test_an_unreadable_artifact_does_not_break_the_view(client):
    """Half a JSON file must render as 'nothing to show', not as an error page."""
    d = _page(client)
    (d / "02_split").mkdir()
    (d / "02_split" / "split.json").write_text("{ truncated", encoding="utf-8")
    r = client.get("/api/jobs/j1/pages/page_001/inspect")
    assert r.status_code == 200 and r.json()["split"] is None


# --------------------------------------------------------------------------
# Previews
# --------------------------------------------------------------------------


def test_image_is_downscaled_to_the_requested_width(client):
    d = _page(client)
    _png(d / "debug" / "02_split.png", 2000, 1500)
    r = client.get("/api/jobs/j1/pages/page_001/image",
                   params={"path": "debug/02_split.png", "w": 320})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    import io
    assert Image.open(io.BytesIO(r.content)).size[0] == 320


def test_an_unchanged_image_is_not_sent_twice(client):
    d = _page(client)
    _png(d / "debug" / "02_split.png")
    p = {"path": "debug/02_split.png", "w": 200}
    first = client.get("/api/jobs/j1/pages/page_001/image", params=p)
    again = client.get("/api/jobs/j1/pages/page_001/image", params=p,
                       headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and not again.content


# --------------------------------------------------------------------------
# What it must never do
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    "../../config.yaml",
    "../page_002/debug/02_split.png",
    "..\\..\\config.yaml",
])
def test_the_image_route_cannot_be_walked_out_of_the_page_directory(client, bad):
    _page(client)
    r = client.get("/api/jobs/j1/pages/page_001/image", params={"path": bad})
    assert r.status_code in (400, 404)


def test_a_non_image_artifact_is_refused_even_inside_the_page(client):
    """``split.json`` is readable through /inspect, which shapes it. The image
    route is not a general file server for the page directory."""
    d = _page(client)
    (d / "02_split").mkdir()
    (d / "02_split" / "split.json").write_text("{}", encoding="utf-8")
    r = client.get("/api/jobs/j1/pages/page_001/image",
                   params={"path": "02_split/split.json"})
    assert r.status_code == 400


def test_a_bogus_page_name_is_rejected_before_any_filesystem_work(client):
    _page(client)
    assert client.get("/api/jobs/j1/pages/..%2F..%2Fetc/inspect").status_code in (400, 404)
    assert client.get("/api/jobs/j1/pages/notapage/inspect").status_code == 400


def test_inspecting_a_page_writes_nothing(client):
    d = _page(client)
    _png(d / "debug" / "02_split.png")
    before = {p: p.stat().st_mtime_ns for p in d.rglob("*") if p.is_file()}
    client.get("/api/jobs/j1/pages/page_001/inspect")
    client.get("/api/jobs/j1/pages/page_001/image",
               params={"path": "debug/02_split.png"})
    after = {p: p.stat().st_mtime_ns for p in d.rglob("*") if p.is_file()}
    assert before == after, "the inspector must not touch the immutable trace"


def test_rerun_goes_through_the_worker_and_does_not_run_a_stage_itself(client):
    """The one mutating endpoint. It must ENQUEUE — a web handler that ran a
    stage in-process would be a second execution path and would block the loop.
    """
    d = _page(client)
    seen = []
    client.app.state.worker.enqueue = seen.append
    r = client.post("/api/jobs/j1/pages/page_001/rerun")
    assert r.status_code == 200 and seen == [d]
    assert json.loads((d / "worker.json").read_text(encoding="utf-8"))["state"] == "queued"


# --------------------------------------------------------------------------
# The console itself
# --------------------------------------------------------------------------


def test_the_console_is_served_at_the_root(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>bookscan</title>" in r.text


def test_the_job_list_carries_what_a_chooser_needs(client):
    _page(client, "j1", "page_001")
    _page(client, "j1", "page_002")
    rows = client.get("/api/jobs").json()["jobs"]
    row = next(j for j in rows if j["job_id"] == "j1")
    assert row["pages"] == 2 and row["mode"] == "flag"
    assert row["has_document"] is False


def test_the_job_list_puts_the_newest_first(client, tmp_path):
    """`jobs/` holds every harness run too. An alphabetical list buries the book
    someone shot an hour ago under fixtures named `bg_01`."""
    import os
    import time
    root = client.app.state.jobs_root
    for name, age_s in [("zzz_old", 4000), ("aaa_new", 0), ("mmm_mid", 2000)]:
        d = root / name / "page_001"
        d.mkdir(parents=True)
        t = time.time() - age_s
        os.utime(root / name, (t, t))
    ids = [j["job_id"] for j in client.get("/api/jobs").json()["jobs"]]
    assert ids == ["aaa_new", "mmm_mid", "zzz_old"]
