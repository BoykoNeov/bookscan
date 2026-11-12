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
