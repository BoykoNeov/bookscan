"""server.worker — single serialized background worker (Gate 5, step 3).

Subprocesses ``python -m pipeline.run_all <page_dir>`` per queued page, one at
a time (``asyncio.Queue`` + a single drain task) — deliberately serialized:
one consumer GPU, no concurrent pipeline runs (see
docs/plans/partitioned-questing-pillow.md and pipeline/run_all.py's own
docstring for why this is a subprocess, never an in-process call).

The queue only ever holds a ``page_dir`` (Path). ``run_all`` is invoked with
**no** ``--input`` — it reads ``<page_dir>/raw/`` itself (Stage 00's
``src=None`` branch), which the upload endpoint has already populated before
enqueuing.

A failed page (non-zero subprocess exit, or a crash before ``run_all.py`` even
gets to write its own ``run_all.json``) must never kill the drain loop — one
bad page just leaves its failure on disk (``run_all.json`` if ``run_all.py``
got that far, plus this module's own ``worker.log`` with the raw stdout/stderr
either way) and the worker moves on to the next queued page.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


class Worker:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.queue: asyncio.Queue[Path] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def enqueue(self, page_dir: Path) -> None:
        self.queue.put_nowait(page_dir)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _drain(self) -> None:
        while True:
            page_dir = await self.queue.get()
            try:
                await self._run_one(page_dir)
            except Exception:
                pass  # this page's failure is on disk; the worker must survive it
            finally:
                self.queue.task_done()

    async def _run_one(self, page_dir: Path) -> None:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pipeline.run_all", str(page_dir),
            cwd=self.repo_root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        log = (page_dir / "worker.log")
        log.write_text(
            f"exit code: {proc.returncode}\n\n"
            f"--- stdout ---\n{stdout.decode(errors='replace')}\n"
            f"--- stderr ---\n{stderr.decode(errors='replace')}\n",
            encoding="utf-8",
        )
