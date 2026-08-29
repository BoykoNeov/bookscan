"""Ask a local vision-language model whether a "figure" is really a text panel.

**Why this exists.** A guidebook lays its most valuable data out in boxes: the
route tables (times, altitudes, grades), the hut information panels, the
glossary, and — in a multilingual book — the English and Italian translation
panels. Stage 04 detects a box printed on a coloured background as a picture,
which is a defensible call from geometry alone, and Stage 08 then renders it as
a **photograph of text**. It is not searchable, not correctable, not
translatable, and not spell-checkable.

**How many blocks that actually is, measured rather than assumed.** On the
owner's 25-spread guide, 18 blocks in the finished document are text rendered as
photographs — but only **4** of them are figures at Stage 05, where this pass
runs. The other fourteen are text blocks all the way through Stage 05 and are
turned into pictures at Stage 07 by ``unreadable_panel``, **correctly**: their
OCR is not text a reader could use (the English-language panel of this German
book reads "Englist Version Crane a Of w wa Z SH Zu SO Saar Aatter" at median
confidence 19.2 against that pass's floor of 70.5). Re-typing those would render
noise. They need the *reading* fixed first, and the largest single cause there is
language — an English panel and a trilingual glossary being read as ``deu``.
So this module's job is the 4, which are worth having: 683 words at OCR
confidence ~90, including both of the book's route tables.

**This is the exact inverse of ``pipeline/unreadable_panel.py``**, which re-types
a text block FIGURE when its words are unreadable noise. Both exist because
neither direction is decidable from geometry: one asks "can this be read?", this
one asks "is this worth reading?".

**Two questions, and both must agree.** Asked about the crop alone the model
calls a photographic banner with a table header strip "text"; asked about the
whole page with the candidate outlined it does not. Measured over the 55
candidates of that book, the crop arm calls 23 of them text and the context arm
vetoes 2 — a photo banner and, exactly as ``figure_surface`` predicted, a
photograph of an information board. Both vetoes are correct.

**And a third guard, in the opposite direction: the surface question.** Without
it the pass promotes the **sofa**. Blurred woven upholstery has regular
horizontal striations, and the model calls it TEXT confidently in BOTH arms —
including one full-width band on ``page_004`` carrying **534 words** of weave
noise at median OCR confidence 19.7, which would have rendered as a wall of
garbage. Offering ``SURFACE`` as a third answer to the text prompt does not help:
measured, it changes not one answer of 55. What does work is asking
``figure_surface``'s own question and refusing on **either** arm — over the 36
Stage 05 candidates of that book it refuses 1 (that band) and costs 0 real
panels, and over a wider 21-block set measured through the document it caught
3 of 3 upholstery blocks and cost 0 of 18.

The asymmetry with ``figure_surface`` is deliberate, and it is set by which way
the mistake hurts:

* to **flag** a block as surface (Stage 08 drops it) both arms must say SURFACE,
  because a false positive deletes real content;
* to **promote** a figure to text, neither arm may suspect surface, because a
  suspicion is enough to abstain and abstaining costs only a picture that stays
  a picture.

**THE WORDING OF THE PROMPT IS PART OF THE MEASUREMENT.** These prompts were
first measured naming the book being scanned ("a printed mountaineering
guidebook") and then generalised, as they must be — this is a book scanner, not
a guidebook scanner. The generalisation *changed an answer*: a photographed
warning sign nailed to a rock ("Benützung des Klettersteiges auf eigene
Gefahr!", 15 junk words at OCR confidence 33.9) flipped from PICTURE to TEXT and
was promoted. Restoring it needed one clause — "a PHOTOGRAPH of a sign, a notice
board, a screen or another document is still a PICTURE" — and adding a *second*,
apparently harmless clause to the TEXT branch ("printed as part of the page
itself") then lost a real four-country difficulty table. Every one of those was
3-5 identical draws, so:

* the model is deterministic here at temperature 0; a flip between two runs is a
  changed prompt, not sampling, and the first place to look is your own edit;
* **an edited prompt is an unmeasured prompt.** Re-measure after changing one
  word of these strings, exactly as you would after changing a threshold.

**Promotion deletes pixels — it is not a lesser risk than flagging.** Stage 08
renders a PARAGRAPH from its words, so a picture wrongly promoted is *gone from
the PDF*, not merely mis-labelled. It is recoverable — the block keeps its id,
bbox, words and reading order, ``type_promoted`` marks the change as automatic,
and the editor re-types it back — but the two-questions-must-agree rule is the
safety argument here, exactly as it is there, and must not be "simplified" into
one question.

``unreadable_panel`` is a partial net under it, and only a partial one: measured,
under the un-corrected prompt above the warning-sign photograph *was* promoted
here and that pass demoted it straight back to FIGURE at Stage 07 (median
confidence 33.9 against its floor of 70.5), while all three good promotions
stayed text. **But it can only catch a false positive whose text is junk.** A
photograph carrying *readable* burned-in text — a sign shot close up, a
photographed page of another document — would pass both passes and be deleted
from the render. Do not treat the net as general cover.

**Order matters: this runs BEFORE ``block_reocr``.** That module's
``SKIP_TYPES`` is ``{FIGURE}`` — words inside artwork are labels, not prose — so
a block promoted first is re-read from its own crop for free, under
``block_reocr``'s own measured acceptance rule, with no change to that module.
Running it after would promote a panel and leave it with the page pass's starved
reading. Do not move it.

**The word floor is measured, not inherited.** ``min_words`` is 8 because
sweeping it to 3 adds 15 candidates to that book and **zero** promotions, while
costing 15 more model calls. A figure with no words cannot be a text panel worth
promoting, so some floor is definitional; this one is where the evidence puts it.

**OFF unless configured, and a missing service is never an error.** Same
contract as ``pipeline/vlm_box.py`` and ``pipeline/figure_surface.py``: if Ollama
is not running, an answer is unreadable, or the arms disagree, the block stays a
figure and says so.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

from pipeline import figure_surface as FS
from pipeline.page_model import Block, BlockType

DEFAULTS: dict = {
    "enabled": False,
    "url": "http://127.0.0.1:11434",
    "model": "qwen3.6:27b",
    # The sizes the 21/21 result was measured at, and the same ones
    # figure_surface uses: the crop arm sees the block on its own, the context
    # arm needs the whole page, so they differ.
    "crop_max_side": 768,
    "page_max_side": 1120,
    "num_ctx": 4096,
    "timeout_s": 180,
    # See the module docstring: sweeping this to 3 adds 15 candidates and no
    # promotions on the book it was measured on.
    "min_words": 8,
    # The surface veto. On by default because it is the whole reason three
    # blocks of upholstery are not promoted to paragraphs of weave-noise; the
    # switch exists so that A/B stays runnable.
    "surface_veto": True,
}

CROP_PROMPT = (
    "This is a region cropped from a page of a printed book.\n"
    "Which is it?\n"
    # Do NOT add "printed as part of the page itself" to this branch: measured,
    # it makes the model refuse a four-country difficulty TABLE set with little
    # national flags beside each column (87 words, OCR conf 89.9). The clause
    # below carries the whole correction on its own.
    "TEXT - it is essentially a block of running text, a list, or a table of "
    "figures, possibly printed on a coloured background or inside a box. Its "
    "value to a reader is the words.\n"
    "PICTURE - it is a photograph, a map, a topographic diagram or a drawing. "
    "It may carry labels, place names, or even a great deal of writing: a "
    "PHOTOGRAPH of a sign, a notice board, a screen or another document is "
    "still a PICTURE.\n"
    "Answer with one word only: TEXT or PICTURE."
)

PAGE_PROMPT = (
    "This is a photograph of one page of a printed book, with one region "
    "outlined in a thick magenta rectangle.\n"
    "Is the OUTLINED REGION a block of text (running text, a list, or a table "
    "of figures - possibly printed on a coloured background or inside a box), "
    "or is it a picture (a photograph, a map, a topographic diagram or a "
    "drawing, which may carry labels)? A PHOTOGRAPH of a sign, a notice board "
    "or another document is a picture, however much writing it contains.\n"
    "Answer with one word only: TEXT or PICTURE."
)

# What a promoted panel becomes. Stage 08 maps PARAGRAPH and TABLE to the same
# <p> with a different class, so telling them apart would cost a third model
# question and change nothing a reader sees.
PROMOTED_TYPE = BlockType.PARAGRAPH


@dataclass
class PanelNote:
    """One promotion, for ``meta.json`` provenance."""

    block_id: int
    n_words: int
    crop_answer: str
    page_answer: str
    ms: float


def resolve_params(cfg: dict | None) -> dict:
    params = dict(DEFAULTS)
    params.update((cfg or {}).get("text_panel", {}) or {})
    return params


def _clamp(page: np.ndarray, bbox) -> tuple[int, int, int, int]:
    h, w = page.shape[:2]
    x, y = max(0, int(bbox.x)), max(0, int(bbox.y))
    return x, y, min(w, x + int(bbox.w)), min(h, y + int(bbox.h))


def _outlined(page: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    h, w = page.shape[:2]
    marked = page.copy()
    cv2.rectangle(marked, (box[0], box[1]), (box[2], box[3]), (255, 0, 255),
                  max(6, int(min(h, w) * 0.008)))
    return marked


def is_text_panel(page: np.ndarray, bbox, n_words: int,
                  p: dict | None = None) -> tuple[bool, dict]:
    """Is the figure at ``bbox`` really a block of text?

    ``page`` is the dewarped subpage image and ``bbox`` a ``BBox`` in its
    pixels. Returns ``(promote, diag)``. ``promote`` is True only when both text
    questions say TEXT and neither surface question says SURFACE — anything
    else, including a service that is not running, is False and leaves the block
    exactly as it was.
    """
    p = p or dict(DEFAULTS)
    diag: dict = {"model": p["model"]}
    if n_words < int(p["min_words"]):
        return False, {**diag, "refused": f"{n_words} words < min_words"}
    x, y, x1, y1 = _clamp(page, bbox)
    if x1 <= x or y1 <= y:
        return False, {**diag, "refused": "degenerate bbox"}

    t0 = time.perf_counter()
    crop = page[y:y1, x:x1]

    def done(flag: bool) -> tuple[bool, dict]:
        diag["ms"] = (time.perf_counter() - t0) * 1000.0
        return flag, diag

    crop_answer = FS._ask(crop, CROP_PROMPT, p["crop_max_side"], p)
    diag["crop_answer"] = crop_answer[:40]
    # Short-circuit at every step: a later question can only take a promotion
    # away, never grant one, and each call costs about a second.
    if "TEXT" not in crop_answer:
        return done(False)

    marked = _outlined(page, (x, y, x1, y1))
    page_answer = FS._ask(marked, PAGE_PROMPT, p["page_max_side"], p)
    diag["page_answer"] = page_answer[:40]
    if "TEXT" not in page_answer:
        return done(False)

    if not p.get("surface_veto", True):
        return done(True)
    # The veto: EITHER surface arm is enough to refuse. See the docstring for
    # why this bar differs from figure_surface's own.
    surf_crop = FS._ask(crop, FS.CROP_PROMPT, p["crop_max_side"], p)
    diag["surface_crop"] = surf_crop[:40]
    if "SURFACE" in surf_crop:
        return done(False)
    surf_page = FS._ask(marked, FS.PAGE_PROMPT, p["page_max_side"], p)
    diag["surface_page"] = surf_page[:40]
    return done("SURFACE" not in surf_page)


def promote_text_panels(blocks: list[Block], page: np.ndarray,
                        p: dict | None = None) -> tuple[list[Block], list[PanelNote]]:
    """Re-type every FIGURE block the model twice calls text.

    ``blocks`` is mutated in place (the caller already owns fresh copies), which
    is what ``block_reocr`` needs: it is handed the same list immediately after
    and re-reads whatever is no longer a FIGURE.

    Sets ``type`` and raises ``type_promoted``, exactly as caption promotion and
    ``unreadable_panel`` do — this is an AUTOMATIC decision and the editor must
    never read it as a user override. ``type_auto`` is deliberately NOT set here:
    Stage 07's ``_enrich_block`` seeds it from ``type``, so the promoted type
    lands there as the automatic one on its own.
    """
    pp = dict(DEFAULTS)
    if p:
        pp.update({k: v for k, v in p.items() if k in DEFAULTS})
    notes: list[PanelNote] = []
    if not pp["enabled"] or page is None:
        return blocks, notes
    for blk in blocks:
        if blk.type is not BlockType.FIGURE:
            continue
        n_words = sum(1 for w in blk.words if w.text.strip())
        ok, diag = is_text_panel(page, blk.bbox, n_words, pp)
        if not ok:
            continue
        blk.type = PROMOTED_TYPE
        blk.type_promoted = True
        notes.append(PanelNote(
            block_id=blk.id, n_words=n_words,
            crop_answer=diag.get("crop_answer", ""),
            page_answer=diag.get("page_answer", ""),
            ms=round(diag.get("ms", 0.0), 1)))
    return blocks, notes
