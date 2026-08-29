"""server.worker — single serialized background worker (Gate 5, step 3).

Subprocesses ``python -m pipeline.run_all <page_dir>`` per queued page, one at
a time (``asyncio.Queue`` + a single drain task) — deliberately serialized:
one consumer GPU, no concurrent pipeline runs (see
docs/plans/partitioned-questing-pillow.md and pipeline/run_all.py's own
docstring for why this is a subprocess, never an in-process call).

The queue only ever holds a ``page_dir`` (Path). ``run_all`` is invoked with
**no** ``--input`` — it reads ``<page_dir>/raw/`` itself (Stage 00's
``src=None`` branch), which the upload endpoint has already populated before
enqueuing. ``--mode`` IS passed, read from the job's ``job.json`` via
``page_dir.parent`` (``server.jobs.job_mode``) rather than carried on the
queue item — the job-level setting a page belongs to never changes between
enqueue and run, so re-deriving it from disk at run time keeps the queue's
Path-only shape instead of widening it for one field.

A failed page (non-zero subprocess exit, or a crash before ``run_all.py`` even
gets to write its own ``run_all.json``) must never kill the drain loop — one
bad page just leaves its failure on disk and the worker moves on to the next
queued page.

**Every page's state is recorded in ``<page_dir>/worker.json``**
(``server.jobs.write_worker_state``), because the pipeline's own artifacts
cannot express it: ``run_all.json`` only appears when ``run_all.py`` finishes,
so a page whose subprocess died first, or that a restart stranded before it was
picked up, was previously indistinguishable through the API from a page nobody
had started. ``worker.log`` still holds the raw stdout/stderr; ``worker.json``
is the small structured fact the API and the startup reconciliation both read.

**Shutdown kills the page's subprocess AND the processes it spawned.**
``stop()`` cancels the drain task, kills the live child's whole tree, then marks
its page ``interrupted`` so the next startup re-enqueues it. The tree part is
load-bearing and not free: ``run_all`` spawns Tesseract, so killing only the PID
we hold leaves a grandchild running with no parent to reap it.

Killing a tree is where the two platforms genuinely differ:

* **Windows** — ``proc.terminate()`` is ``TerminateProcess``, which takes the
  child alone; worse, once the parent is gone the tree ``taskkill`` would walk
  is gone with it. So the tree kill must be the **first** rung, not the
  escalation: ``taskkill /F /T /PID <pid>``.
* **POSIX** — the child is spawned with ``start_new_session=True`` so it leads
  its own process group, and the group is signalled (``SIGTERM``, then
  ``SIGKILL``). Without that session flag the group would be *our* group and the
  server would sign its own death warrant.

Either way only the PID this module spawned is ever named — nothing is matched
by process name, which would have a blast radius we did not choose. If the tree
kill is unavailable or fails, we fall back to signalling the single PID, which
is strictly no worse than the old behaviour.

**Limit, stated:** only the Windows branch has ever run. The POSIX branch is
written and its test is not platform-gated, so a run on POSIX would exercise it
— but no such run has happened, so treat it as untested rather than proven.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path

from server import jobs as J

TERMINATE_GRACE_S = 5.0     # give a killed child this long to exit before SIGKILL


def _kill_process_tree(pid: int, hard: bool = False) -> bool:
    """Signal ``pid`` *and its descendants*. True only if the kill SUCCEEDED.

    "It ran" is the wrong meaning to return: the caller uses this answer to
    decide whether the single-PID fallback is still needed, so a taskkill that
    ran and was denied must read as False or both fallback rungs get skipped.

    A seam on purpose: tests that stand in a fake process object must be able to
    replace this, because a fabricated PID handed to ``taskkill`` would name a
    real, unrelated process on the machine.
    """
    if os.name == "nt":
        # /T walks the live process tree from this PID; /F because a console
        # child ignores the polite request. Never a name match.
        try:
            done = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=TERMINATE_GRACE_S, check=False)
            return done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL if hard else signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


class Worker:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.queue: asyncio.Queue[Path] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        # The page currently in flight and the process running it, so shutdown
        # can kill exactly the PID this worker spawned (never a name match).
        self._current: tuple[Path, asyncio.subprocess.Process] | None = None

    def enqueue(self, page_dir: Path) -> None:
        J.write_worker_state(page_dir, "queued", enqueued_at=J.now_iso())
        self.queue.put_nowait(page_dir)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        """Cancel the drain loop, kill the live child, and leave every page the
        server was still working on marked ``interrupted`` so startup can
        resume it."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._kill_current()
        self._drain_queue_as_interrupted()

    async def _kill_current(self) -> None:
        if self._current is None:
            return
        page_dir, proc = self._current
        self._current = None
        if proc.returncode is None:
            # Tree first (see the module docstring): on Windows a parent-only
            # terminate would orphan the grandchildren beyond any later reach.
            if not await asyncio.to_thread(_kill_process_tree, proc.pid):
                with contextlib.suppress(ProcessLookupError, OSError):
                    proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=TERMINATE_GRACE_S)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                # Escalate synchronously: if we got here by cancellation, an
                # awaited thread would just raise CancelledError again and the
                # survivor would live on. The single-PID kill fires either way
                # on this rung — it is harmless against an already-dead process,
                # and this is the last chance to take the one PID we do hold.
                _kill_process_tree(proc.pid, hard=True)
                with contextlib.suppress(ProcessLookupError, OSError):
                    proc.kill()
        J.write_worker_state(page_dir, "interrupted",
                             error="server shut down while this page was running")

    def _drain_queue_as_interrupted(self) -> None:
        """Pages still waiting in the in-memory queue are lost on shutdown —
        mark them so the next startup re-enqueues them instead of leaving them
        looking untouched forever."""
        while True:
            try:
                page_dir = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            J.write_worker_state(page_dir, "interrupted",
                                 error="server shut down before this page was picked up")
            self.queue.task_done()

    async def _drain(self) -> None:
        while True:
            page_dir = await self.queue.get()
            try:
                await self._run_one(page_dir)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The page's failure is on disk; the worker must survive it.
                # This is the spawn-failure path — no subprocess ever ran, so
                # there is no worker.log and no run_all.json to read either.
                with contextlib.suppress(Exception):
                    J.write_worker_state(page_dir, "failed",
                                         error=f"{type(exc).__name__}: {exc}")
            finally:
                self.queue.task_done()

    async def _run_one(self, page_dir: Path) -> None:
        mode = J.job_mode(page_dir.parent)
        # The job's OCR language, when it has one. Omitting --lang (a job with
        # no recorded language) is not the same as passing the config default:
        # it leaves the choice to Stage 05, which is what every job did before
        # this setting existed. Passing it is the whole point — until
        # 2026-08-29 the worker never did, so a German book was read as English
        # on every page the console or the phone submitted.
        lang = J.job_lang(page_dir.parent)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pipeline.run_all", str(page_dir),
            "--mode", mode,
            *(("--lang", lang) if lang else ()),
            cwd=self.repo_root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            # POSIX only: give the child its own session so shutdown can signal
            # its process group without the signal reaching this server too.
            # Windows has no equivalent here — the tree walk is taskkill's job.
            **({} if os.name == "nt" else {"start_new_session": True}),
        )
        self._current = (page_dir, proc)
        J.write_worker_state(page_dir, "running", pid=proc.pid, mode=mode,
                             lang=lang,
                             started_at=J.now_iso(), exit_code=None, error=None)
        try:
            stdout, stderr = await proc.communicate()
        except asyncio.CancelledError:
            # Deliberately do NOT clear the handle: stop() cancels this task and
            # then needs the PID to kill the child it spawned.
            raise
        except BaseException:
            self._current = None
            raise
        self._current = None
        log = (page_dir / "worker.log")
        log.write_text(
            f"exit code: {proc.returncode}\n\n"
            f"--- stdout ---\n{stdout.decode(errors='replace')}\n"
            f"--- stderr ---\n{stderr.decode(errors='replace')}\n",
            encoding="utf-8",
        )
        J.write_worker_state(page_dir, "done" if proc.returncode == 0 else "failed",
                             exit_code=proc.returncode, finished_at=J.now_iso())
