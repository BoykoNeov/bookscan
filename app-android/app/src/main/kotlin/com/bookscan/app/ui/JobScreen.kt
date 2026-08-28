package com.bookscan.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.bookscan.app.UiState
import com.bookscan.network.STAGE_ORDER

/** Stage 06's three modes, in server/jobs.py's MODES order; sent as the `mode` query param. */
private val UNCERTAINTY_MODES = listOf("flag", "best_guess", "patch")

/** What each mode does to a word the OCR is unsure of, in the user's terms. */
private val MODE_LABELS = mapOf(
    "flag" to "highlight them",
    "best_guess" to "just print the best guess",
    "patch" to "show a picture of the word",
)

/**
 * No job picked: list existing jobs (`GET /api/jobs`, M5) to resume, or start
 * a new one. Job picked: capture trigger + per-page pipeline progress via
 * polled `GET /api/jobs/{id}` (docs/plans/android-guided-capture.md).
 */
@Composable
fun JobScreen(
    state: UiState.Ready,
    onCreateJob: (String) -> Unit,
    onCapturePage: () -> Unit,
    onResumeJob: (String) -> Unit,
    onRefreshJobs: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Server: ${state.serverUrl}")

        if (state.jobId == null) {
            // Stage 06's uncertainty mode, chosen per job because the server
            // persists it per job and the worker reads it for every page.
            // Fixed at "flag" until 2026-08-28 — the picker did not exist, so
            // two of the three modes CLAUDE.md requires were unreachable from
            // the phone even though the server had supported them since
            // commit ecc9993.
            var mode by remember { mutableStateOf(UNCERTAINTY_MODES.first()) }
            Text("Uncertain words: ${MODE_LABELS[mode]}")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                UNCERTAINTY_MODES.forEach { choice ->
                    if (choice == mode) {
                        Button(onClick = { mode = choice }) { Text(choice) }
                    } else {
                        OutlinedButton(onClick = { mode = choice }) { Text(choice) }
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = { onCreateJob(mode) }) { Text("New job") }
                Button(onClick = onRefreshJobs) { Text("Refresh jobs") }
            }
            state.error?.let { Text(it, color = Color.Red) }
            LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                items(state.jobs) { job ->
                    Text(
                        job.job_id,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onResumeJob(job.job_id) }
                            .padding(8.dp),
                    )
                }
            }
        } else {
            Text("Job: ${state.jobId}")
            Button(onClick = onCapturePage, enabled = !state.uploading) {
                Text(if (state.uploading) "Uploading…" else "Capture page")
            }
            if (state.uploading) CircularProgressIndicator()

            state.error?.let { Text(it, color = Color.Red) }

            state.jobStatus?.pages?.let { pages ->
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(pages) { page ->
                        Column {
                            Text(page.name, color = Color.Black)
                            val doneCount = STAGE_ORDER.count { page.stages[it] != null }
                            LinearProgressIndicator(
                                progress = { doneCount / STAGE_ORDER.size.toFloat() },
                                modifier = Modifier.fillMaxWidth(),
                            )
                            Text("$doneCount/${STAGE_ORDER.size} stages")
                            val summary = STAGE_ORDER.joinToString(" ") { stageName ->
                                when (page.stages[stageName]?.ok) {
                                    true -> "$stageName✓"
                                    false -> "$stageName✗"
                                    null -> "$stageName…"
                                }
                            }
                            Text(summary)
                        }
                    }
                }
            }
        }
    }
}
