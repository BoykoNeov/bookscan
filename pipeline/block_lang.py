"""Label a text block with the language it is actually printed in.

THE CASE. A real book carries several languages on one page. This corpus's
via-ferrata guide prints the German route description, then the English one, then
the Italian one, each in its own printed box; a page of it is read in ONE
language, because Stage 05 takes a single ``--lang``. The consequence a reader
sees is not the OCR — it is de-hyphenation. Stage 08 joins a line-end hyphen only
when the joined token is in the document's dictionary (CLAUDE.md's rule), so in a
German job every English paragraph keeps its broken words: the rendered PDF says
``rou- tes``, ``at- tractive``, ``distinc- tive``, ``lone- liness``.

WHAT THIS PASS DOES, AND WHAT IT DELIBERATELY DOES NOT. It writes
``Block.language`` and nothing else. It does not re-read, re-order, add, drop or
edit a single word, so word conservation is untouched and an abstain costs
nothing.

**Re-reading the block in its own language was measured first, and REFUSED**
(RESULTS 2026-08-31). The plan this work came from assumed the win was a
per-block re-OCR — read the English panel with English Tesseract. Over all 36
nominated blocks of the owner's book, read twice from the same crop:

  * on the blocks that read WELL, the language changes almost nothing. Word
    counts are identical (101/101, 103/103, 87/87, 56/56, 45/45, 42/42, 32/32),
    confidence moves by under a point, and the text diff is a wash — English
    fixes ``interestin -> interesting`` and ``yalley -> valley``, and breaks
    ``Ferrata Roghel -> Ferrara Roghe!``, ``From -> from``, ``15 -> [5``. One
    99-word English paragraph comes back BYTE-IDENTICAL under German.
  * on the blocks that read BADLY — the translation panels this work was aimed at
    — the other language produces DIFFERENT garbage, not better garbage:
    ``technacz! 68- Kcules (1-6`` becomes ``wana! 6 ficunes (A-€``. Those panels
    are unreadable because of the pixels (a coloured banner, small type), not
    because of the dictionary, and no language setting recovers them.

So the language of a block is worth knowing, and re-reading it is not worth
doing. That asymmetry is the whole design.

THE VOTE. Score the block's already-read words against every installed Hunspell
dictionary and take the winner. Four guards, each one earned by a measured false
positive rather than chosen for taste:

  * ``min_len`` **3** — the guard that matters. English Hunspell accepts a long
    tail of two-letter forms (``la ir at do av se vs fa is cr``), so a block of
    pure garbage scores 0.61 against English on two-letter noise alone. At
    ``min_len`` 2 the junk block of ``it_geo_05`` (median confidence 24, text
    ``I nia pica ian na n PE aaa EEE``) is nominated; at 3 it is not, and no real
    paragraph is lost anywhere in the corpus.
  * ``min_tokens`` / ``min_distinct`` — a block must have enough DIFFERENT words
    to vote. Three blocks of route heights (``840 Hm 1450 Hm 1400 Hm ...``) score
    Italian at 1.00 off one repeated token, ``hm``.
  * ``min_rate`` — the winner must actually fit its own dictionary. Real prose
    scores 0.70-0.91; a mixed German/English caption scores 0.33.
  * ``min_margin`` — and it must beat the document's language by a real gap. A
    bilingual line (``Sehr gut versicherter Steig / Very good secured route``)
    ties at margin 0.00 and is correctly refused: it has no single language.

MEASURED (2026-08-31). On the owner's 25-spread book the label fires on 17 of 209
scorable text blocks; through Stage 08's de-hyphenation that is **15 broken words
rejoined that the document language cannot rejoin, and 0 joins lost** — every join
the document language could make, the block language can make too. On the fifteen
single-language testset fixtures the pass fires on **4 blocks, all in the two
spreads of that same German guide, and all of them genuinely English**; the other
thirteen fixtures (Bulgarian, English, Italian) label nothing at all.

CONSUMER, SINGULAR. Stage 08's de-hyphenation is the only thing that reads
``Block.language`` today, deliberately: it is the one consumer with a measured
number behind it. The obvious others — the EasyOCR disagreement gate, Stage 06's
threshold — are unmeasured here, and wiring them on the strength of this row would
make the row unfalsifiable. ``None`` means "use the document's language", which is
what every existing document says, so an un-relabelled ``document.json`` renders
byte-identically.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.page_model import Block, BlockType
from pipeline.second_opinion import load_lexicon, normalize_token

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULTS = {
    # On by default: measured strictly better on the deliverable (15 joins
    # gained, 0 lost) and inert on thirteen of fifteen single-language fixtures.
    "enabled": True,
    # Tokens shorter than this do not vote. THE load-bearing guard — see the
    # module docstring; at 2 a block of pure noise wins English on "la ir at do".
    "min_len": 3,
    # A block needs this many voting tokens at all, and this many DIFFERENT ones.
    "min_tokens": 8,
    "min_distinct": 6,
    # The winner must fit its own dictionary this well...
    "min_rate": 0.65,
    # ...and beat the document's language by this much. A genuinely bilingual
    # line ties near 0.00 and must stay on the document language.
    "min_margin": 0.25,
}

# A language vote over the labels printed inside artwork is noise, and a figure
# renders as pixels anyway. Same exclusion, same reason, as block_reocr.
SKIP_TYPES = frozenset({BlockType.FIGURE})


@dataclass
class LangNote:
    """One applied label, for ``meta.json`` provenance."""

    block_id: int
    block_type: str
    language: str
    doc_language: str
    n_tokens: int
    rate: float
    margin: float


def resolve_params(cfg: dict) -> dict:
    p = dict(DEFAULTS)
    over = (cfg.get("block_lang", {}) or {})
    for k, v in over.items():
        if k in p:
            p[k] = bool(v) if k == "enabled" else type(DEFAULTS[k])(v)
    return p


def lexicon_paths(cfg: dict) -> dict[str, Path]:
    """Per-language Hunspell paths from config.

    Reads ``engines.easyocr.lexicon`` — the same map Stage 08's de-hyphenation
    already reads. The key lives under ``easyocr`` for historical reasons (the
    disagreement gate was its first consumer) and is a per-language *dictionary*
    map, not an EasyOCR setting; a second copy of it under another key would be
    two places to keep in step.
    """
    raw = (((cfg.get("engines") or {}).get("easyocr") or {}).get("lexicon") or {})
    return {str(k): (REPO_ROOT / str(v)) for k, v in raw.items()}


def load_lexicons(paths: dict[str, Path]) -> dict[str, object]:
    """One dictionary per language, loaded ONCE per Stage 05 run.

    ``load_lexicon`` takes a LIST and returns the first usable entry, so it must
    be called per language — handing it every path returns one dictionary four
    times. A language whose pair is missing is simply absent from the result and
    can never win a vote (a fresh clone has no ``models/lexicons/``, so this pass
    is inert there, exactly like the de-hyphenation seam it feeds).
    """
    out: dict[str, object] = {}
    for lc, path in paths.items():
        try:
            lex = load_lexicon([path])
        except Exception:
            lex = None
        if lex is not None:
            out[lc] = lex
    return out


def vote_tokens(texts: list[str], min_len: int) -> list[str]:
    """Normalized tokens allowed to vote: at least ``min_len`` characters and at
    least one letter. A page number, a route height (``840``) or a stray ``|``
    says nothing about language, and a two-letter fragment says something FALSE
    (see the module docstring)."""
    out = []
    for t in texts:
        n = normalize_token(t)
        if len(n) >= min_len and any(c.isalpha() for c in n):
            out.append(n)
    return out


def score(tokens: list[str], lexicons: dict[str, object]) -> dict[str, float]:
    """Fraction of the block's voting tokens each dictionary accepts."""
    n = max(1, len(tokens))
    return {lc: sum(1 for t in tokens if t in lex) / n
            for lc, lex in lexicons.items()}


