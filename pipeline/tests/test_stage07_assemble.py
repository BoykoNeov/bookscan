"""Tests for pipeline.stage07_assemble — the editable job-level document.

Builds a tiny synthetic job on disk (one spread, one subpage, a couple blocks,
one patch crop) and asserts the load-bearing properties of the editable format:
self-containment (image + crops copied, references relative and present),
per-word OCR provenance, reversible structure (type_auto/order_auto), the
owner's per-word flag-visibility rule, and the don't-clobber-edits guard.

Run with pytest, or directly:
    python -m pipeline.tests.test_stage07_assemble
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline.page_model import Block, Document, Word
from pipeline import stage07_assemble as S7
from pipeline.stage06_uncertainty import PatchRef, ResolvedPage, UncertaintyResult

CFG = {"reconstruct": {"fonts": ["Noto Serif"],
                       "strip_running_headers": True, "strip_page_numbers": False}}


def _word(text: str, x: int, conf: float, decision: str) -> Word:
    return Word(text=text, bbox={"x": x, "y": 10, "w": 40, "h": 20},
                conf=conf, decision=decision, block_id=0)


def _build_job(tmp: Path, mode: str = "flag", with_patch: bool = False,
               lang: str | None = "ita") -> Path:
    """A minimal one-subpage job that Stage 06 could have produced."""
    job = tmp / "job1"
    page = job / "page_001"
    (page / "03_dewarp").mkdir(parents=True)
    (page / "06_uncertain").mkdir(parents=True)
    if lang is not None:
        (page / "05_ocr").mkdir(parents=True)
        (page / "05_ocr" / "meta.json").write_text(
            json.dumps({"params": {"lang": lang}}), encoding="utf-8")

    cv2.imwrite(str(page / "03_dewarp" / "single.png"),
                np.full((120, 200, 3), 255, np.uint8))

    words = [_word("Roma", 10, 92.0, "keep"),
             _word("caput", 60, 40.0, mode if mode != "best_guess" else "keep")]
    blocks = [Block(id=0, type="paragraph", bbox={"x": 0, "y": 0, "w": 200, "h": 120},
                    reading_order=0, words=words)]

    patches = []
    if with_patch:
        (page / "06_uncertain" / "patches").mkdir()
        cv2.imwrite(str(page / "06_uncertain" / "patches" / "single_b0_w01.png"),
                    np.zeros((20, 40, 3), np.uint8))
        patches = [PatchRef(file="patches/single_b0_w01.png", text="caput",
                            conf=40.0, block_id=0, word_index=1,
                            bbox={"x": 60, "y": 10, "w": 40, "h": 20})]

    resolved = UncertaintyResult(
        mode=mode, threshold=75.0, threshold_raw=80.0, flag_rate_target=0.1,
        conf_floor=45.0, conf_ceiling=75.0, scored_words=2,
        pages=[ResolvedPage(name="single.png", width=200, height=120,
                            blocks=blocks, patches=patches)])
    (page / "06_uncertain" / "resolved.json").write_text(
        resolved.model_dump_json(indent=2), encoding="utf-8")
    return job


def test_assemble_is_self_contained(tmp_path: Path):
    job = _build_job(tmp_path)
    doc = S7.run(job, CFG)

    assert (job / "document.json").exists()
    assert (job / "document.meta.json").exists()
    assert len(doc.pages) == 1
    pg = doc.pages[0]
    assert pg.page_id == "page_001__single" and pg.subpage == "single"
    # image asset is a RELATIVE path under document_assets/ and really exists
    assert pg.image_asset == "document_assets/page_001__single.png"
    assert (job / pg.image_asset).exists()


def test_word_provenance_and_reversible_structure(tmp_path: Path):
    job = _build_job(tmp_path)
    doc = S7.run(job, CFG)
    blk = doc.pages[0].blocks[0]
    # structure auto-values preserved, nothing marked edited on a fresh assemble
    assert blk.type_auto == blk.type and blk.order_auto == blk.reading_order
    assert blk.structure_edited is False and blk.text is None
    for w in blk.words:
        assert w.text_ocr == w.text        # provenance seeded to the OCR read
        assert w.edited is False


def test_flag_visible_follows_per_word_edit(tmp_path: Path):
    job = _build_job(tmp_path)                 # 'caput' is decision=flag
    doc = S7.run(job, CFG)
    flagged = [w for w in doc.pages[0].blocks[0].words if w.text == "caput"][0]
    assert flagged.flag_visible is True        # marker shown before any edit
    edited = flagged.model_copy(update={"text": "capita", "edited": True})
    assert edited.flag_visible is False        # cleared once THIS word is edited


def test_patch_crops_copied_and_referenced(tmp_path: Path):
    job = _build_job(tmp_path, mode="patch", with_patch=True)
    doc = S7.run(job, CFG)
    patched = [w for pg in doc.pages for b in pg.blocks for w in b.words
               if w.patch_asset]
    assert len(patched) == 1
    ref = patched[0].patch_asset
    assert ref.startswith("document_assets/") and (job / ref).exists()
    assert doc.settings.uncertainty_mode == "patch"


def test_language_carried_from_ocr_meta(tmp_path: Path):
    job = _build_job(tmp_path, lang="ita")
    doc = S7.run(job, CFG)
    assert doc.settings.source_language == "ita"
    assert doc.settings.fonts == ["Noto Serif"]
    assert doc.settings.strip_page_numbers is False   # carried from config


def test_refuses_to_clobber_edits_without_force(tmp_path: Path):
    job = _build_job(tmp_path)
    S7.run(job, CFG)
    # simulate a user edit, save it back
    p = job / "document.json"
    d = Document.model_validate_json(p.read_text(encoding="utf-8"))
    d.pages[0].blocks[0].words[0].edited = True
    p.write_text(d.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="carries edits"):
        S7.run(job, CFG)                       # no --force -> refuse
    doc2 = S7.run(job, CFG, force=True)         # --force -> rebuild
    assert doc2.pages[0].blocks[0].words[0].edited is False


def test_order_mode_defaults_to_auto(tmp_path: Path):
    job = _build_job(tmp_path)
    doc = S7.run(job, CFG)
    assert doc.settings.order_mode == "auto"
    # a pristine auto-mode block never needs review, and nothing is confirmed
    blk = doc.pages[0].blocks[0]
    assert blk.order_confirmed is False
    assert blk.order_review_visible("auto") is False


def test_order_mode_review_persists_and_flags_blocks(tmp_path: Path):
    job = _build_job(tmp_path)
    doc = S7.run(job, CFG, order_mode="review")
    assert doc.settings.order_mode == "review"
    meta = json.loads((job / "document.meta.json").read_text(encoding="utf-8"))
    assert meta["params"]["order_mode"] == "review"
    # pristine review-mode blocks surface as needing review, but that alone is NOT
    # an "edit" — the doc stays re-assemblable until the user confirms/renumbers
    blk = doc.pages[0].blocks[0]
    assert blk.order_review_visible("review") is True
    assert S7._document_has_edits(doc) is False


def test_confirmed_order_protects_from_clobber(tmp_path: Path):
    job = _build_job(tmp_path)
    S7.run(job, CFG, order_mode="review")
    p = job / "document.json"
    d = Document.model_validate_json(p.read_text(encoding="utf-8"))
    d.pages[0].blocks[0].order_confirmed = True        # user accepted the auto order
    p.write_text(d.model_dump_json(indent=2), encoding="utf-8")
    with pytest.raises(RuntimeError, match="carries edits"):
        S7.run(job, CFG, order_mode="review")          # no --force -> refuse


def test_empty_job_raises(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(RuntimeError, match="no page folders"):
        S7.run(tmp_path / "empty", CFG)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
