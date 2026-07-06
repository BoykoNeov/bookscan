"""Tests for pipeline.stage08_render — the pure document->HTML function.

Covers the load-bearing render behaviors (advisor's must-honors): the
``block.text`` translation override supersedes words; rendering uses CURRENT
editable values not provenance; the three uncertainty modes ride
``flag_visible`` (an edited word renders plain); figures are cropped from the
page image and captions grouped; running headers/page numbers strip by CURRENT
type; and the de-hyphenation seam is conservative without a dictionary.

Run with pytest, or directly:
    python -m pipeline.tests.test_stage08_render
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline.page_model import (
    Block, BlockType, Document, DocPage, DocSettings, Word,
)
from pipeline import stage08_render as S8


def _w(text: str, x: int = 0, conf: float = 90.0, decision: str = "keep",
       line_id: int = 0, edited: bool = False, patch_asset: str | None = None) -> Word:
    return Word(text=text, bbox={"x": x, "y": 0, "w": 30, "h": 20}, conf=conf,
                decision=decision, line_id=line_id, edited=edited,
                patch_asset=patch_asset)


# ---- de-hyphenation seam --------------------------------------------------


def test_join_hyphen_conservative_without_dictionary():
    assert S8.join_hyphen("compara-", "tive", None) is None      # keep hyphen
    assert S8.join_hyphen("well-", "Known", None) is None        # not lowercase anyway


def test_join_hyphen_uses_dictionary_when_present():
    d = {"comparative"}
    assert S8.join_hyphen("compara-", "tive", d) == "comparative"
    assert S8.join_hyphen("compara-", "tive", {"other"}) is None  # not in dict
    assert S8.join_hyphen("compara-", "Tive", d) is None          # next not lowercase
    assert S8.join_hyphen("plain", "word", d) is None             # no hyphen


def test_merge_hyphens_noop_without_dict_but_joins_with_dict():
    words = [_w("compara-", line_id=0), _w("tive", line_id=1)]
    assert [w.text for w in S8.merge_hyphens(words, None)] == ["compara-", "tive"]
    merged = S8.merge_hyphens(words, {"comparative"})
    assert [w.text for w in merged] == ["comparative"]


# ---- per-word rendering + the 3 modes -------------------------------------


def test_keep_word_renders_plain(tmp_path: Path):
    assert S8._word_html(_w("Roma", decision="keep"), "flag", tmp_path) == "Roma"


def test_flagged_word_renders_highlighted_span(tmp_path: Path):
    out = S8._word_html(_w("caput", decision="flag", conf=40.0), "flag", tmp_path)
    assert 'class="flag"' in out and "caput" in out


def test_edited_flagged_word_renders_plain(tmp_path: Path):
    # flag_visible is False once edited -> no marker, even though decision=flag
    w = _w("capita", decision="flag", edited=True)
    assert S8._word_html(w, "flag", tmp_path) == "capita"


def test_patch_word_inlines_image(tmp_path: Path):
    asset = "document_assets/p.png"
    (tmp_path / "document_assets").mkdir()
    cv2.imwrite(str(tmp_path / asset), np.zeros((10, 20, 3), np.uint8))
    out = S8._word_html(_w("x", decision="patch", patch_asset=asset), "patch", tmp_path)
    assert out.startswith('<img class="patch"') and "data:image/png;base64," in out


def test_implicit_edit_clears_marker_without_edited_flag(tmp_path: Path):
    """Interim hand-edit safety: changing `text` away from `text_ocr` clears the
    marker even if the user forgot `edited: true`."""
    w = Word(text="fixed", text_ocr="fixd", bbox={"x": 0, "y": 0, "w": 30, "h": 20},
             conf=40.0, decision="flag", edited=False)
    assert w.flag_visible is False
    assert S8._word_html(w, "flag", tmp_path) == "fixed"      # plain, no span


def test_patch_stale_crop_not_rendered_after_text_edit(tmp_path: Path):
    """The load-bearing patch case: a hand-corrected word must render the CORRECTED
    TEXT, never the stale original crop, even without an explicit edited flag."""
    asset = "document_assets/p.png"
    (tmp_path / "document_assets").mkdir()
    cv2.imwrite(str(tmp_path / asset), np.zeros((10, 20, 3), np.uint8))
    w = Word(text="corrected", text_ocr="c0rrupt", bbox={"x": 0, "y": 0, "w": 30, "h": 20},
             conf=30.0, decision="patch", patch_asset=asset, edited=False)
    out = S8._word_html(w, "patch", tmp_path)
    assert out == "corrected"                                 # text wins
    assert "<img" not in out and "base64" not in out          # stale crop suppressed


# ---- block-level behaviors ------------------------------------------------


def test_block_text_translation_supersedes_words(tmp_path: Path):
    blk = Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": 100, "h": 50},
                reading_order=0, words=[_w("original", decision="flag")],
                text="tradotto <b>")
    out = S8._block_body_html(blk, "flag", tmp_path, None)
    assert out == "tradotto &lt;b&gt;"          # translated + escaped, words bypassed
    assert "original" not in out


def _doc(page: DocPage, **settings) -> Document:
    return Document(document_id="d", job_id="d",
                    settings=DocSettings(**settings), pages=[page])


def _page_with(blocks, tmp_path, img="document_assets/pg.png") -> tuple[DocPage, Path]:
    (tmp_path / "document_assets").mkdir(exist_ok=True)
    cv2.imwrite(str(tmp_path / img), np.full((200, 200, 3), 200, np.uint8))
    return DocPage(page_id="pg", source_spread="page_001", subpage="single",
                   width=200, height=200, image_asset=img, blocks=blocks), tmp_path


def test_header_stripped_by_current_type(tmp_path: Path):
    blocks = [
        Block(id=0, type="header", bbox={"x": 0, "y": 0, "w": 100, "h": 20},
              reading_order=0, words=[_w("RUNNINGHEAD")]),
        Block(id=1, type="paragraph", bbox={"x": 0, "y": 30, "w": 100, "h": 40},
              reading_order=1, words=[_w("Body")]),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page, strip_running_headers=True), jd)
    assert "RUNNINGHEAD" not in html and "Body" in html
    html2 = S8.render_html(_doc(page, strip_running_headers=False), jd)
    assert "RUNNINGHEAD" in html2               # toggle honored


def test_figure_cropped_and_caption_grouped(tmp_path: Path):
    blocks = [
        Block(id=0, type="figure", bbox={"x": 10, "y": 10, "w": 80, "h": 80},
              reading_order=0, words=[_w("garbageocr")]),
        Block(id=1, type="caption", bbox={"x": 10, "y": 95, "w": 80, "h": 15},
              reading_order=1, words=[_w("Fig."), _w("1", x=30)]),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "<figure" in html and 'class="figure"' in html
    assert "data:image/png;base64," in html     # crop inlined
    assert "<figcaption" in html and "Fig." in html
    assert "garbageocr" not in html             # figure words NOT rendered


def test_reading_order_drives_output_sequence(tmp_path: Path):
    blocks = [
        Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": 100, "h": 20},
              reading_order=5, words=[_w("LATER")]),
        Block(id=1, type="paragraph", bbox={"x": 0, "y": 30, "w": 100, "h": 20},
              reading_order=1, words=[_w("EARLIER")]),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert html.index("EARLIER") < html.index("LATER")


def test_no_external_asset_refs_in_html(tmp_path: Path):
    """Path-bug guard: every image is inlined; no relative document_assets/ src."""
    page, jd = _page_with(
        [Block(id=0, type="figure", bbox={"x": 5, "y": 5, "w": 50, "h": 50},
               reading_order=0, words=[])], tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert 'src="document_assets' not in html and 'src="../' not in html


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
