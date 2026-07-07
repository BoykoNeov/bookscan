package com.bookscan.capture

import kotlin.math.roundToInt
import kotlin.math.sqrt

/** Target pixel dimensions for a downscaled close-up, aspect-ratio preserved. */
data class ScaledSize(val width: Int, val height: Int)

/**
 * `fullspread_area_frac` from `pipeline/stage01_fuse.py`'s `DEFAULTS`: Stage 01
 * classifies a frame as a full-spread (anchor) candidate when its pixel area
 * is >= this fraction of the largest frame's area; everything smaller is a
 * close-up to stitch.
 */
const val FULLSPREAD_AREA_FRAC = 0.70

/**
 * Area fraction a close-up is downscaled to before upload: comfortably below
 * [FULLSPREAD_AREA_FRAC] (not just under it), so a close-up can never drift
 * into full-spread territory from rounding or a future threshold tweak on
 * the pipeline side.
 */
const val CLOSEUP_AREA_FRACTION = 0.5

/**
 * Target size for downscaling a close-up still to [areaFraction] of its own
 * captured resolution, aspect ratio preserved. CameraX's `ImageCapture`
 * always saves a close-up at the same sensor resolution as the anchor (zoom
 * narrows field of view, not pixel count) — Stage 01 Fuse's classifier
 * partitions frames purely by `width * height` on disk, not by physical
 * scene coverage, so shrinking the saved dimensions post-capture is what
 * actually makes a close-up read as a close-up.
 *
 * Downscaling (not cropping) is deliberate: at high zoom the user has
 * already framed the region of interest to fill the whole frame, so a
 * further crop would cut into content they just composed. Resampling keeps
 * the full framed region while still delivering a real DPI win on it (the
 * whole point of a close-up) — e.g. a 3x optical/digital zoom downscaled by
 * sqrt(0.5) is still ~2.1x the anchor's effective resolution on that patch.
 */
fun scaledCloseupSize(fullWidth: Int, fullHeight: Int, areaFraction: Double = CLOSEUP_AREA_FRACTION): ScaledSize {
    require(fullWidth > 0 && fullHeight > 0) { "fullWidth/fullHeight must be positive" }
    require(areaFraction > 0.0 && areaFraction < 1.0) { "areaFraction must be in (0, 1)" }
    val scale = sqrt(areaFraction)
    val w = (fullWidth * scale).roundToInt().coerceIn(1, fullWidth)
    val h = (fullHeight * scale).roundToInt().coerceIn(1, fullHeight)
    return ScaledSize(w, h)
}
