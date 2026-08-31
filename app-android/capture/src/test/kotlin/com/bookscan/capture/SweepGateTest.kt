package com.bookscan.capture

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

private const val SHARP = 400.0
private const val MOTION = 200.0
private const val IDLE_FLOOR = 3.1
private const val INTERVAL_MS = 400L

/** A sharp frame that reports [stability] of apparent motion since the previous one. */
private fun moving(t: Long, stability: Double = 14.0, sharpness: Double = 900.0) =
    FrameScore(sharpness = sharpness, stability = stability, timestampMs = t)

/** A sharp frame from a phone being held still — below the idle floor, so it banks no travel. */
private fun still(t: Long) = FrameScore(sharpness = 900.0, stability = 1.0, timestampMs = t)

/** Motion, but too blurry to keep. */
private fun blurry(t: Long, stability: Double = 30.0) =
    FrameScore(sharpness = 50.0, stability = stability, timestampMs = t)

private fun newGate(
    motionThreshold: Double? = MOTION,
    minCaptureIntervalMs: Long = INTERVAL_MS,
    maxFrames: Int = 24,
) = SweepGate(
    sharpnessThreshold = SHARP,
    motionThreshold = motionThreshold,
    idleStabilityFloor = IDLE_FLOOR,
    minCaptureIntervalMs = minCaptureIntervalMs,
    maxFrames = maxFrames,
)

/** Feeds frames 33 ms apart (~30 fps, the recorded device rate) and returns every command emitted. */
private fun SweepGate.run(count: Int, startMs: Long = 0L, frame: (Long) -> FrameScore): List<SweepCommand> =
    (0 until count).map { i -> onFrame(frame(startMs + i * 33L)) }

class SweepGateTest {
    @Test
    fun `emits nothing until started`() {
        val gate = newGate()
        repeat(10) { i -> assertEquals(SweepCommand.None, gate.onFrame(moving(t = i * 33L))) }
        assertFalse(gate.isRunning)
        assertEquals(0, gate.capturedCount)
    }

