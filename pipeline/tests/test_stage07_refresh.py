"""Tests for the Stage 07 additions of v0.2.0: refreshing one spread inside an
existing document, a failed assemble leaving the old document whole, and the
pages an assemble leaves out being named.

The property that matters most is the first one stated the other way round:
**a refresh of spread B must leave spread A byte-for-byte as the operator saved
it** — text corrections, structure edits, settings, assets and all.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline.page_model import Block, Document, Word
from pipeline import stage07_assemble as S7
from pipeline.stage06_uncertainty import ResolvedPage, UncertaintyResult
from pipeline.tests.test_stage07_assemble import CFG, _build_job


def _add_page(job: Path, name: str, text: str = "Milano", mode: str = "flag",
              lang: str = "ita", size: tuple[int, int] = (200, 120)) -> Path:
    """Write (or overwrite — that is what a re-run does) one single-subpage
    page folder holding one paragraph of one word."""
    page = job / name
    for sub in ("03_dewarp", "06_uncertain", "05_ocr"):
        (page / sub).mkdir(parents=True, exist_ok=True)
    (page / "05_ocr" / "meta.json").write_text(
        json.dumps({"params": {"language": lang}}), encoding="utf-8")
    w, h = size
    cv2.imwrite(str(page / "03_dewarp" / "single.png"),
                np.full((h, w, 3), 255, np.uint8))
    blocks = [Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": w, "h": h},
                    reading_order=0,
                    words=[Word(text=text, bbox={"x": 10, "y": 10, "w": 40, "h": 20},
                                conf=90.0, decision="keep", block_id=0)])]
    resolved = UncertaintyResult(
        mode=mode, threshold=75.0, threshold_raw=80.0, flag_rate_target=0.1,
        conf_floor=45.0, conf_ceiling=75.0, scored_words=1,
        pages=[ResolvedPage(name="single.png", width=w, height=h,
                            blocks=blocks, patches=[])])
    (page / "06_uncertain" / "resolved.json").write_text(
        resolved.model_dump_json(indent=2), encoding="utf-8")
    return page


def _load(job: Path) -> Document:
    return Document.model_validate_json(
        (job / "document.json").read_text(encoding="utf-8"))


def _save(job: Path, doc: Document) -> None:
    (job / "document.json").write_text(doc.model_dump_json(indent=2),
                                       encoding="utf-8")


def _edited_two_page_job(tmp_path: Path) -> Path:
    """Two spreads assembled, then page_001 corrected by hand and a translation
    target set — the document a real operator would be protecting."""
    job = _build_job(tmp_path)
    _add_page(job, "page_002", "Milano")
    S7.run(job, CFG)
    d = _load(job)
    w = d.pages[0].blocks[0].words[0]
    w.text, w.edited = "ROMA", True
    d.settings.target_language = "eng"
    _save(job, d)
    return job


# --- refresh ---------------------------------------------------------------


def test_refresh_keeps_every_other_page_and_the_settings(tmp_path: Path):
    job = _edited_two_page_job(tmp_path)
    before = _load(job)
    _add_page(job, "page_002", "Torino")              # the page was re-run

    # page_001 carries edits, page_002 does not: no --force needed.
    doc = S7.run(job, CFG, only_spreads=["page_002"])

    assert [p.page_id for p in doc.pages] == ["page_001__single", "page_002__single"]
    assert doc.pages[0] == before.pages[0]            # untouched, edit and all
    assert doc.pages[0].blocks[0].words[0].text == "ROMA"
    assert doc.settings == before.settings            # translation target kept
    assert doc.pages[1].blocks[0].words[0].text == "Torino"
    assert doc.pages[1].blocks[0].words[0].text_ocr == "Torino"
    assert _load(job) == doc                          # and that is what is on disk
    for pg in doc.pages:
        assert (job / pg.image_asset).exists()
    assert not (job / S7.STAGING_DIRNAME).exists()


def test_refresh_refuses_only_when_the_refreshed_spread_has_edits(tmp_path: Path):
    job = _edited_two_page_job(tmp_path)
    _add_page(job, "page_001", "Roma2")
    with pytest.raises(RuntimeError, match="page_001.*carry edits"):
        S7.run(job, CFG, only_spreads=["page_001"])
    assert _load(job).pages[0].blocks[0].words[0].text == "ROMA"   # nothing lost

    doc = S7.run(job, CFG, only_spreads=["page_001"], force=True)
    assert doc.pages[0].blocks[0].words[0].text == "Roma2"
    assert doc.pages[0].blocks[0].words[0].edited is False
    assert doc.settings.target_language == "eng"      # force is spread-scoped


def test_refresh_inserts_a_spread_scanned_after_the_first_assemble(tmp_path: Path):
    job = _build_job(tmp_path)                        # page_001
    _add_page(job, "page_003", "Bari")
    S7.run(job, CFG)
    _add_page(job, "page_002", "Pisa")                # arrives late
    doc = S7.run(job, CFG, only_spreads=["page_002"])
    assert [p.source_spread for p in doc.pages] == ["page_001", "page_002", "page_003"]


def test_refresh_replaces_assets_of_that_spread_only(tmp_path: Path):
    job = _edited_two_page_job(tmp_path)
    assets = job / S7.ASSETS_DIRNAME
    (assets / "page_002__single__stale.png").write_bytes(b"old")   # e.g. an old hires cut
    keep = (assets / "page_001__single.png").read_bytes()
    _add_page(job, "page_002", "Torino", size=(300, 150))
    S7.run(job, CFG, only_spreads=["page_002"])
    assert not (assets / "page_002__single__stale.png").exists()
    assert (assets / "page_001__single.png").read_bytes() == keep
    assert cv2.imread(str(assets / "page_002__single.png")).shape[:2] == (150, 300)


def test_refresh_needs_a_document_and_a_finished_page(tmp_path: Path):
    job = _build_job(tmp_path)
    with pytest.raises(RuntimeError, match="assemble the whole job first"):
        S7.run(job, CFG, only_spreads=["page_001"])
    S7.run(job, CFG)
    (job / "page_009").mkdir()
    with pytest.raises(RuntimeError, match="cannot refresh"):
        S7.run(job, CFG, only_spreads=["page_009"])


def test_refresh_appends_to_the_meta_instead_of_replacing_it(tmp_path: Path):
    job = _edited_two_page_job(tmp_path)
    S7.run(job, CFG, only_spreads=["page_002"])
    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    assert meta["params"]["pages"] == 2               # the full assemble's record
    assert [r["params"]["refreshed_spreads"] for r in meta["params"]["refreshes"]] \
        == [["page_002"]]


# --- a failed assemble leaves the old document whole -------------------------


def test_failed_assemble_keeps_the_previous_document_and_its_assets(tmp_path: Path):
    job = _build_job(tmp_path)
    _add_page(job, "page_002", "Milano")
    S7.run(job, CFG)
    doc_bytes = (job / "document.json").read_bytes()
    (job / "page_002" / "03_dewarp" / "single.png").unlink()   # page 2 now breaks

    with pytest.raises(RuntimeError, match="missing dewarp image"):
        S7.run(job, CFG)

    assert (job / "document.json").read_bytes() == doc_bytes
    for pg in _load(job).pages:                       # before v0.2.0: both gone
        assert (job / pg.image_asset).exists()


# --- pages left out are named ----------------------------------------------


def test_missing_and_stale_pages_are_reported(tmp_path: Path):
    job = _build_job(tmp_path)
    (job / "page_002" / "raw").mkdir(parents=True)    # uploaded, never finished
    (job / "page_003").mkdir()
    (job / "page_003" / "run_all.json").write_text(
        json.dumps({"ok": False, "failed_stage": "03_dewarp"}), encoding="utf-8")
    (job / "page_001" / "run_all.json").write_text(   # re-run failed, old 06 left
        json.dumps({"ok": False, "failed_stage": "04_layout"}), encoding="utf-8")

    r = S7.page_readiness(job)
    assert r["missing"] == [{"page": "page_002", "failed_stage": None},
                            {"page": "page_003", "failed_stage": "03_dewarp"}]
    assert r["stale"] == [{"page": "page_001", "failed_stage": "04_layout"}]

    S7.run(job, CFG)
    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    assert meta["params"]["pages_missing"] == r["missing"]
    text = " ".join(meta["warnings"])
    assert "page_002 is NOT in the document" in text
    assert "page_003 is NOT in the document" in text and "03_dewarp" in text
    assert "page_001: its last run FAILED at 04_layout" in text


def test_page_image_and_word_boxes_from_different_runs_are_flagged(tmp_path: Path):
    job = _build_job(tmp_path)
    cv2.imwrite(str(job / "page_001" / "03_dewarp" / "single.png"),
                np.full((90, 150, 3), 255, np.uint8))  # Stage 03 re-ran, 06 did not
    S7.run(job, CFG)
    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    assert any("150x90" in w and "200x120" in w for w in meta["warnings"])


def test_document_language_is_the_majority_not_the_alphabetical_first(tmp_path: Path):
    job = _build_job(tmp_path, lang="ita")
    _add_page(job, "page_002", lang="ita")
    _add_page(job, "page_003", lang="eng")            # one page read in the default
    assert S7.run(job, CFG).settings.source_language == "ita"


def test_page_1000_comes_after_page_999_not_after_page_100(tmp_path: Path):
    """A 1,000+-page PDF import: folder names sort as text past three digits."""
    job = _build_job(tmp_path)                        # page_001
    for name in ("page_100", "page_101", "page_999", "page_1000"):
        _add_page(job, name)
    doc = S7.run(job, CFG)
    assert [p.source_spread for p in doc.pages] == [
        "page_001", "page_100", "page_101", "page_999", "page_1000"]
    _add_page(job, "page_1001")
    doc = S7.run(job, CFG, only_spreads=["page_1001"])
    assert doc.pages[-1].source_spread == "page_1001"
    _add_page(job, "page_500")
    doc = S7.run(job, CFG, only_spreads=["page_500"])
    assert [p.source_spread for p in doc.pages][3] == "page_500"


# --- carrying hand edits across a refresh (v0.3.0) ---------------------------
#
# The rule under test: an edit is carried onto the re-run page only on an EXACT
# match, every edit that is not carried is REPORTED, and a carry that would drop
# anything refuses and changes nothing on disk unless forced.

from pipeline.editor import normalize_edits
from pipeline.page_model import BBox, BlockRef, BlockType, PairSource


def _w(text: str, x: int, y: int, conf: float = 90.0, bid: int = 0) -> Word:
    return Word(text=text, bbox={"x": x, "y": y, "w": 40, "h": 20}, conf=conf,
                decision="keep", block_id=bid)


def _rich_blocks(shift_alpha: int = 0, id_offset: int = 0,
                 extra_block: bool = False) -> list[Block]:
    """Two paragraphs, a picture with its caption, and an 8-word block read at
    confidence 20 that the unreadable-panel pass turns into a picture."""
    o = id_offset
    blocks = [
        Block(id=o + 0, type="paragraph", bbox={"x": 0, "y": 0, "w": 200, "h": 40},
              reading_order=0, words=[_w("Alpha", 10 + shift_alpha, 10, bid=o),
                                      _w("Beta", 60, 10, bid=o)]),
        Block(id=o + 1, type="paragraph", bbox={"x": 0, "y": 45, "w": 200, "h": 30},
              reading_order=1, words=[_w("Gamma", 10, 50, bid=o + 1),
                                      _w("Delta", 60, 50, bid=o + 1)]),
        Block(id=o + 2, type="figure", bbox={"x": 0, "y": 80, "w": 100, "h": 40},
              reading_order=2),
        Block(id=o + 3, type="caption", bbox={"x": 100, "y": 80, "w": 100, "h": 40},
              reading_order=3, words=[_w("Sopra", 110, 90, bid=o + 3)]),
        Block(id=o + 4, type="paragraph", bbox={"x": 0, "y": 125, "w": 200, "h": 30},
              reading_order=4,
              words=[_w(f"x{i}", 2 + 24 * i, 130, conf=20.0, bid=o + 4)
                     for i in range(8)]),
    ]
    if extra_block:
        blocks.append(Block(id=o + 5, type="paragraph",
                            bbox={"x": 0, "y": 160, "w": 200, "h": 15},
                            reading_order=5, words=[_w("Epsilon", 10, 160, bid=o + 5)]))
    return blocks


def _write_page(job: Path, name: str,
                pages: list[tuple[str, int, int, list[Block]]]) -> None:
    """Write (or overwrite: a re-run) a page folder from (subpage file, w, h, blocks)."""
    page = job / name
    for sub in ("03_dewarp", "06_uncertain", "05_ocr"):
        (page / sub).mkdir(parents=True, exist_ok=True)
    for old in (page / "03_dewarp").glob("*.png"):
        old.unlink()
    (page / "05_ocr" / "meta.json").write_text(
        json.dumps({"params": {"language": "ita"}}), encoding="utf-8")
    rp = []
    for fname, w, h, blocks in pages:
        cv2.imwrite(str(page / "03_dewarp" / fname), np.full((h, w, 3), 255, np.uint8))
        rp.append(ResolvedPage(name=fname, width=w, height=h, blocks=blocks, patches=[]))
    resolved = UncertaintyResult(
        mode="flag", threshold=75.0, threshold_raw=80.0, flag_rate_target=0.1,
        conf_floor=45.0, conf_ceiling=75.0, scored_words=1, pages=rp)
    (page / "06_uncertain" / "resolved.json").write_text(
        resolved.model_dump_json(indent=2), encoding="utf-8")


def _rich(job: Path, size: tuple[int, int] = (200, 180), **kw) -> None:
    _write_page(job, "page_001", [("single.png", size[0], size[1], _rich_blocks(**kw))])


def _every_kind_of_edit(job: Path) -> Document:
    """Assemble two spreads, then edit page_001 the way the editor would: a word
    correction, a type change, a text override, a reorder, a hand pair, and a
    delete on the block the panel pass turned into a picture. Saved through the
    editor's own normalize_edits, as a real save is."""
    _rich(job)
    _add_page(job, "page_002", "Milano")
    S7.run(job, CFG)
    d = _load(job)
    pg = d.pages[0]
    by = {b.id: b for b in pg.blocks}
    assert by[4].type_auto.value == "figure" and by[4].type_promoted   # panel pass fired
    by[0].words[0].text = "ALPHA"
    by[0].type = BlockType.HEADING
    by[1].text = "Translated paragraph"
    by[0].reading_order, by[1].reading_order = 1, 0                    # a drag
    by[3].figure_ref = BlockRef(page_id=pg.page_id, block_id=2)
    by[3].pair_source = PairSource.USER
    by[4].deleted = True
    d.settings.target_language = "eng"
    d = normalize_edits(d)
    _save(job, d)
    return _load(job)


