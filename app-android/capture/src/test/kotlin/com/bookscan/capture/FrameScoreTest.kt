package com.bookscan.capture

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

private const val W = 16
private const val H = 16

private fun checkerboard(): ByteArray = ByteArray(W * H) { i ->
    val x = i % W
    val y = i / W
    if ((x + y) % 2 == 0) 255.toByte() else 0.toByte()
}

private fun flat(value: Int): ByteArray = ByteArray(W * H) { value.toByte() }

// A single low-frequency sine cycle across the frame: bounded but nonzero
// second derivative everywhere, unlike a pure linear ramp (whose second
// derivative is ~0 at every interior point) — a stand-in for a softly
// out-of-focus edge, much lower-frequency than the checkerboard.
private fun softWave(): ByteArray = ByteArray(W * H) { i ->
    val x = i % W
    (128 + 10 * kotlin.math.sin(2 * kotlin.math.PI * x / W)).toInt().toByte()
}

class VarianceOfLaplacianTest {
    @Test
    fun `flat frame has zero variance`() {
        assertEquals(0.0, varianceOfLaplacian(flat(128), W, H))
    }

    @Test
    fun `checkerboard scores sharper than a smooth low-frequency wave`() {
        val sharp = varianceOfLaplacian(checkerboard(), W, H)
        val smooth = varianceOfLaplacian(softWave(), W, H)
        assertTrue(sharp > smooth, "checkerboard ($sharp) should score sharper than soft wave ($smooth)")
    }

    @Test
    fun `smooth wave scores sharper than dead flat`() {
        val smooth = varianceOfLaplacian(softWave(), W, H)
        val flatScore = varianceOfLaplacian(flat(128), W, H)
        assertTrue(smooth > flatScore)
    }
}

class MeanAbsLumaDiffTest {
    @Test
    fun `identical frames are perfectly stable`() {
        val frame = checkerboard()
        assertEquals(0.0, meanAbsLumaDiff(frame, frame))
    }

    @Test
    fun `constant offset diff matches the offset`() {
        val a = flat(100)
        val b = flat(140)
        assertEquals(40.0, meanAbsLumaDiff(a, b))
    }

    @Test
    fun `large frame-to-frame change scores high`() {
        val diff = meanAbsLumaDiff(flat(0), checkerboard())
        assertTrue(diff > 100.0)
    }
}

class FrameScorerTest {
    @Test
    fun `first frame reports max stability (never auto-passes a stability gate alone)`() {
        val scorer = FrameScorer()
        val score = scorer.score(flat(128), W, H, timestampMs = 0)
        assertEquals(Double.MAX_VALUE, score.stability)
    }

    @Test
    fun `two identical frames in a row report near-zero stability`() {
        val scorer = FrameScorer()
        val frame = checkerboard()
        scorer.score(frame, W, H, timestampMs = 0)
        val second = scorer.score(frame, W, H, timestampMs = 33)
        assertEquals(0.0, second.stability)
    }

    @Test
    fun `sharpness is independent of the stability tracking`() {
        val scorer = FrameScorer()
        val score = scorer.score(checkerboard(), W, H, timestampMs = 0)
        assertEquals(varianceOfLaplacian(checkerboard(), W, H), score.sharpness)
    }
}
