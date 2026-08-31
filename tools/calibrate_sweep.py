"""Replay the Android **sweep** gate over real on-device frame logs.

``SweepScreen.kt``'s thresholds decide how often a still is taken while the
operator slides the phone across a spread. Unlike the hover gate's, they could
not be *fitted*, because no recording of a sweep exists yet — the 2026-08-19
device session recorded a steady hold, deliberate re-framing, and mixed use.
What those logs CAN do is answer the two questions that would otherwise be
guesses:

1. **How often would the shipped rule fire during real hand motion?**
   ``2_moving`` is 21 s of a hand moving the phone over a book. It is not a page
   sweep, but it is the same regime, and it bounds the shot rate.
2. **Would a standing phone fire at all?** ``1_steady`` is 23 s of a deliberate
   hold. Any shot there beyond the first is a duplicate of one patch, spending a
   capped frame budget on nothing.

Question 2 is what picked the accumulation rule. Summing raw
``stability`` fires repeatedly at a phone that is not moving; summing only the
**excess** over ``HoverGate``'s fitted still/moving boundary does not. Both arms
are reported so the choice is auditable rather than asserted.

**What this cannot tell you.** It replays the GATE, not the camera. A real
device can refuse a shot the gate asked for (``SweepScreen``'s in-flight bound,
which hands the frame back via ``SweepGate.abandonShot``), so a shot counted here
is one the gate would have commanded, not necessarily one that reached the disk.

Nor is it a distance. ``stability`` is a mean absolute luma difference — a proxy
for "the picture changed", nothing more. So a threshold here is a
*rate* control and never an overlap guarantee, and the rate itself is
scene-dependent (a dense block of text changes faster than a blank margin at the
same speed). Calibrating for overlap needs registration, which is the large
build (``docs/plans/panorama-and-next-steps.md`` Phase 3).

CSV columns are ``com.bookscan.capture.FrameLog``'s, same as the hover tool's.

Usage::

    python -m tools.calibrate_sweep --logs docs/data/hover_calibration_20260819_*.csv \\
        [--json docs/data/sweep_calibration_20260831.json]
    python -m tools.calibrate_sweep --self-test

The number-crunching is pure and unit tested in
``tools/tests/test_calibrate_sweep.py``; the IO lives at the bottom.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.calibrate_hover import STABILITY_SENTINEL, Frame, _load

# Mirrored from SweepScreen.kt / SweepGate.kt so a replay here matches what the
# phone would actually have done. Keep in step with the app if those change.
SHARPNESS_THRESHOLD = 400.0
MOTION_THRESHOLD = 200.0
IDLE_STABILITY_FLOOR = 3.1
MIN_CAPTURE_INTERVAL_MS = 400
MAX_FRAMES = 24

# Candidate motion thresholds swept for the report. 200 is what ships.
CANDIDATES = (100.0, 150.0, 200.0, 300.0, 400.0)


@dataclass(frozen=True)
class SweepResult:
    """One replay of the gate over one log."""

    shots: int
    duration_s: float
    #: Timestamps the gate would have fired at, relative to the log's first frame.
    fired_at_ms: tuple[int, ...]
    #: True if the frame cap ended the sweep before the log did.
    capped: bool

    @property
    def shots_per_s(self) -> float:
        return self.shots / self.duration_s if self.duration_s > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "shots": self.shots,
            "duration_s": round(self.duration_s, 3),
            "shots_per_s": round(self.shots_per_s, 3),
            "fired_at_ms": list(self.fired_at_ms),
            "capped": self.capped,
        }


def simulate_sweep(
    frames: list[Frame],
    *,
    sharpness_threshold: float = SHARPNESS_THRESHOLD,
    motion_threshold: float | None = MOTION_THRESHOLD,
    idle_floor: float = IDLE_STABILITY_FLOOR,
    min_interval_ms: int = MIN_CAPTURE_INTERVAL_MS,
    max_frames: int = MAX_FRAMES,
    subtract_idle_floor: bool = True,
) -> SweepResult:
    """Run ``SweepGate.onFrame`` over ``frames``, statement for statement.

    ``subtract_idle_floor=False`` is the REJECTED arm — accumulating raw
    stability instead of its excess over ``idle_floor`` — kept so the reason the
    shipped rule is the shipped rule stays measurable rather than remembered.
    """
    if not frames:
        return SweepResult(0, 0.0, (), capped=False)

    t0 = frames[0].timestamp_ms
    banked = 0.0
    last_fired: int | None = None
    fired: list[int] = []
    capped = False

    for f in frames:
        if len(fired) >= max_frames:
            capped = True
            break
        # The first frame of a log carries FrameScorer's "no previous frame"
        # sentinel. It is a non-measurement, not a large motion.
        if f.stability < STABILITY_SENTINEL:
            banked += max(0.0, f.stability - idle_floor) if subtract_idle_floor else f.stability
        # Blurry frames are skipped but their motion is still banked: the view
        # genuinely travelled during them.
        if f.sharpness < sharpness_threshold:
            continue
        if last_fired is not None:
            if f.timestamp_ms - last_fired < min_interval_ms:
                continue
            # The first shot is exempt from the motion test — there is no
            # previous capture to have moved away from.
            if motion_threshold is not None and banked < motion_threshold:
                continue
        last_fired = f.timestamp_ms
        banked = 0.0
        fired.append(f.timestamp_ms - t0)

    duration_s = (frames[-1].timestamp_ms - t0) / 1000.0
    return SweepResult(len(fired), duration_s, tuple(fired), capped)


def sharp_pass_rate(frames: list[Frame], threshold: float = SHARPNESS_THRESHOLD) -> float:
    """Share of frames clearing the sharpness floor — how much of a hand sweep survives it."""
    if not frames:
        return 0.0
    return sum(1 for f in frames if f.sharpness >= threshold) / len(frames)


def build_report(logs: dict[str, list[Frame]]) -> str:
    lines: list[str] = []
    lines.append("Sweep gate replay")
    lines.append(f"  sharpness >= {SHARPNESS_THRESHOLD:.0f}, idle floor {IDLE_STABILITY_FLOOR}, "
                 f"min interval {MIN_CAPTURE_INTERVAL_MS} ms, cap {MAX_FRAMES}")
    lines.append("")
    lines.append("  shots fired, by motion threshold (shipped = %.0f)" % MOTION_THRESHOLD)
    header = "    %-14s %6s  " % ("log", "sharp%") + "".join("%7.0f" % c for c in CANDIDATES)
    lines.append(header)
    for name, frames in logs.items():
        row = "    %-14s %5.0f%%  " % (name, 100 * sharp_pass_rate(frames))
        row += "".join("%7d" % simulate_sweep(frames, motion_threshold=c).shots for c in CANDIDATES)
        lines.append(row)
    lines.append("")
    lines.append("  the rejected arm: accumulating RAW stability (no idle floor)")
    for name, frames in logs.items():
        kept = simulate_sweep(frames, subtract_idle_floor=True)
        raw = simulate_sweep(frames, subtract_idle_floor=False)
        lines.append(f"    {name:<14} shipped {kept.shots:3d}   raw {raw.shots:3d}")
    lines.append("")
    lines.append("  A steady log firing more than ONE shot is the failure this rule exists to")
    lines.append("  prevent: every extra shot is a duplicate of one patch out of a 24-frame budget.")
    return "\n".join(lines)


def _synthetic(n: int, *, sharpness: float, stability: float, step_ms: int = 33) -> list[Frame]:
    return [
        Frame(timestamp_ms=i * step_ms, sharpness=sharpness, stability=stability,
              passes=False, streak=0, command="none")
        for i in range(n)
    ]


def _self_test() -> int:
    # A held phone: one mandatory first shot, nothing after it.
    still = _synthetic(900, sharpness=900.0, stability=1.0)
    assert simulate_sweep(still).shots == 1, simulate_sweep(still)
    # ...and the rejected arm fires repeatedly on exactly those frames.
    assert simulate_sweep(still, subtract_idle_floor=False).shots > 1

    # Real motion: fires repeatedly, and the cap is what stops it.
    moving = _synthetic(900, sharpness=900.0, stability=14.0)
    res = simulate_sweep(moving)
    assert res.shots == MAX_FRAMES and res.capped, res

    # Blurry motion banks travel but takes nothing.
    blurry = _synthetic(900, sharpness=10.0, stability=14.0)
    assert simulate_sweep(blurry).shots == 0

    # The time-only fallback ignores motion entirely.
    assert simulate_sweep(still, motion_threshold=None, min_interval_ms=800).shots == MAX_FRAMES

    print(build_report({"synth-still": still, "synth-moving": moving}))
    print("\nself-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--logs", type=Path, nargs="+", help="frame-log CSVs to replay")
    ap.add_argument("--json", type=Path, help="write the machine-readable result here (docs/data/ by convention)")
    ap.add_argument("--self-test", action="store_true", help="run on synthetic frames, no logs needed")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.logs:
        ap.error("--logs is required (or use --self-test)")

    logs = {p.stem.replace("hover_calibration_20260819_", ""): _load(p).frames for p in args.logs}
    print(build_report(logs))

    if args.json:
        payload = {
            "note": "Replay of SweepGate over the 2026-08-19 hover-calibration logs. "
                    "Those logs are a hold, a re-frame and mixed use — NOT a page sweep — "
                    "so this bounds the shot RATE and settles the idle-floor question; it "
                    "does not fit the thresholds. A sweep log off SweepScreen would.",
            "params": {
                "sharpness_threshold": SHARPNESS_THRESHOLD,
                "motion_threshold": MOTION_THRESHOLD,
                "idle_stability_floor": IDLE_STABILITY_FLOOR,
                "min_capture_interval_ms": MIN_CAPTURE_INTERVAL_MS,
                "max_frames": MAX_FRAMES,
            },
            "logs": {
                name: {
                    "path": str(next(p for p in args.logs if p.stem.endswith(name))),
                    "frames": len(frames),
                    "sharp_pass_rate": round(sharp_pass_rate(frames), 4),
                    "by_motion_threshold": {
                        str(int(c)): simulate_sweep(frames, motion_threshold=c).to_dict()
                        for c in CANDIDATES
                    },
                    "raw_accumulation_rejected_arm": simulate_sweep(
                        frames, subtract_idle_floor=False
                    ).to_dict(),
                    "timed_fallback_800ms": simulate_sweep(
                        frames, motion_threshold=None, min_interval_ms=800
                    ).to_dict(),
                }
                for name, frames in logs.items()
            },
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