def _disk(job: Path) -> dict[str, bytes]:
    out = {"document.json": (job / "document.json").read_bytes(),
           "document.meta.json": (job / "document.meta.json").read_bytes()}
    for p in sorted((job / S7.ASSETS_DIRNAME).iterdir()):
        out[p.name] = p.read_bytes()
    return out


def test_identical_rerun_carries_every_kind_of_edit(tmp_path: Path):
    job = tmp_path / "job"
    saved = _every_kind_of_edit(job)
    _rich(job)                                         # re-run, same result
    doc = S7.run(job, CFG, only_spreads=["page_001"], carry=True)
    assert doc == saved                                # every edit, exactly as saved
    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    rep = meta["params"]["refreshes"][-1]["params"]["carry_edits"]
    assert rep["dropped"] == []
    assert rep["words_carried"] == 1 and rep["orders_carried"] == 1
    assert rep["blocks_carried"] == 4                  # type, text, pair, delete


def test_carry_without_edits_is_a_plain_refresh(tmp_path: Path):
    job = _build_job(tmp_path)
    _add_page(job, "page_002", "Milano")
    S7.run(job, CFG)
    _add_page(job, "page_002", "Torino")
    doc = S7.run(job, CFG, only_spreads=["page_002"], carry=True)
    assert doc.pages[1].blocks[0].words[0].text == "Torino"


