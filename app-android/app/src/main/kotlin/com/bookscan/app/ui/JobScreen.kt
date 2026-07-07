package com.bookscan.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.bookscan.app.UiState
import com.bookscan.network.STAGE_ORDER

/**
 * M1 scope: one job, one gallery-picked frame upload, polled status. Job
 * list/resume (GET /api/jobs) is M5. Camera capture is M2/M3.
 */
@Composable
fun JobScreen(
    state: UiState.Ready,
    onCreateJob: () -> Unit,
    onPickAndUploadFrame: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Server: ${state.serverUrl}")

        if (state.jobId == null) {
            Button(onClick = onCreateJob) { Text("New job") }
        } else {
            Text("Job: ${state.jobId}")
            Button(onClick = onPickAndUploadFrame, enabled = !state.uploading) {
                Text(if (state.uploading) "Uploading…" else "Pick image & upload as page")
            }
            if (state.uploading) CircularProgressIndicator()
        }

        state.error?.let { Text(it, color = Color.Red) }

        state.jobStatus?.pages?.let { pages ->
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(pages) { page ->
                    Column {
                        Text(page.name, color = Color.Black)
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
