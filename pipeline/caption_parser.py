"""Gate-4 textual caption parser — recognize a printed figure-caption reference
("Figura NN", "Fig. NN", "Abbildung NN", "Фигура NN") at the START of an OCR'd
text block, extract the figure NUMBER, and (where a figure's own number is
recoverable) pair caption N to figure N.

WHY THIS EXISTS (measured on the testset 2026-07-03, not assumed):
- The DocLayout-YOLO detector mistypes captions as ``paragraph``: on it_geo_06
  ALL 6 real captions are typed ``paragraph`` (0/6 ``caption``); on it_geo_07 the
  C31 caption is mistyped too. Gate-4 reflow floats a caption WITH its figure
  keyed on caption TYPE, so a mistyped caption breaks the float. Recognizing the
  printed "Figura NN" at block start re-types these robustly — the keyword
  survives OCR cleanly even on the garbled sofa-shot pages (the six captions
  OCR'd as "Figura 25/26/27/28", "Sopra: Figura 29", "A lato: Figura 30").
- The caption STACK order on it_geo_06 (25,26,27,28) does NOT track figure spatial
  position (F26 is the top-RIGHT plate, yet its caption C26 is 2nd in the
  left-side stack), so nearest-figure GEOMETRY must mispair C26. Correct pairing
  has to read the printed number — hence a TEXTUAL parser, not a geometric rule.

SCOPE / HONEST LIMIT (empirically grounded on it_geo_06, 2026-07-03):
- Caption TYPING + number extraction is robust and is the durable win here.
- Caption->figure pairing BY NUMBER needs each FIGURE's number too. The only
  textual source is the in-photo corner label ("25/26/27/28") routed into the
  figure block. What was VERIFIED on it_geo_06 (2026-07-03): every detected
  figure block is EMPTY text, i.e. no figure-number signal reaches the figure
  blocks via center-routing. (A stray "26" could in principle have OCR'd and
  routed into another column or dropped as an orphan — not separately checked —
  but it could not be attributed to F26 anyway while the three cliff figures are
  merged into one detector box.) Either way the C26->F26 trap is NOT textually
  solvable on this fixture: a figure-OCR / detector-under-segmentation limit, not
  a parser gap. ``pair_by_number`` is built and unit-tested so it pairs correctly
  the moment a figure number IS available; on the current detector it yields no
  pairs on it_geo_06 (reported by the eval, never asserted away).

Number extraction is OCR-fragile even when the keyword is clean: on it_geo_07 the
keyword read "Figura" but the number "31" OCR'd as "3". Typing does not depend on
the number being right; pairing does — another reason the pairing claim is gated.

This module is PURE: text in, dataclasses out. No I/O, no OCR, no cv2. It is
imported by ``tools.layout_order_eval`` now (the "Figura-NN parser arm") and by
Stage 07 reconstruct later (float a caption with its figure, keyed on the parsed
type + number).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Caption keywords per language. Italian is VALIDATED on the testset
# (it_geo_04..07); English / German / Bulgarian are provided for the project's
# target languages but are NOT exercised by any fixture yet — do not report them
# as validated. Keys are ISO-639-2/T codes to match ``page_model``/config usage;
# a few common aliases ("it", "en", "eng"...) are normalized in ``_lang_key``.
CAPTION_KEYWORDS: dict[str, list[str]] = {
    "ita": ["figura", "fig", "tavola", "tav"],
    "eng": ["figure", "fig", "plate"],
    "deu": ["abbildung", "abb", "bild", "tafel"],
    "bul": ["фигура", "фиг", "обр"],
}

# Directional / positional prefixes that legitimately precede the keyword on
# these layouts ("In questa pagina: Figura 25", "Sopra: Figura 29",
# "A lato: Figura 30", "In queste pagine: Figura 31"). We do NOT hard-code the
# list — the parser accepts any short run of letters+spaces ending in a colon
# immediately before the keyword (bounded so it can't swallow a sentence). The
# colon is what disambiguates a real prefix from body prose.
_MAX_PREFIX_CHARS = 30

# Letters we allow inside a directional prefix (Latin + accented + Cyrillic).
_PREFIX_LETTERS = r"A-Za-zÀ-ɏЀ-ӿ"

_LANG_ALIASES = {
    "it": "ita", "ita": "ita", "italian": "ita",
    "en": "eng", "eng": "eng", "english": "eng",
    "de": "deu", "deu": "deu", "ger": "deu", "german": "deu",
    "bg": "bul", "bul": "bul", "bulgarian": "bul",
}


def _lang_key(lang: str) -> str:
    """Normalize a language token to a CAPTION_KEYWORDS key. A multi-lang string
    like ``"ita+eng"`` takes the first recognized component; unknown -> ``ita``
    (the validated default for this book-scanning corpus)."""
    if not lang:
        return "ita"
    for part in re.split(r"[+,\s]+", lang.strip().lower()):
        if part in _LANG_ALIASES:
            return _LANG_ALIASES[part]
    return "ita"


def _build_pattern(lang_key: str) -> re.Pattern[str]:
    """Compile the start-anchored caption pattern for one language.

    Shape: optional ``<prefix>:`` then a keyword (longest first so "figura" wins
    over "fig"), an optional dot, then a 1-3 digit number. Anchored at ``^`` so a
    mid-sentence reference like "(fig. 28)" in body prose can never match — that
    start-anchoring is the whole non-regression guard.
    """
    kws = sorted(CAPTION_KEYWORDS[lang_key], key=len, reverse=True)
    kw_alt = "|".join(re.escape(k) for k in kws)
    prefix = rf"(?:(?P<prefix>[{_PREFIX_LETTERS} ]{{1,{_MAX_PREFIX_CHARS}}}?)\s*:\s*)?"
    body = rf"(?P<kw>{kw_alt})\.?\s*(?P<num>\d{{1,3}})(?![0-9])"
    return re.compile(rf"^\s*{prefix}{body}", re.IGNORECASE | re.UNICODE)


# Compiled once per language (tiny table).
_PATTERNS: dict[str, re.Pattern[str]] = {k: _build_pattern(k) for k in CAPTION_KEYWORDS}


@dataclass(frozen=True)
class CaptionRef:
    """A recognized caption header parsed off the start of a text block."""

    number: int          # printed figure number (OCR-fragile; may misread, e.g. 31->3)
    keyword: str         # the keyword as OCR'd/matched, lowercased ("figura", "fig")
    lang: str            # normalized language key used ("ita"...)
    prefix: str | None   # directional prefix if present ("In questa pagina"), else None
    caption_text: str    # residual caption body after "<keyword> <number>"


def parse_caption(text: str, lang: str = "ita") -> CaptionRef | None:
    """Parse a caption header off the START of ``text``.

    Returns a ``CaptionRef`` if the block begins with an optional directional
    prefix + a figure keyword + a number; otherwise ``None`` (the block is not a
    caption header — e.g. body prose, even if it mentions "(fig. 28)" later).

    Only the block START is inspected, so this never re-types a paragraph that
    merely references a figure mid-sentence.
    """
    if not text or not text.strip():
        return None
    key = _lang_key(lang)
    m = _PATTERNS[key].match(text)
    if not m:
        return None
    prefix = m.group("prefix")
    prefix = prefix.strip() if prefix and prefix.strip() else None
    residual = text[m.end():]
    # Strip leading separators OCR often leaves between number and caption body
    # ("Figura 25 | La Maiolica" -> "La Maiolica"; "Figura 26 CSR Fossili" keeps
    # the stray token — we only trim punctuation/space, not words).
    residual = residual.lstrip(" \t:;.,-–—|/·").strip()
    return CaptionRef(
        number=int(m.group("num")),
        keyword=m.group("kw").lower(),
        lang=key,
        prefix=prefix,
        caption_text=residual,
    )


def is_caption(text: str, lang: str = "ita") -> bool:
    """Convenience: does this block text start with a recognizable caption header?"""
    return parse_caption(text, lang) is not None


# --------------------------------------------------------------------------
# Figure-side number (the corner label) — future-proofing; see module docstring.
# --------------------------------------------------------------------------

_BARE_NUM = re.compile(r"^\s*(?:fig\.?|figura|abb\.?|фиг\.?)?\s*(\d{1,3})\s*$",
                       re.IGNORECASE | re.UNICODE)


def figure_number(block_text: str) -> int | None:
    """Recover a FIGURE's own number from its routed OCR text — i.e. the in-photo
    corner label ("25") that fell inside the figure block.

    Deliberately conservative: returns an int ONLY when the block's text is
    essentially just that number (optionally with a bare "Fig"/"25"-style label),
    so body words leaking into a figure box never fabricate a number. On the
    current detector + it_geo_06 every figure block is EMPTY, so this returns
    ``None`` there — it exists so number-pairing works the moment a real figure
    number survives OCR, and is unit-tested on synthetic input, NOT validated on
    real figure pixels yet (see module docstring)."""
    if not block_text or not block_text.strip():
        return None
    m = _BARE_NUM.match(block_text.strip())
    if m:
        return int(m.group(1))
    return None


# --------------------------------------------------------------------------
# Number-keyed pairing (pure) — caption N <-> figure N.
# --------------------------------------------------------------------------


def pair_by_number(captions: dict[str, int], figures: dict[str, int | None]
                   ) -> dict[str, str]:
    """Pair caption ids to figure ids BY PRINTED NUMBER.

    ``captions``: caption_id -> parsed number. ``figures``: figure_id -> figure
    number (or ``None`` when the figure's number could not be recovered). Returns
    ``{caption_id: figure_id}`` for every caption whose number matches exactly one
    figure's number. Captions with no numbered figure (the it_geo_06 reality,
    where all figure numbers are ``None``) are simply omitted — NOT guessed
    geometrically. This defeats the number-keyed trap (C26 pairs to the figure
    printed "26", wherever it sits) precisely because it ignores geometry.

    A figure number shared by >1 figure (shouldn't happen with clean labels, but
    a merged/duplicated detector box could) is treated as ambiguous and pairs
    nothing for that number.
    """
    by_num: dict[int, list[str]] = {}
    for fid, num in figures.items():
        if num is None:
            continue
        by_num.setdefault(num, []).append(fid)
    out: dict[str, str] = {}
    for cid, num in captions.items():
        cands = by_num.get(num)
        if cands and len(cands) == 1:
            out[cid] = cands[0]
    return out


# --------------------------------------------------------------------------
# Small helper used by callers that store the raw parsed keyword.
# --------------------------------------------------------------------------


def normalize_keyword(kw: str) -> str:
    """Strip accents/case from a matched keyword for stable comparison/logging."""
    return "".join(c for c in unicodedata.normalize("NFKD", kw.lower())
                   if not unicodedata.combining(c))