def test_a_moved_word_refuses_and_changes_nothing_then_force_drops_only_it(
        tmp_path: Path):
    job = tmp_path / "job"
    saved = _every_kind_of_edit(job)
    before = _disk(job)
    _rich(job, shift_alpha=1)                          # one word box moved by 1 px

    with pytest.raises(S7.EditsWouldBeDropped) as ei:
        S7.run(job, CFG, only_spreads=["page_001"], carry=True)
    rep = ei.value.report
    assert [(d["kind"], d["text_ocr"], d["text"]) for d in rep["dropped"]] \
        == [("word", "Alpha", "ALPHA")]
    assert _disk(job) == before                        # byte-identical, assets too
    assert not (job / S7.STAGING_DIRNAME).exists()

    doc = S7.run(job, CFG, only_spreads=["page_001"], carry=True, force=True)
    by = {b.id: b for b in doc.pages[0].blocks}
    assert by[0].words[0].text == "Alpha" and not by[0].words[0].edited
    assert by[0].words[0].bbox.x == 11
    assert by[0].type.value == "heading" and by[1].text == "Translated paragraph"
    assert by[4].deleted and by[0].reading_order == 1
    assert doc.pages[1] == saved.pages[1]              # the other spread untouched
    assert doc.settings == saved.settings
    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    assert meta["params"]["refreshes"][-1]["params"]["carry_edits"]["words_dropped"] == 1


