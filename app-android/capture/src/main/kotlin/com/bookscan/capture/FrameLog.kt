package com.bookscan.capture

/**
 * One recorded analysis frame: the two scores the gate decided on, whether
 * they passed, how long the pass streak was at that point, and what the gate
 * emitted. This is the calibration record: the sharpness/stability thresholds
 * `CaptureScreen` feeds [HoverGate] are placeholders until they are fitted
 * against real rows of this shape (see docs/plans/android-guided-capture.md M3).
 */
data class FrameLogRow(
    val timestampMs: Long,
    val sharpness: Double,
    val stability: Double,
    val passes: Boolean,
    val streak: Int,
    val command: String,
)

/**
 * In-memory recorder for [FrameLogRow]s, with a CSV rendering.
 *
 * Deliberately does NO file I/O: frames arrive on the camera analysis
 * callback (main thread in `CaptureScreen`), and a per-frame write at ~30fps
 * would stall it. The caller records into memory while hovering and writes
 * [toCsv] once, off the main thread, when logging stops.
 *
 * Doubles are rendered with [Double.toString], not `String.format` — the
 * latter is locale-sensitive and would emit `62,4` on a comma-decimal device,
 * silently corrupting the CSV that the calibration is fitted from.
 * Non-finite and sentinel values (the first frame's [Double.MAX_VALUE]
 * stability, see [FrameScorer]) round-trip through `float()` in Python as-is.
 */
class FrameLog(private val capacity: Int = 20_000) {
    private val rows = ArrayList<FrameLogRow>()

    /** Rows discarded because [capacity] was reached; reported in the CSV footer so a truncated log can never read as a complete one. */
    var dropped: Int = 0
        private set

    val size: Int get() = rows.size

    fun record(row: FrameLogRow) {
        if (rows.size >= capacity) {
            dropped++
            return
        }
        rows.add(row)
    }

    fun clear() {
        rows.clear()
        dropped = 0
    }

    fun toCsv(): String = buildString {
        append("timestamp_ms,sharpness,stability,passes,streak,command\n")
        for (r in rows) {
            append(r.timestampMs).append(',')
            append(r.sharpness).append(',')
            append(r.stability).append(',')
            append(if (r.passes) 1 else 0).append(',')
            append(r.streak).append(',')
            append(r.command).append('\n')
        }
        if (dropped > 0) {
            append("# dropped_rows,").append(dropped).append('\n')
        }
    }
}
