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
    Block, BlockType, Document, DocPage, DocSettings, Word, WordDecision,
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
    return Document(
        document_id="mini", job_id="mini",
        settings=DocSettings(source_language="eng", uncertainty_mode="flag"),
        pages=[DocPage(page_id="page_001__single", source_spread="page_001",
                       subpage="single", width=200, height=100,
                       image_asset="document_assets/page_001__single.png", blocks=[b0, b1])],
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
            # the flagged word "wrold" is the 3rd word box (Title, hello, wrold)
            boxes = pg.query_selector_all("#ovWords .wbox")
            assert len(boxes) == 3
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
