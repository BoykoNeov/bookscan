"""server.reconcile — find the pages a restart stranded, so they can be re-run.

The worker's queue lives in memory. If the server stops (crash, reboot, Ctrl-C)
while pages are queued or running, that queue is simply gone: the uploads are on
disk, the pipeline never ran, and nothing ever picks them up again. Before this
module, the only way to notice was to look at ``GET /api/jobs/{id}`` and see
stages that stayed empty forever.

The rule is deliberately narrow — **resume interrupted work, never retry failed
work**:

* ``queued`` / ``running`` / ``interrupted`` -> re-enqueue. The first two mean the
  process died before ``stop()`` could mark them; the third means it shut down
  cleanly and said so.
* ``done`` / ``failed`` -> leave alone. Re-running a ``failed`` page every time the
  server starts would turn one page that crashes the pipeline into a permanent
  restart loop, burning the GPU on a page that will fail again. A failed page is
  re-run by asking for it, not by rebooting.
* **no ``worker.json`` at all** -> re-enqueue only if the page has raw uploads and
  no ``run_all.json``. That is the pre-worker.json page: either uploaded before
  this file existed, or stranded before it was ever picked up.

A page with no (or empty) ``raw/`` is never enqueued whatever its state says —
``run_all`` would have nothing to read.

The scan is a pure function of the jobs tree so it can be tested against a temp
directory without a server, a worker, or a pipeline run.
"""

from __future__ import annotations

from pathlib import Path

from server import jobs as J


def _has_uploads(page_dir: Path) -> bool:
    raw = page_dir / "raw"
    return raw.is_dir() and any(p.is_file() for p in raw.iterdir())


def page_needs_work(page_dir: Path) -> bool:
    if not _has_uploads(page_dir):
        return False
    state = J.read_worker_state(page_dir)
    if state is None:
        return not (page_dir / "run_all.json").exists()
    return state.get("state") in J.RESUMABLE_STATES


def pages_needing_work(jobs_root: Path) -> list[Path]:
    """Every stranded page under ``jobs_root``, in (job, page) name order —
    which is upload order, so the worker resumes them the way they arrived."""
    if not jobs_root.is_dir():
        return []
    out: list[Path] = []
    for job_dir in sorted(p for p in jobs_root.iterdir() if p.is_dir()):
        for page_dir in sorted(p for p in job_dir.iterdir()
                               if p.is_dir() and J.PAGE_DIR_RE.match(p.name)):
            if page_needs_work(page_dir):
                out.append(page_dir)
    return out


def resume(jobs_root: Path, worker) -> list[Path]:
    """Re-enqueue everything the last run left unfinished. Returns what it
    enqueued (the caller logs it; the pages themselves get ``queued`` written
    back by ``Worker.enqueue``)."""
    pages = pages_needing_work(jobs_root)
    for page_dir in pages:
        worker.enqueue(page_dir)
    return pages
