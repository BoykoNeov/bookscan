"""Tests for pipeline.pdf_text_layer — an imported PDF's hidden text as a second
opinion that can only ADD a marker (plan Slice 3, RESULTS 2026-09-24).

The rule's fidelity to the MEASURED rule is checked by replaying it on the audited
pages (``W:/temp/claude/pdf_textlayer/replay_shipped_rule.py``: 71/71 labelled
sites, every page's coverage and counts identical). These tests pin its pieces.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import pdf_text_layer as TL
from pipeline import stage06_uncertainty as S6
from pipeline.page_model import BBox, Block, BlockType, Word

FILLER = [f"word{i}" for i in range(200)]       # enough agreeing text to clear the floors


def _w(text: str, conf: float = 96.0) -> Word:
    return Word(text=text, bbox=BBox(x=0, y=0, w=10, h=10), conf=conf)


def _page(*blocks: list[str], orders: list[int | None] | None = None) -> dict:
    orders = orders or list(range(len(blocks)))
    return {"name": "single.png", "blocks": [
        Block(id=i, type=BlockType.PARAGRAPH, bbox=BBox(x=0, y=0, w=1, h=1),
              reading_order=o, words=[_w(t) for t in texts])
        for i, (texts, o) in enumerate(zip(blocks, orders))]}


def _texts(words) -> list[str]:
    return [w.text if hasattr(w, "text") else w["text"] for w in words]


# ------------------------------------------------------------ tokens and order
def test_line_end_marks_and_hyphens_join_like_the_measurement():
    toks = TL.prep_tokens([("oxy\u00ad", 0), ("gen", 1), ("per\u00ac", 2), ("haps", 3),
                           ("\ufb01eld", 4), ("well-", 5), ("Known", 6), ("--", 7)])
    assert [t["norm"] for t in toks] == ["oxygen", "perhaps", "field", "well", "known"]
    assert toks[0]["refs"] == [0, 1] and toks[2]["refs"] == [4]


def test_page_words_follow_reading_order_on_models_and_on_json():
    pg = _page(["c"], ["a"], ["b"], orders=[2, 0, 1])
    assert _texts(TL.page_words([pg])) == ["a", "b", "c"]
    as_json = {"blocks": [b.model_dump(mode="json") for b in pg["blocks"]]}
    as_json["blocks"].append({"reading_order": None, "words": [{"text": "z"}]})
    as_json["blocks"].reverse()
    assert _texts(TL.page_words([as_json])) == ["a", "b", "c", "z"]   # unordered last


# ------------------------------------------------------------ the rule
def test_a_one_for_one_disagreement_marks_that_word_only():
    words = [_w(t) for t in FILLER + ["O2", "was", "measured"]]
    chk = TL.check(words, FILLER + ["02", "was", "measured"])
    assert _texts(words[i] for i in chk.marked) == ["O2"]
    assert len(chk.sites) == 1 and chk.coverage > 0.99


def test_a_hyphen_joined_token_marks_every_word_in_it():
    words = [_w(t) for t in FILLER + ["sus-", "pended"]]
    chk = TL.check(words, FILLER + ["suspendod"])
    assert _texts(words[i] for i in chk.marked) == ["sus-", "pended"]


def test_a_many_to_one_disagreement_is_counted_never_marked():
    words = [_w(t) for t in FILLER + ["in", "to"]]
    chk = TL.check(words, FILLER + ["into"])
    assert chk.marked == set() and chk.other_replace == 1


def test_agreement_marks_nothing_and_nothing_here_can_clear_a_flag():
    words = [_w(t, conf=10.0) for t in FILLER]          # all low confidence
    chk = TL.check(words, list(FILLER))
    assert chk.marked == set()
    # the check returns only marks to ADD; a flagged word stays flagged
    assert all(S6.is_uncertain(w, 50.0) for w in words)


def test_abstains_outside_the_measured_population():
    words = [_w(t) for t in FILLER + ["O2"]]
    assert "outside the measured" in TL.check(words, FILLER + ["02"], language="deu").abstained
    assert TL.check(words, FILLER + ["02"], language="eng+deu").marked  # English is in it
    short = TL.check(words[-50:], FILLER[-49:] + ["02"])
    assert short.marked == set() and "50 words" in short.abstained
    unrelated = TL.check(words, [f"other{i}" for i in range(201)])
    assert unrelated.marked == set() and "coverage" in unrelated.abstained
    off = TL.check(words, FILLER + ["02"], dict(TL.DEFAULTS, enabled=False))
    assert off.marked == set() and "disabled" in off.abstained


def test_the_floor_keeps_the_lowest_measured_page_inside():
    """D2 page 201 matched 0.4286; a floor at its rounded 0.429 would drop it."""
    assert TL.DEFAULTS["min_coverage"] < 3 / 7


# ------------------------------------------------------------ the file and Stage 05
def test_a_phone_page_has_no_layer_and_nothing_happens(tmp_path: Path):
    pg = _page(FILLER)
    assert TL.apply(tmp_path, [pg], {}, "eng") == (None, [])
    assert not any(w.layer_disagree for w in TL.page_words([pg]))


def test_a_corrupt_layer_file_is_reported_and_marks_nothing(tmp_path: Path):
    (tmp_path / TL.LAYER_FILE).write_text("{not json", encoding="utf-8")
    pg = _page(FILLER)
    meta, notes = TL.apply(tmp_path, [pg], {}, "eng")
    assert meta is None and "unreadable" in notes[0]
    (tmp_path / TL.LAYER_FILE).write_text(json.dumps({"words": "abc"}), encoding="utf-8")
    assert TL.apply(tmp_path, [pg], {}, "eng")[0] is None


def test_apply_marks_the_words_in_place_across_sub_pages(tmp_path: Path):
    left, right = _page(FILLER[:120]), _page(FILLER[120:] + ["cxygen"])
    right["name"] = "right.png"
    TL.write_layer(tmp_path, FILLER + ["oxygen"], pdf_name="x.pdf", pdf_page=3)
    meta, notes = TL.apply(tmp_path, [left, right], {}, "eng")
    marked = [w.text for w in TL.page_words([left, right]) if w.layer_disagree]
    assert marked == ["cxygen"]
    assert meta["words_marked"] == 1 and meta["abstained"] == "" and "1 word(s)" in notes[0]


def test_config_can_narrow_the_rule(tmp_path: Path):
    TL.write_layer(tmp_path, FILLER + ["oxygen"], pdf_name="x.pdf", pdf_page=1)
    pg = _page(FILLER + ["cxygen"])
    meta, _ = TL.apply(tmp_path, [pg], {"pdf_text_layer": {"enabled": False}}, "eng")
    assert meta["words_marked"] == 0 and meta["abstained"]


# ------------------------------------------------------------ Stage 06
def test_stage06_flags_a_confident_word_the_layer_disputes():
    w = _w("cxygen", conf=97.0)
    assert S6.decide(w, 75.0, "flag").value == "keep"
    w.layer_disagree = True
    assert S6.is_uncertain(w, 75.0)
    assert S6.decide(w, 75.0, "flag").value == "flag"
    assert S6.decide(w, 75.0, "best_guess").value == "keep"