def test_provenance_is_never_changed_by_a_carry(tmp_path: Path):
    job = tmp_path / "job"
    _every_kind_of_edit(job)
    _rich(job, shift_alpha=1)
    doc = S7.run(job, CFG, only_spreads=["page_001"], carry=True, force=True)
    fresh = {b.id: b for b in _rich_blocks(shift_alpha=1)}
    for b in doc.pages[0].blocks:
        assert b.order_auto == fresh[b.id].reading_order
        assert [w.text_ocr for w in b.words] == [w.text for w in fresh[b.id].words]
    by = {b.id: b for b in doc.pages[0].blocks}
    assert by[0].type_auto.value == "paragraph" and by[4].type_auto.value == "figure"


def test_a_page_that_changed_size_carries_nothing(tmp_path: Path):
    job = tmp_path / "job"
    _every_kind_of_edit(job)
    _rich(job, size=(200, 190))
    with pytest.raises(S7.EditsWouldBeDropped):
        S7.run(job, CFG, only_spreads=["page_001"], carry=True)
    doc = S7.run(job, CFG, only_spreads=["page_001"], carry=True, force=True)
    assert not S7._page_has_edits(doc.pages[0])
    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    rep = meta["params"]["refreshes"][-1]["params"]["carry_edits"]
    assert rep["words_carried"] == rep["blocks_carried"] == rep["orders_carried"] == 0
    assert all("changed size" in d["why"] for d in rep["dropped"])
    assert {d["kind"] for d in rep["dropped"]} == {"word", "block", "order"}


