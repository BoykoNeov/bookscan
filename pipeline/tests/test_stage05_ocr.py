"""Unit tests for pipeline.stage05_ocr pure routing — the coordinate map-back,
word->block routing, orphan slotting, the word-conservation invariant, and the
"raw confidence only" contract.

Hand-built TWords + Blocks with a known answer — no photos, no Tesseract, no
torch. The two load-bearing correctness properties the advisor flagged are pinned
here: (1) the /scale map-back lands word boxes in 1x dewarp coords (get this wrong
and every Stage 06 patch crop is offset), and (2) every recognized word ends up in
exactly one output block (a routing bug must not silently drop/duplicate words).
Run with pytest, or directly:
    python -m pipeline.tests.test_stage05_ocr
"""

from __future__ import annotations

from pipeline.page_model import BBox, Block, BlockType
from pipeline.stage04_layout import DEFAULTS
from pipeline.stage05_ocr import (
    _word_box, attach_words, resolve_language,
)
from tools.ocr_metrics import TWord


def _tw(text: str, left: int, top: int, width: int, height: int,
        conf: float = 90.0, block_num: int = 1, par_num: int = 1,
        line_num: int = 1, word_num: int = 1) -> TWord:
    return TWord(text=text, conf=conf, left=left, top=top, width=width,
                 height=height, block_num=block_num, par_num=par_num,
                 line_num=line_num, word_num=word_num)


def _blk(id: int, x: int, y: int, w: int, h: int,
         type: BlockType = BlockType.PARAGRAPH, ro: int | None = None) -> Block:
    return Block(id=id, type=type, bbox=BBox(x=x, y=y, w=w, h=h),
                 reading_order=id if ro is None else ro)


def test_word_box_maps_upscaled_back_to_1x():
    """A word OCR'd on a 2x image must be divided back to 1x dewarp coords (the
    space of Stage 04 blocks AND Stage 06 patch crops)."""
    tw = _tw("x", left=200, top=400, width=60, height=40)
    box = _word_box(tw, scale=2.0)
    assert (box.x, box.y, box.w, box.h) == (100, 200, 30, 20)
    # scale 1.0 is identity; zero-size dims clamp to >=1 so a box is never empty.
    assert _word_box(_tw("y", 10, 10, 0, 0), 1.0) == BBox(x=10, y=10, w=1, h=1)


def test_routes_to_smallest_containing_block():
    """A word whose center is inside two nested blocks routes to the SMALLER one."""
    outer = _blk(0, 0, 0, 1000, 1000)
    inner = _blk(1, 100, 100, 200, 100, type=BlockType.CAPTION)
    words = [_tw("hi", left=150, top=120, width=40, height=30)]  # center (170,135)
    ordered, orphans = attach_words(words, [outer, inner], 1.0, 1000, 1000, DEFAULTS)
    assert orphans == 0
    by_type = {b.type: b for b in ordered}
    assert len(by_type[BlockType.CAPTION].words) == 1
    assert by_type[BlockType.PARAGRAPH].words == []   # figure/empty blocks kept


def test_word_conservation_with_orphans():
    """Every recognized word ends up in exactly one block; a word outside all
    blocks becomes a synthetic OTHER block (never dropped)."""
    blk = _blk(0, 0, 0, 400, 400)
    words = [
        _tw("inside", left=100, top=100, width=50, height=30),   # in blk
        _tw("orphan", left=800, top=800, width=50, height=30),   # outside everything
    ]
    ordered, orphans = attach_words(words, [blk], 1.0, 1000, 1000, DEFAULTS)
    assert orphans == 1
    assert sum(len(b.words) for b in ordered) == 2               # conservation
    others = [b for b in ordered if b.type == BlockType.OTHER]
    assert len(others) == 1 and others[0].words[0].text == "orphan"


def test_reading_order_and_ids_are_gapless_and_synced():
    """id + reading_order are 0..n-1 with no gaps, and each word's block_id
    matches the block it lives in (renumbered after orphan slotting)."""
    top = _blk(0, 0, 0, 1000, 100, ro=0)
    bottom = _blk(1, 0, 200, 1000, 100, ro=1)
    words = [
        _tw("A", left=10, top=20, width=40, height=30),    # -> top
        _tw("B", left=10, top=220, width=40, height=30),   # -> bottom
        _tw("orph", left=10, top=600, width=40, height=30),  # orphan between/after
    ]
    ordered, _ = attach_words(words, [top, bottom], 1.0, 1000, 1000, DEFAULTS)
    assert [b.reading_order for b in ordered] == list(range(len(ordered)))
    assert [b.id for b in ordered] == list(range(len(ordered)))
    for b in ordered:
        for w in b.words:
            assert w.block_id == b.id


def test_no_orphans_trusts_stage04_order():
    """With every word routed, Stage 04's reading_order is preserved (blocks come
    back sorted by it), not recomputed."""
    # Stage 04 order says the geometrically-lower block reads FIRST (ro=0).
    lower = _blk(0, 0, 500, 1000, 100, ro=0)
    upper = _blk(1, 0, 0, 1000, 100, ro=1)
    words = [
        _tw("low", left=10, top=520, width=40, height=30),   # -> lower (ro 0)
        _tw("up", left=10, top=20, width=40, height=30),     # -> upper (ro 1)
    ]
    ordered, orphans = attach_words(words, [lower, upper], 1.0, 1000, 1000, DEFAULTS)
    assert orphans == 0
    assert [b.words[0].text for b in ordered] == ["low", "up"]  # trusts ro, not y


def test_raw_confidence_only_no_decision():
    """Stage 05 emits raw conf + engine and leaves decision=None (Stage 06 owns
    the keep/flag/patch call)."""
    blk = _blk(0, 0, 0, 400, 400)
    words = [_tw("w", left=100, top=100, width=50, height=30, conf=42.0)]
    ordered, _ = attach_words(words, [blk], 1.0, 500, 500, DEFAULTS)
    w = ordered[0].words[0]
    assert w.conf == 42.0
    assert w.engine == "tesseract"
    assert w.decision is None


def test_line_ids_track_tsv_lines():
    """Words on the same TSV (block,par,line) share a line_id; a new line bumps
    it — the handle Stage 06 uses for line-end de-hyphenation."""
    blk = _blk(0, 0, 0, 1000, 1000)
    words = [
        _tw("a", left=10, top=10, width=30, height=20, line_num=1),
        _tw("b", left=50, top=10, width=30, height=20, line_num=1),
        _tw("c", left=10, top=40, width=30, height=20, line_num=2),
    ]
    ordered, _ = attach_words(words, [blk], 1.0, 1000, 1000, DEFAULTS)
    ids = {w.text: w.line_id for b in ordered for w in b.words}
    assert ids["a"] == ids["b"] and ids["c"] != ids["a"]


def test_resolve_language_precedence():
    """--lang overrides config; else config languages.default; friendly names +
    multi-lang map to Tesseract codes."""
    cfg = {"languages": {"default": "eng"}}
    assert resolve_language(cfg, None) == "eng"
    assert resolve_language(cfg, "bulgarian") == "bul"
    assert resolve_language(cfg, "eng+bul") == "eng+bul"
    assert resolve_language({"languages": {"default": "italian"}}, None) == "ita"


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
