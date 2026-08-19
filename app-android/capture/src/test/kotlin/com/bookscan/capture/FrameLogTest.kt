package com.bookscan.capture

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class FrameLogTest {
    private fun row(t: Long, sharp: Double = 50.0, still: Double = 2.0, passes: Boolean = true, streak: Int = 1, cmd: String = "none") =
        FrameLogRow(t, sharp, still, passes, streak, cmd)

    @Test
    fun `csv has a header and one line per recorded frame`() {
        val log = FrameLog()
        log.record(row(1000, sharp = 62.5, still = 3.25, passes = true, streak = 4, cmd = "none"))
        log.record(row(1033, sharp = 12.0, still = 40.0, passes = false, streak = 0, cmd = "finalize"))

        val lines = log.toCsv().trim().lines()
        assertEquals("timestamp_ms,sharpness,stability,passes,streak,command", lines[0])
        assertEquals("1000,62.5,3.25,1,4,none", lines[1])
        assertEquals("1033,12.0,40.0,0,0,finalize", lines[2])
        assertEquals(3, lines.size)
    }

    @Test
    fun `the first frame's MAX_VALUE stability survives as a parseable number`() {
        val log = FrameLog()
        log.record(row(0, still = Double.MAX_VALUE))

        val field = log.toCsv().trim().lines()[1].split(",")[2]
        assertEquals(Double.MAX_VALUE, field.toDouble())
    }

    @Test
    fun `overflow past capacity is counted and reported, not silently dropped`() {
        val log = FrameLog(capacity = 2)
        repeat(5) { log.record(row(it.toLong())) }

        assertEquals(2, log.size)
        assertEquals(3, log.dropped)
        assertTrue(log.toCsv().trimEnd().endsWith("# dropped_rows,3"))
    }

    @Test
    fun `a complete log carries no dropped footer`() {
        val log = FrameLog()
        log.record(row(1))

        assertTrue(!log.toCsv().contains("dropped_rows"))
    }

    @Test
    fun `clear empties the buffer and the drop count`() {
        val log = FrameLog(capacity = 1)
        repeat(3) { log.record(row(it.toLong())) }
        log.clear()

        assertEquals(0, log.size)
        assertEquals(0, log.dropped)
        assertEquals("timestamp_ms,sharpness,stability,passes,streak,command", log.toCsv().trim())
    }
}
