package com.bookscan.capture

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.test.assertNull

private const val SHARP = 50.0
private const val STABLE = 5.0
private const val INTERVAL_MS = 100L

private fun sharpAndStable(sharpness: Double = 100.0, stability: Double = 1.0, t: Long) =
    FrameScore(sharpness = sharpness, stability = stability, timestampMs = t)

private fun blurryOrMoving(t: Long) =
    FrameScore(sharpness = 1.0, stability = 50.0, timestampMs = t)

private fun newGate(
    requiredConsecutiveFrames: Int = 3,
    minCaptureIntervalMs: Long = INTERVAL_MS,
    maxBurstSize: Int = 4,
) = HoverGate(
    sharpnessThreshold = SHARP,
    stabilityThreshold = STABLE,
    requiredConsecutiveFrames = requiredConsecutiveFrames,
    minCaptureIntervalMs = minCaptureIntervalMs,
    maxBurstSize = maxBurstSize,
)

class HoverGateTest {
    @Test
    fun `stays silent while frames never pass the gate`() {
        val gate = newGate()
        repeat(10) { i ->
            assertEquals(HoverCommand.None, gate.onFrame(blurryOrMoving(t = i * 33L)))
        }
    }

    @Test
    fun `does not fire before requiredConsecutiveFrames is reached`() {
        val gate = newGate(requiredConsecutiveFrames = 3)
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(t = 0)))
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(t = 1000)))
    }

    @Test
    fun `fires CaptureNow exactly on the frame that completes the streak`() {
        val gate = newGate(requiredConsecutiveFrames = 3)
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(t = 0)))
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(t = 1000)))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 2000)))
    }

    @Test
    fun `throttles captures to at least minCaptureIntervalMs apart`() {
        val gate = newGate(requiredConsecutiveFrames = 1, minCaptureIntervalMs = 100)
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 0)))
        // arrives too soon after the last fire
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(t = 50)))
        // now enough time has elapsed
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 120)))
    }

    @Test
    fun `keeps firing while hover holds, then finalizes when maxBurstSize is hit`() {
        val gate = newGate(requiredConsecutiveFrames = 1, minCaptureIntervalMs = 100, maxBurstSize = 3)
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 0)))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 100)))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 200)))
        // burst cap (3) reached — next passing frame finalizes instead of capturing a 4th
        assertEquals(HoverCommand.FinalizeBurst, gate.onFrame(sharpAndStable(t = 300)))
    }

    @Test
    fun `hover breaking mid-burst finalizes immediately`() {
        val gate = newGate(requiredConsecutiveFrames = 1, minCaptureIntervalMs = 100, maxBurstSize = 10)
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 0)))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 100)))
        assertEquals(HoverCommand.FinalizeBurst, gate.onFrame(blurryOrMoving(t = 200)))
    }

    @Test
    fun `a failing frame before the gate ever opened reports None, not FinalizeBurst`() {
        val gate = newGate(requiredConsecutiveFrames = 3)
        gate.onFrame(sharpAndStable(t = 0))
        assertEquals(HoverCommand.None, gate.onFrame(blurryOrMoving(t = 1000)))
    }

    @Test
    fun `motion resets the consecutive-frame streak, requiring it to restart`() {
        val gate = newGate(requiredConsecutiveFrames = 3)
        gate.onFrame(sharpAndStable(t = 0))
        gate.onFrame(sharpAndStable(t = 1000))
        gate.onFrame(blurryOrMoving(t = 2000)) // interrupts before completing the streak
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(t = 3000)))
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(t = 4000)))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 5000)))
    }

    @Test
    fun `after finalizing, a fresh hover can open the gate again`() {
        val gate = newGate(requiredConsecutiveFrames = 1, minCaptureIntervalMs = 100, maxBurstSize = 1)
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 0)))
        assertEquals(HoverCommand.FinalizeBurst, gate.onFrame(sharpAndStable(t = 100)))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 500)))
    }

    @Test
    fun `manual reset clears in-progress state`() {
        val gate = newGate(requiredConsecutiveFrames = 3)
        gate.onFrame(sharpAndStable(t = 0))
        gate.onFrame(sharpAndStable(t = 1000))
        gate.reset()
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(t = 2000)))
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(t = 3000)))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 4000)))
    }
}

class PickSharpestTest {
    @Test
    fun `returns null for an empty list`() {
        assertNull(pickSharpest(emptyList<Pair<String, Double>>()))
    }

    @Test
    fun `picks the highest-scored candidate`() {
        val candidates = listOf("a" to 10.0, "b" to 99.5, "c" to 40.0)
        assertEquals("b", pickSharpest(candidates))
    }

    @Test
    fun `a single candidate wins trivially`() {
        assertEquals("only", pickSharpest(listOf("only" to 0.0)))
    }
}

/**
 * The observation surface the capture screen's calibration readout reads.
 * These must never influence the gate's decisions — only report them.
 */
