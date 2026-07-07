package com.bookscan.capture

/**
 * Per-analysis-frame score: sharpness (higher = sharper) and stability
 * (lower = more stable, i.e. less motion since the previous frame).
 *
 * [timestampMs] is supplied by the caller (never read from the system clock
 * inside this module) so the whole scoring/gate pipeline stays deterministic
 * and unit-testable against fixture sequences.
 */
data class FrameScore(
    val sharpness: Double,
    val stability: Double,
    val timestampMs: Long,
)

/**
 * Variance of the Laplacian over an 8-bit grayscale ("luma") buffer — the
 * same focus measure `pipeline/stage00_ingest.py`'s `sharpness()` computes
 * with `cv2.Laplacian(gray, cv2.CV_64F).var()` (default `ksize=1` kernel:
 * `[[0,1,0],[1,-4,1],[0,1,0]]`), reimplemented here in pure Kotlin so it can
 * run per `ImageAnalysis` frame with no OpenCV dependency.
 *
 * IMPORTANT — this does NOT produce pipeline-comparable absolute values.
 * `stage00_ingest.py` scores full-resolution frames; this scores a small
 * downsampled on-device luma buffer. Variance-of-Laplacian is not
 * scale-invariant, so the two numbers live in different scales. What
 * transfers is the *metric* (same formula) and *relative ordering within a
 * device's own burst* — not a shared absolute threshold. Any gate threshold
 * built on top of this must be calibrated on real on-device frames, not
 * copied from pipeline config.
 */
fun varianceOfLaplacian(luma: ByteArray, width: Int, height: Int): Double {
    require(luma.size >= width * height) {
        "luma buffer (${luma.size}) smaller than width*height (${width * height})"
    }
    if (width < 3 || height < 3) return 0.0

    fun px(x: Int, y: Int): Int = luma[y * width + x].toInt() and 0xFF

    var sum = 0.0
    var sumSq = 0.0
    var count = 0
    for (y in 1 until height - 1) {
        for (x in 1 until width - 1) {
            val lap = (px(x - 1, y) + px(x + 1, y) + px(x, y - 1) + px(x, y + 1) - 4 * px(x, y)).toDouble()
            sum += lap
            sumSq += lap * lap
            count++
        }
    }
    if (count == 0) return 0.0
    val mean = sum / count
    return sumSq / count - mean * mean
}

/**
 * Mean absolute per-pixel luma difference between two same-sized frames —
 * the "hover" stability signal (near 0 while the camera is held still over a
 * page, large during motion/hand movement).
 */
fun meanAbsLumaDiff(prev: ByteArray, curr: ByteArray): Double {
    require(prev.size == curr.size) {
        "frame size mismatch: prev=${prev.size} curr=${curr.size}"
    }
    if (prev.isEmpty()) return 0.0
    var sum = 0L
    for (i in prev.indices) {
        val a = prev[i].toInt() and 0xFF
        val b = curr[i].toInt() and 0xFF
        sum += kotlin.math.abs(a - b)
    }
    return sum.toDouble() / prev.size
}

/**
 * Stateful wrapper that scores successive analysis frames, computing
 * stability against the previously seen frame. The first frame has no prior
 * frame to diff against, so it reports [Double.MAX_VALUE] stability (i.e.
 * "not stable") rather than a false 0 — a hover gate needs at least two
 * frames before it can ever pass.
 */
class FrameScorer {
    private var previousLuma: ByteArray? = null

    fun score(luma: ByteArray, width: Int, height: Int, timestampMs: Long): FrameScore {
        val sharpness = varianceOfLaplacian(luma, width, height)
        val prev = previousLuma
        val stability = if (prev != null && prev.size == luma.size) {
            meanAbsLumaDiff(prev, luma)
        } else {
            Double.MAX_VALUE
        }
        previousLuma = luma.copyOf()
        return FrameScore(sharpness, stability, timestampMs)
    }
}
