"""Unit tests for tools.calibrate_hover — the pure threshold-fitting logic.

Run with pytest, or directly: ``python -m tools.tests.test_calibrate_hover``.
Every input here has an answer known by hand.
"""

from __future__ import annotations

import math

import pytest

from tools.calibrate_hover import (
    Frame,
    fit_thresholds,
    parse_frame_log,
    pass_rate,
    percentile,
    simulate_gate,
    summarize,
)

HEADER = "timestamp_ms,sharpness,stability,passes,streak,command"


def frames(n: int, sharp: float, stab: float, start: int = 0, step: int = 33) -> list[Frame]:
    return [Frame(start + i * step, sharp, stab, False, 0, "none") for i in range(n)]


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_parses_rows_and_types():
    log = parse_frame_log(f"{HEADER}\n1000,62.5,3.25,1,4,none\n1033,12.0,40.0,0,0,finalize\n")
    assert [f.timestamp_ms for f in log.frames] == [1000, 1033]
    assert log.frames[0].sharpness == 62.5
    assert log.frames[0].passes is True
    assert log.frames[1].command == "finalize"
    assert log.dropped == 0


def test_drops_the_sentinel_stability_warmup_frame():
    """The first scored frame has no predecessor and reports Double.MAX_VALUE;
    keeping it would drag every stability percentile to infinity."""
    log = parse_frame_log(f"{HEADER}\n0,50.0,1.7976931348623157E308,0,0,none\n33,50.0,2.0,1,1,none\n")
    assert log.warmup_skipped == 1
    assert [f.stability for f in log.frames] == [2.0]


def test_reads_the_truncation_footer():
    log = parse_frame_log(f"{HEADER}\n0,50.0,2.0,1,1,none\n# dropped_rows,17\n")
    assert log.dropped == 17


def test_rejects_a_file_that_is_not_a_frame_log():
    with pytest.raises(ValueError, match="header"):
        parse_frame_log("a,b,c\n1,2,3\n")


def test_rejects_a_short_row():
    with pytest.raises(ValueError, match="6 columns"):
        parse_frame_log(f"{HEADER}\n1000,62.5,3.25\n")


# --------------------------------------------------------------------------
# Distributions
# --------------------------------------------------------------------------


def test_percentile_interpolates_and_handles_edges():
    values = [0.0, 10.0, 20.0, 30.0, 40.0]
    assert percentile(values, 0) == 0.0
    assert percentile(values, 100) == 40.0
    assert percentile(values, 50) == 20.0
    assert percentile(values, 25) == 10.0
    assert math.isnan(percentile([], 50))
    assert percentile([7.0], 90) == 7.0


def test_summarize_reports_every_band():
    stats = summarize([float(i) for i in range(101)])
    assert stats["n"] == 101
    assert stats["min"] == 0.0
    assert stats["max"] == 100.0
    assert stats["p50"] == 50.0


def test_pass_rate_needs_both_thresholds_met():
    fs = frames(1, sharp=50.0, stab=2.0) + frames(1, sharp=50.0, stab=99.0) + frames(1, sharp=1.0, stab=2.0)
    assert pass_rate(fs, 40.0, 6.0) == pytest.approx(1 / 3)
    assert math.isnan(pass_rate([], 40.0, 6.0))


# --------------------------------------------------------------------------
# Fitting
# --------------------------------------------------------------------------


def test_fit_separates_two_clean_populations():
    fit = fit_thresholds(frames(100, 80.0, 2.0), frames(100, 15.0, 25.0))
    assert fit.separates
    assert fit.steady_pass_rate == 1.0
    assert fit.moving_pass_rate == 0.0
    assert fit.sharpness_threshold <= 80.0
    assert fit.stability_threshold >= 2.0


def test_fit_reports_failure_when_the_metric_cannot_separate():
    """Identical populations: no pair can keep the moving frames out. The tool
    must say so rather than return a threshold that fires during motion."""
    same = frames(100, 50.0, 3.0)
    fit = fit_thresholds(same, list(same))
    assert not fit.separates
    assert "overlap" in fit.note


def test_fit_respects_the_false_fire_budget():
    steady = frames(100, 80.0, 2.0)
    # A tenth of the "moving" frames are actually indistinguishable from steady.
    moving = frames(90, 15.0, 25.0) + frames(10, 80.0, 2.0)
    strict = fit_thresholds(steady, moving, max_false_fire=0.0)
    assert not strict.separates
    loose = fit_thresholds(steady, moving, max_false_fire=0.10)
    assert loose.separates
    assert loose.moving_pass_rate <= 0.10


def test_fit_requires_both_logs():
    with pytest.raises(ValueError):
        fit_thresholds(frames(10, 80.0, 2.0), [])


# --------------------------------------------------------------------------
# Gate simulation (mirrors HoverGateTest.kt's expectations)
# --------------------------------------------------------------------------


def test_simulation_waits_for_the_streak_then_throttles():
    sim = simulate_gate(frames(300, 80.0, 2.0), 40.0, 6.0)
    # 8th passing frame at t=231 opens it; then one per 400ms up to the cap.
    assert sim.fired_at_ms[:4] == [231, 660, 1089, 1518]


def test_simulation_fires_nothing_one_frame_short_of_the_streak():
    assert simulate_gate(frames(7, 80.0, 2.0), 40.0, 6.0).captures == 0


def test_simulation_fires_nothing_when_frames_never_pass():
    sim = simulate_gate(frames(300, 15.0, 25.0), 40.0, 6.0)
    assert sim.captures == 0
    assert sim.bursts == 0


def test_a_broken_hover_ends_the_burst():
    fs = frames(20, 80.0, 2.0) + frames(20, 15.0, 25.0, start=20 * 33)
    sim = simulate_gate(fs, 40.0, 6.0)
    assert sim.bursts == 1
    assert sim.captures >= 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
