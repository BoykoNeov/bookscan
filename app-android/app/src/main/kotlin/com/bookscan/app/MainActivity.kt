package com.bookscan.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.bookscan.app.ui.CaptureScreen
import com.bookscan.app.ui.CloseupScreen
import com.bookscan.app.ui.JobScreen
import com.bookscan.app.ui.ServerSetupScreen
import com.bookscan.app.ui.SpreadReviewScreen
import java.io.File

/**
 * Drives one spread's capture: anchor first (M2/M3's [CaptureScreen],
 * unchanged), then M4's review/close-up loop before upload. See
 * docs/plans/android-guided-capture.md.
 */
private sealed interface CaptureFlow {
    data object Hidden : CaptureFlow
    data object CapturingAnchor : CaptureFlow
    data class CapturingCloseup(val anchor: File, val closeups: List<File>) : CaptureFlow
    data class ReviewingSpread(val anchor: File, val closeups: List<File>) : CaptureFlow
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val viewModel: BookscanViewModel = viewModel()
            val state by viewModel.state.collectAsState()
            var flow by remember { mutableStateOf<CaptureFlow>(CaptureFlow.Hidden) }

            val requestCameraPermission = rememberLauncherForActivityResult(
                ActivityResultContracts.RequestPermission(),
            ) { granted -> if (granted) flow = CaptureFlow.CapturingAnchor }

            fun openCapture() {
                val granted = ContextCompat.checkSelfPermission(
                    this@MainActivity,
                    Manifest.permission.CAMERA,
                ) == PackageManager.PERMISSION_GRANTED
                if (granted) flow = CaptureFlow.CapturingAnchor else requestCameraPermission.launch(Manifest.permission.CAMERA)
            }

            MaterialTheme {
                Surface(modifier = Modifier) {
                    when (val s = state) {
                        is UiState.ServerSetup -> ServerSetupScreen(onConnect = viewModel::setServerUrl)
                        is UiState.Ready -> when (val f = flow) {
                            CaptureFlow.Hidden -> JobScreen(
                                state = s,
                                onCreateJob = viewModel::createJob,
                                onCapturePage = ::openCapture,
                            )

                            CaptureFlow.CapturingAnchor -> CaptureScreen(
                                outputDir = cacheDir,
                                onCaptured = { file -> flow = CaptureFlow.ReviewingSpread(file, emptyList()) },
                                onCancel = { flow = CaptureFlow.Hidden },
                            )

                            is CaptureFlow.CapturingCloseup -> CloseupScreen(
                                outputDir = cacheDir,
                                closeupCount = f.closeups.size,
                                onCaptured = { file -> flow = CaptureFlow.ReviewingSpread(f.anchor, f.closeups + file) },
                                onDone = { flow = CaptureFlow.ReviewingSpread(f.anchor, f.closeups) },
                            )

                            is CaptureFlow.ReviewingSpread -> SpreadReviewScreen(
                                anchor = f.anchor,
                                closeups = f.closeups,
                                uploading = s.uploading,
                                error = s.error,
                                onAddCloseup = { flow = CaptureFlow.CapturingCloseup(f.anchor, f.closeups) },
                                onUpload = {
                                    viewModel.uploadSpread(f.anchor, f.closeups)
                                    flow = CaptureFlow.Hidden
                                },
                                onDiscard = {
                                    f.anchor.delete()
                                    f.closeups.forEach { it.delete() }
                                    flow = CaptureFlow.Hidden
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}
