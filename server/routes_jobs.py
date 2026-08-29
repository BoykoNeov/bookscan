"""server.routes_jobs — job lifecycle + page-upload endpoints.

Upload writes a spread's capture frame(s) into a new ``page_NNN/raw/`` folder,
then enqueues that page onto the background worker (``server/worker.py``),
which subprocesses ``pipeline.run_all`` against it. Poll
``GET /api/jobs/{id}`` to watch a page's stages fill in as the worker gets to
it — there is no push/websocket transport (see the plan doc: no real client
exists yet to build that contract against).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from server import jobs as J

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

_UPLOAD_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def _root(request: Request) -> Path:
    return request.app.state.jobs_root


def _require_job(request: Request, job_id: str) -> Path:
    job_dir = J.resolve_job_dir(_root(request), job_id)
    if job_dir is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return job_dir


@router.post("")
def create_job(request: Request, mode: str = "flag",
               lang: str | None = None) -> dict:
    if mode not in J.MODES:
        raise HTTPException(400, f"invalid mode: {mode!r} (choices: {J.MODES})")
    # Omitted -> the job records no language and Stage 05 uses
    # ``languages.default``; that is the pre-2026-08-29 behaviour and stays
    # the default so an existing client that never sends ``lang`` is unchanged.
    if lang is not None and not J.LANG_RE.match(lang):
        raise HTTPException(400, f"invalid lang: {lang!r}")
    job_id = J.create_job(_root(request), mode=mode, lang=lang)
    return {"job_id": job_id, "mode": mode, "lang": lang}


@router.get("")
def list_jobs(request: Request) -> dict:
    return {"jobs": J.list_jobs(_root(request))}


@router.get("/{job_id}")
def get_job_status(job_id: str, request: Request) -> dict:
    out = J.job_status(_require_job(request, job_id))
    # The choices an operator may pick from, and what a job with no recorded
    # language actually gets. Both come from config.yaml, which the job folder
    # has no way to know about — so they are added here, not in jobs.py.
    langs = (request.app.state.cfg.get("languages", {}) or {})
    out["languages"] = [e.get("code") for e in (langs.get("supported") or [])
                        if isinstance(e, dict) and e.get("code")]
    out["lang_default"] = langs.get("default", "eng")
    return out


@router.patch("/{job_id}")
def set_job_lang(job_id: str, request: Request, lang: str | None = None) -> dict:
    """Change the job's OCR language.

    Applies to pages processed AFTER this call — the per-page trace is
    immutable, so pages already read in another language keep that reading
    until they are re-run. The response says how many those are rather than
    implying the whole job changed.
    """
    job_dir = _require_job(request, job_id)
    if lang is not None and not J.LANG_RE.match(lang):
        raise HTTPException(400, f"invalid lang: {lang!r}")
    J.set_job_lang(job_dir, lang)
    return {"job_id": job_dir.name, "lang": lang,
            "pages_already_processed": J.count_processed_pages(job_dir)}


@router.post("/{job_id}/pages")
async def upload_page(job_id: str, request: Request,
                       files: list[UploadFile] = File(...)) -> dict:
    """One spread's capture frame(s) -> a new ``page_NNN/raw/`` folder.

    Multiple files in one request are the anchor frame + its multi-zoom
    close-ups for the SAME page/spread (Stage 00's ``frame_00`` = anchor
    convention) — not one page per file. Rejects an empty or bad-extension
    upload before creating any folder, so a bad request never leaves a
    half-populated page behind.
    """
    job_dir = _require_job(request, job_id)
    if not files:
        raise HTTPException(400, "no files uploaded")
    for f in files:
        if Path(f.filename or "").suffix.lower() not in _UPLOAD_EXTS:
            raise HTTPException(400, f"unsupported file type: {f.filename}")

    # Locked span: next_page_dir() (read the job dir) through mkdir() (claim
    # the name) must be atomic against a concurrent upload to the same job —
    # see the upload_lock comment in server/app.py.
    async with request.app.state.upload_lock:
        page_dir = J.next_page_dir(job_dir)
        raw_dir = page_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=False)

    saved = []
    for i, f in enumerate(files):
        ext = Path(f.filename).suffix.lower()
        dest = raw_dir / f"frame_{i:02d}{ext}"
        dest.write_bytes(await f.read())
        saved.append(dest.name)

    request.app.state.worker.enqueue(page_dir)
    return {"page": page_dir.name, "files": saved}
