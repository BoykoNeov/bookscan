"""server.routes_editor — the visual editor SPA + its job-scoped API, mounted
under ``/jobs/{job_id}/``.

Lifts ``pipeline/editor.py``'s pure functions UNCHANGED (``load_document``,
``save_document`` — which internally normalizes edits — and
``render_preview``, the HTML-only preview path; the slow Playwright/Chromium
PDF export stays a separate, not-yet-built path, per editor.py's own
docstring: "Preview is HTML-only ... [PDF] stays a separate explicit export,
not the live-preview loop"). Only the transport is new: FastAPI routes
instead of editor.py's stdlib ``http.server``, and job-scoped instead of one
job per server process.

The SPA (``pipeline/assets/editor/index.html``) fetches every one of its own
API paths RELATIVE to its own URL (``api/document``, ``document_assets/...``,
``render/page.html`` — no leading ``/``), so mounting it at
``/jobs/{job_id}/`` makes every fetch resolve correctly with zero further
changes to the file: it is the exact same SPA editor.py serves at its own
root ``/``, just given a job-scoped base URL instead. The trailing slash on
that base URL is load-bearing (``api/document`` resolves against
``/jobs/{id}/`` to ``/jobs/{id}/api/document``; against ``/jobs/{id}``
without the slash it would resolve to ``/jobs/api/document``), so a bare
``/jobs/{id}`` request redirects to the slash form before anything else runs.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from pipeline.editor import (
    ASSETS_DIRNAME, EDITOR_DIR, _document_has_edits, _safe_child,
    load_document, render_preview, save_document,
)
from pipeline.page_model import Document
from server import jobs as J

router = APIRouter(prefix="/jobs/{job_id}", tags=["editor"])


def _job_dir(request: Request, job_id: str) -> Path:
    job_dir = J.resolve_job_dir(request.app.state.jobs_root, job_id)
    if job_dir is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return job_dir


@router.get("")
def redirect_to_trailing_slash(job_id: str) -> RedirectResponse:
    return RedirectResponse(f"/jobs/{job_id}/", status_code=307)


@router.get("/")
def index(job_id: str, request: Request) -> FileResponse:
    _job_dir(request, job_id)  # 404 before serving the SPA for an unknown job
    return FileResponse(EDITOR_DIR / "index.html")


@router.get("/api/meta")
def meta(job_id: str, request: Request) -> dict:
    job_dir = _job_dir(request, job_id)
    return {"job_dir": str(job_dir), "job": job_dir.name}


@router.get("/api/document")
def get_document(job_id: str, request: Request) -> Response:
    job_dir = _job_dir(request, job_id)
    try:
        doc = load_document(job_dir)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return Response(doc.model_dump_json(), media_type="application/json")


@router.put("/api/document")
async def put_document(job_id: str, request: Request) -> dict:
    job_dir = _job_dir(request, job_id)
    try:
        doc = Document.model_validate_json(await request.body())
    except Exception as e:  # pydantic ValidationError or malformed JSON
        raise HTTPException(400, f"invalid document: {str(e)[:2000]}")
    save_document(job_dir, doc)  # normalizes edit flags + atomic write + .bak
    return {"ok": True, "has_edits": _document_has_edits(doc)}


@router.post("/api/render")
def post_render(job_id: str, request: Request) -> dict:
    job_dir = _job_dir(request, job_id)
    try:
        render_preview(job_dir)  # HTML-only, no Playwright — safe in-process
    except Exception as e:
        raise HTTPException(500, str(e)[:2000])
    return {"ok": True, "href": "render/page.html"}


@router.get("/render/page.html")
def get_render(job_id: str, request: Request) -> FileResponse:
    job_dir = _job_dir(request, job_id)
    path = job_dir / "render" / "page.html"
    if not path.is_file():
        raise HTTPException(404, "no render yet — POST api/render first")
    return FileResponse(path)


@router.get("/document_assets/{relpath:path}")
def get_asset(job_id: str, relpath: str, request: Request) -> FileResponse:
    job_dir = _job_dir(request, job_id)
    target = _safe_child(job_dir / ASSETS_DIRNAME, relpath)
    if target is None or not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(target)
