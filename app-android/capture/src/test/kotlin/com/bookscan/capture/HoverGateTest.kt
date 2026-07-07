package com.bookscan.capture

import kotlin.test.Test
import kotlin.test.assertEquals
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
