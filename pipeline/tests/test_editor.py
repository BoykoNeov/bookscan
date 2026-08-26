"""Tests for pipeline.editor — the mutable edit surface over document.json.

Three layers, cheapest first:
  * PURE edit-apply / persistence (``normalize_edits`` / ``save_document``): the
    load-bearing invariants assemble's clobber-detection keys on — a word edit sets
    ``edited`` (and flips ``flag_visible``), a type/order change sets
    ``structure_edited``, provenance (``text_ocr``/``*_auto``) is never touched, and
    the write is atomic with a ``.bak``.
  * HTTP round-trip via the real stdlib server (no browser): GET the doc, mutate a
    word, PUT it back, GET again and confirm the flag flipped on disk.
  * Playwright DOM e2e (advisor's "verify the UI for real"): launch the server on a
    real synthetic job, click a word box, edit its text in the inspector, hit Save,
    and assert ``document.json`` on disk changed and ``flag_visible`` flipped.

Run with pytest, or directly:
    python -m pipeline.tests.test_editor
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline import editor as ED
from pipeline.page_model import (
    Block, BlockRef, BlockType, Document, DocPage, DocSettings, PairSource, Word,
    WordDecision,
)


# --------------------------------------------------------------------------
# Fixtures — a tiny, hermetic job (document.json + one page image asset)
# --------------------------------------------------------------------------


def _mini_doc() -> Document:
    """One page, two blocks; block 1 carries a FLAGGED word (uncertainty marker)."""
    b0 = Block(
        id=0, type=BlockType.HEADING, bbox={"x": 10, "y": 10, "w": 180, "h": 20},
        reading_order=0, type_auto=BlockType.HEADING, order_auto=0,
        words=[Word(text="Title", text_ocr="Title", bbox={"x": 10, "y": 10, "w": 60, "h": 18},
                    conf=95.0, decision=WordDecision.KEEP, line_id=0, block_id=0)],
    )
    b1 = Block(
        id=1, type=BlockType.PARAGRAPH, bbox={"x": 10, "y": 40, "w": 180, "h": 40},
        reading_order=1, type_auto=BlockType.PARAGRAPH, order_auto=1,
        words=[
            Word(text="hello", text_ocr="hello", bbox={"x": 10, "y": 40, "w": 50, "h": 18},
                 conf=92.0, decision=WordDecision.KEEP, line_id=1, block_id=1),
            Word(text="wrold", text_ocr="wrold", bbox={"x": 70, "y": 40, "w": 55, "h": 18},
                 conf=41.0, decision=WordDecision.FLAG, line_id=1, block_id=1),
        ],
    )
    # A figure + the caption Stage 07's grouping pass PAIRED to it. Present in the
    # fixture so every editor test exercises a document that carries grouping
    # provenance — the fields must survive an unrelated edit, or the first thing a
    # user does silently unpairs the document.
    b2 = Block(
        id=2, type=BlockType.FIGURE, bbox={"x": 10, "y": 90, "w": 180, "h": 60},
        reading_order=2, type_auto=BlockType.FIGURE, order_auto=2, figure_number=7,
    )
    b3 = Block(
        id=3, type=BlockType.CAPTION, bbox={"x": 10, "y": 155, "w": 180, "h": 20},
        reading_order=3, type_auto=BlockType.CAPTION, order_auto=3,
        caption_number=7, type_promoted=True, pair_source=PairSource.NUMBER,
        figure_ref=BlockRef(page_id="page_001__single", block_id=2),
        words=[Word(text="Figure", text_ocr="Figure",
                    bbox={"x": 10, "y": 155, "w": 60, "h": 18}, conf=90.0,
                    decision=WordDecision.KEEP, line_id=2, block_id=3)],
    )
    return Document(
        document_id="mini", job_id="mini",
        settings=DocSettings(source_language="eng", uncertainty_mode="flag"),
        pages=[DocPage(page_id="page_001__single", source_spread="page_001",
                       subpage="single", width=200, height=100,
                       image_asset="document_assets/page_001__single.png",
                       blocks=[b0, b1, b2, b3])],
    )


@pytest.fixture
def job(tmp_path: Path) -> Path:
    doc = _mini_doc()
    (tmp_path / "document_assets").mkdir()
    img = np.full((100, 200, 3), 255, np.uint8)
    cv2.imwrite(str(tmp_path / "document_assets" / "page_001__single.png"), img)
    (tmp_path / "document.json").write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return tmp_path


def _flagged_word(doc: Document) -> Word:
    return doc.pages[0].blocks[1].words[1]  # "wrold" (decision=FLAG)


# --------------------------------------------------------------------------
# Layer 1 — pure edit-apply / persistence invariants
# --------------------------------------------------------------------------


def test_editing_word_sets_edited_and_clears_flag(job: Path):
    doc = ED.load_document(job)
    w = _flagged_word(doc)
    assert w.flag_visible and not w.edited          # precondition: marker shown
    w.text = "world"                                # the correction
    ED.normalize_edits(doc)
    assert w.edited is True                          # <- what assemble's guard checks
    assert w.flag_visible is False                   # owner's per-word rule: marker cleared
    assert w.text_ocr == "wrold"                     # provenance NEVER touched


def test_type_and_order_change_set_structure_edited(job: Path):
    doc = ED.load_document(job)
    blk = doc.pages[0].blocks[0]
    blk.type = BlockType.TITLE                        # was HEADING (type_auto)
    ED.normalize_edits(doc)
    assert blk.structure_edited is True
    assert blk.type_auto == BlockType.HEADING         # auto preserved

    doc2 = ED.load_document(job)
    b2 = doc2.pages[0].blocks[1]
    b2.reading_order = 5                               # was 1 (order_auto)
    ED.normalize_edits(doc2)
    assert b2.structure_edited is True
    assert b2.order_auto == 1


def test_normalize_is_noop_on_pristine_doc(job: Path):
    doc = ED.load_document(job)
    ED.normalize_edits(doc)
    assert not ED._document_has_edits(doc)            # fresh assemble = not protected


def test_save_is_atomic_and_keeps_bak(job: Path):
    doc = ED.load_document(job)
    _flagged_word(doc).text = "world"
    ED.save_document(job, doc)
    assert (job / "document.json.bak").exists()       # prior copy retained
    assert not (job / "document.json.tmp").exists()   # temp cleaned by os.replace
    reloaded = ED.load_document(job)                  # persisted + still valid
    assert _flagged_word(reloaded).edited is True
    assert ED._document_has_edits(reloaded)


def test_target_language_marks_document_edited(job: Path):
    doc = ED.load_document(job)
    doc.settings.target_language = "ita"
    assert ED._document_has_edits(doc)


# --------------------------------------------------------------------------
# Layer 1 (cont.) — reading-order review mode (Block.order_review_visible)
# --------------------------------------------------------------------------


def _review_block() -> Block:
    return Block(id=0, type=BlockType.PARAGRAPH,
                 bbox={"x": 0, "y": 0, "w": 10, "h": 10}, reading_order=3,
                 type_auto=BlockType.PARAGRAPH, order_auto=3)


def test_order_review_auto_mode_never_needs_review():
    assert _review_block().order_review_visible("auto") is False


def test_order_review_untouched_needs_review_in_review_mode():
    assert _review_block().order_review_visible("review") is True


def test_order_review_type_edit_does_not_clear_review():
    """The load-bearing correctness rule (advisor): a type-only edit sets the shared
    ``structure_edited`` bit but must NOT count as reviewing the order."""
    b = _review_block()
    b.type = BlockType.HEADING
    b.structure_edited = True                 # a type change flips the shared bit
    assert b.reading_order == b.order_auto     # order itself untouched
    assert b.order_review_visible("review") is True


def test_order_review_renumber_clears_review():
    b = _review_block()
    b.reading_order = 9                         # diverges from order_auto=3
    assert b.order_review_visible("review") is False


def test_order_review_explicit_confirm_clears_review():
    b = _review_block()
    b.order_confirmed = True                    # accepted auto order (number unchanged)
    assert b.reading_order == b.order_auto
    assert b.order_review_visible("review") is False


def test_order_review_none_order_auto_is_conservative():
    b = Block(id=0, type=BlockType.PARAGRAPH,
              bbox={"x": 0, "y": 0, "w": 10, "h": 10}, reading_order=3)  # no order_auto
    assert b.order_review_visible("review") is True


def test_confirming_order_marks_document_edited(job: Path):
    """order_confirmed is real review work — it must protect the doc from a
    re-assemble even though no number diverged."""
    doc = ED.load_document(job)
    assert not ED._document_has_edits(doc)          # pristine
    doc.pages[0].blocks[0].order_confirmed = True
    assert ED._document_has_edits(doc)              # both editor + assemble copies agree
    from pipeline import stage07_assemble as S7
    assert S7._document_has_edits(doc)


def test_grouping_survives_a_load_save_roundtrip(job: Path):
    """Grouping lives in the editable document, so it only means anything if it
    survives editing. Pure layer first."""
    doc = ED.load_document(job)
    ED.save_document(job, doc)
    cap = ED.load_document(job).pages[0].blocks[3]
    assert cap.figure_ref is not None and cap.figure_ref.block_id == 2
    assert cap.pair_source is PairSource.NUMBER
    assert cap.caption_number == 7 and cap.type_promoted is True


def test_pristine_grouped_document_does_not_read_as_edited(job: Path):
    """An automatic caption promotion must not trip the clobber guard: Stage 07
    writes the promoted type into type_auto as well, so re-assembling without
    --force stays possible on a document nobody has touched."""
    doc = ED.load_document(job)
    ED.normalize_edits(doc)
    assert doc.pages[0].blocks[3].structure_edited is False
    from pipeline.stage07_assemble import _document_has_edits
    assert _document_has_edits(doc) is False


def _add_abstained_pair(job: Path) -> Path:
    """Append a second FIGURE (id 4) plus a caption the grouping pass ABSTAINED on
    (id 5: no figure_ref, no pair_source) — the state the editor's pairing control
    exists to resolve. Kept out of the shared fixture so the existing DOM counts
    (4 word boxes) stay meaningful."""
    doc = ED.load_document(job)
    pg = doc.pages[0]
    pg.blocks.append(Block(
        id=4, type=BlockType.FIGURE, bbox={"x": 10, "y": 200, "w": 180, "h": 60},
        reading_order=4, type_auto=BlockType.FIGURE, order_auto=4))
    pg.blocks.append(Block(
        id=5, type=BlockType.CAPTION, bbox={"x": 10, "y": 265, "w": 180, "h": 20},
        reading_order=5, type_auto=BlockType.CAPTION, order_auto=5,
        words=[Word(text="Loose", text_ocr="Loose",
                    bbox={"x": 10, "y": 265, "w": 60, "h": 18}, conf=90.0,
                    decision=WordDecision.KEEP, line_id=3, block_id=5)]))
    (job / "document.json").write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    return job


def test_abstained_caption_does_not_read_as_edited(job: Path):
    """Precondition for the two tests below: an abstained caption (no ref, no
    provenance) is the pipeline's own output, so it must NOT protect the document."""
    _add_abstained_pair(job)
    doc = ED.load_document(job)
    assert doc.pages[0].blocks[5].figure_ref is None
    assert doc.pages[0].blocks[5].pair_source is None
    assert ED._document_has_edits(doc) is False


