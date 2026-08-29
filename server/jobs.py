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

# A Tesseract language code, or a "+"-joined combination of them ("deu+ita").
# Anchored and narrow because this value is persisted and later handed to a
# subprocess as an argv element.
LANG_RE = re.compile(r"^[a-z]{3}(?:\+[a-z]{3})*$")


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


def create_job(root: Path, mode: str = "flag",
               lang: str | None = None) -> str:
    """Mint a job dir and persist its uncertainty ``mode`` and OCR ``lang`` in
    ``job.json`` — the job-level settings the API needs before any page is
    uploaded (the worker passes both to ``run_all`` for each page: Stage 06
    reads the mode, Stage 05 the language).

    ``lang`` of ``None`` means "no override": ``run_all`` is called without
    ``--lang`` and Stage 05 falls back to ``languages.default`` from
    config.yaml, which is what every job did before this setting existed."""
    if mode not in MODES:
        raise ValueError(f"invalid mode: {mode!r} (choices: {MODES})")
    if lang is not None and not LANG_RE.match(lang):
        raise ValueError(f"invalid lang: {lang!r}")
    job_id = new_job_id()
    job_dir = root / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    payload: dict = {"mode": mode}
    if lang is not None:
        payload["lang"] = lang
    (job_dir / "job.json").write_text(
        json.dumps(payload), encoding="utf-8")
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


def job_lang(job_dir: Path) -> str | None:
    """The job's Tesseract language override, or ``None`` for "use the config
    default" — which is what a job created before this setting existed gets,
    and what the pipeline did for every job until 2026-08-29.

    Deliberately NOT validated against ``languages.supported``: that list is
    config's, Tesseract accepts combinations like ``deu+ita`` that the list
    does not enumerate, and a job's recorded language is history — refusing to
    read it back because config changed would rewrite that history. The shape
    is checked (``LANG_RE``) because the value reaches a subprocess argv."""
    path = job_dir / "job.json"
    if not path.exists():
        return None
    try:
        lang = json.loads(path.read_text(encoding="utf-8")).get("lang")
    except Exception:
        return None
    if not isinstance(lang, str) or not LANG_RE.match(lang):
        return None
    return lang


def set_job_lang(job_dir: Path, lang: str | None) -> None:
    """Persist (or clear, with ``None``) the job's OCR language, merging over
    whatever else ``job.json`` holds so the uncertainty mode survives."""
    if lang is not None and not LANG_RE.match(lang):
        raise ValueError(f"invalid lang: {lang!r}")
    path = job_dir / "job.json"
    payload: dict = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if lang is None:
        payload.pop("lang", None)
    else:
        payload["lang"] = lang
    path.write_text(json.dumps(payload), encoding="utf-8")


def count_processed_pages(job_dir: Path) -> int:
    """Pages that have already been through Stage 05 — i.e. pages whose text
    was read in whatever language was set at the time, and which a language
    change therefore does NOT retroactively affect."""
    return sum(1 for p in job_dir.iterdir()
               if p.is_dir() and PAGE_DIR_RE.match(p.name)
               and (p / "05_ocr" / "ocr.json").exists())


# What the worker has done with a page, recorded by the worker itself in
# ``<page_dir>/worker.json``. This exists because the pipeline's own artifacts
# cannot answer the question: ``run_all.json`` is written by ``run_all.py`` at
# the END of a run, so a page whose subprocess died before that — or was never
# picked up at all — is indistinguishable from a page nobody has started, and
# ``GET /api/jobs/{id}`` reported both as "no stages yet".
#
#   queued      enqueued, not yet picked up by the drain loop
#   running     a subprocess is (or was) live for this page
#   done        the subprocess exited 0
#   failed      the subprocess exited non-zero, or never started (spawn error)
#   interrupted the server shut down while the page was queued or running
#
# ``interrupted`` is deliberately distinct from ``failed``: the page is
# re-enqueued at the next startup (``reconcile.py``), whereas a ``failed`` page
# is not — a page that crashes the pipeline must not re-run on every restart
# forever.
WORKER_STATES = ("queued", "running", "done", "failed", "interrupted")
RESUMABLE_STATES = ("queued", "running", "interrupted")
WORKER_FILE = "worker.json"