class HoverGateObservationTest {
    @Test
    fun `passes agrees with the thresholds the gate acts on`() {
        val gate = newGate()
        assertEquals(true, gate.passes(sharpAndStable(sharpness = SHARP, stability = STABLE, t = 0)))
        assertEquals(false, gate.passes(sharpAndStable(sharpness = SHARP - 0.1, stability = STABLE, t = 0)))
        assertEquals(false, gate.passes(sharpAndStable(sharpness = SHARP, stability = STABLE + 0.1, t = 0)))
    }

    @Test
    fun `passes is pure - calling it never advances the gate`() {
        val gate = newGate(requiredConsecutiveFrames = 3)
        repeat(10) { gate.passes(sharpAndStable(t = it * 33L)) }
        assertEquals(0, gate.consecutivePassCount)
        // Two real frames still leave it one short of firing.
        gate.onFrame(sharpAndStable(t = 0))
        gate.onFrame(sharpAndStable(t = 33))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = 66)))
    }

    @Test
    fun `streak counts passing frames and resets the moment one fails`() {
        val gate = newGate(requiredConsecutiveFrames = 3)
        gate.onFrame(sharpAndStable(t = 0))
        gate.onFrame(sharpAndStable(t = 33))
        assertEquals(2, gate.consecutivePassCount)
        gate.onFrame(blurryOrMoving(t = 66))
        assertEquals(0, gate.consecutivePassCount)
    }

    @Test
    fun `burstFiredCount tracks stills fired in the open burst`() {
        val gate = newGate(requiredConsecutiveFrames = 1, maxBurstSize = 2)
        assertEquals(0, gate.burstFiredCount)
        gate.onFrame(sharpAndStable(t = 0))
        assertEquals(1, gate.burstFiredCount)
        gate.onFrame(sharpAndStable(t = INTERVAL_MS))
        assertEquals(2, gate.burstFiredCount)
        // Cap hit -> finalize -> reset.
        assertEquals(HoverCommand.FinalizeBurst, gate.onFrame(sharpAndStable(t = 2 * INTERVAL_MS)))
        assertEquals(0, gate.burstFiredCount)
    }
}

/**
 * Entry and hold are different tests. Measured on real device recordings
 * (2026-08-19): with one threshold for both, a single frame over the line
 * collapsed the burst and a realistic hover produced exactly one still.
 */
class HoverGateHysteresisTest {
    private fun hysteresisGate(maxBurstSize: Int = 4) = HoverGate(
        sharpnessThreshold = SHARP,
        stabilityThreshold = STABLE,           // 5.0 to open
        requiredConsecutiveFrames = 2,
        minCaptureIntervalMs = INTERVAL_MS,
        maxBurstSize = maxBurstSize,
        holdStabilityThreshold = 20.0,         // 20.0 to stay open
    )

    @Test
    fun `a frame between the two thresholds does not open a burst`() {
        val gate = hysteresisGate()
        repeat(5) { i -> assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(stability = 12.0, t = i * INTERVAL_MS))) }
        assertEquals(0, gate.burstFiredCount)
    }

    @Test
    fun `a frame between the two thresholds keeps an open burst alive`() {
        val gate = hysteresisGate()
        gate.onFrame(sharpAndStable(t = 0))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = INTERVAL_MS)))
        // 12.0 would have failed the entry test; the burst survives it and keeps firing.
        assertEquals(HoverCommand.None, gate.onFrame(sharpAndStable(stability = 12.0, t = INTERVAL_MS + 1)))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(stability = 12.0, t = 2 * INTERVAL_MS)))
        assertEquals(2, gate.burstFiredCount)
    }

    @Test
    fun `a frame past the hold threshold still ends the burst`() {
        val gate = hysteresisGate()
        gate.onFrame(sharpAndStable(t = 0))
        gate.onFrame(sharpAndStable(t = INTERVAL_MS))
        assertEquals(HoverCommand.FinalizeBurst, gate.onFrame(sharpAndStable(stability = 25.0, t = 2 * INTERVAL_MS)))
        assertEquals(0, gate.burstFiredCount)
    }

    @Test
    fun `without hysteresis one marginal frame still collapses the burst`() {
        // The behaviour being fixed, pinned so a default change is visible.
        val gate = newGate(requiredConsecutiveFrames = 2)
        gate.onFrame(sharpAndStable(t = 0))
        assertEquals(HoverCommand.CaptureNow, gate.onFrame(sharpAndStable(t = INTERVAL_MS)))
        assertEquals(HoverCommand.FinalizeBurst, gate.onFrame(sharpAndStable(stability = 6.0, t = 2 * INTERVAL_MS)))
    }

    @Test
    fun `a hold threshold stricter than the entry threshold is rejected`() {
        assertFailsWith<IllegalArgumentException> {
            HoverGate(
                sharpnessThreshold = SHARP,
                stabilityThreshold = STABLE,
                requiredConsecutiveFrames = 2,
                minCaptureIntervalMs = INTERVAL_MS,
                maxBurstSize = 4,
                holdStabilityThreshold = 1.0,
            )
        }
    }

    @Test
    fun `passes stays the entry test and ignores the hold threshold`() {
        val gate = hysteresisGate()
        assertFalse(gate.passes(sharpAndStable(stability = 12.0, t = 0)))
        assertTrue(gate.passes(sharpAndStable(stability = 1.0, t = 0)))
    }
}