def test_user_pairing_marks_document_edited(job: Path):
    """A pairing the user set is protected work — without this the next
    ``POST /assemble`` (no ?force) silently discards it."""
    _add_abstained_pair(job)
    doc = ED.load_document(job)
    cap = doc.pages[0].blocks[5]
    cap.figure_ref = BlockRef(page_id="page_001__single", block_id=4)
    cap.pair_source = PairSource.USER
    ED.normalize_edits(doc)
    assert ED._document_has_edits(doc)
    from pipeline import stage07_assemble as S7
    assert S7._document_has_edits(doc)          # both mirrors agree


def test_user_unpair_marks_document_edited(job: Path):
    """The inverse, and the easy one to get wrong: detaching a wrong pair leaves
    ``figure_ref`` None — indistinguishable from an abstain EXCEPT for the USER
    provenance stamp. Keying the guard on figure_ref would drop this correction."""
    doc = ED.load_document(job)
    cap = doc.pages[0].blocks[3]                 # was paired by NUMBER
    cap.figure_ref = None
    cap.pair_source = PairSource.USER
    ED.normalize_edits(doc)
    assert ED._document_has_edits(doc)
    from pipeline import stage07_assemble as S7
    assert S7._document_has_edits(doc)


def test_http_put_persists_user_pairing_and_unpair(job: Path):
    """Through the real server, exactly as the SPA sends it: pair the abstained
    caption and detach the number-paired one in one PUT."""
    _add_abstained_pair(job)
    with _Server(job) as srv:
        doc = _get_json(srv.url("/api/document"))
        blocks = doc["pages"][0]["blocks"]
        blocks[5]["figure_ref"] = {"page_id": "page_001__single", "block_id": 4}
        blocks[5]["pair_source"] = "user"
        blocks[3]["figure_ref"] = None            # detach the NUMBER-sourced pair
        blocks[3]["pair_source"] = "user"
        req = urllib.request.Request(
            srv.url("/api/document"), data=json.dumps(doc).encode("utf-8"),
            method="PUT", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read().decode("utf-8"))
        assert body["ok"] and body["has_edits"] is True   # UI reports it as protected
    reloaded = ED.load_document(job).pages[0].blocks
    assert reloaded[5].figure_ref is not None
    assert reloaded[5].figure_ref.block_id == 4
    assert reloaded[5].pair_source is PairSource.USER
    assert reloaded[3].figure_ref is None
    assert reloaded[3].pair_source is PairSource.USER
    assert reloaded[3].caption_number == 7            # provenance untouched by the unpair


