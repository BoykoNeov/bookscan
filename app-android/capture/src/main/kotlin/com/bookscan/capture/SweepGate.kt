package com.bookscan.capture

/** Commands a [SweepGate] emits for the caller to act on; the gate itself never touches files. */
sealed interface SweepCommand {
    /** Nothing to do this frame. */
    data object None : SweepCommand

    /** Take a still now — the view has moved far enough since the last one and this frame is sharp. */
    data object CaptureNow : SweepCommand

    /** [SweepGate.maxFrames] reached: the sweep is over, hand the frames off. */
    data object SweepFull : SweepCommand
}

/**
 * Pure state machine implementing "sweep to capture": while the operator
 * slides the phone across a spread at a fixed zoom, fire a still every time
 * the view has **travelled far enough** since the last one, subject to a
 * sharpness floor and a hard frame cap.
 *
 * **This is deliberately NOT [HoverGate] with different numbers, and its
 * thresholds must never be merged with that gate's.** [HoverGate] is
 * calibrated to fire *because the phone is still* — fitted 2026-08-19 to give
 * **zero** bursts across a whole 21 s moving recording. A sweep is motion, so
 * that gate cannot fire during one by construction, and loosening it to make
 * it fire would destroy a calibration that was paid for on a device. This gate
 * **inverts** the stability test instead: motion is the trigger, and sharpness
 * is the only veto.
 *
 * **What "travelled far enough" actually measures.** [FrameScore.stability] is
 * the mean absolute luma difference against the previous analysis frame, which
 * is a *proxy* for how far the view moved between the two — not a distance.
 * The gate sums it since the last capture. Two honest limits follow. It grows
 * with scene contrast as well as with travel, so a dense block of text
 * accumulates faster than a blank margin and the shots will not be evenly
 * spaced on the page; and it saturates once successive frames stop overlapping,
 * so it cannot distinguish "moved half a frame" from "moved a whole one".
 * Nothing cheaper is available on device without registration, which is the
 * large build (`docs/plans/panorama-and-next-steps.md` Phase 3) rather than
 * this one. Because of that the motion threshold is a **rate** control, not an
 * overlap guarantee, and [motionThreshold] may be null to fall back to firing
 * on [minCaptureIntervalMs] alone.
 *
 * **Only motion ABOVE [idleStabilityFloor] is counted, and that floor is why
 * the gate does not fire at a standing phone.** Measured by replaying the
 * three 2026-08-19 recordings through this rule
 * (`tools/calibrate_sweep.py`, `docs/data/sweep_calibration_20260831.json`):
 * summing raw stability fires **6** shots across the 23 s *steady* recording —
 * pure duplicates, burning a capped budget on one patch — because a held phone
 * still reports ~1.06 per frame and 190 of those reach 200. Summing only the
 * **excess** over 3.1 (the value [HoverGate] separates still from moving at)
 * fires the mandatory first shot and **nothing else** on that same recording,
 * while still firing 24 in 21 s on the moving one.
 *
 * No default thresholds are provided, for the same reason [HoverGate] provides
 * none: variance-of-Laplacian on a downsampled on-device luma buffer is not on
 * the pipeline's scale, and the motion proxy has no pipeline equivalent at all.
 * `SweepScreen` holds the values and states where each came from.
 *
 * Deterministic and side-effect free — [FrameScore.timestampMs] drives all
 * timing decisions — so this is fully unit-testable against fixture sequences
 * with no clock, no CameraX, no device.
 */
