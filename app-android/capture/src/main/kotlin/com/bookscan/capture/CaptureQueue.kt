package com.bookscan.capture

import java.io.File

/**
 * One spread held back for a later upload: its whole-spread shot(s) plus any
 * close-ups, exactly the two lists
 * `BookscanViewModel.uploadSpread` already sends in one multipart request.
 */
data class PendingSpread(val anchors: List<File>, val closeups: List<File>) {
    /** Upload order within the page: anchor(s) first — Stage 00's `frame_00` = anchor convention. */
    val files: List<File> get() = anchors + closeups
}

/**
 * The batch: spreads captured but not yet sent, in **capture order**.
 *
 * **Why a batch exists.** Uploading each spread as it is shot ties photographing
 * a book to the Wi-Fi being up and the server being reachable at that moment.
 * Shooting a whole book is the normal case, so the queue lets the operator take
 * every page first and send them in one go afterwards.
 *
 * **Order is the deliverable.** `server/routes_jobs.py::upload_page` names each
 * page `page_NNN` **by arrival**, so the batch must be uploaded strictly
 * head-first and a failure must NOT be skipped over: dropping page 17 does not
 * lose one page, it renumbers every page after it. Hence [fail] leaves the
 * failing spread at the head, with everything behind it untouched, so
 * retrying resumes at exactly the page that stopped.
 *
 * Immutable, and deliberately free of Android and of the network client: it is a
 * plain JVM value so the advance/stop decisions are unit-testable without a
 * device (same rationale as [HoverGate] and [FrameScore]).
 */
data class CaptureQueue(
    /** Still to send, head first. After [fail] the head IS the page that failed. */
    val pending: List<PendingSpread> = emptyList(),
    /** How many of this batch already reached the server. */
    val uploaded: Int = 0,
    /**
     * 1-based position **in the batch** of the page whose upload failed after
     * its retries, or null if nothing has failed since the last change. Kept
     * for the message shown to the operator — the queue itself recovers by
     * simply being uploaded again.
     */
    val failedAt: Int? = null,
) {
    val isEmpty: Boolean get() = pending.isEmpty()

    /** Everything captured in this batch: already sent + still waiting. */
    val total: Int get() = uploaded + pending.size

    /** The next spread to send, or null when the batch is drained. */
    fun head(): PendingSpread? = pending.firstOrNull()

    /** Queue one more spread. Clears a previous failure marker: the batch grew, the old message is stale. */
    fun add(spread: PendingSpread): CaptureQueue = copy(pending = pending + spread, failedAt = null)

    /** The head reached the server. Drop it and count it. */
    fun advance(): CaptureQueue =
        if (pending.isEmpty()) this
        else copy(pending = pending.drop(1), uploaded = uploaded + 1, failedAt = null)

    /**
     * The head failed after its retries. Nothing moves — the batch stops here,
     * with the failed page still first — and the position is recorded for the
     * operator. Stopping rather than skipping is the point: see the class note.
     */
    fun fail(): CaptureQueue = copy(failedAt = uploaded + 1)

    /** Every file still held by the batch, for deletion when the operator discards it. */
    fun files(): List<File> = pending.flatMap { it.files }
}
