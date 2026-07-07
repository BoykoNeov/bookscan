package com.bookscan.network

import kotlinx.coroutines.delay
import java.io.IOException

/**
 * Exponential backoff delay before retry attempt [attempt] (1-indexed).
 * Doubles from [initialDelayMs], capped at [maxDelayMs]. Pure and
 * deterministic — no jitter — so callers can assert exact values.
 */
fun delayForAttempt(attempt: Int, initialDelayMs: Long = 500, maxDelayMs: Long = 8000): Long {
    require(attempt >= 1) { "attempt must be >= 1" }
    val raw = initialDelayMs * (1L shl (attempt - 1).coerceAtMost(30))
    return raw.coerceAtMost(maxDelayMs)
}

/**
 * Retries [block] up to [maxAttempts] times, waiting [delayForAttempt]
 * between attempts, but only while [isRetryable] accepts the thrown error —
 * see [isRetryableNetworkError] for the default's idempotency tradeoff.
 *
 * Deliberately does NOT wrap [block] in a dispatcher switch: staying on the
 * caller's dispatcher means kotlinx-coroutines-test's virtual time advances
 * [delay] under `runTest`, so retry tests run instantly instead of
 * wall-clock-sleeping.
 */
suspend fun <T> withRetry(
    maxAttempts: Int,
    initialDelayMs: Long = 500,
    maxDelayMs: Long = 8000,
    isRetryable: (Throwable) -> Boolean = ::isRetryableNetworkError,
    block: suspend (attempt: Int) -> T,
): T {
    require(maxAttempts >= 1) { "maxAttempts must be >= 1" }
    for (attempt in 1..maxAttempts) {
        try {
            return block(attempt)
        } catch (e: Throwable) {
            if (attempt >= maxAttempts || !isRetryable(e)) throw e
            delay(delayForAttempt(attempt, initialDelayMs, maxDelayMs))
        }
    }
    error("withRetry: unreachable")
}

/**
 * Retries network-layer failures ([IOException]: connect refused/
 * unreachable, DNS failure, read/write timeout) — not
 * [retrofit2.HttpException] (the server sent an actual response).
 *
 * Idempotency tradeoff, deliberate: `POST .../pages` mints a new page per
 * call, so if a request reaches the server and is processed but its
 * *response* is lost (a read timeout after send), retrying creates a
 * duplicate page. For this personal single-LAN tool, the occasional
 * duplicate — discardable by the user — is accepted rather than building
 * request-dedup infrastructure server-side. Connect-time failures (never
 * reached the server) are unambiguously safe to retry either way.
 */
fun isRetryableNetworkError(e: Throwable): Boolean = e is IOException
