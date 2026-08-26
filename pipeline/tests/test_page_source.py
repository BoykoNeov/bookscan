"""Unit tests for pipeline.page_source — per-page frame selection.

Pure-logic tests on synthetic spreads with a hand-known answer: no photos, no
Tesseract, no dewarp. What they pin is the part that decides what ships — the
bar, the eligibility rule, and the promise that with the option off nothing
changes at all — not the expensive OCR probe, which is measured on real
fixtures by ``tools/perpage_choice_probe.py``.

Run with pytest, or directly:
    python -m pipeline.tests.test_page_source
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline import page_source as PS
from pipeline.stage02_split import run
from pipeline.tests.test_stage02_split import _two_page_spread


def _spread(gutter: int = 1000, w: int = 2000, h: int = 1500) -> np.ndarray:
    return np.dstack([_two_page_spread(w=w, h=h, gutter=gutter)] * 3)


def _single(w: int = 2000, h: int = 1500) -> np.ndarray:
    """One wide text block — the shipped detector finds no confident gutter."""
    img = np.full((h, w), 245, np.uint8)
    for y in range(int(h * 0.1), int(h * 0.9), 12):
        img[y:y + 6, int(w * 0.05):int(w * 0.95)] = 20
    return np.dstack([img] * 3)


def _score(frame: str, words: int, conf: float) -> PS.SideScore:
    return PS.SideScore(frame=frame, words_ge_80=words, mean_conf=conf,
                        n_words=words + 20)


P = dict(PS.DEFAULTS)


# --------------------------------------------------------------------------
# The bar
# --------------------------------------------------------------------------


def test_a_challenger_must_win_both_statistics():
    """More words bought with lower confidence is not a better photograph."""
    scores = [_score("anchor", 100, 90.0), _score("rival", 200, 89.0)]
    choice = PS.decide_side("left.png", "anchor", scores, P)
    assert choice.changed is False and choice.source == "anchor"
    assert "no challenger clears the bar" in choice.reason


def test_the_floor_is_the_churn_floor_and_is_not_rescaled_per_side():
    """60 is where the instrument stops meaning anything, so at 60 exactly the
    incumbent keeps the page — a strict inequality, and the same number a whole
    spread is judged by even though a side holds about half the words."""
    floor = PS.DEFAULTS["min_word_gain"]
    at_the_floor = [_score("anchor", 100, 90.0), _score("rival", 100 + floor, 95.0)]
    assert PS.decide_side("left.png", "anchor", at_the_floor, P).changed is False

    over = [_score("anchor", 100, 90.0), _score("rival", 100 + floor + 1, 95.0)]
    choice = PS.decide_side("left.png", "anchor", over, P)
    assert choice.changed is True and choice.source == "rival"
    assert "+61 words" in choice.reason and "+5.0" in choice.reason


def test_a_tie_keeps_the_anchor():
    scores = [_score("anchor", 142, 75.2), _score("rival", 142, 85.2)]
    assert PS.decide_side("right.png", "anchor", scores, P).changed is False


def test_the_losing_race_still_records_how_close_it_was():
    """A no-change decision that says nothing is indistinguishable from one that
    never ran — the margin has to be in the artifact."""
    scores = [_score("anchor", 100, 90.0), _score("rival", 137, 101.8)]
    reason = PS.decide_side("left.png", "anchor", scores, P).reason
    assert "+37 words" in reason and "+11.8 conf" in reason


def test_the_best_clearing_challenger_wins_not_the_first():
    scores = [_score("anchor", 100, 90.0), _score("ok", 200, 91.0),
              _score("better", 300, 90.5)]
    assert PS.decide_side("left.png", "anchor", scores, P).source == "better"


# --------------------------------------------------------------------------
# The knob
# --------------------------------------------------------------------------


def test_cheap_criteria_are_not_offered_and_the_error_says_why():
    """Sharpness is measured to pick the LOSER on the only race with headroom,
    so it must not be reachable by a config typo away from 'ocr'."""
    with pytest.raises(ValueError) as exc:
        PS.resolve_params({"per_page_source": {"mode": "sharp"}})
    assert "off | ocr" in str(exc.value)
    assert "chance" in str(exc.value)


def test_bare_yaml_off_is_a_boolean_and_is_accepted():
    """``mode: off`` in YAML 1.1 arrives as False, not as the string 'off'."""
    assert PS.resolve_params({"per_page_source": {"mode": False}})["mode"] == "off"


def test_bare_yaml_on_is_refused_rather_than_guessed():
    """The bool has one obvious meaning going OFF and none going on. Guessing
    'ocr' here would silently switch on a dewarp + Tesseract probe per spread."""
    with pytest.raises(ValueError):
        PS.resolve_params({"per_page_source": {"mode": True}})


def test_the_documented_bar_and_the_recorded_bar_are_the_same_number():
    """config.yaml, DEFAULTS and the artifact schema each name the churn floor;
    they must not be able to drift apart."""
    import yaml
    assert PS.SelectionResult(mode="off", incumbent="a").min_word_gain == \
        PS.DEFAULTS["min_word_gain"]
    shipped = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config.yaml").read_text(
            encoding="utf-8"))
    assert shipped["per_page_source"]["min_word_gain"] == PS.DEFAULTS["min_word_gain"]
    assert shipped["per_page_source"]["mode"] == "off", "must ship OFF"


def test_the_shipped_default_is_off():
    assert PS.resolve_params({})["mode"] == "off"


# --------------------------------------------------------------------------
# Eligibility — which frames may supply a page at all
# --------------------------------------------------------------------------


def _seed(td: Path, anchor: np.ndarray, frames: dict[str, np.ndarray],
          anchor_source: str) -> Path:
    """A page dir with Stage 00/01 artifacts, as the stages would leave them."""
    page_dir = td / "page_001"
    (page_dir / "01_fuse").mkdir(parents=True)
    (page_dir / "00_ingest").mkdir(parents=True)
    cv2.imwrite(str(page_dir / "01_fuse" / "anchor.png"), anchor)
    for name, img in frames.items():
        cv2.imwrite(str(page_dir / "00_ingest" / name), img)
    (page_dir / "01_fuse" / "fuse.json").write_text(json.dumps({
        "n_frames": len(frames), "anchor_source": anchor_source,
        "method": "sharpest", "fullspread_frames": sorted(frames), "closeups": [],
    }), encoding="utf-8")
    return page_dir


def test_a_candidate_that_does_not_split_cannot_be_a_page_source():
    """Its 'left page' would be an unknown fraction of the spread. This is the
    probe's pre-registered eligibility rule, in the shipped selector."""
    spread = _spread()
    with tempfile.TemporaryDirectory() as td:
        page_dir = _seed(Path(td), spread,
                         {"frame_00.png": spread, "frame_01.png": _single()},
                         "frame_00.png")
        warns: list[str] = []
        result, chosen = PS.select(page_dir, {}, P | {"mode": "ocr"}, spread, warns)
    assert chosen == {}
    assert any("frame_01.png: no confident gutter" in line
               for line in result.ineligible)
    assert any("candidate excluded" in w for w in warns)
    assert "no eligible challenger" in result.note