    @Test
    fun `takes the first sharp frame immediately, without waiting for travel`() {
        val gate = newGate()
        gate.start()
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 0)))
        assertEquals(1, gate.capturedCount)
    }

    @Test
    fun `waits for a sharp frame before the first capture`() {
        val gate = newGate()
        gate.start()
        repeat(5) { i -> assertEquals(SweepCommand.None, gate.onFrame(blurry(t = i * 33L))) }
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 200)))
    }

    @Test
    fun `after the first shot it fires only once enough motion has accumulated`() {
        val gate = newGate()
        gate.start()
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 0)))
        // 14.0 per frame banks 10.9 of excess over the 3.1 idle floor, so 200
        // needs 19 frames — and the interval alone would have allowed a shot
        // from frame 13 onward.
        val commands = gate.run(count = 18, startMs = 33L) { moving(t = it) }
        assertTrue(commands.all { it == SweepCommand.None }, "fired early: $commands")
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 33L * 19)))
    }

    @Test
    fun `a held phone banks no travel and never fires a second shot`() {
        val gate = newGate()
        gate.start()
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(still(t = 0)))
        // 30 seconds of a perfectly steady hold at 30 fps.
        val commands = gate.run(count = 900, startMs = 33L) { still(t = it) }
        assertTrue(commands.all { it == SweepCommand.None }, "a standing phone fired again")
        assertEquals(1, gate.capturedCount)
        assertEquals(0.0, gate.motionSinceLastCapture, absoluteTolerance = 1e-9)
    }

    @Test
    fun `throttles to at least minCaptureIntervalMs even when motion is plentiful`() {
        val gate = newGate(minCaptureIntervalMs = 400)
        gate.start()
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 0)))
        // One frame carrying far more than the motion threshold on its own:
        // the interval, not the motion, is what must hold it back.
        assertEquals(SweepCommand.None, gate.onFrame(moving(t = 100, stability = 500.0)))
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 400, stability = 1.0)))
    }

    @Test
    fun `motion during a blurry frame is banked, not lost`() {
        val gate = newGate(minCaptureIntervalMs = 0)
        gate.start()
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 0)))
        // All the travel happens while out of focus; the next sharp frame must
        // fire straight away rather than waiting for the same distance again.
        assertEquals(SweepCommand.None, gate.onFrame(blurry(t = 33, stability = 250.0)))
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 66, stability = 1.0)))
    }

    @Test
    fun `reports SweepFull once, on the frame after the cap is reached`() {
        val gate = newGate(motionThreshold = null, minCaptureIntervalMs = 0, maxFrames = 3)
        gate.start()
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 0)))
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 33)))
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 66)))
        assertEquals(SweepCommand.SweepFull, gate.onFrame(moving(t = 99)))
        // Disarmed by the cap: nothing further, no second SweepFull.
        assertEquals(SweepCommand.None, gate.onFrame(moving(t = 132)))
        assertFalse(gate.isRunning)
    }

    @Test
    fun `a shot the caller could not take is given back to the budget`() {
        val gate = newGate(motionThreshold = null, minCaptureIntervalMs = 0, maxFrames = 2)
        gate.start()
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 0)))
        // The camera was busy: this frame never became a file, so it must not
        // spend one of the two the budget allows.
        gate.abandonShot()
        assertEquals(0, gate.capturedCount)
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 33)))
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 66)))
        assertEquals(SweepCommand.SweepFull, gate.onFrame(moving(t = 99)))
    }

    @Test
    fun `abandoning a shot does not give the banked travel back`() {
        val gate = newGate()
        gate.start()
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 0)))
        gate.abandonShot()
        // The view has moved on, so the next shot is earned by fresh travel
        // like any other — abandoning returns the budget, not the moment.
        assertEquals(SweepCommand.None, gate.onFrame(moving(t = 500, stability = 4.0)))
    }

    @Test
    fun `abandoning with nothing captured is harmless`() {
        val gate = newGate()
        gate.start()
        gate.abandonShot()
        gate.abandonShot()
        assertEquals(0, gate.capturedCount)
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(moving(t = 0)))
    }

    @Test
    fun `the time-only fallback fires on the interval with no motion at all`() {
        val gate = newGate(motionThreshold = null, minCaptureIntervalMs = 800)
        gate.start()
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(still(t = 0)))
        assertEquals(SweepCommand.None, gate.onFrame(still(t = 400)))
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(still(t = 800)))
    }

    @Test
    fun `the first frame's sentinel stability does not saturate the accumulator`() {
        val gate = newGate()
        gate.start()
        // FrameScorer's "no previous frame" report. It must count as no
        // measurement, not as a huge one — otherwise the second shot fires
        // immediately after the first with no travel behind it.
        assertEquals(SweepCommand.CaptureNow, gate.onFrame(FrameScore(900.0, Double.MAX_VALUE, 0)))
        assertEquals(SweepCommand.None, gate.onFrame(moving(t = 500, stability = 4.0)))
    }

    @Test
    fun `start resets a previous sweep`() {
        val gate = newGate(motionThreshold = null, minCaptureIntervalMs = 0, maxFrames = 2)
        gate.start()
        gate.onFrame(moving(t = 0))
        assertEquals(1, gate.capturedCount)
        gate.start()
        assertEquals(0, gate.capturedCount)
        assertTrue(gate.isRunning)
    }

    @Test
    fun `stop disarms`() {
        val gate = newGate()
        gate.start()
        gate.onFrame(moving(t = 0))
        gate.stop()
        assertFalse(gate.isRunning)
        assertEquals(SweepCommand.None, gate.onFrame(moving(t = 5000)))
    }

    @Test
    fun `sharpEnough matches the gate's own veto`() {
        val gate = newGate()
        assertTrue(gate.sharpEnough(moving(t = 0)))
        assertFalse(gate.sharpEnough(blurry(t = 0)))
        assertTrue(gate.sharpEnough(FrameScore(SHARP, 10.0, 0)), "the threshold itself must pass")
    }

    @Test
    fun `rejects impossible configurations`() {
        assertFailsWith<IllegalArgumentException> { newGate(maxFrames = 0) }
        assertFailsWith<IllegalArgumentException> { newGate(motionThreshold = 0.0) }
        assertFailsWith<IllegalArgumentException> {
            SweepGate(SHARP, MOTION, idleStabilityFloor = -1.0, minCaptureIntervalMs = 0, maxFrames = 1)
        }
    }
}