def test_http_put_word_edit_preserves_figure_grouping(job: Path):
    """THE regression this guards: the SPA PUTs the whole fetched document back,
    so a word edit in an unrelated block must not drop figure_ref/pair_source.
    A green suite could not detect this before the fixture carried the fields."""
    with _Server(job) as srv:
        doc = _get_json(srv.url("/api/document"))
        doc["pages"][0]["blocks"][1]["words"][1]["text"] = "world"   # unrelated edit
        req = urllib.request.Request(
            srv.url("/api/document"), data=json.dumps(doc).encode("utf-8"),
            method="PUT", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read().decode("utf-8"))["ok"]
    cap = ED.load_document(job).pages[0].blocks[3]
    assert cap.figure_ref is not None
    assert cap.figure_ref.page_id == "page_001__single" and cap.figure_ref.block_id == 2
    assert cap.pair_source is PairSource.NUMBER
    assert cap.caption_number == 7 and cap.type_promoted is True
    assert ED.load_document(job).pages[0].blocks[2].figure_number == 7


def test_http_put_persists_order_confirmed(job: Path):
    """The review-mode 'accept auto order' action round-trips through the server and
    is saved as-is (no divergence to infer it from)."""
    with _Server(job) as srv:
        doc = _get_json(srv.url("/api/document"))
        doc["settings"]["order_mode"] = "review"
        doc["pages"][0]["blocks"][0]["order_confirmed"] = True
        req = urllib.request.Request(
            srv.url("/api/document"), data=json.dumps(doc).encode("utf-8"),
            method="PUT", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read().decode("utf-8"))
        assert body["ok"] and body["has_edits"] is True
    reloaded = ED.load_document(job)
    assert reloaded.settings.order_mode == "review"
    blk = reloaded.pages[0].blocks[0]
    assert blk.order_confirmed is True
    assert blk.order_review_visible("review") is False


