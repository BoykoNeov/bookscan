"""Ask a local vision-language model where the book is, when the detector cannot.

**Why this exists.** ``pipeline/book_boundary.find_book`` abstains whenever its
candidate region covers the whole frame, which is what happens on a pale or
cluttered surface: the mask merges the book with the sofa it is lying on, so no
edge is found anywhere. Stage 02 then searches for the spine across the entire
photograph and locks onto the emptiest column it can find, which is out on the
fabric. Eight families of cue were measured as replacements on 2026-08-28 and
**all eight failed**, structurally (RESULTS 2026-08-28). A vision model does not
have that problem — it is answering "where is the book", not "where is the
paper-coloured blob".

**What it is allowed to change, and what it is not.** The model's box aims the
gutter search and *nothing else*. The pixels Stage 02 emits as the page(s) are
left exactly as the detector decided — which, on every frame this path fires on,
means no crop at all. That is deliberate:

* the measured win is entirely in the gutter (21/21 vs 19/21, RESULTS
  2026-08-29), and it comes from the search WINDOW, not from cutting pixels;
* the one defect that run found was the emitted crop cutting *into* the book by
  more than the outward pad returns (``de_02``, 1.89 % of the labelled page).
  Whether that is acceptable is an open owner decision, deliberately postponed —
  grading "ink lost" is not a safe substitute, because the outer edge of a
  photograph carries no glyphs and would be trimmed silently.

Emitting nothing new sidesteps that decision completely: this path **cannot**
clip, because it never cuts. Nor is running uncropped a new behaviour — 17 of 21
graded spreads already do, and split correctly.

**It is a fallback, never an override.** It runs only when the detector abstained
AND no operator box was supplied, so a working detection and a human's drawn box
both outrank it. If Ollama is not running, the model answers something
unparseable, or the box is a degenerate shape, this returns ``None`` and Stage 02
behaves exactly as it did before — a missing local service must never fail a scan.

See ``tools/vlm_box_eval.py`` for the measurement, and ``docs/RESULTS.md``
2026-08-29.
"""
from __future__ import annotations

import base64
import io
import re
import time

import cv2
import numpy as np
import requests
from PIL import Image

Box = tuple[int, int, int, int]

DEFAULTS: dict = {
    # OFF by default: this path needs a local service that may not be running,
    # and turning it on changes the gutter of every frame the detector abstains
    # on. config.yaml opts in; tools/split_eval takes --vlm to grade it.
    "enabled": False,
    "url": "http://127.0.0.1:11434",
    "model": "qwen3.6:27b",
    # The box was measured at this size; a different one is a different
    # experiment. 1120 px is what RESULTS 2026-08-29 used.
    "max_side": 1120,
    # Ollama defaults num_ctx to 4096 whatever the model advertises, and
    # truncates the image tokens SILENTLY. Always set it.
    "num_ctx": 8192,
    "timeout_s": 180,
    # Refuse a box that is implausible as a book in frame. Not tuning: these
    # reject shapes no book produces, and a refusal costs only the old
    # behaviour.
    "min_area_frac": 0.05,
    "max_area_frac": 0.995,
}

# The model's own documented convention (qwen answers ``bbox_2d`` as x1,y1,x2,y2
# normalised 0-1000). FIXED in advance and never chosen per image — picking the
# reading that fits better on each picture is how a box experiment fools itself.
ORDER = "xyxy"

PROMPT = (
    "This photograph shows an open book lying on a surface. "
    "Return the bounding box of the book itself - the two visible facing pages, "
    "including their printed area and margins. Exclude the surface, the table, "
    "the photographer's hands and the room. "
    'Answer with JSON only, exactly: {"bbox_2d": [x1, y1, x2, y2], "label": "book"} '
    "with coordinates normalised to 0-1000. No other text."
)


