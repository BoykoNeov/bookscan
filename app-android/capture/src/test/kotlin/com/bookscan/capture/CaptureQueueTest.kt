package com.bookscan.capture

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

private fun spread(name: String, closeups: Int = 0) = PendingSpread(
    anchors = listOf(File("$name-anchor.jpg")),
    closeups = (1..closeups).map { File("$name-closeup$it.jpg") },
)

private fun queueOf(vararg names: String) =
    names.fold(CaptureQueue()) { q, n -> q.add(spread(n)) }

class CaptureQueueTest {
    @Test
    fun `a new queue is empty and has nothing to send`() {
        val q = CaptureQueue()
        assertTrue(q.isEmpty)
        assertNull(q.head())
        assertEquals(0, q.total)
    }

    @Test
    fun `anchors are sent before close-ups`() {
        // Stage 00's frame_00 = anchor convention: the server names files by
        // arrival index, so the anchor must be first in the multipart body.
        val s = spread("p1", closeups = 2)
        assertEquals(
            listOf("p1-anchor.jpg", "p1-closeup1.jpg", "p1-closeup2.jpg"),
            s.files.map { it.name },
        )
    }

    @Test
    fun `spreads come back out in capture order`() {
        var q = queueOf("p1", "p2", "p3")
        val order = mutableListOf<String>()
        while (!q.isEmpty) {
            order += q.head()!!.anchors.first().name
            q = q.advance()
        }
        assertEquals(listOf("p1-anchor.jpg", "p2-anchor.jpg", "p3-anchor.jpg"), order)
    }

    @Test
    fun `advancing counts the page and drops it`() {
        val q = queueOf("p1", "p2").advance()
        assertEquals(1, q.uploaded)
        assertEquals(2, q.total)
        assertEquals("p2-anchor.jpg", q.head()!!.anchors.first().name)
    }

    @Test
    fun `a failure stops the batch and keeps the failing page at the head`() {
        // The whole point: page_NNN is assigned by arrival, so skipping a
        // failed page silently renumbers every page after it.
        val q = queueOf("p1", "p2", "p3").advance().fail()
        assertEquals(2, q.failedAt, "1-based position within the batch")
        assertEquals(1, q.uploaded)
        assertEquals("p2-anchor.jpg", q.head()!!.anchors.first().name, "the failed page is still next")
        assertEquals(2, q.pending.size, "and everything behind it is untouched")
    }

    @Test
    fun `retrying after a failure resumes at the page that stopped`() {
        val stopped = queueOf("p1", "p2", "p3").advance().fail()
        val resumed = stopped.advance()
        assertEquals("p3-anchor.jpg", resumed.head()!!.anchors.first().name)
        assertNull(resumed.failedAt, "a successful send clears the stale message")
        assertEquals(3, resumed.total, "nothing was lost or double-counted")
    }

    @Test
    fun `capturing another page clears a stale failure message`() {
        val q = queueOf("p1").fail().add(spread("p2"))
        assertNull(q.failedAt)
        assertEquals(2, q.pending.size)
    }

    @Test
    fun `advancing a drained queue is a no-op rather than an error`() {
        val drained = CaptureQueue()
        assertSame(drained, drained.advance())
    }

    @Test
    fun `discarding collects every file the batch is holding`() {
        val q = CaptureQueue().add(spread("p1", closeups = 1)).add(spread("p2"))
        assertEquals(
            listOf("p1-anchor.jpg", "p1-closeup1.jpg", "p2-anchor.jpg"),
            q.files().map { it.name },
        )
    }

    @Test
    fun `a fully drained batch reports what it sent`() {
        var q = queueOf("p1", "p2")
        q = q.advance().advance()
        assertTrue(q.isEmpty)
        assertFalse(q.uploaded == 0)
        assertEquals(2, q.uploaded)
        assertEquals(2, q.total)
    }
}
