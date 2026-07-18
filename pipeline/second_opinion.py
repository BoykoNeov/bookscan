"""Stage 05 second opinion — EasyOCR cross-engine disagreement.

CLAUDE.md non-negotiable: cross-engine disagreement is a SECOND, independent
uncertainty trigger. Tesseract stays the sole text + confidence source; EasyOCR
only sets ``Word.engine_disagree`` (never the text, never the confidence — no
reliable word boxes, hallucination risk).

**Why the alignment is token-sequence-level, not box-IoU.** EasyOCR's ``readtext``
returns line/phrase polygons with *concatenated* text (one region ≈ one line,
up to ~15 words), NOT word boxes. So we cannot IoU-match EasyOCR boxes to
Tesseract words. Instead: group Tesseract words into the EasyOCR line region that
spatially contains them, x-sort them (Tesseract's block word-ORDER must not
masquerade as a text disagreement), and diff the two token sequences with
``difflib``. Only ``replace`` opcodes are candidates:

  - a pure ``delete`` is as likely EasyOCR under-detection as a Tesseract error;
  - an ``insert`` has no Tesseract word to mark.

**The dictionary gate — the load-bearing precision filter (see RESULTS.md,
2026-07-18).** A raw token-diff was MEASURED on real Cyrillic (bg_01) to flag
89/763 words (11.7%) — precision ≈ 0. The cause: on Cyrillic, EasyOCR is the
*noisier* reader (it emits Latin homoglyphs — ``се``→``ce``, ``а``→``a`` — and
its own misreads ``които``→``конто``), so raw disagreement surfaces EASYOCR's
errors, not Tesseract's. Edit distance can't separate a real 1-char Tesseract
misread (``Chapmarked``→``Chopmarked``) from 1-char homoglyph noise — both are
single substitutions. The tiebreaker is a per-language dictionary:

    flag a Tesseract word iff it is a 1↔1 replace with EasyOCR
    AND  norm(T) ∉ dict  AND  the paired norm(E) ∈ dict

i.e. flag only when Tesseract produced a NON-word and EasyOCR nominated a VALID
word IN PLACE OF THAT EXACT TOKEN. The **1↔1 restriction is load-bearing**: the
premise ("EasyOCR nominated a valid word in place of *this* token") is only
defined when the replace slot pairs one token with one token. In a multi-token
replace the aligned counterpart is undetermined, so a valid E token can vouch for
flagging a DIFFERENT T token whose real counterpart is itself garbage — measured
on bg_01: T[``помашки`` ``села``] ↔ E[``помошки`` ``село``] wrongly flagged the
CORRECT ``помашки`` because ``село`` ∈ dict. The gate subsumes homoglyph-folding
and join-tolerance (``се`` ∈ dict → never flagged, whatever EasyOCR read).
Measured on bg_01 against a GENERAL (non-GT-derived) frequency lexicon: 1 clean
catch (``касалница``→``касапница``, ``касапница`` count 478 — robust), no false
flags; a naive raw token-diff over the same page flagged 89 (precision ≈ 0). See
RESULTS.md 2026-07-18 for the honest measurement + activation caveats.

Honest blind spot: ``norm(T) ∉ dict AND norm(E) ∉ dict`` is a MISS (both
non-words). The **measured dominant miss is PROPER NOUNS / toponyms**
(``Дедеагач``, ``Гюмурджина``, ``Дуганхисар`` are ALL absent from a general
frequency list, yet dominate this corpus and are the highest OCR-error-risk
tokens) — closing that needs a gazetteer overlay, not a bigger wordlist. An
accepted recall loss traded for precision, correct when raw precision is ≈ 0.

**Inert-seam contract (repo pattern, mirrors ``stage08.join_hyphen``).** The gate
NEEDS a per-language lexicon, which does not yet exist in the repo (it is the same
dependency the de-hyphenation seam waits on). With ``dictionary is None`` the
trigger flags NOTHING — the mechanism is built + unit-tested but stays inert until
the owner supplies a lexicon (see config ``engines.easyocr.lexicon``). Stage 05
therefore does not even load EasyOCR when no lexicon is present (its second pass
would produce nothing — wasted GPU).

**Region-confidence gate.** EasyOCR emits its own junk (e.g. conf 0.09 ``'L='``
against a perfect Tesseract ``'a'``@96). Regions below ``min_region_conf`` are
ignored so the second engine's unreliable reads can't nominate an alternative.
This does NOT contradict CLAUDE.md's "independent of raw confidence" rule — that
rule is about ignoring *Tesseract's* confidence; gating on the *second* engine's
own reliability is correct.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

# Keep letters (Latin + Cyrillic) and digits; drop everything else, casefold.
_NORM_RE = re.compile(r"[^0-9a-zA-Zа-яёА-ЯЁ]+")


def normalize_token(s: str) -> str:
    """Comparison form: strip punctuation/whitespace, fold case. Latin + Cyrillic."""
    return _NORM_RE.sub("", s).casefold()


def load_lexicon(paths: list[Path | str]) -> set[str] | None:
    """Load a per-language lexicon (whitespace-separated words, one or many per
    line) from the first path that exists, normalized to ``normalize_token`` form.

    Returns ``None`` when no path exists — the inert-seam signal that keeps the
    disagreement trigger dormant (and, in Stage 05, keeps EasyOCR unloaded). This
    lexicon does not yet ship in the repo; supplying it is an owner dependency,
    shared with the de-hyphenation seam (see RESULTS.md 2026-07-18)."""
    for p in paths:
        if p and Path(p).exists():
            words = Path(p).read_text(encoding="utf-8").split()
            lex = {n for n in (normalize_token(w) for w in words) if n}
            return lex or None
    return None


@dataclass(frozen=True)
class Region:
    """One EasyOCR line/phrase read: axis-aligned box + concatenated text + conf."""
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: float


def _center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2.0, y + h / 2.0


def _overlap_area(box: tuple[float, float, float, float], r: Region) -> float:
    x, y, w, h = box
    ix0, iy0 = max(x, r.x0), max(y, r.y0)
    ix1, iy1 = min(x + w, r.x1), min(y + h, r.y1)
    return max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)


def find_disagreements(
    word_boxes: list[tuple[float, float, float, float]],
    word_texts: list[str],
    regions: list[Region],
    min_region_conf: float,
    dictionary: set[str] | None,
) -> set[int]:
    """Return the indices of Tesseract words that disagree with EasyOCR.

    ``word_boxes`` (x, y, w, h) and ``regions`` must share the SAME pixel space
    (both come from the 03_dewarp subpage image). ``word_texts`` is parallel to
    ``word_boxes``. ``dictionary`` is the per-language lexicon of NORMALIZED words
    (``normalize_token`` form). Pure function — no cv2 / no easyocr — so the
    alignment logic is unit-testable without a GPU.

    Inert-seam contract: with ``dictionary is None`` (no lexicon available) this
    flags NOTHING — the disagreement trigger needs the dictionary tiebreaker to
    have any precision (see module docstring + RESULTS.md 2026-07-18).
    """
    if dictionary is None:
        return set()
    regions = [r for r in regions if r.conf >= min_region_conf]
    if not regions or not word_boxes:
        return set()

    # Assign each word to the single best containing region (word center inside
    # the region box, max box-overlap area) — avoids double-processing a word
    # that two overlapping regions both cover.
    assignment: dict[int, list[int]] = {}
    for wi, box in enumerate(word_boxes):
        cx, cy = _center(box)
        best_ri: int | None = None
        best_key = (0.0, 0.0)  # (overlap area, -region area): tie-break to tighter line
        for ri, r in enumerate(regions):
            if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1:
                key = (_overlap_area(box, r), -(r.x1 - r.x0) * (r.y1 - r.y0))
                if key > best_key:
                    best_key, best_ri = key, ri
        if best_ri is not None:
            assignment.setdefault(best_ri, []).append(wi)

    flagged: set[int] = set()
    for ri, word_idxs in assignment.items():
        # x-sort so Tesseract's stored word order can't look like a text change.
        word_idxs.sort(key=lambda i: word_boxes[i][0])
        # Drop Tesseract tokens that normalize to empty (pure punctuation) — keep
        # the surviving tokens' original word indices for flagging.
        t_pairs = [(i, normalize_token(word_texts[i])) for i in word_idxs]
        t_pairs = [(i, n) for i, n in t_pairs if n]
        t_toks = [n for _, n in t_pairs]
        e_toks = [n for n in (normalize_token(t) for t in regions[ri].text.split()) if n]
        if not t_toks:
            continue
        sm = difflib.SequenceMatcher(a=t_toks, b=e_toks, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "replace":
                continue
            # Only 1<->1 replaces (see module docstring): the dictionary
            # tiebreaker's premise — "EasyOCR nominated a valid word IN PLACE OF
            # this exact Tesseract token" — is only defined when one token pairs
            # with one token. A multi-token replace has an undetermined alignment,
            # so a valid E token could vouch for flagging a DIFFERENT T token whose
            # true counterpart is itself garbage (the помашки/село false flag).
            if i2 - i1 != 1 or j2 - j1 != 1:
                continue
            t_tok, e_tok = t_toks[i1], e_toks[j1]
            if t_tok not in dictionary and e_tok in dictionary:
                flagged.add(t_pairs[i1][0])
    return flagged


class EasyOCRSecondOpinion:
    """Lazy EasyOCR reader. Model loads on first ``regions()`` call; ``close()``
    drops it and frees VRAM, matching the pipeline's per-stage GPU hygiene."""

    def __init__(self, langs: list[str], gpu: bool = True) -> None:
        self._langs = list(langs)
        self._gpu = gpu
        self._reader = None

    def _ensure(self):
        if self._reader is None:
            import easyocr  # heavy import; only when a page actually needs it
            self._reader = easyocr.Reader(self._langs, gpu=self._gpu)
        return self._reader

    def regions(self, image) -> list[Region]:
        """``image`` = a path (str/Path) or a BGR numpy array, as ``readtext`` accepts."""
        reader = self._ensure()
        out: list[Region] = []
        for poly, text, conf in reader.readtext(str(image) if not hasattr(image, "shape") else image):
            xs = [float(p[0]) for p in poly]
            ys = [float(p[1]) for p in poly]
            out.append(Region(min(xs), min(ys), max(xs), max(ys), text, float(conf)))
        return out

    def close(self) -> None:
        self._reader = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