def test_edits_on_a_page_that_vanished_are_reported_not_lost_in_silence(
        tmp_path: Path):
    """The re-run cut the spread into left and right: page_001__single is gone."""
    job = tmp_path / "job"
    _every_kind_of_edit(job)
    _write_page(job, "page_001", [("left.png", 200, 180, _rich_blocks()),
                                  ("right.png", 200, 180, _rich_blocks())])
    with pytest.raises(S7.EditsWouldBeDropped) as ei:
        S7.run(job, CFG, only_spreads=["page_001"], carry=True)
    rep = ei.value.report
    assert rep["words_dropped"] == 1 and rep["blocks_dropped"] == 4
    assert rep["orders_dropped"] == 1
    assert all(d["page_id"] == "page_001__single" and "not in the re-run" in d["why"]
               for d in rep["dropped"])


def test_a_hand_pair_follows_its_picture_to_a_new_block_id(tmp_path: Path):
    job = tmp_path / "job"
    _every_kind_of_edit(job)
    _rich(job, id_offset=10)                           # same boxes, ids renumbered
    doc = S7.run(job, CFG, only_spreads=["page_001"], carry=True)
    cap = next(b for b in doc.pages[0].blocks if b.id == 13)
    assert cap.pair_source is PairSource.USER
    assert cap.figure_ref == BlockRef(page_id="page_001__single", block_id=12)


