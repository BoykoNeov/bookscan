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
Also load-bearing: the voucher (``e_tok``) must be **≥2 chars**. A bare valid
letter (Cyrillic ``к``, which a Hunspell dict accepts but a frequency list never
listed) is too weak to certify a Tesseract non-word is wrong — measured on bg_01,
it let ``кК.),`` ← ``к`` flag; the guard drops it.

Measured on bg_01 against the REAL production lexicon (LibreOffice ``bg_BG``
Hunspell via spylls + a GeoNames-BG overlay): 1 clean catch
(``касалница``→``касапница``), 0 false flags — and the gate correctly did NOT
flag ``караагач`` (Tesseract right, EasyOCR's ``каразгач`` wrong: the dictionary
protected the correct word). Honest framing: on this clean page Hunspell does not
*measurably* beat the frequency list (both ~0 FP; the помашки over-flag was
already killed by the 1↔1 fix, not by coverage). The Hunspell win is *principled*
coverage — inflected real words like ``помашки`` validate morphologically, so the
gate over-flags less in principle — which one thin page cannot demonstrate. A
naive raw token-diff over the same page flagged 89 (precision ≈ 0). See RESULTS.md
2026-07-18 for the full measurement + activation caveats.

Honest blind spot: ``norm(T) ∉ dict AND norm(E) ∉ dict`` is a MISS (both
non-words). The **measured dominant miss is PROPER NOUNS / toponyms**
(``Дедеагач``, ``Гюмурджина``, ``Дуганхисар`` are ALL absent from a general
frequency list, yet dominate this corpus and are the highest OCR-error-risk
tokens) — closing that needs a gazetteer overlay, not a bigger wordlist. An
accepted recall loss traded for precision, correct when raw precision is ≈ 0.

**The lexicon is a Hunspell dictionary, checked at runtime (see
``HunspellLexicon``).** ``load_lexicon`` resolves ``models/lexicons/<lang>.dic`` +
``.aff`` into a spylls-backed checker whose ``__contains__`` validates a token
against Hunspell's morphology — so inflected forms (``помашки``) validate WITHOUT
being enumerated, which a flat frequency list could not do. For Bulgarian a
GeoNames gazetteer overlay (``bg.geo.txt``) is unioned on for the toponym blind
spot. ``find_disagreements`` is agnostic to which it gets: a ``set`` or a
``HunspellLexicon`` both answer ``tok in dictionary``. Build both with
``python -m tools.setup_lexicons`` (downloads LibreOffice dicts + the GeoNames-BG
dump into gitignored ``models/lexicons/``).

**Inert-seam contract (repo pattern, mirrors ``stage08.join_hyphen``).** The gate
NEEDS that per-language lexicon (the same dependency the de-hyphenation seam waits
on). A fresh clone has no ``models/lexicons/`` (gitignored), so ``load_lexicon``
returns ``None`` and the trigger flags NOTHING — the mechanism is built +
unit-tested but stays inert until ``setup_lexicons`` (or the owner) supplies the
dicts (see config ``engines.easyocr.lexicon``). Stage 05 therefore does not even
load EasyOCR when no lexicon is present (its second pass would produce nothing —
wasted GPU).

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


def _load_overlay(path: Path | str | None) -> frozenset[str]:
    """Load an optional gazetteer overlay (one word per line) as NORMALIZED
    tokens, to union proper nouns / toponyms onto the Hunspell base. Place names
    are the MEASURED blind spot — ``Дедеагач``/``Гюмурджина`` are absent from the
    general dictionary yet dominate this corpus (see RESULTS.md 2026-07-18)."""
    if path and Path(path).exists():
        words = Path(path).read_text(encoding="utf-8").split()
        return frozenset(n for n in (normalize_token(w) for w in words) if n)
    return frozenset()