def resolve_params(cfg: dict | None) -> dict:
    params = dict(DEFAULTS)
    params.update((cfg or {}).get("vlm_box", {}) or {})
    return params


def encode(image: np.ndarray, max_side: int) -> str:
    """BGR array -> base64 JPEG, downscaled so the long side is ``max_side``."""
    im = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def parse_box(text: str, w: int, h: int) -> tuple[Box | None, str]:
    """First 4-number list in the answer -> pixel box under the FIXED [ORDER].

    Values are read as 0-1000 normalised, the convention [PROMPT] asks for.
    Anything larger is REFUSED rather than reinterpreted as pixels: rescuing an
    off-convention answer per image is exactly the selection this approach
    exists to avoid. Returns ``(box, how_it_was_read)``; the second element is
    recorded in the artifacts so a wrong box can be told from a wrong *reading*
    of a right one.
    """
    vals: list[float] | None = None
    for blob in re.findall(r"\[[^\[\]]*\]", text):
        nums = re.findall(r"-?\d+(?:\.\d+)?", blob)
        if len(nums) == 4:
            vals = [float(n) for n in nums]
            break
    if vals is None:
        return None, "unparseable"
    if max(vals) > 1000.0:
        return None, "out-of-range"
    x0, y0, x1, y1 = vals                      # ORDER == "xyxy", never flipped
    box = (int(round(x0 / 1000 * w)), int(round(y0 / 1000 * h)),
           int(round(x1 / 1000 * w)), int(round(y1 / 1000 * h)))
    return (min(box[0], box[2]), min(box[1], box[3]),
            max(box[0], box[2]), max(box[1], box[3])), "norm1000"


def plausible(box: Box, w: int, h: int, p: dict) -> str | None:
    """Reasons to distrust a parsed box, or None. Shape only — never accuracy."""
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return "degenerate box"
    if not (0 <= x0 and 0 <= y0 and x1 <= w and y1 <= h):
        return "box outside the frame"
    frac = (x1 - x0) * (y1 - y0) / float(w * h)
    if frac < p["min_area_frac"]:
        return f"box covers {frac:.1%} of the frame, too small to be the book"
    if frac > p["max_area_frac"]:
        return f"box covers {frac:.1%} of the frame, so it locates nothing"
    return None


def find_box(image: np.ndarray, p: dict | None = None) -> tuple[Box | None, dict]:
    """Ask the model for the book's box in ORIGINAL image pixels.

    Returns ``(box, diag)``. ``box`` is None whenever anything at all went
    wrong, and ``diag['refused']`` then says what — the caller's correct
    response is always "carry on exactly as before".
    """
    p = p or dict(DEFAULTS)
    h, w = image.shape[:2]
    diag: dict = {"model": p["model"], "max_side": p["max_side"]}
    t0 = time.perf_counter()
    try:
        b64 = encode(image, int(p["max_side"]))
        r = requests.post(
            f"{p['url']}/api/generate",
            json={"model": p["model"], "prompt": PROMPT, "images": [b64],
                  "stream": False, "think": False,
                  "options": {"temperature": 0, "num_ctx": int(p["num_ctx"])}},
            timeout=int(p["timeout_s"]))
        r.raise_for_status()
        text = r.json()["response"]
    except Exception as exc:      # noqa: BLE001 — every failure has one answer
        diag.update(refused=f"{type(exc).__name__}: {exc}",
                    ms=(time.perf_counter() - t0) * 1000.0)
        return None, diag
    diag["ms"] = (time.perf_counter() - t0) * 1000.0
    diag["answer"] = text.strip()[:400]

    box, read_as = parse_box(text, w, h)
    diag["read_as"] = read_as
    if box is None:
        diag["refused"] = f"could not read a box from the answer ({read_as})"
        return None, diag
    bad = plausible(box, w, h, p)
    if bad:
        diag.update(box=list(box), refused=bad)
        return None, diag
    diag["box"] = list(box)
    return box, diag
