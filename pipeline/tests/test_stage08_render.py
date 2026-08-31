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


def test_disagreement_flagged_word_clears_through_the_same_edit_path(tmp_path: Path):
    """A CONFIDENT word flagged only by the cross-engine disagreement trigger
    (conf 90, Stage 06 -> decision=flag) shows its marker like any flag, and clears
    through the SAME per-word edit path — the marker is decision-based, never keyed
    on which trigger fired, so no separate un-clearable disagreement marker exists."""
    w = _w("Chapmarked", decision="flag", conf=90.0)
    w.text_ocr = "Chapmarked"                # provenance as Stage 07 assemble sets it
    w.engine_disagree = True
    assert w.flag_visible is True
    assert 'class="flag"' in S8._word_html(w, "flag", tmp_path)
    w.text = "Chopmarked"                    # user accepts EasyOCR's nomination
    assert w.flag_visible is False           # cleared via text!=text_ocr, like any flag
    assert S8._word_html(w, "flag", tmp_path) == "Chopmarked"


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


def test_paired_caption_floats_to_its_figure_across_the_page(tmp_path: Path):
    """Stage 07's pairing wins over adjacency. Mirrors it_geo_06: the caption
    stack sits far from the figures and its order does not track figure position,
    so CAP-26 must land in FIG-26's <figure> even though FIG-25 precedes it."""
    blocks = [
        Block(id=0, type="figure", bbox={"x": 0, "y": 0, "w": 60, "h": 60},
              reading_order=0),
        Block(id=1, type="figure", bbox={"x": 120, "y": 0, "w": 60, "h": 60},
              reading_order=1),
        Block(id=2, type="caption", bbox={"x": 120, "y": 150, "w": 60, "h": 20},
              reading_order=2, words=[_w("CAPTIONTWENTYSIX")],
              figure_ref={"page_id": "pg", "block_id": 1}, pair_source="number"),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page), jd)
    figs = html.split("<figure")
    assert len(figs) == 3                                   # two <figure> blocks
    assert "CAPTIONTWENTYSIX" not in figs[1]                # NOT swallowed by figure 0
    assert "CAPTIONTWENTYSIX" in figs[2]                    # floated into figure 1
    assert html.count("CAPTIONTWENTYSIX") == 1              # rendered exactly once


def test_adjacent_caption_bound_elsewhere_is_not_swallowed(tmp_path: Path):
    """The adjacency fallback must not fire for a caption that claims a different
    figure — otherwise promoting captions (which Stage 07 now does) would make
    grouping WORSE than before by handing the first figure the wrong caption."""
    blocks = [
        Block(id=0, type="figure", bbox={"x": 0, "y": 0, "w": 60, "h": 60},
              reading_order=0),
        Block(id=1, type="caption", bbox={"x": 0, "y": 70, "w": 60, "h": 20},
              reading_order=1, words=[_w("BELONGSTOTWO")],
              figure_ref={"page_id": "pg", "block_id": 2}, pair_source="geometry"),
        Block(id=2, type="figure", bbox={"x": 0, "y": 100, "w": 60, "h": 60},
              reading_order=2),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page), jd)
    figs = html.split("<figure")
    assert "BELONGSTOTWO" not in figs[1]                    # the preceding figure
    assert "BELONGSTOTWO" in figs[2]                        # its actual partner


