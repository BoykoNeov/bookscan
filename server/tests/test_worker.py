"""Unit tests for server.worker.Worker — sequencing/logging behavior with a
stubbed subprocess (no real pipeline run, no GPU/Tesseract). The real chain is
covered separately by the slow test in test_worker_e2e.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from server import jobs as J
from server.worker import Worker


class _FakeProc:
    """Stands in for asyncio's Process. ``pid`` is part of the contract now —
    the worker records it in worker.json so a shutdown can kill exactly the
    process it spawned."""

    def __init__(self, returncode: int | None, out: bytes, err: bytes, on_communicate=None,
                 pid: int = 4242):
        self.returncode = returncode
        self.pid = pid
        self._out = out
        self._err = err
        self._on_communicate = on_communicate
        self.terminated = False
        self.killed = False

    async def communicate(self):
        if self._on_communicate:
            await self._on_communicate()
        return self._out, self._err

    async def wait(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


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


@pytest.mark.asyncio
async def test_the_jobs_language_is_passed_to_run_all(tmp_path, monkeypatch):
    """Until 2026-08-29 the worker never passed --lang, so a German book
    submitted through the console or the phone was read as English on every
    page (config's languages.default decided for all of them)."""
    captured: dict = {}

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        return _FakeProc(0, b"ok", b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "job.json").write_text('{"mode": "flag", "lang": "deu"}',
                                      encoding="utf-8")
    page_dir = job_dir / "page_001"
    page_dir.mkdir()

    worker = Worker(tmp_path)
    worker.enqueue(page_dir)
    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    args = captured["args"]
    assert args[args.index("--lang") + 1] == "deu"


@pytest.mark.asyncio
async def test_a_job_without_a_language_passes_no_lang_flag(tmp_path, monkeypatch):
    """Not the same as passing the config default: omitting the flag leaves
    the choice to Stage 05, which is what every job did before the setting
    existed. Passing `--lang eng` here would pin old jobs to today's config."""
    captured: dict = {}

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        return _FakeProc(0, b"ok", b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    job_dir = tmp_path / "job1"
    job_dir.mkdir()
    (job_dir / "job.json").write_text('{"mode": "flag"}', encoding="utf-8")
    page_dir = job_dir / "page_001"
    page_dir.mkdir()

    worker = Worker(tmp_path)
    worker.enqueue(page_dir)
    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    assert "--lang" not in captured["args"]


# --------------------------------------------------------------------------
# worker.json — the state file that makes a dead page distinguishable from an
# untouched one (server/jobs.py's WORKER_STATES).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_records_queued_then_running_then_done(tmp_path, monkeypatch):
    seen: list[str] = []

    async def fake_exec(*args, **kwargs):
        page_dir = Path(args[args.index("pipeline.run_all") + 1])

        async def on_communicate():
            # Sampled DURING the run: the state file must already say "running",
            # with the pid of the process the worker actually spawned.
            rec = J.read_worker_state(page_dir)
            seen.append(rec["state"])
            assert rec["pid"] == 4242

        return _FakeProc(0, b"ok", b"", on_communicate)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    page_dir = tmp_path / "page_001"
    page_dir.mkdir()
    worker = Worker(tmp_path)
    worker.enqueue(page_dir)
    assert J.read_worker_state(page_dir)["state"] == "queued"

    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    assert seen == ["running"]
    rec = J.read_worker_state(page_dir)
    assert rec["state"] == "done"
    assert rec["exit_code"] == 0
    assert rec["enqueued_at"] and rec["started_at"] and rec["finished_at"]


@pytest.mark.asyncio
async def test_nonzero_exit_is_recorded_as_failed(tmp_path, monkeypatch):
    async def fake_exec(*args, **kwargs):
        return _FakeProc(3, b"", b"boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    page_dir = tmp_path / "page_001"
    page_dir.mkdir()
    worker = Worker(tmp_path)
    worker.enqueue(page_dir)
    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    rec = J.read_worker_state(page_dir)
    assert rec["state"] == "failed"
    assert rec["exit_code"] == 3


@pytest.mark.asyncio
async def test_a_crash_before_run_all_writes_anything_is_still_visible(tmp_path, monkeypatch):
    """The gap this file closes: no run_all.json, no worker.log, and the page
    used to be indistinguishable through the API from one nobody had started."""

    async def fake_exec(*args, **kwargs):
        raise OSError("subprocess spawn failed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    page_dir = tmp_path / "page_001"
    (page_dir / "raw").mkdir(parents=True)
    worker = Worker(tmp_path)
    worker.enqueue(page_dir)
    await worker.start()
    await asyncio.wait_for(worker.queue.join(), timeout=5)
    await worker.stop()

    assert not (page_dir / "run_all.json").exists()
    assert not (page_dir / "worker.log").exists()
    rec = J.read_worker_state(page_dir)
    assert rec["state"] == "failed"
    assert "subprocess spawn failed" in rec["error"]
    assert J.page_status(page_dir)["worker"]["state"] == "failed"


@pytest.mark.asyncio
async def test_stop_kills_the_live_child_and_marks_the_page_interrupted(tmp_path, monkeypatch):
    procs: list[_FakeProc] = []
    started = asyncio.Event()

    async def fake_exec(*args, **kwargs):
        async def on_communicate():
            started.set()
            await asyncio.sleep(60)      # "still running" when stop() arrives

        # returncode None == still running, which is what stop() must detect
        p = _FakeProc(None, b"", b"", on_communicate)
        procs.append(p)
        return p

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    # The tree kill is stubbed here on purpose: this test's process is a fake,
    # and handing its fabricated PID to taskkill would name a real, unrelated
    # process on the machine. What the stub asserts is the thing that matters —
    # the PID signalled is the one this worker spawned, never a name match.
    signalled: list[int] = []
    monkeypatch.setattr("server.worker._kill_process_tree",
                        lambda pid, hard=False: signalled.append(pid) or True)

    page_dir = tmp_path / "page_001"
    page_dir.mkdir()
    worker = Worker(tmp_path)
    worker.enqueue(page_dir)
    await worker.start()
    await asyncio.wait_for(started.wait(), timeout=5)

    await worker.stop()

    assert signalled == [procs[0].pid]
    rec = J.read_worker_state(page_dir)
    assert rec["state"] == "interrupted"


@pytest.mark.asyncio
async def test_stop_marks_still_queued_pages_interrupted(tmp_path, monkeypatch):
    """The in-memory queue dies with the process; the pages in it must not be
    left looking untouched, or startup cannot tell them from finished work."""
    started = asyncio.Event()

    async def fake_exec(*args, **kwargs):
        async def on_communicate():
            started.set()
            await asyncio.sleep(60)

        return _FakeProc(None, b"", b"", on_communicate)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    p1, p2 = tmp_path / "page_001", tmp_path / "page_002"
    p1.mkdir()
    p2.mkdir()
    worker = Worker(tmp_path)
    worker.enqueue(p1)
    worker.enqueue(p2)
    await worker.start()
    await asyncio.wait_for(started.wait(), timeout=5)
    await worker.stop()

    assert J.read_worker_state(p1)["state"] == "interrupted"   # was running
    assert J.read_worker_state(p2)["state"] == "interrupted"   # never picked up


# --------------------------------------------------------------------------
# Shutdown kills the grandchild, proven on real processes
# --------------------------------------------------------------------------
# run_all spawns Tesseract, so "we killed the PID we hold" is not the same claim
# as "nothing survives the shutdown". These two scripts build the smallest real
# version of that shape: a child that outlives its own spawn, and a grandchild
# that keeps writing. Asserting the grandchild's PID is gone would be weak —
# PIDs get reused — so the assertion is that its heartbeat file STOPS GROWING.
_GRANDCHILD_SRC = (
    "import sys, time\n"
    "while True:\n"
    "    with open(sys.argv[1], 'a') as fh:\n"
    "        fh.write('.')\n"
    "    time.sleep(0.05)\n"
)

_CHILD_SRC = (
    "import subprocess, sys, time\n"
    "heartbeat, pidfile, grandchild_src = sys.argv[1], sys.argv[2], sys.argv[3]\n"
    "p = subprocess.Popen([sys.executable, '-c', grandchild_src, heartbeat])\n"
    "open(pidfile, 'w').write(str(p.pid))\n"
    "time.sleep(300)\n"      # outlive the test; shutdown is what ends this
)


async def _grow_stops(path: Path, settle_s: float = 0.6, watch_s: float = 0.6) -> tuple[int, int]:
    await asyncio.sleep(settle_s)      # anything already in flight lands
    before = path.stat().st_size
    await asyncio.sleep(watch_s)
    return before, path.stat().st_size


@pytest.mark.asyncio
async def test_stop_kills_the_childs_own_child_not_just_the_child(tmp_path, monkeypatch):
    import sys as _sys

    from server import worker as W

    heartbeat = tmp_path / "heartbeat.txt"
    pidfile = tmp_path / "grandchild.pid"
    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(*args, **kwargs):
        # Same spawn kwargs the worker uses; only the command is swapped.
        return await real_exec(
            _sys.executable, "-c", _CHILD_SRC,
            str(heartbeat), str(pidfile), _GRANDCHILD_SRC,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **{k: v for k, v in kwargs.items() if k in ("cwd", "start_new_session")},
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    page_dir = tmp_path / "page_001"
    page_dir.mkdir()
    worker = Worker(tmp_path)
    grandchild_pid = None
    try:
        worker.enqueue(page_dir)
        await worker.start()

        for _ in range(200):           # up to ~10s for the tree to come up
            if pidfile.exists() and heartbeat.exists() and heartbeat.stat().st_size > 0:
                break
            await asyncio.sleep(0.05)
        assert pidfile.exists(), "the child never spawned its own child"
        grandchild_pid = int(pidfile.read_text())

        alive_before, alive_after = await _grow_stops(heartbeat, settle_s=0.0, watch_s=0.3)
        assert alive_after > alive_before, "the grandchild was not writing before shutdown"

        await worker.stop()

        settled, later = await _grow_stops(heartbeat)
        assert settled == later, (
            f"the grandchild outlived the shutdown: heartbeat grew {later - settled} bytes "
            f"after stop() (pid {grandchild_pid})"
        )
        assert J.read_worker_state(page_dir)["state"] == "interrupted"
    finally:
        # Never leak a real process out of a failing test. Only the PID this
        # test's own tree reported is touched.
        if grandchild_pid is not None:
            W._kill_process_tree(grandchild_pid, hard=True)
