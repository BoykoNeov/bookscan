"""Unit tests for server.worker.Worker — sequencing/logging behavior with a
stubbed subprocess (no real pipeline run, no GPU/Tesseract). The real chain is
covered separately by the slow test in test_worker_e2e.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from server.worker import Worker


class _FakeProc:
    def __init__(self, returncode: int, out: bytes, err: bytes, on_communicate=None):
        self.returncode = returncode
        self._out = out
        self._err = err
        self._on_communicate = on_communicate

    async def communicate(self):
        if self._on_communicate:
            await self._on_communicate()
        return self._out, self._err


@pytest.mark.asyncio
async def test_processes_queued_pages_one_at_a_time_in_order(tmp_path, monkeypatch):
    order: list[str] = []
    concurrent = {"n": 0, "max": 0}

    async def fake_exec(*args, **kwargs):
        page_dir = Path(args[args.index("pipeline.run_all") + 1])
        concurrent["n"] += 1
        concurrent["max"] = max(concurrent["max"], concurrent["n"])

        async def on_communicate():
            await asyncio.sleep(0)  # yield, so a second concurrent call WOULD interleave
            order.append(page_dir.name)
            concurrent["n"] -= 1

        return _FakeProc(0, b"ok", b"", on_communicate)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    worker = Worker(tmp_path)
    p1, p2, p3 = tmp_path / "page_001", tmp_path / "page_002", tmp_path / "page_003"
    for p in (p1, p2, p3):
        p.mkdir()
    worker.enqueue(p1)
    worker.enqueue(p2)
    worker.enqueue(p3)

    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    assert order == ["page_001", "page_002", "page_003"]
    assert concurrent["max"] == 1  # never two subprocesses in flight at once


@pytest.mark.asyncio
async def test_writes_worker_log_with_exit_code_and_output(tmp_path, monkeypatch):
    async def fake_exec(*args, **kwargs):
        return _FakeProc(1, b"stdout stuff", b"stderr stuff")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    page_dir = tmp_path / "page_001"
    page_dir.mkdir()
    worker = Worker(tmp_path)
    worker.enqueue(page_dir)

    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    log = (page_dir / "worker.log").read_text(encoding="utf-8")
    assert "exit code: 1" in log
    assert "stdout stuff" in log
    assert "stderr stuff" in log


@pytest.mark.asyncio
async def test_a_page_that_raises_does_not_kill_the_drain_loop(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def fake_exec(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("subprocess spawn failed")
        return _FakeProc(0, b"ok", b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    p1, p2 = tmp_path / "page_001", tmp_path / "page_002"
    p1.mkdir()
    p2.mkdir()
    worker = Worker(tmp_path)
    worker.enqueue(p1)
    worker.enqueue(p2)

    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    # page_001 never got a worker.log (it crashed before create_subprocess_exec
    # returned) but page_002 still ran — the drain loop survived page_001's error.
    assert not (p1 / "worker.log").exists()
    assert (p2 / "worker.log").exists()


@pytest.mark.asyncio
async def test_passes_mode_from_job_json_to_run_all(tmp_path, monkeypatch):
    captured: dict = {}

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        return _FakeProc(0, b"ok", b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "job.json").write_text('{"mode": "patch"}', encoding="utf-8")
    page_dir = job_dir / "page_001"
    page_dir.mkdir()

    worker = Worker(tmp_path)
    worker.enqueue(page_dir)
    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    args = captured["args"]
    assert args[args.index("--mode") + 1] == "patch"


@pytest.mark.asyncio
async def test_defaults_to_flag_mode_without_job_json(tmp_path, monkeypatch):
    captured: dict = {}

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        return _FakeProc(0, b"ok", b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    page_dir = tmp_path / "page_001"  # no job.json in tmp_path (its parent)
    page_dir.mkdir()

    worker = Worker(tmp_path)
    worker.enqueue(page_dir)
    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    args = captured["args"]
    assert args[args.index("--mode") + 1] == "flag"