def test_a_changed_block_set_drops_the_hand_order_but_keeps_the_rest(tmp_path: Path):
    job = tmp_path / "job"
    _every_kind_of_edit(job)
    _rich(job, extra_block=True)                       # the re-run found one more block
    with pytest.raises(S7.EditsWouldBeDropped) as ei:
        S7.run(job, CFG, only_spreads=["page_001"], carry=True)
    assert [d["kind"] for d in ei.value.report["dropped"]] == ["order"]
    doc = S7.run(job, CFG, only_spreads=["page_001"], carry=True, force=True)
    by = {b.id: b for b in doc.pages[0].blocks}
    assert [by[i].reading_order for i in range(6)] == [0, 1, 2, 3, 4, 5]   # automatic
    assert by[0].words[0].text == "ALPHA" and by[0].type.value == "heading"
    assert by[1].text == "Translated paragraph" and by[4].deleted


def test_a_split_block_is_reported_not_replayed(tmp_path: Path):
    job = tmp_path / "job"
    _every_kind_of_edit(job)
    d = _load(job)
    pg = d.pages[0]
    gamma_block = next(b for b in pg.blocks if b.id == 1)
    tail = gamma_block.words[1:]
    gamma_block.words = gamma_block.words[:1]
    gamma_block.bbox = BBox(x=10, y=50, w=40, h=20)
    gamma_block.structure_edited = True
    pg.blocks.append(Block(id=5, type="paragraph",
                           bbox={"x": 60, "y": 50, "w": 40, "h": 20},
                           reading_order=5, words=tail, structure_edited=True))
    _save(job, normalize_edits(d))
    _rich(job)
    with pytest.raises(S7.EditsWouldBeDropped) as ei:
        S7.run(job, CFG, only_spreads=["page_001"], carry=True)
    kinds = sorted((x["kind"], x.get("block_id") or -1) for x in ei.value.report["dropped"])
    assert ("block", 1) in kinds and ("block", 5) in kinds and ("order", -1) in kinds


def test_carry_is_for_a_refresh_only(tmp_path: Path):
    job = _build_job(tmp_path)
    S7.run(job, CFG)
    with pytest.raises(RuntimeError, match="refresh"):
        S7.run(job, CFG, carry=True)


def _surface_pages(order_swapped: bool, extra_block: bool = False):
    """An old page where the operator cleared the pipeline's surface mark on
    block 1 (and maybe reordered), and its re-run where the pipeline marks
    block 1 as surface again."""
    from pipeline.page_model import DocPage

    def blocks(surface: bool, edited: bool) -> list[Block]:
        out = []
        for i in range(2 + int(extra_block and not edited)):
            out.append(Block(id=i, type=BlockType.FIGURE,
                             bbox=BBox(x=0, y=50 * i, w=100, h=40),
                             reading_order=i, type_auto=BlockType.FIGURE,
                             order_auto=i))
        out[1].is_surface = surface
        if edited:
            out[1].structure_edited = True
            if order_swapped:
                out[0].reading_order, out[1].reading_order = 1, 0
                out[0].structure_edited = True
        return out

    def page(bl: list[Block]) -> DocPage:
        return DocPage(page_id="page_001__single", source_spread="page_001",
                       subpage="single", width=200, height=200,
                       image_asset="document_assets/page_001__single.png", blocks=bl)
    return [page(blocks(False, True))], [page(blocks(True, False))]


@pytest.mark.parametrize("order_swapped", [False, True])
def test_a_cleared_surface_mark_is_carried_not_silently_undone(order_swapped: bool):
    old, new = _surface_pages(order_swapped)
    out, rep = S7._carry_edits(old, new, ["page_001"])
    b1 = next(b for b in out[0].blocks if b.id == 1)
    assert b1.is_surface is False and b1.structure_edited
    assert rep["dropped"] == [] and rep["blocks_carried"] == 1


def test_a_cleared_surface_mark_on_a_changed_page_is_reported_as_itself():
    """The block set changed, so the order cannot carry; the cleared mark still
    matches and carries, and the loss reported is the order alone."""
    old, new = _surface_pages(order_swapped=True, extra_block=True)
    out, rep = S7._carry_edits(old, new, ["page_001"])
    b1 = next(b for b in out[0].blocks if b.id == 1)
    assert b1.is_surface is False
    assert [d["kind"] for d in rep["dropped"]] == ["order"]
