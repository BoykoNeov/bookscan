"""A scanned PDF's own hidden text as a SECOND OPINION on Tesseract (plan Slice 3).

**OFF by default since 2026-09-24** (``DEFAULTS["enabled"]`` and config.yaml). It
passed its gate on pages Stage 03 flattened, but once Stage 03 stopped flattening
imported pages it was re-judged on those pages (prereg addendum 2) and failed the
per-document clause: 35 catches / 23 false alarms, 3 of the 4 required documents
at >= 0.50 — Tesseract now reads several of the mistakes it used to catch. The
importer still saves the layer, so switching it on needs no re-import; that is
the owner's call. Everything below describes what it does when switched on.

A scanned PDF often carries an invisible text layer: somebody else's OCR of the
same page. Where that layer and Tesseract read a word differently, the word gets a
marker (``Word.layer_disagree``, ORed into Stage 06's ``uncertain`` exactly like
``engine_disagree``). The layer NEVER supplies text, never supplies a confidence,
never clears a marker, and its reading is not stored on the word.

**Measured before it was built** (pre-registration
``docs/data/pdf_textlayer_prereg_20260924.md``, RESULTS 2026-09-24; 7 English
documents from 7 OCR producers, 71 disagreements judged blind). On words Stage 06
had kept, the raw rule below found 48 Tesseract mistakes against 16 correct words
questioned (precision 0.75, about 3 new markers per page), passing its gate in 4
of 5 eligible documents, exactly the minimum. What it catches is mostly notation
(O2, subscripts, Greek letters, zeros in codes) where BOTH readers were wrong; on
ordinary words the layer is worse than Tesseract (one ABBYY layer read "the" as
"die" six times). The dictionary-gated variant EasyOCR uses caught 5 and was
refused. Where the two readers AGREE on a word Stage 06 flagged, 23 % are still
wrong — so agreement must never clear a flag, and nothing here does.

**The rule is exactly the measured one, and this module is its only copy**
(``tools/pdf_textlayer_eval.py`` imports it):

1. Tesseract tokens: every word of the page, sub-pages in order, blocks by
   ``reading_order``, words in stored order. Layer tokens: ``get_text("words")``
   of the original PDF page, in the order the PDF stores them (saved by the
   importer, because the console deletes the uploaded PDF afterwards).
2. The same normalisation on both sides (``prep_tokens``): NFKC; a trailing soft
   hyphen or ``¬`` is a line-end ``-``; ``x-`` + a lowercase next token joins;
   ``second_opinion.normalize_token``; empty tokens dropped.
3. ``difflib.SequenceMatcher(autojunk=False)`` over the whole page — by SEQUENCE,
   because Stage 03 moves the words and the layer's boxes no longer match ours.
4. A disagreement is a ``replace`` with exactly one token on each side. Every
   Tesseract word inside that token (a hyphen-joined token is several) is marked.

**Where it abstains — the edges of the measured population, not tuned numbers:**
a language other than English (the only one measured; a producer that drops
accents would mark every "für"/"fur" pair), a layer with fewer than 150 words (the
pre-registered page-selection floor), and a page whose alignment coverage is
below 0.42 (the lowest measured page matched 0.4286 and must stay inside). Each
abstention is reported in Stage 05's meta, never silent.
"""

from __future__ import annotations

import difflib
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.second_opinion import normalize_token

LAYER_FILE = "pdf_text_layer.json"
LINE_END_MARKS = ("­", "¬")      # soft hyphen, ¬

# The measured population's edges (see module docstring). Config may narrow them
# (``pdf_text_layer`` in config.yaml); widening them is an unmeasured claim.
DEFAULTS = {
    "enabled": False,            # switched off 2026-09-24 (module docstring)
    "languages": ["eng"],
    "min_layer_words": 150,
    "min_coverage": 0.42,
}


def resolve_params(cfg: dict) -> dict:
    p = dict(DEFAULTS)
    p.update({k: v for k, v in (cfg.get("pdf_text_layer", {}) or {}).items() if k in DEFAULTS})
    return p


# ------------------------------------------------------------------ the layer file
def layer_words(page) -> list[str]:
    """The text-layer words of a PyMuPDF page, in the order the PDF stores them."""
    return [w[4] for w in page.get_text("words")]


def write_layer(page_dir: Path, words: list[str], *, pdf_name: str, pdf_page: int,
                producer: str = "") -> Path:
    """``<page_dir>/pdf_text_layer.json``: INPUT, like ``page_layout.json`` — no
    stage writes it, and a phone page never has one."""
    path = page_dir / LAYER_FILE
    path.write_text(json.dumps({
        "source": "pdf_import", "pdf": pdf_name, "pdf_page": pdf_page,
        "producer": producer, "words": words}, ensure_ascii=False, indent=0),
        encoding="utf-8")
    return path


def read_layer(page_dir: Path) -> tuple[list[str] | None, str | None]:
    """(words, problem). No file -> (None, None): a phone page, the normal case. A
    corrupt file -> (None, reason): reported, and the page is read as if it had no
    layer — a broken input must not fail a page, nor mark anything."""
    path = page_dir / LAYER_FILE
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        words = data["words"]
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise ValueError("'words' is not a list of strings")
        return words, None
    except (OSError, ValueError, KeyError, TypeError) as e:
        return None, f"{LAYER_FILE} unreadable ({type(e).__name__}: {e}); ignored"


