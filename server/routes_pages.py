"""server.routes_pages — READ-ONLY inspection of a page's pipeline trace, plus
the one write that is allowed here (re-running a page through the worker).

**Why this is read-only, and why that is not a style choice.** Stages 00-06 are
the immutable per-page trace (CLAUDE.md, "Architecture: the stage contract"):
a stage writes only its own numbered folder, and nothing else ever writes into
one. So this module *serves* those artifacts and never touches them. The single
mutating endpoint, ``POST .../rerun``, does not write artifacts either — it
hands the page to ``server.worker``, which subprocesses ``python -m
pipeline.run_all`` exactly as the upload path does. There is deliberately no
second execution path: a web handler that ran a stage in-process would be one,
and it would also block the event loop on a GPU model.

``run_all`` has no single-stage flag (it is the whole chain, by design), so the
only honest affordance the UI can offer is "re-run this page" — which is also
precisely what the stage contract guarantees is safe.

**Previews are generated, never stored.** A debug overlay is a 5-15 MB PNG at
full page resolution; seven of them per page is not something to hand a browser.
``GET .../image`` downscales to JPEG on the fly (~80 ms measured) and sets
``Last-Modified``/``ETag`` so the browser caches it. Nothing is written to disk:
a server-side cache would need invalidating every time a stage re-ran, and at
80 ms it buys nothing worth that.

Endpoints (all under ``/api/jobs/{job_id}/pages/{page}``):
  GET  /inspect   the page's whole story as one small JSON (stages, fuse, split,
                  layout, uncertainty counts) — everything but the words
  GET  /words     per-word text/bbox/conf/decision, straight off Stage 06
  GET  /image     ?path=<rel>&w=<px>  one artifact, downscaled to JPEG
  POST /rerun     enqueue the page on the worker (the ONLY writing endpoint)
"""

from __future__ import annotations

import io
import json
from email.utils import formatdate
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image

from pipeline.editor import _safe_child
from pipeline.run_all import STAGE_ORDER
from server import jobs as J

router = APIRouter(prefix="/api/jobs/{job_id}/pages/{page}", tags=["pages"])

# What a human wants to look at, in the order they want to look at it. Each row
# is (stage folder, overlay file, plain-language label). The labels are for the
# operator, not for the code — "01_fuse" means nothing to someone holding a phone.
OVERLAYS: tuple[tuple[str, str, str], ...] = (
    ("00_ingest", "debug/00_ingest.png", "As uploaded"),
    ("01_fuse", "debug/01_fuse.png", "Chosen frame + close-ups"),
    ("02_split", "debug/02_split.png", "Book found + spine"),
    ("03_dewarp", "debug/03_dewarp.png", "Flattened pages"),
    ("04_layout", "debug/04_layout.png", "Blocks + reading order"),
    ("05_ocr", "debug/05_ocr.png", "Words read"),
    ("06_uncertain", "debug/06_uncertain.png", "Certain vs uncertain"),
)

MAX_PREVIEW_PX = 3000


def _job_dir(request: Request, job_id: str) -> Path:
    job_dir = J.resolve_job_dir(request.app.state.jobs_root, job_id)
    if job_dir is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return job_dir


def _page_dir(request: Request, job_id: str, page: str) -> Path:
    job_dir = _job_dir(request, job_id)
    if not J.PAGE_DIR_RE.match(page):
        raise HTTPException(400, f"not a page name: {page}")
    page_dir = job_dir / page
    if not page_dir.is_dir():
        raise HTTPException(404, f"no such page: {page}")
    return page_dir