# --------------------------------------------------------------------------
# Layer 2 — HTTP round-trip through the real server (no browser)
# --------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    def __init__(self, job_dir: Path):
        self.port = _free_port()
        handler = type("_Bound", (ED._Handler,), {"job_dir": job_dir.resolve()})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.t.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read().decode("utf-8"))


def test_http_put_persists_edit_and_flips_flag(job: Path):
    with _Server(job) as srv:
        doc = _get_json(srv.url("/api/document"))
        doc["pages"][0]["blocks"][1]["words"][1]["text"] = "world"   # fix "wrold"
        req = urllib.request.Request(
            srv.url("/api/document"), data=json.dumps(doc).encode("utf-8"),
            method="PUT", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read().decode("utf-8"))
        assert body["ok"] and body["has_edits"] is True

    # on disk: server normalized the edit flag; the marker is now cleared
    reloaded = ED.load_document(job)
    w = _flagged_word(reloaded)
    assert w.text == "world" and w.edited is True and w.flag_visible is False
    assert (job / "document.json.bak").exists()


def test_http_put_rejects_malformed_document(job: Path):
    with _Server(job) as srv:
        req = urllib.request.Request(
            srv.url("/api/document"), data=b'{"not":"a document"}',
            method="PUT", headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req)
        assert ei.value.code == 400                    # pydantic rejected the write
    # the good copy on disk is untouched
    assert ED.load_document(job).pages[0].blocks[1].words[1].text == "wrold"


def test_http_render_writes_html(job: Path):
    with _Server(job) as srv:
        req = urllib.request.Request(srv.url("/api/render"), data=b"", method="POST")
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["ok"] is True
    html = (job / "render" / "page.html").read_text(encoding="utf-8")
    assert "<html" in html and "Title" in html


