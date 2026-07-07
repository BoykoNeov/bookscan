package com.bookscan.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import com.bookscan.capture.CLOSEUP_AREA_FRACTION
import com.bookscan.capture.scaledCloseupSize
import java.io.File
import java.io.FileOutputStream

private const val JPEG_QUALITY = 92

/**
 * Downscales [srcFile] (a full-resolution close-up still) to
 * [CLOSEUP_AREA_FRACTION] of its own area and overwrites it in place — see
 * [scaledCloseupSize] for why this is a resample, not a crop, and why the
 * fraction is applied to the close-up's own resolution rather than the
 * anchor's (CameraX zoom narrows field of view, not pixel count, so a
 * close-up is captured at the same sensor resolution as the anchor; only
 * this downscale actually shrinks its saved pixel area, which is what Stage
 * 01 Fuse's `fullspread_area_frac` classifier keys on).
 *
 * Bakes in EXIF orientation before re-encoding: `pipeline/stage00_ingest.py`
 * applies `exif_transpose` to every ingested frame, but decoding through
 * `BitmapFactory` and re-saving via `Bitmap.compress` does not carry the
 * source JPEG's orientation tag forward — without correcting for it here, a
 * rotated close-up would desync from the anchor before Stage 01's ORB stitch
 * ever sees them, and look like a pipeline bug when it's actually app-side.
 */
fun downscaleCloseupInPlace(srcFile: File) {
    val orientation = ExifInterface(srcFile.path)
        .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)

    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(srcFile.path, bounds)
    val target = scaledCloseupSize(bounds.outWidth, bounds.outHeight)

    val decoded = BitmapFactory.decodeFile(srcFile.path)
        ?: error("unreadable close-up capture: ${srcFile.path}")
    val upright = applyExifOrientation(decoded, orientation)
    val scaled = Bitmap.createScaledBitmap(upright, target.width, target.height, true)

    FileOutputStream(srcFile).use { out -> scaled.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out) }

    if (upright !== decoded) decoded.recycle()
    if (scaled !== upright) upright.recycle()
    scaled.recycle()
}

private fun applyExifOrientation(bitmap: Bitmap, orientation: Int): Bitmap {
    val matrix = Matrix()
    when (orientation) {
        ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
        ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
        ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(270f)
        ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.postScale(-1f, 1f)
        ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.postScale(1f, -1f)
        ExifInterface.ORIENTATION_TRANSPOSE -> {
            matrix.postRotate(90f)
            matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_TRANSVERSE -> {
            matrix.postRotate(270f)
            matrix.postScale(-1f, 1f)
        }
        else -> return bitmap
    }
    return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
}