class HunspellLexicon:
    """Per-language validity check backed by a Hunspell ``.dic``/``.aff`` pair
    (via the pure-Python ``spylls``), optionally unioned with a normalized overlay
    set (a GeoNames gazetteer for the proper-noun blind spot).

    Implements ``__contains__`` over NORMALIZED tokens (``normalize_token`` form)
    so it is a DROP-IN for the ``set[str]`` the gate used before: the whole of
    ``find_disagreements`` is unchanged — it still just tests ``tok in dictionary``.
    Membership means the token is a valid surface form per Hunspell's morphology
    (inflections/derivations — this is why ``помашки`` validates where a flat
    frequency list missed it) OR is present in the overlay.

    Case: gate tokens arrive casefolded; Hunspell is case-aware, so we also try
    the Capitalized form (a lowered proper noun / German noun still validates).
    ``spylls`` is imported LAZILY here — the module stays importable (and the pure
    logic tests keep running) without the dependency; it is only needed once a
    real lexicon is actually configured.
    """

    def __init__(self, dic_path: Path | str, aff_path: Path | str,
                 overlay: frozenset[str] = frozenset()) -> None:
        from spylls.hunspell import Dictionary  # lazy: only when a lexicon exists
        # spylls reads ``<base>.aff`` + ``<base>.dic``; aff_path is required to
        # exist by the caller but the base drives both.
        self._dic = Dictionary.from_files(str(Path(dic_path).with_suffix("")))
        self._overlay = overlay
        self._stems = len(self._dic.dic.words)
        self._cache: dict[str, bool] = {}

    def __contains__(self, token: str) -> bool:
        if not token:
            return False
        if token in self._overlay:
            return True
        hit = self._cache.get(token)
        if hit is None:
            hit = bool(self._dic.lookup(token)
                       or self._dic.lookup(token.capitalize()))
            self._cache[token] = hit
        return hit

    def __len__(self) -> int:
        """Reported as ``lexicon_words`` in Stage 05 meta. NOTE: this counts
        dictionary STEMS + overlay tokens, NOT the (generative) number of valid
        surface forms — Hunspell validates far more than it lists."""
        return self._stems + len(self._overlay)


def load_lexicon(paths: list[Path | str]) -> "set[str] | HunspellLexicon | None":
    """Resolve the per-language lexicon from the first usable path.

    Two shapes are tried per path:

      * a Hunspell pair — ``<base>.dic`` + ``<base>.aff`` both present → a
        ``HunspellLexicon`` (spylls), unioned with an optional ``<base>.geo.txt``
        gazetteer overlay next to it. THIS is the production shape, built by
        ``tools/setup_lexicons.py`` into gitignored ``models/lexicons/``.
      * a flat ``.txt`` wordlist → a normalized ``set[str]`` (legacy / tests).

    Returns ``None`` when no path yields either — the inert-seam signal that keeps
    the disagreement trigger dormant (and, in Stage 05, keeps EasyOCR unloaded). A
    fresh clone has no ``models/lexicons/`` (gitignored), so the seam ships inert;
    ``tools/setup_lexicons.py`` activates it locally. Shared with the Stage 08
    de-hyphenation seam (same owner dependency; see RESULTS.md 2026-07-18)."""
    for p in paths:
        if not p:
            continue
        p = Path(p)
        dic, aff = p.with_suffix(".dic"), p.with_suffix(".aff")
        if dic.exists() and aff.exists():
            return HunspellLexicon(dic, aff, _load_overlay(p.with_suffix(".geo.txt")))
        if p.suffix == ".txt" and p.exists():
            words = p.read_text(encoding="utf-8").split()
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
    dictionary: "set[str] | HunspellLexicon | None",
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
            # The voucher must be more than one character. A bare letter — e.g.
            # Cyrillic ``к`` (an abbreviation marker), which a Hunspell dictionary
            # accepts as valid though a frequency list never listed it — is too
            # weak to certify that a Tesseract non-word is wrong: it would let any
            # stray single letter vouch for flagging a garbled neighbor (measured
            # on bg_01, ``кК.),`` ← ``к``). Guards the leak class the real
            # dictionary introduced; see RESULTS.md 2026-07-18.
            if len(e_tok) < 2:
                continue
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