# --------------------------------------------------------------------------
# Layer 3 — Playwright DOM e2e (the UI itself, not just the endpoints)
# --------------------------------------------------------------------------


@pytest.mark.e2e
def test_e2e_edit_word_via_dom(job: Path):
    playwright = pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # chromium not installed -> skip, don't fail the suite
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.wait_for_selector("#ovWords .wbox")
            # word boxes in reading order: Title, hello, wrold, Figure (the last
            # belongs to the paired caption block). The flagged word is the 3rd.
            boxes = pg.query_selector_all("#ovWords .wbox")
            assert len(boxes) == 4
            boxes[2].click()
            inp = pg.wait_for_selector("#inspector .card input")   # the editable text field
            inp.fill("world")
            inp.dispatch_event("input")
            pg.click("#save")
            pg.wait_for_function(
                "() => document.querySelector('#status').textContent.includes('saved')")
        finally:
            browser.close()

    w = _flagged_word(ED.load_document(job))
    assert w.text == "world" and w.edited is True and w.flag_visible is False


@pytest.mark.e2e
def test_e2e_review_mode_confirm_all_via_dom(job: Path):
    """Drive the review workflow through the real UI: switch reading-order mode to
    'review' in Settings, click 'Confirm all', Save, and assert every block on disk
    is order_confirmed."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.click('.tabs button[data-tab="settings"]')
            # order-mode is the 2nd select in the settings pane (after uncertainty mode)
            selects = pg.query_selector_all("#settings select")
            assert len(selects) >= 2
            selects[1].select_option("review")
            pg.click('.tabs button[data-tab="inspect"]')
            pg.wait_for_selector("#blocklist .reviewbar button")   # "Confirm all" present
            pg.click("#blocklist .reviewbar button")
            pg.click("#save")
            pg.wait_for_function(
                "() => document.querySelector('#status').textContent.includes('saved')")
        finally:
            browser.close()

    reloaded = ED.load_document(job)
    assert reloaded.settings.order_mode == "review"
    assert all(b.order_confirmed for b in reloaded.pages[0].blocks)
    assert not any(b.order_review_visible("review") for b in reloaded.pages[0].blocks)


@pytest.mark.e2e
def test_e2e_pair_and_unpair_a_caption_via_dom(job: Path):
    """Drive the pairing control through the real UI: select the abstained caption,
    pick its figure from the dropdown, then detach the number-paired caption with
    Unpair, Save, and assert both rulings landed on disk with USER provenance."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    _add_abstained_pair(job)
    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.wait_for_selector("#blocklist .blockrow")
            # the abstained caption is flagged on the page and in the list
            assert pg.query_selector("#blocklist .reviewbar.pair") is not None
            assert len(pg.query_selector_all("#blocklist .blockrow .dot.pair")) == 1
            assert len(pg.query_selector_all("#ovBlocks .bbox.pairing")) == 1

            rows = pg.query_selector_all("#blocklist .blockrow")   # reading order 0..5
            assert len(rows) == 6
            rows[5].click()                                        # the loose caption
            pg.wait_for_selector("#inspector .card select")
            # block card selects: [type, figure-pairing]
            sels = pg.query_selector_all("#inspector .card select")
            assert len(sels) == 2
            sels[1].select_option("4")                             # pair to FIGURE id 4
            pg.wait_for_selector("#blocklist .blockrow .dot.pair", state="detached")

            rows = pg.query_selector_all("#blocklist .blockrow")
            rows[3].click()                                        # the NUMBER-paired caption
            pg.wait_for_selector("#inspector .card button:has-text('Unpair')")
            pg.click("#inspector .card button:has-text('Unpair')")

            pg.click("#save")
            pg.wait_for_function(
                "() => document.querySelector('#status').textContent.includes('saved')")
            # the UI must tell the user their pairing is now protected
            assert "edits protected" in pg.text_content("#status")
        finally:
            browser.close()

    blocks = ED.load_document(job).pages[0].blocks
    assert blocks[5].figure_ref is not None and blocks[5].figure_ref.block_id == 4
    assert blocks[5].figure_ref.page_id == "page_001__single"
    assert blocks[5].pair_source is PairSource.USER
    assert blocks[3].figure_ref is None and blocks[3].pair_source is PairSource.USER


