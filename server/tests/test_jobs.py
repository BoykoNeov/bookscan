"""Unit tests for server.jobs — pure filesystem-derived job lifecycle, no HTTP."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
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


def test_create_job_defaults_to_flag_mode(tmp_path: Path):
    job_id = J.create_job(tmp_path)
    assert J.job_mode(tmp_path / job_id) == "flag"


def test_create_job_persists_requested_mode(tmp_path: Path):
    job_id = J.create_job(tmp_path, mode="patch")
    assert J.job_mode(tmp_path / job_id) == "patch"
    assert J.job_status(tmp_path / job_id)["mode"] == "patch"


def test_create_job_rejects_invalid_mode(tmp_path: Path):
    import pytest
    with pytest.raises(ValueError):
        J.create_job(tmp_path, mode="not-a-mode")


def test_job_mode_defaults_when_job_json_missing(tmp_path: Path):
    # a job dir with no job.json at all (e.g. created before this setting
    # existed) must still resolve to the flag default, not raise.
    job_dir = tmp_path / "legacy-job"
    job_dir.mkdir()
    assert J.job_mode(job_dir) == "flag"


# ---- stages left over from an earlier run (handoff 2026-11-12 item 2) --------

_T0 = 1_700_000_000.0          # an arbitrary fixed epoch, so no test sleeps


def _stage(page_dir: Path, name: str, at: float) -> None:
    d = page_dir / name
    d.mkdir(parents=True, exist_ok=True)
    m = d / "meta.json"
    m.write_text(StageMeta(stage=name, version="0.1.0").model_dump_json())
    os.utime(m, (at, at))


def _run_all(page_dir: Path, *, started: float | None, ok: bool,
             failed: str | None, ran: list[str]) -> None:
    rec = {"page_dir": str(page_dir), "ok": ok, "failed_stage": failed,
           "stages": [{"name": n, "ok": n != failed} for n in ran]}
    if started is not None:
        rec["started_at"] = datetime.fromtimestamp(started, timezone.utc).isoformat()
    (page_dir / "run_all.json").write_text(json.dumps(rec))


def test_failed_rerun_marks_the_unreached_stages_stale(tmp_path: Path):
    page = tmp_path / "page_001"
    for i, n in enumerate(J.STAGE_ORDER):          # yesterday's full run
        _stage(page, n, _T0 + i)
    start = _T0 + 86_400                           # today's re-run fails at 03
    for i, n in enumerate(J.STAGE_ORDER[:3]):
        _stage(page, n, start + 1 + i)
    _run_all(page, started=start, ok=False, failed="03_dewarp",
             ran=["00_ingest", "01_fuse", "02_split", "03_dewarp"])

    st = J.page_status(page)["stages"]
    assert [n for n in J.STAGE_ORDER if st[n].get("stale")] == [
        "03_dewarp", "04_layout", "05_ocr", "06_uncertain"]
    assert st["04_layout"]["stale_reason"] == "run_failed"
    assert st["02_split"] == {"ok": True, "warnings": [], "timings_ms": {}}


def test_a_stage_the_run_says_it_wrote_is_never_stale_whatever_the_clock(tmp_path: Path):
    """The run summary outranks file times: a disk clock running behind the
    machine clock must not paint this run's own output hollow."""
    page = tmp_path / "page_001"
    start = _T0 + 86_400
    for n in J.STAGE_ORDER[:3]:
        _stage(page, n, start - 3600)              # mtimes an hour BEFORE start
    _run_all(page, started=start, ok=False, failed="03_dewarp",
             ran=["00_ingest", "01_fuse", "02_split", "03_dewarp"])

    st = J.page_status(page)["stages"]
    assert not any(st[n].get("stale") for n in J.STAGE_ORDER[:3])


def test_a_summary_without_started_at_marks_nothing_run_failed(tmp_path: Path):
    page = tmp_path / "page_001"
    for i, n in enumerate(J.STAGE_ORDER):
        _stage(page, n, _T0 + i)
    _run_all(page, started=None, ok=False, failed="03_dewarp",
             ran=["00_ingest", "01_fuse", "02_split", "03_dewarp"])

    st = J.page_status(page)["stages"]
    assert not any(st[n].get("stale") for n in J.STAGE_ORDER)


def test_a_successful_run_marks_nothing(tmp_path: Path):
    page = tmp_path / "page_001"
    start = _T0
    for i, n in enumerate(J.STAGE_ORDER):
        _stage(page, n, start + 1 + i)
    _run_all(page, started=start, ok=True, failed=None, ran=list(J.STAGE_ORDER))

    st = J.page_status(page)["stages"]
    assert not any(st[n].get("stale") for n in J.STAGE_ORDER)


def test_restplit_alone_marks_the_later_stages_older_than_upstream(tmp_path: Path):
    """The book-box editor's "Save & re-split" runs Stage 02 on its own; 03-06
    are then cut from the OLD crop. No run failed, so this is its own reason."""
    page = tmp_path / "page_001"
    for i, n in enumerate(J.STAGE_ORDER):
        _stage(page, n, _T0 + i)
    _run_all(page, started=_T0 - 1, ok=True, failed=None, ran=list(J.STAGE_ORDER))
    _stage(page, "02_split", _T0 + 3600)           # re-split an hour later

    st = J.page_status(page)["stages"]
    assert [n for n in J.STAGE_ORDER if st[n].get("stale")] == [
        "03_dewarp", "04_layout", "05_ocr", "06_uncertain"]
    assert st["05_ocr"]["stale_reason"] == "older_than_upstream"
    assert st["05_ocr"]["stale_since"] == "02_split"
    assert "stale" not in st["02_split"]


def test_seconds_of_clock_jitter_are_not_staleness(tmp_path: Path):
    page = tmp_path / "page_001"
    # Times that wobble back and forth by up to 1.5 s, as a copied folder or a
    # coarse disk clock produces: within the slack, so nothing is "older".
    for n, jitter in zip(J.STAGE_ORDER, [0, -1, 0.5, -0.5, 0, -1, 0.5]):
        _stage(page, n, _T0 + jitter)
    st = J.page_status(page)["stages"]
    assert not any(st[n].get("stale") for n in J.STAGE_ORDER)


def test_a_garbled_started_at_does_not_break_the_view(tmp_path: Path):
    page = tmp_path / "page_001"
    _stage(page, "00_ingest", _T0)
    (page / "run_all.json").write_text(json.dumps(
        {"ok": False, "failed_stage": "01_fuse", "started_at": "yesterday", "stages": None}))
    st = J.page_status(page)["stages"]
    assert st["00_ingest"] == {"ok": True, "warnings": [], "timings_ms": {}}
