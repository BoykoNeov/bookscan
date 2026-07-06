"""Unit tests for pipeline.stage06_uncertainty pure decision logic — the adaptive
threshold (clip of a percentile between config rails), the uncertain->decision
mapping, the mode policy layer, word eligibility, and the small-sample fallback.

Hand-built Words with known confidences — no photos, no Tesseract. The two
load-bearing properties: (1) flag_rate is a TARGET that BENDS — a clean doc's
ceiling bites (flag fewer), a garbage doc's floor bites (flag more) — the
operating point moves with the distribution, so it is not a single hard cutoff;
(2) a real-text conf<=0 word is excluded from the percentile yet still decided
uncertain. Run with pytest, or directly:
    python -m pipeline.tests.test_stage06_uncertainty
"""

from __future__ import annotations

from pipeline.page_model import BBox, Word, WordDecision
from pipeline.stage06_uncertainty import (
    MIN_WORDS_FOR_PERCENTILE, adaptive_threshold, decide, is_scored,
    is_uncertain, resolve_mode, resolve_rails,
)

LO, HI, RATE = 45.0, 75.0, 0.10


def _w(text: str, conf: float) -> Word:
    return Word(text=text, conf=conf, bbox=BBox(x=0, y=0, w=10, h=10))


# ---- the adaptive threshold: rails bite in the pathological tails -----------


def test_clean_doc_ceiling_bites_flag_fewer_than_target():
    """A clean doc's p10 sits high (~90); the ceiling clamps the threshold to HI so
    good words aren't flagged — the effective flag rate is BELOW the target."""
    # 96% clean at conf 95, a thin bad tail of 4 -> p10 lands up in the clean bulk.
    confs = [95.0] * 96 + [30.0, 30.0, 30.0, 30.0]
    thr, raw = adaptive_threshold(confs, RATE, LO, HI)
    assert raw == 95.0                     # raw percentile is up in the clean bulk
    assert thr == HI                       # clamped down to the ceiling rail
    flagged = sum(c < thr for c in confs)
    assert flagged / len(confs) < RATE     # fewer than 10% — ceiling bit


def test_garbage_doc_floor_bites_flag_more_than_target():
    """A garbage doc's p10 sits very low; the floor clamps the threshold UP to LO,
    flagging MORE than the target — aggressive on junk, as intended."""
    confs = [15.0] * 60 + [90.0] * 40      # p10 well below LO
    thr, raw = adaptive_threshold(confs, RATE, LO, HI)
    assert raw < LO
    assert thr == LO                       # clamped up to the floor rail
    flagged = sum(c < thr for c in confs)
    assert flagged / len(confs) > RATE     # more than 10% — floor bit


def test_mid_doc_honors_target_between_rails():
    """When the raw percentile lands between the rails it is used verbatim and the
    effective rate tracks the target."""
    confs = [float(v) for v in range(1, 101)]   # uniform 1..100; p10 = 10.9
    thr, raw = adaptive_threshold(confs, 0.60, LO, HI)  # p60 ~= 60.4, inside rails
    assert LO < thr < HI
    assert abs(thr - raw) < 1e-9           # no clamp applied


def test_small_sample_falls_back_to_floor():
    """Below MIN_WORDS_FOR_PERCENTILE the percentile is unreliable -> fall back to
    the floor rail (raw reported as -1)."""
    confs = [10.0] * (MIN_WORDS_FOR_PERCENTILE - 1)
    thr, raw = adaptive_threshold(confs, RATE, LO, HI)
    assert thr == LO and raw == -1.0


def test_threshold_always_within_rails():
    for confs in ([100.0] * 50, [0.1] * 50, [50.0] * 50):
        thr, _ = adaptive_threshold(confs, RATE, LO, HI)
        assert LO <= thr <= HI


# ---- eligibility: empties / conf<=0 excluded from percentile, still decided --


def test_is_scored_excludes_empty_and_nonpositive_conf():
    assert is_scored(_w("word", 90.0))
    assert not is_scored(_w("   ", 90.0))     # whitespace
    assert not is_scored(_w("", 90.0))        # empty
    assert not is_scored(_w("word", 0.0))     # conf sentinel (Stage 05 clamps -1->0)


def test_nonpositive_conf_word_is_uncertain_despite_exclusion():
    """A real-text conf=0 word doesn't feed the percentile but IS flagged: 0 < any
    threshold >= floor, so the plain conf<threshold rule catches it naturally."""
    w = _w("garbled", 0.0)
    assert not is_scored(w)
    assert is_uncertain(w, LO)                 # 0 < 45
    assert decide(w, LO, "flag") is WordDecision.FLAG


# ---- decision + mode policy layer ------------------------------------------


def test_decide_keep_when_confident():
    assert decide(_w("clean", 96.0), 70.0, "flag") is WordDecision.KEEP
    assert decide(_w("clean", 96.0), 70.0, "patch") is WordDecision.KEEP


def test_mode_maps_uncertain_word():
    low = _w("shaky", 50.0)                    # below threshold 70
    assert decide(low, 70.0, "flag") is WordDecision.FLAG
    assert decide(low, 70.0, "patch") is WordDecision.PATCH
    assert decide(low, 70.0, "best_guess") is WordDecision.KEEP  # computed, not acted


def test_empty_token_is_inert_keep():
    assert decide(_w("   ", 5.0), 70.0, "patch") is WordDecision.KEEP


# ---- config resolution ------------------------------------------------------


def test_resolve_rails_from_config_and_defaults():
    cfg = {"uncertainty": {"flag_rate": 0.2, "conf_floor": 40, "conf_ceiling": 80}}
    assert resolve_rails(cfg) == (0.2, 40.0, 80.0)
    assert resolve_rails({}) == (0.10, 45.0, 75.0)          # defaults
    # swapped rails are normalized (floor <= ceiling)
    swapped = {"uncertainty": {"conf_floor": 80, "conf_ceiling": 40}}
    _, lo, hi = resolve_rails(swapped)
    assert lo == 40.0 and hi == 80.0


def test_resolve_mode_override_and_default():
    assert resolve_mode({}, None) == "flag"
    assert resolve_mode({"uncertainty": {"default_mode": "patch"}}, None) == "patch"
    assert resolve_mode({}, "best_guess") == "best_guess"
    try:
        resolve_mode({}, "bogus")
        assert False, "expected ValueError for unknown mode"
    except ValueError:
        pass


if __name__ == "__main__":
    import sys
    import traceback

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
