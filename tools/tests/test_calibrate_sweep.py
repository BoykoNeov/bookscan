"""Unit tests for the sweep-gate replay.

The replay's job is to mirror ``SweepGate.kt`` statement for statement, so
these mirror ``SweepGateTest.kt``: if one of these fails and the Kotlin test
does not, the two have drifted and a number in ``docs/data/`` is describing a
rule the phone no longer runs.
"""

from __future__ import annotations

import pytest

from tools.calibrate_hover import STABILITY_SENTINEL, Frame
from tools.calibrate_sweep import (
    IDLE_STABILITY_FLOOR,
    MAX_FRAMES,
    sharp_pass_rate,
    simulate_sweep,
)


def frames(n: int, *, sharpness: float, stability: float, step_ms: int = 33,
           start_ms: int = 0) -> list[Frame]:
    return [
        Frame(timestamp_ms=start_ms + i * step_ms, sharpness=sharpness,
              stability=stability, passes=False, streak=0, command="none")
        for i in range(n)
    ]


def test_a_held_phone_fires_only_the_mandatory_first_shot():
    # 30 s of a perfectly steady hold. Every extra shot here would be a
    # duplicate of one patch out of a capped budget.
    res = simulate_sweep(frames(900, sharpness=900.0, stability=1.0))
    assert res.shots == 1
    assert res.fired_at_ms == (0,)


def test_the_rejected_raw_accumulation_arm_fires_at_a_held_phone():
    """This is the whole reason the idle floor exists — keep it measurable."""
    held = frames(900, sharpness=900.0, stability=1.0)
    assert simulate_sweep(held, subtract_idle_floor=False).shots > 1
    assert simulate_sweep(held, subtract_idle_floor=True).shots == 1


def test_motion_fills_the_budget_and_the_cap_stops_it():
    res = simulate_sweep(frames(900, sharpness=900.0, stability=14.0))
    assert res.shots == MAX_FRAMES
    assert res.capped


def test_blurry_frames_are_never_taken():
    assert simulate_sweep(frames(900, sharpness=10.0, stability=14.0)).shots == 0


def test_motion_during_a_blurry_frame_is_banked_not_lost():
    # One sharp frame, a long blurry travel, then a sharp frame with no motion
    # of its own: it must fire on the travel that happened while out of focus.
    seq = (
        frames(1, sharpness=900.0, stability=1.0, start_ms=0)
        + frames(1, sharpness=10.0, stability=300.0, start_ms=500)
        + frames(1, sharpness=900.0, stability=1.0, start_ms=1000)
    )
    assert simulate_sweep(seq).shots == 2


def test_the_first_frames_sentinel_stability_does_not_saturate_the_accumulator():
    seq = [
        Frame(timestamp_ms=0, sharpness=900.0, stability=STABILITY_SENTINEL,
              passes=False, streak=0, command="none"),
        Frame(timestamp_ms=1000, sharpness=900.0, stability=4.0,
              passes=False, streak=0, command="none"),
    ]
    # Only the first shot: the sentinel is a non-measurement, and 0.9 of real
    # excess is nowhere near the threshold.
    assert simulate_sweep(seq).shots == 1


def test_the_interval_holds_back_a_frame_carrying_plenty_of_motion():
    seq = (
        frames(1, sharpness=900.0, stability=1.0, start_ms=0)
        + frames(1, sharpness=900.0, stability=500.0, start_ms=100)
        + frames(1, sharpness=900.0, stability=1.0, start_ms=400)
    )
    res = simulate_sweep(seq)
    assert res.fired_at_ms == (0, 400)


def test_the_timed_fallback_ignores_motion_entirely():
    held = frames(900, sharpness=900.0, stability=1.0)
    assert simulate_sweep(held, motion_threshold=None, min_interval_ms=800).shots == MAX_FRAMES


def test_an_empty_log_is_not_an_error():
    res = simulate_sweep([])
    assert res.shots == 0 and res.duration_s == 0.0 and sharp_pass_rate([]) == 0.0


@pytest.mark.parametrize("stability,expected_banked_per_frame", [
    (IDLE_STABILITY_FLOOR, 0.0),
    (IDLE_STABILITY_FLOOR - 1.0, 0.0),
])
def test_motion_at_or_below_the_idle_floor_banks_nothing(stability, expected_banked_per_frame):
    assert simulate_sweep(frames(900, sharpness=900.0, stability=stability)).shots == 1