def write_worker_state(page_dir: Path, state: str, **fields) -> dict:
    """Record (and return) this page's worker state, merging over what is
    already there so a transition keeps the earlier timestamps."""
    if state not in WORKER_STATES:
        raise ValueError(f"invalid worker state: {state!r} (choices: {WORKER_STATES})")
    rec = read_worker_state(page_dir) or {}
    rec.update(state=state, updated_at=now_iso(), **fields)
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / WORKER_FILE).write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def read_worker_state(page_dir: Path) -> dict | None:
    """None means no worker has ever touched this page — which is itself the
    answer for a page uploaded before this file existed, or stranded by a
    restart before it was picked up."""
    path = page_dir / WORKER_FILE
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"state": "failed", "error": "unreadable worker.json"}
    return rec if isinstance(rec, dict) else {"state": "failed", "error": "malformed worker.json"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_job_dir(root: Path, job_id: str) -> Path | None:
    """job_id -> its folder, or None if it doesn't exist or isn't a bare id
    (job_id becomes a path component directly, so this also guards traversal
    like ``../../etc``)."""
    if not JOB_ID_RE.match(job_id):
        return None
    d = root / job_id
    return d if d.is_dir() else None


def list_jobs(root: Path) -> list[dict]:
    """Every job, NEWEST FIRST, with the few facts a chooser needs.

    Deliberately cheap — a directory count and one small read per job, never
    ``job_status`` (which stats every stage of every page). The console shows
    dozens of jobs at once; the phone shows the same list to pick a job to
    resume. Extra keys beyond ``job_id`` are additive: the Android
    ``JobSummary`` DTO ignores fields it does not declare.
    """
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        pages = [d for d in p.iterdir() if d.is_dir() and PAGE_DIR_RE.match(d.name)]
        out.append({
            "job_id": p.name,
            "pages": len(pages),
            "mode": job_mode(p),
            "lang": job_lang(p),
            "mtime": p.stat().st_mtime,
            "has_document": (p / "document.json").exists(),
            "has_render": (p / "render" / "page.html").exists(),
        })
    # Newest first. `jobs/` accumulates every harness and tool run alongside real
    # scans — 100+ of them here — and an alphabetical list buries the book someone
    # photographed an hour ago under fixtures named `bg_01`. Sorting by the folder's
    # own mtime rather than by the id keeps hand-named jobs (`demo`, `floor_de_01`)
    # in the same ordering as the timestamp-named ones, which a name sort cannot.
    out.sort(key=lambda j: j["mtime"], reverse=True)
    return out


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
        # None until a worker touches the page. Distinguishes "queued, nothing
        # has happened yet" from "the subprocess died before run_all.py could
        # write its own summary" — which used to look identical from here.
        "worker": read_worker_state(page_dir),
    }


def job_status(job_dir: Path) -> dict:
    pages = sorted(
        (p for p in job_dir.iterdir() if p.is_dir() and PAGE_DIR_RE.match(p.name)),
        key=lambda p: p.name,
    )
    return {
        "job_id": job_dir.name,
        "mode": job_mode(job_dir),
        # None = "no override recorded"; Stage 05 uses languages.default.
        "lang": job_lang(job_dir),
        # The canonical stage sequence, so a client can render progress without
        # hard-coding the chain or inferring it from whichever stages happen to
        # have run on the first page it sees.
        "stage_order": list(STAGE_ORDER),
        "pages": [page_status(p) for p in pages],
        "has_document": (job_dir / "document.json").exists(),
        "has_render": (job_dir / "render" / "page.html").exists(),
    }
