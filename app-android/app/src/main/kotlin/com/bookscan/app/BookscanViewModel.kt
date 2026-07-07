package com.bookscan.app

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.bookscan.network.BookscanApi
import com.bookscan.network.BookscanClientFactory
import com.bookscan.network.JobStatus
import com.bookscan.network.multipartPart
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.File

sealed interface UiState {
    data object ServerSetup : UiState

    data class Ready(
        val serverUrl: String,
        val jobId: String? = null,
        val jobStatus: JobStatus? = null,
        val uploading: Boolean = false,
        val error: String? = null,
    ) : UiState
}

private const val POLL_INTERVAL_MS = 2000L

/**
 * Server address entry, job creation, spread upload (anchor + any close-ups
 * captured for it, M4), status polling. No retry/backoff yet — that's M5
 * (docs/plans/android-guided-capture.md).
 */
class BookscanViewModel(application: Application) : AndroidViewModel(application) {
    private val prefs = ServerPrefs(application)

    private val _state = MutableStateFlow<UiState>(
        prefs.serverUrl?.let { UiState.Ready(serverUrl = it) } ?: UiState.ServerSetup
    )
    val state: StateFlow<UiState> = _state.asStateFlow()

    private var api: BookscanApi? = null
    private var pollJob: Job? = null

    init {
        prefs.serverUrl?.let { api = BookscanClientFactory.create(it) }
    }

    fun setServerUrl(url: String) {
        val normalized = if (url.startsWith("http")) url else "http://$url"
        prefs.serverUrl = normalized
        api = BookscanClientFactory.create(normalized)
        _state.value = UiState.Ready(serverUrl = normalized)
    }

    fun createJob() {
        val api = api ?: return
        viewModelScope.launch {
            try {
                val res = api.createJob()
                updateReady { it.copy(jobId = res.job_id, jobStatus = null, error = null) }
                startPolling(res.job_id)
            } catch (e: Exception) {
                updateReady { it.copy(error = "create job failed: ${e.message}") }
            }
        }
    }

    /**
     * [anchor] and [closeups] are one spread's capture frames, uploaded
     * together in a single multipart request — [anchor] is always index 0
     * ("frame_00" server-side); Stage 01 Fuse classifies anchor-vs-closeup by
     * area itself (see docs/plans/android-guided-capture.md M4).
     */
    fun uploadSpread(anchor: File, closeups: List<File>) {
        val api = api ?: return
        val jobId = (_state.value as? UiState.Ready)?.jobId ?: return
        viewModelScope.launch {
            updateReady { it.copy(uploading = true, error = null) }
            try {
                val parts = (listOf(anchor) + closeups).mapIndexed { index, file -> multipartPart(index, file) }
                api.uploadPage(jobId, parts)
                refreshStatus(jobId)
            } catch (e: Exception) {
                updateReady { it.copy(error = "upload failed: ${e.message}") }
            } finally {
                updateReady { it.copy(uploading = false) }
            }
        }
    }

    private fun startPolling(jobId: String) {
        pollJob?.cancel()
        pollJob = viewModelScope.launch {
            while (true) {
                refreshStatus(jobId)
                delay(POLL_INTERVAL_MS)
            }
        }
    }

    private suspend fun refreshStatus(jobId: String) {
        val api = api ?: return
        try {
            val status = api.getJobStatus(jobId)
            updateReady { it.copy(jobStatus = status, error = null) }
        } catch (e: Exception) {
            updateReady { it.copy(error = "status poll failed: ${e.message}") }
        }
    }

    private fun updateReady(transform: (UiState.Ready) -> UiState.Ready) {
        (_state.value as? UiState.Ready)?.let { _state.value = transform(it) }
    }

    override fun onCleared() {
        pollJob?.cancel()
        super.onCleared()
    }
}