def test_a_missing_frame_is_reported_not_raised():
    spread = _spread()
    with tempfile.TemporaryDirectory() as td:
        page_dir = _seed(Path(td), spread, {"frame_00.png": spread},
                         "frame_00.png")
        # Stage 01 listed a second frame; Stage 00's file is not there.
        fuse = page_dir / "01_fuse" / "fuse.json"
        rec = json.loads(fuse.read_text(encoding="utf-8"))
        rec["fullspread_frames"] = ["frame_00.png", "frame_99.png"]
        fuse.write_text(json.dumps(rec), encoding="utf-8")
        warns: list[str] = []
        result, chosen = PS.select(page_dir, {}, P | {"mode": "ocr"}, spread, warns)
    assert chosen == {}
    assert any("frame_99.png: frame not in 00_ingest/" in line
               for line in result.ineligible)


def test_a_single_page_anchor_has_no_sides_to_choose_between():
    single = _single()
    with tempfile.TemporaryDirectory() as td:
        page_dir = _seed(Path(td), single,
                         {"frame_00.png": single, "frame_01.png": _spread()},
                         "frame_00.png")
        warns: list[str] = []
        result, chosen = PS.select(page_dir, {}, P | {"mode": "ocr"}, single, warns)
    assert chosen == {}
    assert "no confident gutter" in result.note
    assert result.sides == []


def test_one_frame_means_nothing_to_choose_between_and_says_so():
    spread = _spread()
    with tempfile.TemporaryDirectory() as td:
        page_dir = _seed(Path(td), spread, {"frame_00.png": spread},
                         "frame_00.png")
        warns: list[str] = []
        result, chosen = PS.select(page_dir, {}, P | {"mode": "ocr"}, spread, warns)
    assert chosen == {} and "nothing to choose between" in result.note
    assert any("nothing to choose between" in w for w in warns)


def test_max_candidates_reports_what_it_dropped():
    """A silent cap reads as 'everything was considered' when it was not."""
    spread = _spread()
    frames = {f"frame_{i:02d}.png": spread for i in range(4)}
    with tempfile.TemporaryDirectory() as td:
        page_dir = _seed(Path(td), spread, frames, "frame_00.png")
        warns: list[str] = []
        result, _ = PS.select(page_dir, {},
                              P | {"mode": "ocr", "max_candidates": 1}, spread,
                              warns)
    assert any("2 further frame(s) not scored" in line for line in result.ineligible)


# --------------------------------------------------------------------------
# Off is off
# --------------------------------------------------------------------------


def test_mode_off_reads_no_candidate_and_records_the_anchor_as_the_source():
    """The default path must not touch 00_ingest at all: Stage 02's documented
    input is 01_fuse/anchor.png, and the exception exists only for 'ocr' mode."""
    spread = _spread()
    with tempfile.TemporaryDirectory() as td:
        page_dir = _seed(Path(td), spread,
                         {"frame_00.png": spread, "frame_01.png": _spread(1100)},
                         "frame_00.png")
        # Remove the ingest folder entirely: with the mode off nothing may look.
        for f in (page_dir / "00_ingest").iterdir():
            f.unlink()
        (page_dir / "00_ingest").rmdir()

        result = run(page_dir, {})
    assert result.per_page_source is None
    assert [p.source for p in result.pages] == ["01_fuse/anchor.png"] * 2
    assert all(p.gutter_x == result.gutter_x for p in result.pages)


def _run() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print(f"{len(fns)} page_source tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
