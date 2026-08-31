package com.bookscan.app.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.unit.dp
import java.io.File

private const val THUMBNAIL_SAMPLE_SIZE = 8

/**
 * M4's review step between capture and upload: shows every shot of the spread
 * (several manual shots of the same spread, or an auto-capture burst) plus any
 * close-ups captured so far, lets the user add more or finish — upload sends
 * them all together in one
 * `POST /api/jobs/{id}/pages` request (server/routes_jobs.py; Stage 01 Fuse
 * classifies anchor-vs-closeup by area itself, no per-file tagging needed).
 * See docs/plans/android-guided-capture.md.
 *
 * Close-ups arrive two ways: one tap each ([CloseupScreen]) or a continuous
 * sweep across the page ([SweepScreen]). Both produce the same thing — the
 * sweep exists because one tap per close-up is why few get taken.
 *
 * Finishing a spread offers three exits, not one. "Upload spread" sends it now
 * — the flow verified on a real phone on 2026-08-28. The two "Save" actions put
 * it in the batch instead (`com.bookscan.capture.CaptureQueue`) so a whole book
 * can be photographed first and sent afterwards, which is what shooting a book
 * over a flaky link actually needs.
 */
@Composable
fun SpreadReviewScreen(
    anchors: List<File>,
    closeups: List<File>,
    uploading: Boolean,
    error: String?,
    queued: Int,
    onAddAnchor: () -> Unit,
    onAddCloseup: () -> Unit,
    onSweep: () -> Unit,
    onSaveAndNext: () -> Unit,
    onSaveAndStop: () -> Unit,
    onUpload: () -> Unit,
    onDiscard: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Spread captured — ${anchors.size} shot(s), ${closeups.size} close-up(s)")
        if (queued > 0) Text("$queued page(s) already waiting to upload")

        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(anchors + closeups) { file -> Thumbnail(file) }
        }

        error?.let { Text(it, color = Color.Red) }

        // Strictly TWO buttons per row: four labels side by side already
        // clipped on a narrow phone, and this screen now has six actions.
        // Order is by how often each is used when photographing a book —
        // "Save & next page" is the one tapped once per page, so it leads its
        // row and is the filled button; sending a single spread on its own is
        // the exception now, not the rule.
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onAddAnchor, enabled = !uploading) { Text("Add full shot") }
            Button(onClick = onAddCloseup, enabled = !uploading) { Text("Add close-up") }
        }
        // Own row, and worded as what it does rather than "sweep": it banks
        // ordinary close-ups, just many of them per pass instead of one per
        // tap. Nothing downstream treats them differently — see SweepScreen.
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onSweep, enabled = !uploading) { Text("Sweep close-ups") }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onSaveAndNext, enabled = !uploading) { Text("Save & next page") }
            OutlinedButton(onClick = onSaveAndStop, enabled = !uploading) { Text("Save & stop") }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            OutlinedButton(onClick = onDiscard, enabled = !uploading) { Text("Discard") }
            OutlinedButton(onClick = onUpload, enabled = !uploading) {
                Text(if (uploading) "Uploading…" else "Upload spread now")
            }
        }
        if (uploading) CircularProgressIndicator()
    }
}

/** Decoded at a fixed downsample — these are local review thumbnails, not full-res previews. */
@Composable
private fun Thumbnail(file: File) {
    val bitmap = remember(file.path) {
        val options = BitmapFactory.Options().apply { inSampleSize = THUMBNAIL_SAMPLE_SIZE }
        BitmapFactory.decodeFile(file.path, options)
    }
    if (bitmap != null) {
        Image(bitmap = bitmap.asImageBitmap(), contentDescription = file.name, modifier = Modifier.size(96.dp))
    } else {
        Text(file.name)
    }
}