class SweepGate(
    /** A frame blurrier than this is skipped; the sweep waits for a sharp one. */
    private val sharpnessThreshold: Double,
    /**
     * Accumulated motion (excess over [idleStabilityFloor], summed over frames)
     * required between captures. Null fires on [minCaptureIntervalMs] alone —
     * the fallback for a device where the motion proxy proves uncalibratable.
     */
    private val motionThreshold: Double?,
    /** Per-frame stability below this is hand tremor, not travel, and contributes nothing. */
    private val idleStabilityFloor: Double,
    /** Floor on the gap between captures, whatever the motion says: the shutter has a cadence. */
    private val minCaptureIntervalMs: Long,
    /**
     * Hard cap on **this** sweep. [start] resets the count, so a caller that
     * lets the operator sweep a spread more than once must budget across runs
     * itself — this alone does not bound the upload.
     */
    val maxFrames: Int,
) {
    init {
        require(maxFrames >= 1) { "maxFrames must be >= 1" }
        require(idleStabilityFloor >= 0.0) { "idleStabilityFloor must not be negative" }
        require(motionThreshold == null || motionThreshold > 0.0) {
            "motionThreshold must be positive when set (null = fire on the interval alone)"
        }
    }

    private var running = false
    private var captured = 0
    private var motionSinceCapture = 0.0
    private var lastFiredAtMs: Long? = null

    /** Stills fired in the current sweep. */
    val capturedCount: Int get() = captured

    /** Motion banked since the last capture, for the on-screen readout. Meaningless before the first shot. */
    val motionSinceLastCapture: Double get() = motionSinceCapture

    /** Whether a sweep is currently armed. */
    val isRunning: Boolean get() = running

    /**
     * Whether a frame clears the sharpness floor. Exposed so the calibration
     * log records the same test the gate acts on rather than re-deriving it
     * from a copy of the threshold that could drift. Pure.
     */
    fun sharpEnough(score: FrameScore): Boolean = score.sharpness >= sharpnessThreshold

    /** Arm a fresh sweep. Discards any state from a previous one. */
    fun start() {
        reset()
        running = true
    }

    /** Disarm. The caller decides what to do with the frames already taken. */
    fun stop() {
        reset()
    }

    fun onFrame(score: FrameScore): SweepCommand {
        if (!running) return SweepCommand.None

        // The cap is checked before anything else so it is reported exactly
        // once: the frame that would have been the (maxFrames + 1)-th ends the
        // sweep instead, mirroring HoverGate's burst-cap shape.
        if (captured >= maxFrames) {
            reset()
            return SweepCommand.SweepFull
        }

        // FrameScorer reports Double.MAX_VALUE for the very first frame, which
        // has no predecessor to diff against. Adding that sentinel would
        // saturate the accumulator forever, so it is skipped — it is a
        // "no measurement", not a large one.
        if (score.stability < Double.MAX_VALUE && score.stability.isFinite()) {
            motionSinceCapture += (score.stability - idleStabilityFloor).coerceAtLeast(0.0)
        }

        // Blurry frames are skipped but their motion is still banked: the view
        // genuinely did travel during them, and dropping it would make the gate
        // fire late by exactly the blur.
        if (!sharpEnough(score)) return SweepCommand.None

        val firstShot = lastFiredAtMs == null
        if (!firstShot) {
            if (score.timestampMs - lastFiredAtMs!! < minCaptureIntervalMs) return SweepCommand.None
            // The first shot is exempt from the motion test on purpose: there
            // is no previous capture to have moved away from, and requiring
            // travel first would mean the frame the operator aimed at when
            // they tapped Start is the one frame never taken.
            if (motionThreshold != null && motionSinceCapture < motionThreshold) return SweepCommand.None
        }

        lastFiredAtMs = score.timestampMs
        motionSinceCapture = 0.0
        captured++
        return SweepCommand.CaptureNow
    }

    /**
     * The caller could NOT take the still [onFrame] just asked for — the camera
     * still had too many shots in flight, say. Gives the frame back to the
     * budget.
     *
     * It exists because the budget is small and the alternative is silent: the
     * gate counts a shot the moment it commands one, so without this a device
     * that cannot hold the cadence reaches [maxFrames] with far fewer files
     * than that on disk, ends the sweep, and never says why. (The same defect
     * shape is already on the books once — `figure_hires`'s `candidates`
     * skipping a failed decode in silence.)
     *
     * The banked travel is deliberately **not** restored. By the time a shot is
     * refused the view has moved on, so the picture the gate wanted is gone;
     * the next one should be earned by fresh travel, exactly like any other.
     */
    fun abandonShot() {
        if (captured > 0) captured--
    }

    /** Clears all state and disarms. */
    fun reset() {
        running = false
        captured = 0
        motionSinceCapture = 0.0
        lastFiredAtMs = null
    }
}
