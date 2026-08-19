"""Fit the Android hover-gate thresholds from real on-device frame logs.

``CaptureScreen.kt``'s ``SHARPNESS_THRESHOLD`` / ``STABILITY_THRESHOLD`` are
placeholders: variance-of-Laplacian on a downsampled on-device luma buffer is
not on ``stage00_ingest.py``'s absolute scale, so no value could be copied from
the pipeline. The app's "Log frames (calibration)" button records every scored
analysis frame to a CSV; this tool turns two labelled logs — one recorded while
holding the phone over a spread, one while moving it — into a threshold pair
plus the false-fire / miss rates that pair would have produced on exactly those
frames.

CSV columns (written by ``com.bookscan.capture.FrameLog``)::

    timestamp_ms,sharpness,stability,passes,streak,command

**Fit on ``sharpness`` and ``stability`` only.** ``passes`` is evaluated
*before* the gate steps and ``streak`` is read *after*, so a burst-cap frame
reads ``passes=1,streak=0``; both columns describe the OLD thresholds, and are
diagnostics here, never fit inputs. A trailing ``# dropped_rows,N`` line means
the log hit its in-memory cap and is truncated.

Usage::

    python -m tools.calibrate_hover --steady steady.csv --moving moving.csv \\
        [--mixed mixed.csv] [--max-false-fire 0.01] [--json out.json]
    python -m tools.calibrate_hover --self-test

The IO lives at the bottom; the number-crunching above it is pure and unit
tested in ``tools/tests/test_calibrate_hover.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

# The gate's own constants, mirrored from CaptureScreen.kt / HoverGate.kt so a
# simulated run here matches what the phone would actually have done. Keep in
# step with the app if those change.
REQUIRED_CONSECUTIVE_FRAMES = 8
MIN_CAPTURE_INTERVAL_MS = 400
MAX_BURST_SIZE = 4

PERCENTILES = (5, 10, 25, 50, 75, 90, 95)

# The first frame of every log has no predecessor to diff against and reports
# Double.MAX_VALUE stability (FrameScorer). It is a sentinel, not a measurement.
STABILITY_SENTINEL = 1e300


@dataclass(frozen=True)
class Frame:
    """One scored analysis frame. ``passes``/``streak``/``command`` are the OLD
    gate's diagnostics — see the module docstring on why they are never fit."""

    timestamp_ms: int
    sharpness: float
    stability: float
    passes: bool
    streak: int
    command: str


@dataclass
class LogFile:
    path: str
    frames: list[Frame]
    dropped: int = 0
    warmup_skipped: int = 0

    @property
    def duration_s(self) -> float:
        if len(self.frames) < 2:
            return 0.0
        return (self.frames[-1].timestamp_ms - self.frames[0].timestamp_ms) / 1000.0


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def parse_frame_log(text: str, path: str = "<memory>") -> LogFile:
    """Parses a FrameLog CSV. Drops the leading sentinel-stability frame(s)."""
    frames: list[Frame] = []
    dropped = 0
    header_seen = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            parts = line.lstrip("# ").split(",")
            if len(parts) == 2 and parts[0] == "dropped_rows":
                dropped = int(parts[1])
            continue
        if not header_seen:
            if not line.startswith("timestamp_ms,"):
                raise ValueError(f"{path}:{lineno}: expected the FrameLog header, got {line!r}")
            header_seen = True
            continue
        parts = line.split(",")
        if len(parts) != 6:
            raise ValueError(f"{path}:{lineno}: expected 6 columns, got {len(parts)}: {line!r}")
        frames.append(
            Frame(
                timestamp_ms=int(parts[0]),
                sharpness=float(parts[1]),
                stability=float(parts[2]),
                passes=parts[3] == "1",
                streak=int(parts[4]),
                command=parts[5],
            )
        )
    if not header_seen:
        raise ValueError(f"{path}: no FrameLog header found")

    usable = [f for f in frames if f.stability < STABILITY_SENTINEL]
    return LogFile(
        path=path,
        frames=usable,
        dropped=dropped,
        warmup_skipped=len(frames) - len(usable),
    )


