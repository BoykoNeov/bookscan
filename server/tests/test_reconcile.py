"""Tests for server.reconcile — which stranded pages a restart picks back up.

The scan is a pure function over a jobs tree, so these build the tree by hand:
no server, no worker, no pipeline run.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from server import jobs as J
from server import reconcile as R
from server.worker import Worker


def _page(root: Path, job: str, name: str, *, uploads: bool = True,
          state: str | None = None, run_all: bool = False) -> Path:
    page_dir = root / job / name
    page_dir.mkdir(parents=True)
    if uploads:
        (page_dir / "raw").mkdir()
        (page_dir / "raw" / "frame_00.jpg").write_bytes(b"x")
    if state is not None:
        J.write_worker_state(page_dir, state)
    if run_all:
        (page_dir / "run_all.json").write_text('{"ok": true}', encoding="utf-8")
    return page_dir


@pytest.mark.parametrize("state,expected", [
    ("queued", True),        # died before the drain loop reached it
    ("running", True),       # died mid-run, with no chance to mark it
    ("interrupted", True),   # shut down cleanly and said so
    ("done", False),
    ("failed", False),       # never: a poison page would re-run every restart
])
def test_resumes_interrupted_work_only(tmp_path, state, expected):
    page = _page(tmp_path, "job1", "page_001", state=state)
    assert R.page_needs_work(page) is expected


def test_page_with_uploads_and_no_worker_file_is_resumed(tmp_path):
    """The pre-worker.json page: uploaded, never picked up, nothing recorded."""
    page = _page(tmp_path, "job1", "page_001")
    assert R.page_needs_work(page) is True


def test_page_with_no_worker_file_but_a_finished_run_is_left_alone(tmp_path):
    page = _page(tmp_path, "job1", "page_001", run_all=True)
    assert R.page_needs_work(page) is False


def test_page_without_uploads_is_never_enqueued(tmp_path):
    """run_all would have nothing to read — whatever the state file claims."""
    page = _page(tmp_path, "job1", "page_001", uploads=False, state="running")
    assert R.page_needs_work(page) is False


def test_empty_raw_dir_counts_as_no_uploads(tmp_path):
    page = _page(tmp_path, "job1", "page_001", uploads=False, state="queued")
    (page / "raw").mkdir()
    assert R.page_needs_work(page) is False


def test_scan_returns_upload_order_across_jobs(tmp_path):
    _page(tmp_path, "job2", "page_002", state="queued")
    _page(tmp_path, "job1", "page_002", state="running")
    _page(tmp_path, "job1", "page_001", state="done")
    _page(tmp_path, "job1", "page_003", state="failed")
    _page(tmp_path, "job2", "page_001")
    (tmp_path / "job1" / "not_a_page").mkdir()

    found = [str(p.relative_to(tmp_path)).replace("\\", "/")
             for p in R.pages_needing_work(tmp_path)]
    assert found == ["job1/page_002", "job2/page_001", "job2/page_002"]


def test_missing_jobs_root_is_not_an_error(tmp_path):
    assert R.pages_needing_work(tmp_path / "nope") == []


@pytest.mark.asyncio
async def test_resume_enqueues_and_marks_them_queued(tmp_path):
    stranded = _page(tmp_path, "job1", "page_001", state="interrupted")
    _page(tmp_path, "job1", "page_002", state="done")

    worker = Worker(tmp_path)
    resumed = R.resume(tmp_path, worker)

    assert resumed == [stranded]
    assert worker.queue.qsize() == 1
    assert await asyncio.wait_for(worker.queue.get(), timeout=1) == stranded
    assert J.read_worker_state(stranded)["state"] == "queued"


@pytest.mark.asyncio
async def test_a_restart_reruns_the_interrupted_page_and_only_that_one(tmp_path, monkeypatch):
    """End to end over the two halves: stop() marks what it was working on, and
    a fresh worker + resume() picks up exactly that page."""
    started = asyncio.Event()
    ran: list[str] = []

    class _Proc:
        returncode = None
        pid = 7

        async def communicate(self):
            started.set()
            await asyncio.sleep(60)

        async def wait(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def kill(self):
            self.returncode = -9

    async def fake_exec(*args, **kwargs):
        ran.append(Path(args[args.index("pipeline.run_all") + 1]).name)
        return _Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    p1 = _page(tmp_path, "job1", "page_001")
    _page(tmp_path, "job1", "page_002", state="failed")

    worker = Worker(tmp_path)
    worker.enqueue(p1)
    await worker.start()
    await asyncio.wait_for(started.wait(), timeout=5)
    await worker.stop()                                   # the "crash"
    assert J.read_worker_state(p1)["state"] == "interrupted"

    assert [p.name for p in R.pages_needing_work(tmp_path)] == ["page_001"]


def test_startup_resumes_stranded_pages_through_the_real_lifespan(tmp_path, monkeypatch):
    """The wiring, not just the scan: entering the app's lifespan must re-enqueue
    what the last run left behind. The subprocess is faked — this asserts the
    handoff, not a pipeline run."""
    import asyncio as _asyncio

    from fastapi.testclient import TestClient

    from server.app import create_app

    launched: list[str] = []

    class _Proc:
        returncode = 0
        pid = 11

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, **kwargs):
        launched.append(Path(args[args.index("pipeline.run_all") + 1]).name)
        return _Proc()

    monkeypatch.setattr(_asyncio, "create_subprocess_exec", fake_exec)

    stranded = _page(tmp_path, "job1", "page_001", state="interrupted")
    _page(tmp_path, "job1", "page_002", state="failed")     # must NOT come back
    _page(tmp_path, "job1", "page_003", state="done")

    app = create_app()
    app.state.jobs_root = tmp_path
    with TestClient(app) as client:
        assert client.get("/api/health").json()["resumed_pages"] == [str(stranded)]

    assert launched == ["page_001"]
    assert J.read_worker_state(stranded)["state"] == "done"