def test_caption_ref_to_another_page_still_renders_in_place(tmp_path: Path):
    """The cross-gutter case the schema can express but this renderer cannot yet
    float. It must render the caption where it sits — never drop the text."""
    blocks = [
        Block(id=0, type="figure", bbox={"x": 0, "y": 0, "w": 60, "h": 60},
              reading_order=0),
        Block(id=1, type="caption", bbox={"x": 0, "y": 70, "w": 60, "h": 20},
              reading_order=1, words=[_w("FACINGPAGECAPTION")],
              figure_ref={"page_id": "some_other_page", "block_id": 3}),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "FACINGPAGECAPTION" in html


def test_unpaired_caption_still_groups_by_adjacency(tmp_path: Path):
    """Non-regression: a document assembled before grouping existed (schema 1.0,
    no figure_ref anywhere) must render exactly as it used to."""
    blocks = [
        Block(id=0, type="figure", bbox={"x": 0, "y": 0, "w": 60, "h": 60},
              reading_order=0),
        Block(id=1, type="caption", bbox={"x": 0, "y": 70, "w": 60, "h": 20},
              reading_order=1, words=[_w("LEGACYCAPTION")]),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "<figcaption" in html and "LEGACYCAPTION" in html


def test_user_pairing_flips_a_standalone_caption_into_its_figure(tmp_path: Path):
    """The end-to-end point of the editor's pairing control: an abstained caption
    renders as a standalone <p class="caption">, and the user's correction must move
    it INSIDE the <figure> as a real <figcaption>. Asserting the rendered output, not
    just that the field round-tripped."""
    def blocks(ref, src):
        return [
            Block(id=0, type="figure", bbox={"x": 0, "y": 0, "w": 60, "h": 60},
                  reading_order=0),
            Block(id=1, type="paragraph", bbox={"x": 0, "y": 70, "w": 60, "h": 20},
                  reading_order=1, words=[_w("Body")]),
            Block(id=2, type="caption", bbox={"x": 0, "y": 150, "w": 60, "h": 20},
                  reading_order=2, words=[_w("ABSTAINEDCAPTION")],
                  figure_ref=ref, pair_source=src),
        ]

    # before: the grouping pass abstained (no ref, no provenance)
    page, jd = _page_with(blocks(None, None), tmp_path)
    before = S8.render_html(_doc(page), jd)
    assert '<p class="caption">ABSTAINEDCAPTION' in before
    assert "<figcaption" not in before          # a bare figcaption here would be invalid HTML

    # after: the user paired it in the editor
    page2, _ = _page_with(blocks({"page_id": "pg", "block_id": 0}, "user"), tmp_path)
    after = S8.render_html(_doc(page2), jd)
    assert "<figcaption" in after and "ABSTAINEDCAPTION" in after
    assert '<p class="caption">' not in after
    assert after.count("ABSTAINEDCAPTION") == 1  # moved, not duplicated
    assert after.index("ABSTAINEDCAPTION") > after.index("<figure")  # inside the figure


def test_user_pairing_outranks_an_inferred_claim_on_the_same_figure(tmp_path: Path):
    """Repointing a caption at a figure the pipeline already gave to someone else is
    the normal way to FIX a wrong pair, and it_geo_06's cross-paired caption stack is
    exactly that shape. Binding was first-claimant-by-reading-order, so the pipeline's
    guess could beat the user to the figure and the correction would silently vanish
    from the output. A human ruling now wins regardless of position; the displaced
    caption still renders (no text lost)."""
    blocks = [
        Block(id=0, type="figure", bbox={"x": 0, "y": 0, "w": 60, "h": 60},
              reading_order=0),
        Block(id=1, type="caption", bbox={"x": 0, "y": 70, "w": 60, "h": 20},
              reading_order=1, words=[_w("GUESSEDBYPIPELINE")],
              figure_ref={"page_id": "pg", "block_id": 0}, pair_source="geometry"),
        Block(id=2, type="caption", bbox={"x": 0, "y": 100, "w": 60, "h": 20},
              reading_order=2, words=[_w("CORRECTEDBYUSER")],     # LATER in reading order
              figure_ref={"page_id": "pg", "block_id": 0}, pair_source="user"),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "<figcaption" in html and "CORRECTEDBYUSER" in html.split("<figcaption")[1]
    assert '<p class="caption">GUESSEDBYPIPELINE' in html   # displaced, not dropped
    assert html.count("GUESSEDBYPIPELINE") == 1


def test_two_user_claims_on_one_figure_fall_back_to_reading_order(tmp_path: Path):
    """Within the same provenance tier the old first-claimant rule still applies, so
    the outcome stays deterministic and the loser still renders."""
    blocks = [
        Block(id=0, type="figure", bbox={"x": 0, "y": 0, "w": 60, "h": 60},
              reading_order=0),
        Block(id=1, type="caption", bbox={"x": 0, "y": 70, "w": 60, "h": 20},
              reading_order=1, words=[_w("FIRSTUSERCLAIM")],
              figure_ref={"page_id": "pg", "block_id": 0}, pair_source="user"),
        Block(id=2, type="caption", bbox={"x": 0, "y": 100, "w": 60, "h": 20},
              reading_order=2, words=[_w("SECONDUSERCLAIM")],
              figure_ref={"page_id": "pg", "block_id": 0}, pair_source="user"),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "FIRSTUSERCLAIM" in html.split("<figcaption")[1]
    assert '<p class="caption">SECONDUSERCLAIM' in html


def test_user_unpair_is_not_undone_by_the_adjacency_fallback(tmp_path: Path):
    """A caption sitting right under the WRONG figure is the commonest thing a user
    detaches — and it is exactly the shape the adjacency fallback would re-pair. The
    user's ruling (pair_source=user with figure_ref None) must survive rendering, or
    'Unpair' is a no-op in the deliverable."""
    blocks = [
        Block(id=0, type="figure", bbox={"x": 0, "y": 0, "w": 60, "h": 60},
              reading_order=0),
        Block(id=1, type="caption", bbox={"x": 0, "y": 70, "w": 60, "h": 20},
              reading_order=1, words=[_w("DETACHEDBYUSER")], pair_source="user"),
    ]
    page, jd = _page_with(blocks, tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "<figcaption" not in html
    assert '<p class="caption">DETACHEDBYUSER' in html
    # ...while an untouched caption in the same position still groups (prior test),
    # so the fallback is narrowed by the user's decision, not removed.


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


# ---- Embedded fonts (self-contained Noto, Latin + Cyrillic) ---------------


def test_noto_serif_bundled_and_verifiable():
    """The tracked TTF exists and its family name matches the CSS stack string
    exactly (a mismatch would silently fall back to a system serif)."""
    p = S8.FONTS_DIR / "NotoSerif.ttf"
    assert p.exists() and p.stat().st_size > 100_000
    fams = {fam for _f, fam, *_ in S8._FONT_FACES}
    assert "Noto Serif" in fams          # must equal the name used in font-family


def test_font_face_embedded_as_data_uri():
    """@font-face is emitted from files PRESENT (not settings.fonts), carries a
    non-trivial base64 payload, declares the variable weight range, and is
    prepended to the stylesheet so it wins over the system serif."""
    faces = S8._font_face_css()
    assert '@font-face' in faces and 'font-family: "Noto Serif"' in faces
    assert 'base64,' in faces and 'font-weight: 100 900' in faces
    b64 = faces.split('base64,')[1].split(')')[0]
    assert len(b64) > 100_000           # the real font, not an empty stub
    assert S8._css([]).lstrip().startswith('@font-face')   # even with empty fonts


def test_font_face_degrades_gracefully_when_dir_missing(tmp_path: Path):
    """No bundled TTFs -> no faces (pre-fix behavior), never a crash."""
    assert S8._font_face_css(tmp_path) == ""


# ---- PDF backend dispatch -------------------------------------------------


def test_render_meta_reports_unreviewed_order(tmp_path: Path):
    """In review mode, render honestly counts blocks whose reading order is still
    unreviewed (auto order used) in meta + warns — an editor-only signal, never
    shown in the print output."""
    import json as _json
    blocks = [
        Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": 100, "h": 20},
              reading_order=0, order_auto=0, words=[_w("alpha")]),          # unreviewed
        Block(id=1, type="paragraph", bbox={"x": 0, "y": 30, "w": 100, "h": 20},
              reading_order=1, order_auto=1, order_confirmed=True, words=[_w("beta")]),  # confirmed
    ]
    page, jd = _page_with(blocks, tmp_path)
    doc = _doc(page, order_mode="review")
    (jd / "document.json").write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    S8.run(jd, {"reconstruct": {"pdf_backend": "none"}})
    meta = _json.loads((jd / "render" / "meta.json").read_text(encoding="utf-8"))
    assert meta["params"]["order_mode"] == "review"
    assert meta["params"]["order_unreviewed"] == 1        # only block 0
    assert any("unreviewed reading order" in w for w in meta["warnings"])
    # the signal never leaks into the print output
    html = (jd / "render" / "page.html").read_text(encoding="utf-8")
    assert "unreviewed" not in html.lower()


def test_render_meta_no_order_warning_in_auto_mode(tmp_path: Path):
    import json as _json
    blocks = [Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": 100, "h": 20},
                    reading_order=0, order_auto=0, words=[_w("alpha")])]
    page, jd = _page_with(blocks, tmp_path)
    (jd / "document.json").write_text(_doc(page).model_dump_json(indent=2), encoding="utf-8")
    S8.run(jd, {"reconstruct": {"pdf_backend": "none"}})
    meta = _json.loads((jd / "render" / "meta.json").read_text(encoding="utf-8"))
    assert meta["params"]["order_mode"] == "auto"
    assert meta["params"]["order_unreviewed"] == 0
    assert not any("unreviewed reading order" in w for w in meta["warnings"])


def test_pdf_backend_none_skips_and_notes():
    ok, note = S8.try_render_pdf("<h1>x</h1>", Path("nope.pdf"), backend="none")
    assert ok is False and "HTML only" in note


def test_pdf_backend_chromium_without_html_path_falls_through(tmp_path: Path):
    """Chromium needs the on-disk html_path; absent it, the dispatch must not
    write a PDF and must return a clear HTML-only note (never crash)."""
    ok, note = S8.try_render_pdf("<h1>x</h1>", tmp_path / "page.pdf",
                                 backend="chromium", html_path=None)
    assert ok is False and "HTML only" in note
    assert not (tmp_path / "page.pdf").exists()


def test_pdf_chromium_produces_valid_pdf_with_flag_background(tmp_path: Path):
    """Live Chromium check (skipped where Playwright/browser absent): the PDF is
    real (%PDF magic, non-trivial size) and print_background is on so the flag
    highlight survives. This is the path unit tests of pure functions can't cover."""
    pytest.importorskip("playwright")
    blocks = [Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": 100, "h": 20},
                    reading_order=0,
                    words=[_w("plain"), _w("caput", decision="flag", conf=40.0, x=40)])]
    page, jd = _page_with(blocks, tmp_path)
    html_str = S8.render_html(_doc(page, uncertainty_mode="flag"), jd)
    html_path = tmp_path / "page.html"
    html_path.write_text(html_str, encoding="utf-8")
    try:
        ok, note = S8.try_render_pdf(html_str, tmp_path / "page.pdf",
                                     backend="chromium", html_path=html_path)
    except Exception as e:  # browser not installed -> treat like importorskip
        pytest.skip(f"chromium unavailable: {e!r}")
    if not ok:
        pytest.skip(f"chromium unavailable: {note}")
    data = (tmp_path / "page.pdf").read_bytes()
    assert data[:5] == b"%PDF-" and len(data) > 1000


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_a_surface_block_is_not_rendered(tmp_path: Path):
    """A block the vision model twice called the surface the book was lying on
    (pipeline/figure_surface.py) stays in the document but leaves the page."""
    def html_for(is_surface: bool) -> str:
        page, root = _page_with([
            Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": 200, "h": 50},
                  reading_order=0, text="kept text"),
            Block(id=1, type="figure", bbox={"x": 0, "y": 60, "w": 200, "h": 100},
                  reading_order=1, is_surface=is_surface),
        ], tmp_path)
        return S8.render_html(_doc(page), root)

    kept, dropped = html_for(False), html_for(True)
    assert "kept text" in kept and "kept text" in dropped
    assert kept.count("<figure") == 1
    assert dropped.count("<figure") == 0


# --------------------------------------------------------------------------
# De-hyphenation: the lexicon is now actually supplied (2026-08-29)
# --------------------------------------------------------------------------


def test_the_lookup_ignores_punctuation_the_emitted_text_keeps_it():
    """The second half of a broken word carries the line's punctuation
    ("Tourenvor-" + "schlaege,"), and a trailing comma is in no lexicon. The
    membership test normalizes; the output must not."""
    assert S8.join_hyphen("Tourenvor-", "schlaege,", {"tourenvorschlaege"}) \
        == "Tourenvorschlaege,"


def test_the_lookup_folds_case_so_a_german_noun_validates():
    assert S8.join_hyphen("Beruecksich-", "tigung", {"beruecksichtigung"}) \
        == "Beruecksichtigung"


def test_the_dehyphen_lexicon_is_keyed_on_the_documents_own_language(tmp_path):
    """A lexicon for the wrong language silently refuses every join, so the key
    is the language the document was READ in, not the config default."""
    cfg = {"engines": {"easyocr": {"lexicon": {"deu": "models/lexicons/de.dic",
                                               "eng": "models/lexicons/en.dic"}}}}
    seen: list = []
    orig = S8.load_lexicon
    S8.load_lexicon = lambda paths: seen.append(paths) or {"x"}
    try:
        S8._dehyphen_lexicon(cfg, "deu")
        assert seen and seen[0][0].name == "de.dic"
        # a multi-language string takes the first code
        seen.clear()
        S8._dehyphen_lexicon(cfg, "deu+ita")
        assert seen and seen[0][0].name == "de.dic"
    finally:
        S8.load_lexicon = orig


def test_an_unknown_or_missing_language_stays_conservative():
    cfg = {"engines": {"easyocr": {"lexicon": {"eng": "models/lexicons/en.dic"}}}}
    assert S8._dehyphen_lexicon(cfg, "fra") is None
    assert S8._dehyphen_lexicon(cfg, None) is None
    assert S8._dehyphen_lexicon({}, "eng") is None


def test_a_broken_lexicon_does_not_fail_the_render():
    """A render must always produce a document; a missing dictionary only costs
    the joins."""
    cfg = {"engines": {"easyocr": {"lexicon": {"eng": "models/lexicons/en.dic"}}}}
    orig = S8.load_lexicon
    def boom(paths):
        raise RuntimeError("corrupt .aff")
    S8.load_lexicon = boom
    try:
        assert S8._dehyphen_lexicon(cfg, "eng") is None
    finally:
        S8.load_lexicon = orig


# ---- TABLE blocks render as a real table ---------------------------------
#
# The cells come from Stage 05 (pipeline/table_grid.py) on Word.table_row /
# table_col. Stage 08 is deliberately a dumb renderer here — it groups by those
# two fields and lays them out — because the row correspondence of a staggered
# table is NOT a function of word geometry and cannot be recovered at this point.
# So what these tests pin is the fallback and the per-word contract, not layout
# cleverness.


def _cell_w(text: str, row: int, col: int, x: int = 0, y: int = 0,
            **kw) -> Word:
    w = _w(text, x=x, **kw)
    w.bbox.y = y
    w.table_row, w.table_col = row, col
    return w


def _table_block(words) -> Block:
    return Block(id=1, type=BlockType.TABLE,
                 bbox={"x": 0, "y": 0, "w": 500, "h": 200},
                 reading_order=0, words=words)


def test_table_with_cells_renders_a_table(tmp_path: Path):
    blk = _table_block([
        _cell_w("Route", 0, 0, x=0, y=0), _cell_w("3 Std.", 0, 1, x=300, y=0),
        _cell_w("Other", 1, 0, x=0, y=50), _cell_w("8 Std.", 1, 1, x=300, y=50),
    ])
    page, jd = _page_with([blk], tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "<table" in html
    assert "<tr><td>Route</td><td>3 Std.</td></tr>" in html
    assert "<tr><td>Other</td><td>8 Std.</td></tr>" in html


def test_table_without_cells_renders_exactly_as_before(tmp_path: Path):
    """The normal case for every document written before the grid pass existed,
    and for every table it abstained on. It must be the OLD paragraph render —
    half a table would be worse than none."""
    blk = _table_block([_w("Route", x=0), _w("3", x=300), _w("Other", x=0)])
    page, jd = _page_with([blk], tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "<table" not in html
    assert '<p class="table">Route 3 Other</p>' in html


def test_table_text_override_supersedes_the_grid(tmp_path: Path):
    """A human's (or a translator's) copy of the whole block wins, exactly as it
    does for a paragraph. Re-gridding it into stale cells would contradict it."""
    blk = _table_block([_cell_w("Route", 0, 0), _cell_w("3 Std.", 0, 1)])
    blk.text = "translated table"
    page, jd = _page_with([blk], tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "<table" not in html and "translated table" in html


def test_uncertainty_marker_survives_inside_a_cell(tmp_path: Path):
    """Cells go through the same per-word path as a paragraph, so a still-visible
    marker is highlighted inside the cell rather than silently flattened."""
    blk = _table_block([
        _cell_w("Route", 0, 0, x=0), _cell_w("8%", 0, 1, x=300, conf=20.0,
                                             decision="flag"),
    ])
    page, jd = _page_with([blk], tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert '<td><span class="flag"' in html and "8%" in html


def test_table_never_drops_a_word(tmp_path: Path):
    """A word with no cell means the grid does not cover the block; rendering the
    covered part would silently lose the rest, so the whole block falls back."""
    blk = _table_block([_cell_w("Route", 0, 0), _cell_w("3 Std.", 0, 1),
                        _w("orphan", x=400)])
    page, jd = _page_with([blk], tmp_path)
    html = S8.render_html(_doc(page), jd)
    assert "<table" not in html and "orphan" in html


def test_cell_order_is_visual_lines_then_left_to_right():
    """Neither document order nor a plain y-sort. Document order puts the tail of
    a split line first; a y-sort scrambles one line into "Std. 7%"."""
    tail = _w("Aglio", x=520); tail.bbox.y = 8      # same printed line, skewed up
    head = _w("Ferrata", x=300); head.bbox.y = 20
    wrapped = _w("Pegna", x=300); wrapped.bbox.y = 60
    assert [w.text for w in S8.cell_order([tail, head, wrapped])] == [
        "Ferrata", "Aglio", "Pegna"]