@pytest.mark.e2e
def test_e2e_pairing_to_a_taken_figure_is_flagged_not_silently_dropped(job: Path):
    """A figure holds ONE caption. If the user points a caption at a figure another
    caption already holds, the renderer keeps one and the other prints alone — so the
    editor must SAY so on the loser, instead of showing a pair the deliverable ignores.

    Here the user's new claim DISPLACES the pipeline's number-sourced one (the same
    precedence stage08_render applies), so the warning has to land on block #3 — the
    displaced caption the user never touched and would otherwise never think to check.
    """
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    _add_abstained_pair(job)
    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.wait_for_selector("#blocklist .blockrow")
            rows = pg.query_selector_all("#blocklist .blockrow")
            rows[5].click()                                   # the loose caption
            sels = pg.query_selector_all("#inspector .card select")
            sels[1].select_option("2")                        # figure ALREADY held by caption #3
            # the user's own caption reads as cleanly paired...
            assert "figure taken" not in pg.text_content("#inspector")
            # ...and the caption it displaced is flagged, in the list and on inspection
            pg.wait_for_selector("#blocklist .blockrow .dot.pair")
            rows = pg.query_selector_all("#blocklist .blockrow")
            assert "⚠" in rows[3].text_content()
            rows[3].click()
            pg.wait_for_selector("#inspector .card .badge.pair")
            body = pg.text_content("#inspector")
            assert "figure taken" in body
            assert "already belongs to caption #5 (also yours)" in body
            assert "will still print on its own" in body
            # exactly one caption on the page is unattached in the output — the loser
            assert pg.query_selector("#blocklist .reviewbar.pair") is not None
            assert len(pg.query_selector_all("#blocklist .blockrow .dot.pair")) == 1
        finally:
            browser.close()


# --------------------------------------------------------------------------
# Structure edits — reorder + split + undo
#
# The browser owns the edit logic (it is the edit surface), so these are mostly DOM
# e2e tests. Three things are checked at the Python layer instead, because they are
# server-side invariants a browser test cannot prove: that a split-shaped block —
# one the pipeline never proposed, so it has NO ``*_auto`` provenance to diverge
# from — validates, and that assemble's clobber-detection still sees it as work
# worth protecting. That block is the one shape where ``normalize_edits`` cannot
# infer ``structure_edited``, so the editor sets it explicitly; if that ever
# regressed, a re-assemble would silently discard every split the user made.
# --------------------------------------------------------------------------


def _split_shaped_block() -> Block:
    """The tail half a split produces: fresh id above every existing one, no
    ``type_auto``/``order_auto``, ``structure_edited`` set by hand."""
    return Block(
        id=4, type=BlockType.PARAGRAPH, bbox={"x": 70, "y": 40, "w": 55, "h": 18},
        reading_order=2, type_auto=None, order_auto=None, structure_edited=True,
        words=[Word(text="wrold", text_ocr="wrold",
                    bbox={"x": 70, "y": 40, "w": 55, "h": 18}, conf=41.0,
                    decision=WordDecision.FLAG, line_id=1, block_id=4)],
    )


def test_split_shaped_block_survives_normalize(job: Path):
    doc = ED.load_document(job)
    doc.pages[0].blocks.append(_split_shaped_block())
    ED.normalize_edits(doc)
    nb = doc.pages[0].blocks[-1]
    assert nb.structure_edited is True          # not cleared by the divergence check
    assert nb.type_auto is None and nb.order_auto is None   # provenance stays absent


def test_split_shaped_block_reads_as_edited(job: Path):
    """A page whose ONLY human work is a split must block a silent re-assemble."""
    doc = ED.load_document(job)
    assert ED._document_has_edits(doc) is False   # pristine to begin with
    doc.pages[0].blocks.append(_split_shaped_block())
    assert ED._document_has_edits(doc) is True


def test_http_put_persists_a_split_shaped_block(job: Path):
    doc = ED.load_document(job)
    doc.pages[0].blocks.append(_split_shaped_block())
    with _Server(job) as srv:
        req = urllib.request.Request(
            srv.url("/api/document"), data=doc.model_dump_json().encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="PUT")
        body = json.loads(urllib.request.urlopen(req).read())
    assert body["ok"] is True and body["has_edits"] is True
    nb = ED.load_document(job).pages[0].blocks[-1]
    assert nb.id == 4 and nb.structure_edited is True and nb.type_auto is None


def _blocklist_state(pg) -> list:
    """(block id, reading_order) in the order the block list shows them."""
    return [tuple(x) for x in pg.evaluate(
        "() => [...page().blocks].sort((a,b)=>a.reading_order-b.reading_order)"
        "        .map(b=>[b.id, b.reading_order])")]