# --------------------------------------------------------------------------
# Distributions
# --------------------------------------------------------------------------


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile; ``q`` in 0..100. Empty input -> nan."""
    if not values:
        return math.nan
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (q / 100.0) * (len(ordered) - 1)
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "n": len(values),
        "min": min(values) if values else math.nan,
        "max": max(values) if values else math.nan,
        **{f"p{q}": percentile(values, q) for q in PERCENTILES},
    }


def pass_rate(frames: list[Frame], sharp_threshold: float, stability_threshold: float) -> float:
    """Fraction of frames that would clear BOTH thresholds (HoverGate.passes)."""
    if not frames:
        return math.nan
    ok = sum(
        1
        for f in frames
        if f.sharpness >= sharp_threshold and f.stability <= stability_threshold
    )
    return ok / len(frames)


# --------------------------------------------------------------------------
# Fitting
# --------------------------------------------------------------------------


@dataclass
class Fit:
    sharpness_threshold: float
    stability_threshold: float
    steady_pass_rate: float
    moving_pass_rate: float
    separates: bool
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "sharpness_threshold": self.sharpness_threshold,
            "stability_threshold": self.stability_threshold,
            "steady_pass_rate": self.steady_pass_rate,
            "moving_pass_rate": self.moving_pass_rate,
            "separates": self.separates,
            "note": self.note,
        }


def fit_thresholds(
    steady: list[Frame],
    moving: list[Frame],
    max_false_fire: float = 0.01,
) -> Fit:
    """Picks the pair that lets through the most steady frames while letting
    through at most ``max_false_fire`` of the moving ones.

    The search grid is the observed steady percentiles, so every candidate is a
    value the device actually produced — no extrapolation past the data. If no
    candidate clears the constraint, the metric does not separate hovering from
    moving on this device, and that is reported rather than papered over with a
    threshold that fires on motion.
    """
    if not steady or not moving:
        raise ValueError("both a steady and a moving log are required to fit")

    sharp_grid = sorted({percentile([f.sharpness for f in steady], q) for q in range(1, 51)})
    stab_grid = sorted({percentile([f.stability for f in steady], q) for q in range(50, 100)})

    best: Fit | None = None
    for s in sharp_grid:
        for t in stab_grid:
            false_fire = pass_rate(moving, s, t)
            if false_fire > max_false_fire:
                continue
            keep = pass_rate(steady, s, t)
            if best is None or keep > best.steady_pass_rate:
                best = Fit(
                    sharpness_threshold=s,
                    stability_threshold=t,
                    steady_pass_rate=keep,
                    moving_pass_rate=false_fire,
                    separates=True,
                )

    if best is None:
        # Report the loosest pair anyway, labelled as failing, so the operator
        # can see how far apart the two populations are.
        s = percentile([f.sharpness for f in steady], 1)
        t = percentile([f.stability for f in steady], 99)
        return Fit(
            sharpness_threshold=s,
            stability_threshold=t,
            steady_pass_rate=pass_rate(steady, s, t),
            moving_pass_rate=pass_rate(moving, s, t),
            separates=False,
            note=(
                "no threshold pair keeps moving-frame pass rate at or below "
                f"{max_false_fire:.1%}: the two populations overlap. The metric, "
                "not the threshold, is the problem — record this rather than "
                "shipping a value that fires while the phone is moving."
            ),
        )

    if best.steady_pass_rate < 0.5:
        best.note = (
            "fits, but lets through under half of the steady frames — hovering "
            "may feel unresponsive; consider a longer steady recording before "
            "trusting this pair."
        )
    return best


# --------------------------------------------------------------------------
# Gate simulation
# --------------------------------------------------------------------------


@dataclass
class SimResult:
    frames: int
    duration_s: float
    captures: int
    bursts: int
    fired_at_ms: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "frames": self.frames,
            "duration_s": self.duration_s,
            "captures": self.captures,
            "bursts": self.bursts,
            "fired_at_ms": self.fired_at_ms,
        }


def simulate_gate(
    frames: list[Frame],
    sharp_threshold: float,
    stability_threshold: float,
    required_consecutive: int = REQUIRED_CONSECUTIVE_FRAMES,
    min_interval_ms: int = MIN_CAPTURE_INTERVAL_MS,
    max_burst: int = MAX_BURST_SIZE,
    hold_stability_threshold: float | None = None,
) -> SimResult:
    """Replays ``HoverGate.onFrame`` over a recorded log — same state machine,
    so "how often would this pair have triggered" is answerable before
    reinstalling the app. Mirrors HoverGate.kt; keep the two in step.

    Note the gate re-arms: after a burst hits the cap it resets, and a log that
    stays steady simply qualifies again eight frames later. In the app the
    first finalize hands the winning still to the review screen and the capture
    screen leaves composition, so ``bursts`` here means "how many times a hover
    would have qualified", not "stills uploaded".

    ``hold_stability_threshold`` mirrors HoverGate's hysteresis: the stability
    tolerated once a burst is open, looser than the one required to open it.
    Defaults to ``stability_threshold`` (no hysteresis). Leaving it out
    understates stills per burst badly - on the 2026-08-19 logs one threshold
    for both gives ONE still per realistic hover, and 3.1/6.0 gives four."""
    consecutive = 0
    burst_open = False
    burst_fired = 0
    last_fired: int | None = None
    captures = 0
    bursts = 0
    fired_at: list[int] = []

    def reset() -> None:
        nonlocal consecutive, burst_open, burst_fired, last_fired
        consecutive = 0
        burst_open = False
        burst_fired = 0
        last_fired = None

    hold_threshold = stability_threshold if hold_stability_threshold is None else hold_stability_threshold
    if hold_threshold < stability_threshold:
        raise ValueError("hold_stability_threshold must not be stricter than stability_threshold")

    for f in frames:
        limit = hold_threshold if burst_open else stability_threshold
        if not (f.sharpness >= sharp_threshold and f.stability <= limit):
            if burst_open:
                bursts += 1
            reset()
            continue
        consecutive += 1
        if not burst_open:
            if consecutive < required_consecutive:
                continue
            burst_open = True
        if burst_fired >= max_burst:
            bursts += 1
            reset()
            continue
        if last_fired is not None and f.timestamp_ms - last_fired < min_interval_ms:
            continue
        last_fired = f.timestamp_ms
        burst_fired += 1
        captures += 1
        fired_at.append(f.timestamp_ms)
    if burst_open:
        bursts += 1

    duration = (frames[-1].timestamp_ms - frames[0].timestamp_ms) / 1000.0 if len(frames) > 1 else 0.0
    return SimResult(frames=len(frames), duration_s=duration, captures=captures, bursts=bursts, fired_at_ms=fired_at)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def _fmt_summary(name: str, stats: dict[str, float]) -> str:
    if not stats["n"]:
        return f"  {name}: (no frames)"
    cells = "  ".join(f"p{q}={stats[f'p{q}']:.1f}" for q in PERCENTILES)
    return f"  {name}: n={stats['n']}  min={stats['min']:.1f}  {cells}  max={stats['max']:.1f}"


def build_report(
    steady: LogFile,
    moving: LogFile,
    fit: Fit,
    mixed: LogFile | None,
    mixed_sim: SimResult | None,
    old: tuple[float, float] | None = None,
) -> str:
    lines: list[str] = []
    add = lines.append
    add("hover-gate calibration")
    add("=" * 60)
    for label, log in (("steady", steady), ("moving", moving)):
        add(f"{label}: {log.path}  ({len(log.frames)} frames, {log.duration_s:.1f}s)")
        if log.warmup_skipped:
            add(f"  skipped {log.warmup_skipped} warm-up frame(s) with sentinel stability")
        if log.dropped:
            add(f"  WARNING: log truncated — {log.dropped} row(s) dropped at the in-memory cap")
        add(_fmt_summary("sharpness", summarize([f.sharpness for f in log.frames])))
        add(_fmt_summary("stability", summarize([f.stability for f in log.frames])))
    add("")
    add("suggested thresholds (paste into CaptureScreen.kt)")
    add("-" * 60)
    add(f"  SHARPNESS_THRESHOLD = {fit.sharpness_threshold:.1f}")
    add(f"  STABILITY_THRESHOLD = {fit.stability_threshold:.1f}")
    add(f"  fires on {fit.steady_pass_rate:.1%} of steady frames")
    add(f"  fires on {fit.moving_pass_rate:.1%} of moving frames  (false fires)")
    if not fit.separates:
        add("  *** DOES NOT SEPARATE ***")
    if fit.note:
        add(f"  note: {fit.note}")

    if old is not None:
        add("")
        add(f"current values in the app: sharpness>={old[0]:.1f} stability<={old[1]:.1f}")
        add(f"  would fire on {pass_rate(steady.frames, *old):.1%} of steady frames")
        add(f"  would fire on {pass_rate(moving.frames, *old):.1%} of moving frames")

    if mixed is not None and mixed_sim is not None:
        add("")
        add(f"replay on the mixed log ({mixed.path}, {mixed.duration_s:.1f}s) with the suggested pair")
        add("-" * 60)
        add(f"  {mixed_sim.bursts} burst(s), {mixed_sim.captures} still(s) fired")
        if mixed_sim.duration_s > 0:
            add(f"  = one burst per {mixed_sim.duration_s / max(mixed_sim.bursts, 1):.1f}s of use")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _load(path: Path) -> LogFile:
    return parse_frame_log(path.read_text(encoding="utf-8"), path=str(path))


def _self_test() -> int:
    """Synthetic end-to-end: a clean separation must be found and simulated."""

    def synth(n: int, sharp: float, stab: float, start: int = 0) -> list[Frame]:
        return [
            Frame(start + i * 33, sharp, stab, passes=False, streak=0, command="none")
            for i in range(n)
        ]

    steady = LogFile("<steady>", synth(300, sharp=80.0, stab=2.0))
    moving = LogFile("<moving>", synth(300, sharp=15.0, stab=25.0))
    fit = fit_thresholds(steady.frames, moving.frames)
    assert fit.separates, fit
    assert fit.moving_pass_rate == 0.0, fit
    assert fit.steady_pass_rate == 1.0, fit

    # 33ms frames: the 8th passing frame (t=231) opens the burst, then one
    # still per 400ms until the cap — after which the gate re-arms, so a log
    # that never stops being steady keeps qualifying.
    sim = simulate_gate(steady.frames, fit.sharpness_threshold, fit.stability_threshold)
    assert sim.fired_at_ms[:MAX_BURST_SIZE] == [231, 660, 1089, 1518], sim
    assert sim.bursts >= 1, sim

    brief = simulate_gate(steady.frames[:7], fit.sharpness_threshold, fit.stability_threshold)
    assert brief.captures == 0, brief  # one frame short of the streak

    overlapped = LogFile("<overlap>", synth(200, sharp=80.0, stab=2.0))
    bad = fit_thresholds(overlapped.frames, overlapped.frames)
    assert not bad.separates, bad

    print(build_report(steady, moving, fit, None, None, old=(40.0, 6.0)))
    print("\nself-test OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steady", type=Path, help="CSV recorded while holding the phone over a spread")
    ap.add_argument("--moving", type=Path, help="CSV recorded while moving/re-framing")
    ap.add_argument("--mixed", type=Path, help="optional CSV of realistic mixed use, replayed through the gate")
    ap.add_argument("--max-false-fire", type=float, default=0.01, help="max share of moving frames allowed to pass (default 0.01)")
    ap.add_argument("--current", nargs=2, type=float, metavar=("SHARP", "STABILITY"), default=[40.0, 6.0],
                    help="the thresholds now in CaptureScreen.kt, for a before/after column")
    ap.add_argument("--json", type=Path, help="write the machine-readable result here (docs/data/ by convention)")
    ap.add_argument("--self-test", action="store_true", help="run on synthetic frames, no device needed")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.steady or not args.moving:
        ap.error("--steady and --moving are required (or use --self-test)")

    steady = _load(args.steady)
    moving = _load(args.moving)
    fit = fit_thresholds(steady.frames, moving.frames, max_false_fire=args.max_false_fire)

    mixed = _load(args.mixed) if args.mixed else None
    mixed_sim = (
        simulate_gate(mixed.frames, fit.sharpness_threshold, fit.stability_threshold) if mixed else None
    )

    report = build_report(steady, moving, fit, mixed, mixed_sim, old=tuple(args.current))
    print(report)

    if args.json:
        payload = {
            "steady": {"path": str(args.steady), "frames": len(steady.frames), "duration_s": steady.duration_s,
                       "sharpness": summarize([f.sharpness for f in steady.frames]),
                       "stability": summarize([f.stability for f in steady.frames])},
            "moving": {"path": str(args.moving), "frames": len(moving.frames), "duration_s": moving.duration_s,
                       "sharpness": summarize([f.sharpness for f in moving.frames]),
                       "stability": summarize([f.stability for f in moving.frames])},
            "max_false_fire": args.max_false_fire,
            "current": {"sharpness_threshold": args.current[0], "stability_threshold": args.current[1]},
            "fit": fit.to_dict(),
            "mixed_replay": mixed_sim.to_dict() if mixed_sim else None,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 0 if fit.separates else 1


if __name__ == "__main__":
    sys.exit(main())
