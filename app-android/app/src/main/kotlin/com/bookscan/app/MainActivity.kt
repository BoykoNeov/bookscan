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
            // Auto-capture starts DISARMED, and the choice is session-wide so it
            // survives Discard → re-enter. Armed-on-entry made the capture
            // screen unusable for calibration: a passing streak is 8 frames
            // (~0.3 s at 30 fps), so it fired and handed off to the review
            // screen before the calibration button could be tapped at all.
            // FLIP THIS BACK TO true ONLY AFTER BOTH THRESHOLDS ARE FITTED —
            // it is not a UX preference. Today SHARPNESS_THRESHOLD (40) sits
            // two orders of magnitude below the measured range (231–1567), so
            // the only gate doing any work is a stability threshold sitting at
            // the median of the data. Auto-firing on that is firing at random.
            var autoArmed by remember { mutableStateOf(false) }

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
                                onResumeJob = viewModel::resumeJob,
                                onRefreshJobs = viewModel::loadJobs,
                            )

                            CaptureFlow.CapturingAnchor -> CaptureScreen(
                                outputDir = cacheDir,
                                // External files dir, not cacheDir: calibration
                                // CSVs are meant to be pulled off the device
                                // (`adb pull /sdcard/Android/data/<pkg>/files/`),
                                // which internal storage would need `run-as` for.
                                logDir = getExternalFilesDir(null) ?: cacheDir,
                                autoArmed = autoArmed,
                                onAutoArmedChange = { autoArmed = it },
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
