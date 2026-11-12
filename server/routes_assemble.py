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

``?spread=page_NNN`` (repeatable) refreshes only those spreads inside the
existing document and keeps every other page with its edits — see
stage07_assemble's docstring. The 409 then means "THESE spreads carry edits",
and ``force=true`` discards those and nothing else. ``carry=true`` keeps every
edit that still matches the re-run page exactly (stage07_assemble's
``_carry_edits``); if any would be lost it refuses with a 409 whose ``detail``
is an object — ``{"message", "carry"}``, the carry report naming each edit that
cannot be kept — and nothing is written. ``carry=true&force=true`` keeps what
matches and drops the rest.

Every success also says which page folders are NOT in the document
(``not_in_document``: unfinished, failed, or still queued/running — the last is
this server's own knowledge, from ``worker.json``) and which were assembled
from an earlier run because their last run failed (``stale``). Assemble used to
skip the former without a word.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from pipeline import stage07_assemble as S7
from pipeline.editor import _document_has_edits, load_document
from server import jobs as J

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["assemble"])


def _last_carry_report(job_dir) -> dict | None:
    """The carry report stage07 just appended to ``document.meta.json``."""
    import json
    try:
        meta = json.loads((job_dir / "document.meta.json").read_text(encoding="utf-8"))
        return meta["params"]["refreshes"][-1]["params"].get("carry_edits")
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None


@router.post("/assemble")
def assemble(job_id: str, request: Request, force: bool = False,
             order_mode: str = "auto",
             spread: list[str] | None = Query(default=None),
             carry: bool = False) -> dict:
    job_dir = J.resolve_job_dir(request.app.state.jobs_root, job_id)
    if job_dir is None:
        raise HTTPException(404, f"no such job: {job_id}")
    if order_mode not in ("auto", "review"):
        raise HTTPException(
            422, f"order_mode must be 'auto' or 'review', got {order_mode!r}")

    spreads = sorted(set(spread or []))
    for s in spreads:
        if not J.PAGE_DIR_RE.match(s):
            raise HTTPException(400, f"not a page name: {s}")
    if carry and not spreads:
        raise HTTPException(400, "carry applies to a spread refresh (?spread=) only")
    if not force:
        try:
            existing = load_document(job_dir)
        except FileNotFoundError:
            existing = None
        if spreads:
            edited = sorted({pg.source_spread for pg in (existing.pages if existing else [])
                             if pg.source_spread in spreads and S7._page_has_edits(pg)})
            if edited and not carry:
                raise HTTPException(
                    409,
                    f"{', '.join(edited)} carry hand edits in the document. "
                    f"Refreshing discards the edits on those spreads only; "
                    f"re-run with ?carry=true to keep the edits that still "
                    f"match, or ?force=true to discard them.")
        elif existing is not None and _document_has_edits(existing):
            raise HTTPException(
                409,
                "document.json already carries edits (translated / reordered "
                "/ corrected). Re-run with ?force=true to discard those edits "
                "and re-assemble from the pipeline.")
    try:
        doc = S7.run(job_dir, request.app.state.cfg, force=force,
                     order_mode=order_mode, only_spreads=spreads or None,
                     carry=carry)
    except S7.EditsWouldBeDropped as e:
        # Must come before RuntimeError (its base): this is the "ask the
        # operator" refusal, with the list to ask about — not a bad request.
        raise HTTPException(409, {"message": str(e), "carry": e.report})
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except RuntimeError as e:
        # e.g. no pages with 06_uncertain/resolved.json yet — a precondition
        # the client can fix (run pages through the pipeline first), not a
        # server error.
        raise HTTPException(400, str(e))

    n_words = sum(bool(w.text.strip()) for pg in doc.pages for blk in pg.blocks
                  for w in blk.words)
    readiness = S7.page_readiness(job_dir)
    not_in = []
    for m in readiness["missing"]:
        state = (J.read_worker_state(job_dir / m["page"]) or {}).get("state")
        why = ("still being processed" if state in ("queued", "running")
               else f"failed at {m['failed_stage']}" if m["failed_stage"]
               else "interrupted — will resume" if state == "interrupted"
               else "not processed")
        not_in.append({"page": m["page"], "why": why})
    return {
        "ok": True, "pages": len(doc.pages), "words": n_words,
        "mode": doc.settings.uncertainty_mode,
        "order_mode": doc.settings.order_mode,
        "refreshed": spreads,
        "carried": _last_carry_report(job_dir) if carry else None,
        "not_in_document": not_in,
        "stale": readiness["stale"],
    }