def label_blocks(blocks: list[Block], doc_language: str,
                 lexicons: dict[str, object], p: dict | None = None
                 ) -> list[LangNote]:
    """Set ``Block.language`` on every block whose words clearly fit a different
    dictionary from the document's. Mutates ``blocks`` in place (the caller owns
    fresh copies) and returns one note per applied label.

    Abstaining is the normal outcome and leaves ``language`` None, which every
    consumer must read as "use the document's language".
    """
    pp = dict(DEFAULTS)
    if p:
        pp.update({k: v for k, v in p.items() if k in DEFAULTS})
    notes: list[LangNote] = []
    if not pp["enabled"] or len(lexicons) < 2:
        return notes
    base = str(doc_language or "").split("+")[0]
    for blk in blocks:
        if blk.type in SKIP_TYPES:
            continue
        toks = vote_tokens([w.text for w in blk.words], int(pp["min_len"]))
        if len(toks) < int(pp["min_tokens"]):
            continue
        if len(set(toks)) < int(pp["min_distinct"]):
            continue
        rates = score(toks, lexicons)
        winner = max(rates, key=lambda k: rates[k])
        if winner == base:
            continue
        margin = rates[winner] - rates.get(base, 0.0)
        if rates[winner] < float(pp["min_rate"]) or margin < float(pp["min_margin"]):
            continue
        blk.language = winner
        notes.append(LangNote(
            block_id=blk.id, block_type=blk.type.value, language=winner,
            doc_language=base, n_tokens=len(toks), rate=round(rates[winner], 3),
            margin=round(margin, 3)))
    return notes
