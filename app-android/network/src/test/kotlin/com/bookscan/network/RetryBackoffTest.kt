package com.bookscan.network

import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/**
 * M5's CI-able proof (docs/plans/android-guided-capture.md): retry/backoff
 * logic against a fake failing block, no device, no real server. Runs under
 * `runTest`'s virtual time — [withRetry] must stay dispatcher-agnostic for
 * that to hold, see its kdoc.
 */
class RetryBackoffTest {

    @Test
    fun `delayForAttempt doubles from initialDelayMs and caps at maxDelayMs`() {
        assertEquals(500, delayForAttempt(1, initialDelayMs = 500, maxDelayMs = 8000))
        assertEquals(1000, delayForAttempt(2, initialDelayMs = 500, maxDelayMs = 8000))
        assertEquals(2000, delayForAttempt(3, initialDelayMs = 500, maxDelayMs = 8000))
        assertEquals(4000, delayForAttempt(4, initialDelayMs = 500, maxDelayMs = 8000))
        assertEquals(8000, delayForAttempt(5, initialDelayMs = 500, maxDelayMs = 8000))
        assertEquals(8000, delayForAttempt(6, initialDelayMs = 500, maxDelayMs = 8000))
    }

    @Test
    fun `withRetry succeeds once a transient failure clears`() = runTest {
        var calls = 0
        val result = withRetry(maxAttempts = 4) { attempt ->
            calls++
            if (attempt < 3) throw IOException("connect refused") else "ok"
        }
        assertEquals("ok", result)
        assertEquals(3, calls)
    }

    @Test
    fun `withRetry gives up after maxAttempts and rethrows the last error`() = runTest {
        var calls = 0
        val error = assertFailsWith<IOException> {
            withRetry(maxAttempts = 3) {
                calls++
                throw IOException("still down")
            }
        }
        assertEquals("still down", error.message)
        assertEquals(3, calls)
    }

    @Test
    fun `withRetry does not retry an error isRetryable rejects`() = runTest {
        var calls = 0
        assertFailsWith<IllegalStateException> {
            withRetry(maxAttempts = 5, isRetryable = { false }) {
                calls++
                throw IllegalStateException("not retryable")
            }
        }
        assertEquals(1, calls)
    }

    @Test
    fun `isRetryableNetworkError accepts IOException, rejects other throwables`() {
        assertEquals(true, isRetryableNetworkError(IOException("boom")))
        assertEquals(false, isRetryableNetworkError(IllegalStateException("boom")))
    }
}
