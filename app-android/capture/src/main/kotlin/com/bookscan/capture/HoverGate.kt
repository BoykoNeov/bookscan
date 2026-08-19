package com.bookscan.capture

/** Commands a [HoverGate] emits for the caller to act on; the gate itself never touches files. */
sealed interface HoverCommand {
    /** Nothing to do this frame. */
    data object None : HoverCommand

    /** Take a full-resolution still now and score it alongside the others in this burst. */
    data object CaptureNow : HoverCommand

    /** Hover ended (or the burst cap was hit): pick the sharpest captured still and discard the rest. */
    data object FinalizeBurst : HoverCommand
}

/**
 * Pure state machine implementing "hover to capture": the gate opens once
 * sharpness and stability both pass for [requiredConsecutiveFrames]
 * consecutive analysis frames, then keeps firing captures — throttled to at
 * most one per [minCaptureIntervalMs] and capped at [maxBurstSize] — for as
 * long as the hover holds. When the hover breaks (or the cap is hit) it
 * emits [HoverCommand.FinalizeBurst] and the caller uploads the whole burst;
 * Stage 01 picks the sharpest of them at full resolution.
 *
 * **Entry and hold are different tests** ([stabilityThreshold] vs
 * [holdStabilityThreshold]). Opening a burst is strict; keeping one open is
 * not. Measured on three labelled recordings (2026-08-19, see the RESULTS
 * row): with one threshold for both, a single frame over the line collapsed
 * the burst, and realistic use produced exactly **one** still per hover — the
 * pipeline's Stage 01 expects several near-duplicates to choose between, so
 * that wasted its selection step and left no margin for a bad frame.
 * Loosening the hold to 6.0 gives four stills per hover and still fires
 * **zero** bursts across the whole 21 s moving recording: the
 * [requiredConsecutiveFrames] entry test is what prevents false captures, and
 * being strict after that buys nothing.
 *
 * No default thresholds are provided: variance-of-Laplacian on a downsampled
 * on-device luma buffer is not on the same scale as the pipeline's full-res
 * value (see [varianceOfLaplacian]), and the stability threshold has no
 * pipeline equivalent at all (auto-exposure re-metering shifts luma
 * frame-to-frame even when the phone is perfectly still). Both must be
 * calibrated against real on-device frames before shipping a value.
 *
 * Deterministic and side-effect free — [FrameScore.timestampMs] drives all
 * timing decisions, so this is fully unit-testable against fixture sequences
 * with no clock, no CameraX, no device.
 */
class HoverGate(
    private val sharpnessThreshold: Double,
    private val stabilityThreshold: Double,
    private val requiredConsecutiveFrames: Int,
    private val minCaptureIntervalMs: Long,
    private val maxBurstSize: Int,
    /** Stability tolerated once a burst is open; defaults to no hysteresis. */
    private val holdStabilityThreshold: Double = stabilityThreshold,
) {
    init {
        require(requiredConsecutiveFrames >= 1) { "requiredConsecutiveFrames must be >= 1" }
        require(maxBurstSize >= 1) { "maxBurstSize must be >= 1" }
        require(holdStabilityThreshold >= stabilityThreshold) {
            "holdStabilityThreshold must not be stricter than stabilityThreshold"
        }
    }

    private var consecutivePasses = 0
    private var burstOpen = false
    private var burstFired = 0
    private var lastFiredAtMs: Long? = null

    /**
     * How many consecutive frames have passed both thresholds so far (resets
     * to 0 the moment one fails). Read-only observation for the capture
     * screen's calibration readout — the gate's decisions do not depend on
     * anyone reading it.
     */
    val consecutivePassCount: Int get() = consecutivePasses

    /** Stills fired in the currently open burst; 0 when no burst is open. */
    val burstFiredCount: Int get() = burstFired

    /**
     * Whether a frame clears both thresholds. Exposed so the capture screen's
     * calibration log can record the same pass/fail the gate acts on, rather
     * than re-deriving it from a copy of the thresholds that could drift.
     * Pure: reads no gate state and changes none.
     */
    fun passes(score: FrameScore): Boolean =
        score.sharpness >= sharpnessThreshold && score.stability <= stabilityThreshold

    /** The looser test applied only while a burst is already open. */
    private fun holds(score: FrameScore): Boolean =
        score.sharpness >= sharpnessThreshold && score.stability <= holdStabilityThreshold

    fun onFrame(score: FrameScore): HoverCommand {
        val passes = if (burstOpen) holds(score) else passes(score)
        if (!passes) {
            val wasOpen = burstOpen
            reset()
            return if (wasOpen) HoverCommand.FinalizeBurst else HoverCommand.None
        }

        consecutivePasses++
        if (!burstOpen) {
            if (consecutivePasses < requiredConsecutiveFrames) return HoverCommand.None
            burstOpen = true
        }

        if (burstFired >= maxBurstSize) {
            reset()
            return HoverCommand.FinalizeBurst
        }

        val elapsedOk = lastFiredAtMs?.let { score.timestampMs - it >= minCaptureIntervalMs } ?: true
        if (!elapsedOk) return HoverCommand.None

        lastFiredAtMs = score.timestampMs
        burstFired++
        return HoverCommand.CaptureNow
    }

    /** Resets all state (e.g. after the caller cancels a burst manually). */
    fun reset() {
        consecutivePasses = 0
        burstOpen = false
        burstFired = 0
        lastFiredAtMs = null
    }
}

/**
 * Returns the item with the highest score, or null if [candidates] is empty.
 * Ties keep the first max found.
 *
 * No longer used by the capture screen: the whole burst is uploaded and Stage
 * 01 picks the anchor from **full-resolution** sharpness, which is strictly
 * better evidence than this module's 320×240 analysis-frame proxy. Kept
 * because it is the correct client-side choice for any future keep-one mode
 * (a slow link, say), and because it is covered by tests.
 */
fun <T> pickSharpest(candidates: List<Pair<T, Double>>): T? = candidates.maxByOrNull { it.second }?.first
