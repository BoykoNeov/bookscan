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
 */
@Composable
fun SpreadReviewScreen(
    anchors: List<File>,
    closeups: List<File>,
    uploading: Boolean,
    error: String?,
    onAddAnchor: () -> Unit,
    onAddCloseup: () -> Unit,
    onUpload: () -> Unit,
    onDiscard: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Spread captured — ${anchors.size} shot(s), ${closeups.size} close-up(s)")

        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(anchors + closeups) { file -> Thumbnail(file) }
        }

        error?.let { Text(it, color = Color.Red) }

        // Two rows: four labels side by side clip on a narrow phone. The
        // "add" pair leads because the manual flow is several shots of the
        // same spread — take them all, then upload once.
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onAddAnchor, enabled = !uploading) { Text("Add full shot") }
            Button(onClick = onAddCloseup, enabled = !uploading) { Text("Add close-up") }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onDiscard, enabled = !uploading) { Text("Discard") }
            Button(onClick = onUpload, enabled = !uploading) {
                Text(if (uploading) "Uploading…" else "Upload spread")
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
