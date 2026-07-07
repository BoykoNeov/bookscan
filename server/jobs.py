"""server.jobs — filesystem-only job lifecycle (Gate 5).

No database: CLAUDE.md's stage contract already makes the filesystem the
source of truth (every stage writes its own ``meta.json``; ``pipeline.run_all``
writes a per-page ``run_all.json`` summary). This module only mints job ids and
page-folder names, and reads those same files back into a status shape the API
can return — it never duplicates state a stage already recorded.

Job id is exactly the folder name under ``jobs/`` (matches
``stage07_assemble.py`` setting ``document_id=job_dir.name``).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pipeline.page_model import StageMeta
from pipeline.run_all import STAGE_ORDER

JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
PAGE_DIR_RE = re.compile(r"^page_(\d+)$")

# Mirrors pipeline/run_all.py's own --mode choices exactly (Stage 06's
# uncertainty modes) — kept here, not imported from run_all, since this is
# the server's contract with its own job.json, not run_all's CLI surface.
MODES = ("flag", "best_guess", "patch")


def jobs_root(cfg: dict, repo_root: Path) -> Path:
    rel = (cfg.get("paths", {}) or {}).get("jobs", "jobs")
    root = Path(rel)
    if not root.is_absolute():
        root = repo_root / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def new_job_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def create_job(root: Path, mode: str = "flag") -> str:
    """Mint a job dir and persist its uncertainty ``mode`` in ``job.json`` —
    the one job-level setting the API needs before any page is uploaded
    (Stage 06 reads it per page, via ``job_mode()`` below, when the worker
    subprocesses ``run_all`` for each page)."""
    if mode not in MODES:
        raise ValueError(f"invalid mode: {mode!r} (choices: {MODES})")
    job_id = new_job_id()
    job_dir = root / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    (job_dir / "job.json").write_text(
        json.dumps({"mode": mode}), encoding="utf-8")
    return job_id


def job_mode(job_dir: Path) -> str:
    """The job's uncertainty mode, defaulting to ``flag`` if ``job.json`` is
    missing (jobs created before this setting existed) or unreadable."""
    path = job_dir / "job.json"
    if not path.exists():
        return "flag"
    try:
        mode = json.loads(path.read_text(encoding="utf-8")).get("mode", "flag")
    except Exception:
        return "flag"
    return mode if mode in MODES else "flag"


def resolve_job_dir(root: Path, job_id: str) -> Path | None:
    """job_id -> its folder, or None if it doesn't exist or isn't a bare id
    (job_id becomes a path component directly, so this also guards traversal
    like ``../../etc``)."""
    if not JOB_ID_RE.match(job_id):
        return None
    d = root / job_id
    return d if d.is_dir() else None


def list_jobs(root: Path) -> list[dict]:
    return [{"job_id": p.name} for p in sorted(root.iterdir()) if p.is_dir()]


def next_page_dir(job_dir: Path) -> Path:
    """Next ``page_NNN`` folder under a job dir, 1-indexed, zero-padded to 3
    (matches CLAUDE.md's ``jobs/<job_id>/<page_NNN>/`` layout)."""
    existing = [
        int(m.group(1)) for p in job_dir.iterdir() if p.is_dir()
        for m in [PAGE_DIR_RE.match(p.name)] if m
    ]
    n = (max(existing) + 1) if existing else 1
    return job_dir / f"page_{n:03d}"


def _stage_status(page_dir: Path, name: str) -> dict | None:
    """None means the stage hasn't run yet (no meta.json) — distinct from an
    ``ok: False`` entry, which means it ran and left an unreadable meta.json."""
    meta_path = page_dir / name / "meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = StageMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "error": "unreadable meta.json"}
    return {"ok": True, "warnings": meta.warnings, "timings_ms": meta.timings_ms}


def page_status(page_dir: Path) -> dict:
    run_all_path = page_dir / "run_all.json"
    run_all = (json.loads(run_all_path.read_text(encoding="utf-8"))
               if run_all_path.exists() else None)
    return {
        "name": page_dir.name,
        "stages": {name: _stage_status(page_dir, name) for name in STAGE_ORDER},
        "run_all": run_all,
    }


def job_status(job_dir: Path) -> dict:
    pages = sorted(
        (p for p in job_dir.iterdir() if p.is_dir() and PAGE_DIR_RE.match(p.name)),
        key=lambda p: p.name,
    )
    return {
        "job_id": job_dir.name,
        "mode": job_mode(job_dir),
        "pages": [page_status(p) for p in pages],
        "has_document": (job_dir / "document.json").exists(),
        "has_render": (job_dir / "render" / "page.html").exists(),
    }