@pytest.mark.e2e
def test_e2e_reorder_block_keeps_ids_and_pairing(job: Path):
    """Alt+Down moves the selected block one slot later. The result must be a dense
    0..n-1 permutation, block IDS must be untouched (``figure_ref`` is a pointer to
    one — renumbering would silently dangle it), and the caption must still resolve
    to its figure after the move."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.wait_for_selector("#blocklist .blockrow")
            assert _blocklist_state(pg) == [(0, 0), (1, 1), (2, 2), (3, 3)]
            pg.query_selector_all("#blocklist .blockrow")[0].click()   # block 0
            pg.keyboard.press("Alt+ArrowDown")
            assert _blocklist_state(pg) == [(1, 0), (0, 1), (2, 2), (3, 3)]
            pg.click("#save")
            pg.wait_for_function(
                "() => document.querySelector('#status').textContent.includes('saved')")
        finally:
            browser.close()

    blocks = {b.id: b for b in ED.load_document(job).pages[0].blocks}
    assert sorted(blocks) == [0, 1, 2, 3]                        # no id was reassigned
    assert blocks[1].reading_order == 0 and blocks[0].reading_order == 1
    assert sorted(b.reading_order for b in blocks.values()) == [0, 1, 2, 3]  # dense
    assert blocks[3].figure_ref is not None and blocks[3].figure_ref.block_id == 2
    assert blocks[0].structure_edited is True   # its order diverged from order_auto
    # The blocks the move did NOT pass keep their exact number, so nothing outside
    # the travelled span was silently marked as reviewed.
    assert blocks[2].reading_order == 2 and blocks[3].reading_order == 3


@pytest.mark.e2e
def test_e2e_drag_row_reorders(job: Path):
    """The HTML5 drag handlers themselves, driven with a synthetic DataTransfer:
    drop block 0 onto the BOTTOM half of the last row -> it lands last."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.wait_for_selector("#blocklist .blockrow")
            pg.evaluate("""() => {
              const rows = document.querySelectorAll('#blocklist .blockrow');
              const dt = new DataTransfer();
              rows[0].dispatchEvent(new DragEvent('dragstart',
                {bubbles:true, dataTransfer:dt}));
              const last = rows[rows.length-1], r = last.getBoundingClientRect();
              const opts = {bubbles:true, dataTransfer:dt,
                            clientY: r.top + r.height*0.9};   // bottom half -> drop AFTER
              last.dispatchEvent(new DragEvent('dragover', opts));
              last.dispatchEvent(new DragEvent('drop', opts));
            }""")
            assert _blocklist_state(pg) == [(1, 0), (2, 1), (3, 2), (0, 3)]
        finally:
            browser.close()


@pytest.mark.e2e
def test_e2e_split_block_via_dom(job: Path):
    """Select the 2nd word of the two-word paragraph, split there, and assert the
    tail became its own block with a FRESH id, both halves carry only their own
    words, and the whole thing survives a save."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.wait_for_selector("#ovWords .wbox")
            pg.query_selector_all("#ovWords .wbox")[2].click()   # "wrold", word 1 of block 1
            btn = pg.wait_for_selector("#inspector button:has-text('Split here')")
            assert "wrold" in btn.text_content()
            btn.click()
            assert _blocklist_state(pg) == [(0, 0), (1, 1), (4, 2), (2, 3), (3, 4)]
            pg.click("#save")
            pg.wait_for_function(
                "() => document.querySelector('#status').textContent.includes('saved')")
        finally:
            browser.close()

    blocks = {b.id: b for b in ED.load_document(job).pages[0].blocks}
    assert sorted(blocks) == [0, 1, 2, 3, 4]
    assert [w.text for w in blocks[1].words] == ["hello"]
    assert [w.text for w in blocks[4].words] == ["wrold"]
    assert blocks[4].words[0].block_id == 4          # word re-homed to its new block
    assert blocks[4].type is BlockType.PARAGRAPH     # same type as the block it left
    assert blocks[4].type_auto is None and blocks[4].order_auto is None
    assert blocks[4].structure_edited and blocks[1].structure_edited
    assert blocks[4].figure_ref is None              # pairing state stays with the head
    assert blocks[3].figure_ref.block_id == 2        # the real pair is untouched
    # both halves shrink to the geometry of the words they actually own
    assert blocks[1].bbox.w == 50 and blocks[4].bbox.x == 70


@pytest.mark.e2e
def test_e2e_split_refuses_a_figure_and_a_translated_block(job: Path):
    """Splitting is offered only where it would change the output: a figure renders
    from pixels, and a block-level text override supersedes the words entirely."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.wait_for_selector("#blocklist .blockrow")
            # a figure carries no words at all -> no split control is even built
            pg.query_selector_all("#blocklist .blockrow")[2].click()
            assert "Split here" not in pg.text_content("#inspector")
            # give the paragraph a translation, then re-select its 2nd word
            pg.query_selector_all("#ovWords .wbox")[2].click()
            ta = pg.wait_for_selector("#inspector textarea")
            ta.fill("hallo welt")
            ta.dispatch_event("input")
            pg.query_selector_all("#ovWords .wbox")[2].click()
            body = pg.text_content("#inspector")
            assert "Split here" not in body
            assert "block-level text override" in body and "clear it first" in body
        finally:
            browser.close()


