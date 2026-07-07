package com.bookscan.capture

import kotlin.test.Test
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class ScaledCloseupSizeTest {
    @Test
    fun `resulting area fraction matches the requested fraction within rounding`() {
        val full = ScaledSize(4000, 3000)
        val target = scaledCloseupSize(full.width, full.height, CLOSEUP_AREA_FRACTION)
        val frac = (target.width.toDouble() * target.height) / (full.width.toDouble() * full.height)
        assertTrue(
            kotlin.math.abs(frac - CLOSEUP_AREA_FRACTION) < 0.01,
            "area fraction $frac should be close to $CLOSEUP_AREA_FRACTION",
        )
    }

    @Test
    fun `default close-up fraction stays comfortably below Stage 01's fullspread threshold`() {
        val full = ScaledSize(4000, 3000)
        val target = scaledCloseupSize(full.width, full.height)
        val frac = (target.width.toDouble() * target.height) / (full.width.toDouble() * full.height)
        assertTrue(frac < FULLSPREAD_AREA_FRAC - 0.1, "area fraction $frac should have real margin below $FULLSPREAD_AREA_FRAC")
    }

    @Test
    fun `aspect ratio is preserved`() {
        val target = scaledCloseupSize(4000, 3000, 0.5)
        val srcRatio = 4000.0 / 3000.0
        val targetRatio = target.width.toDouble() / target.height
        assertTrue(kotlin.math.abs(srcRatio - targetRatio) < 0.01)
    }

    @Test
    fun `never upscales beyond the source dimensions`() {
        val target = scaledCloseupSize(10, 10, 0.99)
        assertTrue(target.width <= 10 && target.height <= 10)
    }

    @Test
    fun `rejects non-positive dimensions`() {
        assertFailsWith<IllegalArgumentException> { scaledCloseupSize(0, 100) }
        assertFailsWith<IllegalArgumentException> { scaledCloseupSize(100, 0) }
    }

    @Test
    fun `rejects an out-of-range area fraction`() {
        assertFailsWith<IllegalArgumentException> { scaledCloseupSize(100, 100, 0.0) }
        assertFailsWith<IllegalArgumentException> { scaledCloseupSize(100, 100, 1.0) }
    }
}
