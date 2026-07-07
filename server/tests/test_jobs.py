"""Unit tests for server.jobs — pure filesystem-derived job lifecycle, no HTTP."""

from __future__ import annotations

from pathlib import Path

from pipeline.page_model import StageMeta
from server import jobs as J


def test_create_job_mints_unique_dir(tmp_path: Path):
    id1 = J.create_job(tmp_path)
    id2 = J.create_job(tmp_path)
    assert id1 != id2
    assert (tmp_path / id1).is_dir()
    assert (tmp_path / id2).is_dir()


def test_resolve_job_dir_rejects_traversal_and_unknown(tmp_path: Path):
    assert J.resolve_job_dir(tmp_path, "../etc") is None
    assert J.resolve_job_dir(tmp_path, "a/b") is None
    assert J.resolve_job_dir(tmp_path, "nonexistent") is None


def test_resolve_job_dir_finds_real_job(tmp_path: Path):
    job_id = J.create_job(tmp_path)
    assert J.resolve_job_dir(tmp_path, job_id) == tmp_path / job_id


def test_list_jobs(tmp_path: Path):
    id1 = J.create_job(tmp_path)
    id2 = J.create_job(tmp_path)
    ids = {j["job_id"] for j in J.list_jobs(tmp_path)}
    assert ids == {id1, id2}


def test_next_page_dir_starts_at_001(tmp_path: Path):
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    assert J.next_page_dir(job_dir).name == "page_001"


def test_next_page_dir_increments_past_existing(tmp_path: Path):
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "page_001").mkdir()
    (job_dir / "page_003").mkdir()  # gap — next is max+1, not fill-the-gap
    assert J.next_page_dir(job_dir).name == "page_004"


def test_page_status_no_stages_run_yet(tmp_path: Path):
    page_dir = tmp_path / "page_001"
    page_dir.mkdir()
    status = J.page_status(page_dir)
    assert status["name"] == "page_001"
    assert status["run_all"] is None
    assert all(v is None for v in status["stages"].values())


def test_page_status_reads_stage_meta(tmp_path: Path):
    page_dir = tmp_path / "page_001"
    stage_dir = page_dir / "00_ingest"
    stage_dir.mkdir(parents=True)
    meta = StageMeta(stage="00_ingest", version="0.1.0", warnings=["hi"])
    (stage_dir / "meta.json").write_text(meta.model_dump_json())

    status = J.page_status(page_dir)
    assert status["stages"]["00_ingest"] == {
        "ok": True, "warnings": ["hi"], "timings_ms": {}}


def test_job_status_aggregates_pages(tmp_path: Path):
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "page_001").mkdir()
    (job_dir / "page_002").mkdir()
    (job_dir / "not_a_page").mkdir()  # ignored — doesn't match page_NNN

    status = J.job_status(job_dir)
    assert [p["name"] for p in status["pages"]] == ["page_001", "page_002"]
    assert status["has_document"] is False
    assert status["has_render"] is False


def test_job_status_detects_document_and_render(tmp_path: Path):
    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "document.json").write_text("{}")
    (job_dir / "render").mkdir()
    (job_dir / "render" / "page.html").write_text("<html></html>")

    status = J.job_status(job_dir)
    assert status["has_document"] is True
    assert status["has_render"] is True