@pytest.mark.e2e
def test_e2e_undo_reverts_word_edit_split_and_reorder(job: Path):
    """One undo stack over all three kinds of change, popped newest-first."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.wait_for_selector("#blocklist .blockrow")
            assert pg.query_selector("#undo").is_disabled()   # nothing to undo yet

            pg.query_selector_all("#ovWords .wbox")[2].click()   # "wrold"
            inp = pg.wait_for_selector("#inspector .card input")
            inp.fill("world")
            inp.dispatch_event("input")
            pg.query_selector_all("#ovWords .wbox")[2].click()
            pg.wait_for_selector("#inspector button:has-text('Split here')")
            pg.click("#inspector button:has-text('Split here')")
            pg.query_selector_all("#blocklist .blockrow")[0].click()
            pg.keyboard.press("Alt+ArrowDown")
            assert _blocklist_state(pg) == [(1, 0), (0, 1), (4, 2), (2, 3), (3, 4)]

            pg.click("#undo")                                  # undo the reorder
            assert _blocklist_state(pg) == [(0, 0), (1, 1), (4, 2), (2, 3), (3, 4)]
            pg.click("#undo")                                  # undo the split
            assert _blocklist_state(pg) == [(0, 0), (1, 1), (2, 2), (3, 3)]
            assert pg.evaluate(
                "() => page().blocks.find(b=>b.id===1).words.map(w=>w.text)"
            ) == ["hello", "world"]
            pg.click("#undo")                                  # undo the word edit
            assert pg.evaluate(
                "() => page().blocks.find(b=>b.id===1).words.map(w=>w.text)"
            ) == ["hello", "wrold"]
            # the edit flag rides in the snapshot, so it comes back off too
            assert pg.evaluate(
                "() => page().blocks.find(b=>b.id===1).words[1].edited") is False
            assert pg.query_selector("#undo").is_disabled()
            # undoing leaves the in-memory doc ahead of disk on purpose
            assert "unsaved" in pg.text_content("#status")
        finally:
            browser.close()


@pytest.mark.e2e
def test_e2e_undo_after_save_needs_a_second_save(job: Path):
    """Undo is an in-memory stack, not a server rollback: after Save, undoing does
    NOT touch disk until the user saves again."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with _Server(job) as srv, sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"chromium unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(srv.url("/"), wait_until="networkidle")
            pg.wait_for_selector("#ovWords .wbox")
            pg.query_selector_all("#ovWords .wbox")[2].click()
            inp = pg.wait_for_selector("#inspector .card input")
            inp.fill("world")
            inp.dispatch_event("input")
            pg.click("#save")
            pg.wait_for_function(
                "() => document.querySelector('#status').textContent.includes('saved')")
            assert ED.load_document(job).pages[0].blocks[1].words[1].text == "world"
            pg.click("#undo")
            assert pg.evaluate(
                "() => page().blocks.find(b=>b.id===1).words[1].text") == "wrold"
            # disk still holds the saved edit — undo did not roll the server back
            assert ED.load_document(job).pages[0].blocks[1].words[1].text == "world"
            pg.click("#save")
            pg.wait_for_function(
                "() => document.querySelector('#status').textContent.includes('saved')")
        finally:
            browser.close()

    w = ED.load_document(job).pages[0].blocks[1].words[1]
    # normalize_edits only ever SETS a flag from a divergence, so a restored snapshot
    # whose text matches text_ocr again is written back un-flagged rather than stuck.
    assert w.text == "wrold" and w.edited is False and w.flag_visible is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
