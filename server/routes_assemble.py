"""server.routes_assemble — POST /api/jobs/{job_id}/assemble.

Runs stage07_assemble IN-PROCESS, not subprocessed: unlike Stage 03 (UVDoc)
and Stage 04 (DocLayout-YOLO), assemble does no GPU model execution (it only
reads each page's 06_uncertain/resolved.json and copies/crops images), so the
crash-isolation rationale in pipeline/run_all.py's docstring — the reason
the *page pipeline* is always subprocessed — doesn't apply here.

Pre-checks the clobber guard itself (reusing pipeline.editor's own
``_document_has_edits``, the exact predicate stage07's own ``--force`` flag
guards against) so a clean 409 doesn't require parsing stage07's exception
text — mirrors stage07_assemble.py's own refusal rule, just surfaced as an
HTTP status instead of a raised RuntimeError.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from pipeline import stage07_assemble as S7
from pipeline.editor import _document_has_edits, load_document
from server import jobs as J

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["assemble"])


@router.post("/assemble")
def assemble(job_id: str, request: Request, force: bool = False) -> dict:
    job_dir = J.resolve_job_dir(request.app.state.jobs_root, job_id)
    if job_dir is None:
        raise HTTPException(404, f"no such job: {job_id}")

    if not force:
        try:
            existing = load_document(job_dir)
        except FileNotFoundError:
            existing = None
        if existing is not None and _document_has_edits(existing):
            raise HTTPException(
                409,
                "document.json already carries edits (translated / reordered "
                "/ corrected). Re-run with ?force=true to discard those edits "
                "and re-assemble from the pipeline.")

    try:
        doc = S7.run(job_dir, request.app.state.cfg, force=force)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        # e.g. no pages with 06_uncertain/resolved.json yet — a precondition
        # the client can fix (run pages through the pipeline first), not a
        # server error.
        raise HTTPException(400, str(e))

    n_words = sum(bool(w.text.strip()) for pg in doc.pages for blk in pg.blocks
                  for w in blk.words)
    return {
        "ok": True, "pages": len(doc.pages), "words": n_words,
        "mode": doc.settings.uncertainty_mode,
    }
