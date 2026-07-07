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
 * emits [HoverCommand.FinalizeBurst] so the caller can keep only the
 * sharpest still from the burst and upload just that one (mirrors Stage 01's
 * "sharpest wins," done client-side first to avoid uploading redundant
 * blurry frames over Wi-Fi).
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
) {
    init {
        require(requiredConsecutiveFrames >= 1) { "requiredConsecutiveFrames must be >= 1" }
        require(maxBurstSize >= 1) { "maxBurstSize must be >= 1" }
    }

    private var consecutivePasses = 0
    private var burstOpen = false
    private var burstFired = 0
    private var lastFiredAtMs: Long? = null

    fun onFrame(score: FrameScore): HoverCommand {
        val passes = score.sharpness >= sharpnessThreshold && score.stability <= stabilityThreshold
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

/** Returns the item with the highest score, or null if [candidates] is empty. Ties keep the first max found. */
fun <T> pickSharpest(candidates: List<Pair<T, Double>>): T? = candidates.maxByOrNull { it.second }?.first
