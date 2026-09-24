"""server.routes_import — the console's Import PDF button (plan Slice 2).

``docs/plans/pdf-import.md``: a page's layout must be "detected, then shown, then
overridable — never guessed silently", and the console "should say what it is
about to create before it creates it". So an import is two requests, not one:

1. ``POST /api/imports`` uploads the PDF into staging and SURVEYS it — every
   page's shape, its single/spread verdict, whether it is a scan, and the size
   estimate — without rendering a pixel or creating a job.
2. ``POST /api/imports/{token}/start`` takes the operator's per-page layouts,
   the job's mode and language, and runs ``pipeline.pdf_import.import_pdf`` in a
   thread. ``GET /api/imports/{token}`` reports progress until it is ``done``
   (with the new ``job_id``) or ``failed`` (with the importer's own words).

**Why this removes the restart.** The CLI importer cannot reach a running
console's in-memory queue, so its pages wait for the next startup scan. Here the
import runs inside the server: when ``import_pdf`` returns — the job is already
published, all pages at once — every page is enqueued on the worker in page
order. The enqueue happens back on the event loop, never from the render thread:
``asyncio.Queue`` is not thread-safe.

**What is NOT changed.** ``import_pdf`` is called exactly as the CLI calls it,
so every refusal (encrypted, not a scan, empty) and the all-or-nothing publish
are the importer's, not re-implemented here. One import renders at a time (a
second start gets 409): rendering is memory- and disk-heavy, and two at once
would only make both slower. A shutdown mid-render cancels the import after the
page in progress; ``import_pdf`` then leaves nothing in ``jobs/``.

Uploads live beside the importer's staging folder (``<staging>_uploads/<token>``),
never inside it: ``import_pdf`` wipes ``<staging>/<job_id>``, and an upload
folder must not be reachable by any job id. A checked-but-never-started upload
is deleted by ``DELETE``, or swept after a day by the next upload.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from pipeline import pdf_import as PI
from server import jobs as J

router = APIRouter(prefix="/api/imports", tags=["import"])

STALE_UPLOAD_S = 24 * 3600
_CHUNK = 1 << 20
TOKEN_LEN = 16


class ImportCancelled(RuntimeError):
    """Raised from the progress callback so ``import_pdf`` stops and cleans up."""


class StartRequest(BaseModel):
    mode: str = "flag"
    lang: str | None = None
    # 1-based PDF page number (as a string: it is a JSON object key) -> layout.
    # Only pages the operator changed need be sent; the rest keep the survey's.
    layouts: dict[str, str] = Field(default_factory=dict)
    allow_vector: bool = False


def uploads_root(app) -> Path:
    staging = Path(app.state.import_staging)
    return staging.with_name(staging.name + "_uploads")


def _imports(request: Request) -> dict:
    return request.app.state.imports


def _record(request: Request, token: str) -> dict:
    rec = _imports(request).get(token)
    if rec is None:
        raise HTTPException(404, f"no such import: {token}")
    return rec


def _public(rec: dict) -> dict:
    """What the console sees: everything except the server-side paths and flags."""
    return {k: v for k, v in rec.items() if k not in ("pdf_path", "cancel")}


def _safe_name(filename: str | None) -> str:
    stem = re.sub(r"[^\w.\- ]", "_", Path(filename or "").stem).strip(" .")[:120]
    return f"{stem or 'upload'}.pdf"


def _sweep_stale(root: Path, live: set[str]) -> None:
    if not root.is_dir():
        return
    now = time.time()
    for d in root.iterdir():
        if d.is_dir() and d.name not in live and now - d.stat().st_mtime > STALE_UPLOAD_S:
            shutil.rmtree(d, ignore_errors=True)


def _languages(cfg: dict) -> tuple[list[str], str]:
    langs = (cfg.get("languages", {}) or {})
    codes = [e.get("code") for e in (langs.get("supported") or [])
             if isinstance(e, dict) and e.get("code")]
    return codes, langs.get("default", "eng")


@router.post("")
async def check_pdf(request: Request, file: UploadFile = File(...), dpi: int = 300) -> dict:
    """Upload a PDF and survey it. Creates no job; renders nothing."""
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(400, f"not a .pdf file: {file.filename}")
    if not 72 <= dpi <= 1200:
        raise HTTPException(400, f"dpi {dpi} outside 72..1200")
    root = uploads_root(request.app)
    _sweep_stale(root, set(_imports(request)))
    token = uuid.uuid4().hex[:TOKEN_LEN]
    folder = root / token
    folder.mkdir(parents=True)
    # Saved under its own name (made safe): import_pdf records ``pdf_path.name``
    # in import.json and in every page_layout.json note, and "upload.pdf" there
    # would lose the one fact that says which book a job came from.
    pdf_path = folder / _safe_name(file.filename)
    refused = None
    try:
        head = b""
        with open(pdf_path, "wb") as out:
            while chunk := await file.read(_CHUNK):
                if len(head) < 1024:
                    head += chunk[:1024 - len(head)]
                out.write(chunk)
        # The spec lets a few bytes precede the header; an HTML error page or a
        # renamed image never contains it at all.
        if b"%PDF-" not in head:
            refused = f"{file.filename} is not a PDF (no %PDF header)"
        else:
            try:
                pages, warnings = await asyncio.to_thread(PI.survey, pdf_path, dpi)
            except PI.ImportRefused as e:
                refused = str(e)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if refused is not None:
        # Deleted only here, OUTSIDE the except block: on Windows a PDF MuPDF
        # failed to open stays locked while that exception (and the frames its
        # traceback holds) is alive — measured: WinError 32 inside, gone after.
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(400, refused)
    languages, lang_default = _languages(request.app.state.cfg)
    rec = {
        "token": token, "state": "checked", "pdf": Path(file.filename).name,
        "pdf_path": str(pdf_path), "dpi": dpi, "page_count": len(pages),
        "pages": [p.model_dump() for p in pages],
        "not_scans": [p.pdf_page for p in pages if not p.is_scan],
        "estimated_bytes": sum(p.width * p.height * 3 for p in pages),
        "warnings": warnings, "done": 0, "job_id": None, "error": None,
        "languages": languages, "lang_default": lang_default,
        "modes": list(J.MODES), "cancel": False,
    }
    _imports(request)[token] = rec
    return _public(rec)


@router.get("/{token}")
def import_status(token: str, request: Request) -> dict:
    return _public(_record(request, token))


@router.delete("/{token}")
def discard_import(token: str, request: Request) -> dict:
    rec = _record(request, token)
    if rec["state"] == "running":
        raise HTTPException(409, "this import is running; it cannot be discarded")
    shutil.rmtree(Path(rec["pdf_path"]).parent, ignore_errors=True)
    del _imports(request)[token]
    return {"token": token, "discarded": True}


@router.post("/{token}/start")
async def start_import(token: str, body: StartRequest, request: Request) -> dict:
    rec = _record(request, token)
    if rec["state"] != "checked":
        raise HTTPException(409, f"this import is {rec['state']}, not waiting to start")
    if any(r["state"] == "running" for r in _imports(request).values()):
        raise HTTPException(409, "another PDF is being imported; wait for it to finish")
    if body.mode not in J.MODES:
        raise HTTPException(400, f"invalid mode: {body.mode!r} (choices: {J.MODES})")
    if body.lang is not None and not J.LANG_RE.match(body.lang):
        raise HTTPException(400, f"invalid lang: {body.lang!r}")
    try:
        page_layouts = {int(k): v for k, v in body.layouts.items()}
    except ValueError as e:
        raise HTTPException(400, f"a layout key is not a page number: {e}") from e
    if any(v not in ("single", "spread") for v in page_layouts.values()):
        raise HTTPException(400, "a page's layout must be single or spread")
    if not all(1 <= k <= rec["page_count"] for k in page_layouts):
        raise HTTPException(400, f"the PDF has {rec['page_count']} pages")
    if rec["not_scans"] and not body.allow_vector:
        raise HTTPException(400, f"{len(rec['not_scans'])} page(s) are not scans "
                                 f"(PDF page {', '.join(map(str, rec['not_scans'][:20]))}); "
                                 f"tick 'import them anyway' to render them regardless")
    rec.update(state="running", done=0, mode=body.mode, lang=body.lang,
               started_at=J.now_iso())
    task = asyncio.create_task(_run_import(request.app, rec, page_layouts,
                                           body.allow_vector))
    # A task nobody references can be garbage-collected mid-run.
    request.app.state.import_tasks.add(task)
    task.add_done_callback(request.app.state.import_tasks.discard)
    return _public(rec)


async def _run_import(app, rec: dict, page_layouts: dict[int, str],
                      allow_vector: bool) -> None:
    def progress(done: int, total: int) -> None:
        rec["done"] = done
        if rec["cancel"]:
            raise ImportCancelled("the server shut down during the import")

    pdf_path = Path(rec["pdf_path"])
    try:
        res = await asyncio.to_thread(
            PI.import_pdf, pdf_path, app.state.jobs_root, dpi=rec["dpi"],
            mode=rec["mode"], lang=rec["lang"], allow_vector=allow_vector,
            staging_root=Path(app.state.import_staging),
            page_layouts=page_layouts, on_page=progress)
    except asyncio.CancelledError:
        # The loop is going away but the render thread is not: tell it to stop
        # after its current page. The upload is left for the stale sweep — the
        # thread may still have it open.
        rec["cancel"] = True
        raise
    except Exception as e:     # ImportRefused's message is written for the operator
        rec.update(state="failed", finished_at=J.now_iso(),
                   error=str(e) if isinstance(e, (PI.ImportRefused, ImportCancelled))
                   else f"{type(e).__name__}: {e}")
    else:
        job_dir = app.state.jobs_root / res.job_id
        for p in res.pages:                      # page order = the PDF's order
            app.state.worker.enqueue(job_dir / p.page)
        rec.update(state="done", job_id=res.job_id, done=res.page_count,
                   warnings=res.warnings, finished_at=J.now_iso())
    shutil.rmtree(pdf_path.parent, ignore_errors=True)


def cancel_running(app) -> None:
    """Shutdown hook: ask every running import to stop after its current page."""
    for rec in getattr(app.state, "imports", {}).values():
        if rec["state"] == "running":
            rec["cancel"] = True