# ------------------------------------------------------------------ tokens
def prep_tokens(items: list[tuple[str, object]]) -> list[dict]:
    """(raw text, ref) -> comparison tokens, identically for both readers.

    NFKC; a trailing soft hyphen or ``¬`` is a line-end ``-`` and one elsewhere is
    dropped; ``x-`` + lowercase next token joins; then ``normalize_token``; empty
    tokens are dropped. A joined token keeps the refs of every word in it."""
    clean = []
    for raw, ref in items:
        t = unicodedata.normalize("NFKC", raw or "")
        for m in LINE_END_MARKS:
            if t.endswith(m):
                t = t[:-1] + "-"
            t = t.replace(m, "")
        clean.append((t, [ref]))
    joined: list[tuple[str, list]] = []
    i = 0
    while i < len(clean):
        t, refs = clean[i]
        while (t.endswith("-") and len(t) > 1 and i + 1 < len(clean)
               and clean[i + 1][0][:1].islower()):
            i += 1
            t, refs = t[:-1] + clean[i][0], refs + clean[i][1]
        joined.append((t, refs))
        i += 1
    out = []
    for t, refs in joined:
        n = normalize_token(t)
        if n:
            out.append({"norm": n, "raw": t, "refs": refs})
    return out


def _get(o, k):
    return o[k] if isinstance(o, dict) else getattr(o, k)


def page_words(pages) -> list:
    """Every word of a page in the measured order: sub-pages as given, blocks by
    ``reading_order`` (None last), words in stored order. Accepts Stage 05/06
    pydantic pages or their JSON dicts."""
    words = []
    for sp in pages:
        blocks = sorted(_get(sp, "blocks"),
                        key=lambda b: (_get(b, "reading_order") is None,
                                       _get(b, "reading_order") or 0))
        for b in blocks:
            words.extend(_get(b, "words") or [])
    return words


def align(t_toks: list[dict], l_toks: list[dict]):
    sm = difflib.SequenceMatcher(a=[t["norm"] for t in t_toks],
                                 b=[x["norm"] for x in l_toks], autojunk=False)
    return sm.get_opcodes()


@dataclass
class LayerCheck:
    """What the layer said about one page."""
    marked: set[int] = field(default_factory=set)   # indices into page_words()
    sites: list[tuple[dict, dict]] = field(default_factory=list)  # (tesseract, layer)
    coverage: float = 0.0          # share of Tesseract tokens inside `equal` runs
    t_tokens: int = 0
    l_tokens: int = 0
    other_replace: int = 0         # replaces that are not 1<->1: counted, never marked
    abstained: str = ""            # why nothing was marked, when nothing could be


def check(words: list, layer: list[str], params: dict | None = None,
          language: str = "eng") -> LayerCheck:
    """Compare a page's words (``page_words`` order) with its text layer.

    Returns the indices of the words to mark. Pure: no pixels, no files."""
    p = dict(DEFAULTS) if params is None else params
    res = LayerCheck()
    langs = set(p["languages"])
    if not p["enabled"]:
        res.abstained = "disabled in config (pdf_text_layer.enabled)"
        return res
    if not any(lc in langs for lc in language.split("+")):
        res.abstained = (f"page language {language!r} is outside the measured "
                         f"languages {sorted(langs)}")
        return res
    if len(layer) < p["min_layer_words"]:
        res.abstained = (f"text layer has {len(layer)} words (< {p['min_layer_words']}, "
                         f"the measured floor)")
        return res
    t_toks = prep_tokens([(_get(w, "text"), i) for i, w in enumerate(words)])
    l_toks = prep_tokens([(w, None) for w in layer])
    res.t_tokens, res.l_tokens = len(t_toks), len(l_toks)
    ops = align(t_toks, l_toks)
    eq = sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag == "equal")
    res.coverage = eq / len(t_toks) if t_toks else 0.0
    if res.coverage < p["min_coverage"]:
        res.abstained = (f"alignment coverage {res.coverage:.3f} < {p['min_coverage']} "
                         f"(the lowest measured page): the layer does not describe "
                         f"this page's text closely enough to vouch for anything")
        return res
    for tag, i1, i2, j1, j2 in ops:
        if tag != "replace":
            continue
        if i2 - i1 != 1 or j2 - j1 != 1:
            res.other_replace += 1
            continue
        res.sites.append((t_toks[i1], l_toks[j1]))
        res.marked.update(t_toks[i1]["refs"])
    return res


def apply(page_dir: Path, pages, cfg: dict, language: str) -> tuple[dict | None, list[str]]:
    """Stage 05's whole use of the layer: read ``<page_dir>/pdf_text_layer.json``,
    compare it with the page's words, and set ``layer_disagree`` on the words to
    mark (the Word objects in ``pages`` are changed in place). Runs after every
    other Stage 05 pass, so the words compared are exactly the ones Stage 06 sees.

    Returns (meta for Stage 05's meta.json or None when the page has no layer,
    warnings). A phone page has no file and gets (None, [])."""
    layer, problem = read_layer(page_dir)
    notes = [problem] if problem else []
    if layer is None:
        return None, notes
    p = resolve_params(cfg)
    words = page_words(pages)
    chk = check(words, layer, p, language)
    for i in chk.marked:
        words[i].layer_disagree = True
    meta = {**{k: p[k] for k in DEFAULTS},
            "layer_words": len(layer), "coverage": round(chk.coverage, 4),
            "sites": len(chk.sites), "other_replace": chk.other_replace,
            "words_marked": len(chk.marked), "abstained": chk.abstained}
    notes.append(
        f"PDF text layer: abstained, {chk.abstained}" if chk.abstained else
        f"PDF text layer ({len(layer)} words, alignment coverage {chk.coverage:.3f}): "
        f"{len(chk.marked)} word(s) marked layer_disagree at {len(chk.sites)} "
        f"one-for-one disagreement(s). The layer never supplies text; Tesseract "
        f"remains the sole text + confidence source.")
    return meta, notes
