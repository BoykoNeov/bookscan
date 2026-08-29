"""Ask a local vision-language model whether a "figure" is the sofa.

**Why this exists.** ``book_boundary.find_book`` cannot see the book on a pale
or cluttered surface, so Stage 02 emits page images that still contain a band
of whatever the book was lying on. Stage 04 then does its job correctly and
correctly reports a large, textured, picture-shaped region — the upholstery —
and Stage 07 places it in the document as a figure. On the owner's 25-spread
book, 16 of 163 figures are the sofa or the shadow behind it, all on the four
spreads whose crop kept the full frame height. They render in the PDF as
full-width photographs of fabric, with Stage 05's reading of the weave
underneath them.

**This does not fix the crop.** The margins on those spreads are still wrong
and the dewarp still ran on a frame containing fabric. Cutting to a model's box
is a separate, deliberately postponed owner decision (see ``vlm_box``). This
removes the visible symptom only, and does so without cutting a single pixel.

**Two questions, and both must agree.** Asked about the crop alone the model
calls a printed photograph of an information board "surface" — reasonably, since
a book about via ferratas is full of printed photographs of rock, and a picture
of a rough surface looks like a rough surface. Asked about the whole page with
the candidate outlined it calls a tilted chapter banner "surface" instead. Each
single question therefore discards real content. Their intersection, measured
over all 163 figures of that book, flags 16 and loses nothing (RESULTS
2026-08-29):

===========================  ========  =====================================
arm                          flagged   wrong
===========================  ========  =====================================
crop alone                        24   1 real photo + 6 slivers of real photos
page with the block outlined      18   1 real chapter banner
both must agree                   16   none
===========================  ========  =====================================

**Nothing is deleted.** A flagged block keeps its place in ``document.json`` and
is marked ``is_surface``; Stage 08 skips it and the editor can put it back. A
wrongly dropped chapter header the operator can restore is a different risk
class from one that silently vanished — and at n = 1 book that difference is
the whole safety argument.

**OFF unless configured, and a missing service is never an error.** Same
contract as ``pipeline/vlm_box.py``: if Ollama is not running, the answer is
unreadable, or the two arms disagree, the block is kept exactly as before.
"""
from __future__ import annotations

import base64
import io
import time

import cv2
import numpy as np
import requests
from PIL import Image

DEFAULTS: dict = {
    "enabled": False,
    "url": "http://127.0.0.1:11434",
    "model": "qwen3.6:27b",
    # The sizes the 16/16 result was measured at: the crop arm sees the block
    # on its own, the context arm needs the whole page, so they differ.
    "crop_max_side": 768,
    "page_max_side": 1120,
    "num_ctx": 4096,
    "timeout_s": 180,
    # Blocks smaller than this fraction of the page are not worth a second of
    # model time and are not what anyone complained about; a 21 px sliver is
    # also the case both arms handled worst.
    "min_area_frac": 0.01,
}

CROP_PROMPT = (
    "This image is a region cropped from a photograph of an open book.\n"
    "It is EITHER (a) part of the book's printed page - a picture, diagram, "
    "map, table, logo, banner or block of text that is PRINTED ON PAPER - OR "
    "(b) part of the surface the book is lying on, or the room behind it "
    "(fabric, upholstery, a table top, carpet, wood, a wall).\n"
    "Answer with one word only: PAGE or SURFACE."
)

PAGE_PROMPT = (
    "This is a photograph of one page of an open book, with one region "
    "outlined in a thick magenta rectangle.\n"
    "The photograph may include some of the surface the book is lying on "
    "(fabric, upholstery, a table, carpet, wood) around the edges of the "
    "paper.\n"
    "Is the OUTLINED REGION printed on the book's paper, or is it part of "
    "that surrounding surface?\n"
    "Answer with one word only: PAPER or SURFACE."
)


def resolve_params(cfg: dict | None) -> dict:
    params = dict(DEFAULTS)
    params.update((cfg or {}).get("figure_surface", {}) or {})
    return params


def _encode(image: np.ndarray, max_side: int) -> str:
    im = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _ask(image: np.ndarray, prompt: str, max_side: int, p: dict) -> str:
    """The model's one-word answer, upper-cased, or ``""`` if anything failed.

    Every failure has the same meaning to the caller — "no opinion" — so they
    all collapse to the empty string rather than raising."""
    try:
        r = requests.post(
            f"{p['url']}/api/generate",
            json={"model": p["model"], "prompt": prompt,
                  "images": [_encode(image, int(max_side))],
                  "stream": False, "think": False,
                  "options": {"temperature": 0, "num_ctx": int(p["num_ctx"])}},
            timeout=int(p["timeout_s"]))
        r.raise_for_status()
        return str(r.json()["response"]).strip().upper()
    except Exception:      # noqa: BLE001 — one answer to every failure
        return ""


def is_surface(page: np.ndarray, bbox: dict,
               p: dict | None = None) -> tuple[bool, dict]:
    """Is the block at ``bbox`` the surface the book is lying on?

    ``page`` is the dewarped page image, ``bbox`` a ``{x,y,w,h}`` in its
    pixels. Returns ``(flagged, diag)``. ``flagged`` is True only when BOTH
    questions say surface — anything else, including a service that is not
    running, is False and leaves the block exactly as it was.
    """
    p = p or dict(DEFAULTS)
    h, w = page.shape[:2]
    x, y = max(0, int(bbox["x"])), max(0, int(bbox["y"]))
    x1, y1 = min(w, x + int(bbox["w"])), min(h, y + int(bbox["h"]))
    diag: dict = {"model": p["model"]}
    if x1 <= x or y1 <= y:
        return False, {**diag, "refused": "degenerate bbox"}
    frac = (x1 - x) * (y1 - y) / float(w * h)
    if frac < float(p["min_area_frac"]):
        return False, {**diag, "refused": f"block covers {frac:.1%} of the page"}

    t0 = time.perf_counter()
    crop_answer = _ask(page[y:y1, x:x1], CROP_PROMPT,
                       p["crop_max_side"], p)
    diag["crop"] = crop_answer[:40]
    # Short-circuit: the second question costs a second and cannot change a
    # "no" into a "yes" — both arms must agree.
    if "SURFACE" not in crop_answer:
        diag["ms"] = (time.perf_counter() - t0) * 1000.0
        return False, diag

    marked = page.copy()
    thickness = max(6, int(min(h, w) * 0.008))
    cv2.rectangle(marked, (x, y), (x1, y1), (255, 0, 255), thickness)
    page_answer = _ask(marked, PAGE_PROMPT, p["page_max_side"], p)
    diag["page"] = page_answer[:40]
    diag["ms"] = (time.perf_counter() - t0) * 1000.0
    return "SURFACE" in page_answer, diag