def _read_json(path: Path) -> dict | None:
    """A stage artifact, or None. Never raises: a half-written or missing file
    must render the page as 'this stage has nothing to show', not 500 the view."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — unreadable and absent are the same here
        return None


def _fuse_summary(page_dir: Path) -> dict | None:
    d = _read_json(page_dir / "01_fuse" / "fuse.json")
    if d is None:
        return None
    closeups = d.get("closeups", []) or []
    reasons: dict[str, int] = {}
    for c in closeups:
        if not c.get("matched"):
            # The note carries the measured number in parentheses ("only 5
            # inliers (need 8)"); the family is what a human wants counted.
            key = str(c.get("note", "rejected")).split("(")[0].strip()
            reasons[key] = reasons.get(key, 0) + 1
    return {
        "method": d.get("method"),
        "n_frames": d.get("n_frames"),
        "anchor_source": d.get("anchor_source"),
        "closeups_total": len(closeups),
        "closeups_used": sum(1 for c in closeups if c.get("matched")),
        "rejections": reasons,
    }


def _split_summary(page_dir: Path) -> dict | None:
    d = _read_json(page_dir / "02_split" / "split.json")
    if d is None:
        return None
    return {k: d.get(k) for k in (
        "gutter_x", "confident", "method", "width", "height", "pages",
        "book_crop_applied", "book_crop_source", "book_crop_reason",
        "book_crop", "book_search", "ratio",
    )}


def _layout_summary(page_dir: Path) -> dict | None:
    d = _read_json(page_dir / "04_layout" / "layout.json")
    if d is None:
        return None
    types: dict[str, int] = {}
    n = 0
    for sub in d.get("pages", []) or []:
        for b in sub.get("blocks", []) or []:
            n += 1
            t = str(b.get("type", "?"))
            types[t] = types.get(t, 0) + 1
    return {"n_blocks": n, "types": types}


def _uncertainty_summary(page_dir: Path) -> dict | None:
    d = _read_json(page_dir / "06_uncertain" / "resolved.json")
    if d is None:
        return None
    return {
        "mode": d.get("mode"),
        "threshold": d.get("threshold"),
        "conf_floor": d.get("conf_floor"),
        "conf_ceiling": d.get("conf_ceiling"),
        "scored_words": d.get("scored_words"),
        "counts": d.get("counts"),
        "pages": [{"name": p.get("name"), "width": p.get("width"),
                   "height": p.get("height"), "counts": p.get("counts")}
                  for p in d.get("pages", []) or []],
    }


@router.get("/inspect")
def inspect(job_id: str, page: str, request: Request) -> dict:
    """Everything about one page except the words — small enough to fetch eagerly."""
    page_dir = _page_dir(request, job_id, page)
    overlays = [{"stage": s, "path": rel, "label": label}
                for s, rel, label in OVERLAYS if (page_dir / rel).is_file()]
    return {
        "job_id": job_id,
        "page": page,
        "stage_order": list(STAGE_ORDER),
        "status": J.page_status(page_dir),
        "overlays": overlays,
        "fuse": _fuse_summary(page_dir),
        "split": _split_summary(page_dir),
        "layout": _layout_summary(page_dir),
        "uncertainty": _uncertainty_summary(page_dir),
    }


@router.get("/words")
def words(job_id: str, page: str, request: Request) -> Response:
    """Stage 06's per-word verdict, in the coordinate space of the DEWARPED page.

    The sub-page ``name`` ("left.png") is the filename under BOTH ``02_split/``
    and ``03_dewarp/``; the boxes belong to the dewarped one (Stage 05 read it),
    which is why the browser draws them over ``03_dewarp/<name>`` and would be
    subtly wrong to draw them over the split image on a page with any curvature.
    """
    page_dir = _page_dir(request, job_id, page)
    d = _read_json(page_dir / "06_uncertain" / "resolved.json")
    if d is None:
        raise HTTPException(404, "this page has no Stage 06 output yet")
    out = []
    for sub in d.get("pages", []) or []:
        blocks = []
        for b in sub.get("blocks", []) or []:
            blocks.append({
                "id": b.get("id"),
                "type": b.get("type"),
                "bbox": b.get("bbox"),
                "reading_order": b.get("reading_order"),
                "words": [{"text": w.get("text"), "bbox": w.get("bbox"),
                           "conf": w.get("conf"), "decision": w.get("decision")}
                          for w in b.get("words", []) or []],
            })
        blocks.sort(key=lambda b: (b["reading_order"] is None, b["reading_order"]))
        out.append({"name": sub.get("name"), "width": sub.get("width"),
                    "height": sub.get("height"), "counts": sub.get("counts"),
                    "image": f"03_dewarp/{sub.get('name')}", "blocks": blocks})
    return Response(json.dumps({"threshold": d.get("threshold"),
                                "mode": d.get("mode"), "pages": out}),
                    media_type="application/json")


@router.get("/image")
def image(job_id: str, page: str, request: Request,
          path: str, w: int = 1400) -> Response:
    """One artifact under the page dir, downscaled to JPEG. Read-only, guarded."""
    page_dir = _page_dir(request, job_id, page)
    target = _safe_child(page_dir, path)
    if target is None or not target.is_file():
        raise HTTPException(404, "no such artifact")
    if target.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "not an image")

    width = max(64, min(int(w), MAX_PREVIEW_PX))
    mtime = target.stat().st_mtime
    etag = f'W/"{int(mtime)}-{target.stat().st_size}-{width}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    try:
        im = Image.open(target)
        im.thumbnail((width, width * 4), Image.BILINEAR)
        im = im.convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"could not read image: {str(e)[:200]}")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={
        "ETag": etag,
        "Last-Modified": formatdate(mtime, usegmt=True),
        "Cache-Control": "private, max-age=60",
    })


@router.post("/rerun")
def rerun(job_id: str, page: str, request: Request) -> dict:
    """Re-run the whole chain for this page, through the SAME worker as an upload.

    Not "re-run stage N": ``run_all`` is the chain, and re-running from the top
    is what the stage contract promises is safe. Each stage overwrites only its
    own folder, so this is idempotent on the trace.
    """
    page_dir = _page_dir(request, job_id, page)
    request.app.state.worker.enqueue(page_dir)
    J.write_worker_state(page_dir, "queued")
    return {"ok": True, "queued": page_dir.name}
