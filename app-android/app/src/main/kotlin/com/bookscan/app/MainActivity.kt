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
    // `anchors` is the whole auto-capture burst, best-guess first: Stage 01
    // selects the sharpest at full resolution, so the phone does not throw the
    // rest away. A manual shot is a one-element list.
    data class CapturingCloseup(val anchors: List<File>, val closeups: List<File>) : CaptureFlow

    /**
     * Re-entering the capture screen to add ANOTHER whole-spread shot to a
     * spread already under review. Several full views of the same spread are
     * worth uploading: Stage 01 keeps the sharpest as the anchor and the
     * selector has been measured to pick the better of two real full-spread
     * frames (RESULTS 2026-08-19, `zoomset_en_02`). They are NOT stitched —
     * blending was measured to make OCR worse — so extra views cost bytes and
     * buy a better anchor, nothing else.
     */
    data class CapturingMoreAnchors(val anchors: List<File>, val closeups: List<File>) : CaptureFlow
    data class ReviewingSpread(val anchors: List<File>, val closeups: List<File>) : CaptureFlow
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
            // The thresholds are fitted (2026-08-19), and the confirmation run
            // this default was waiting on HAPPENED on 2026-08-28 — it went the
            // other way. Armed over a real spread the burst delivered ONE shot,
            // not the four the hysteresis fix was measured to give, because the
            // replay those four came from was recorded with capture suspended
            // and so contains no frame from just after a shutter fires. Manual
            // capture is therefore the default flow and auto-capture is an
            // opt-in toggle (owner's call, 2026-08-28). Do not flip this to
            // true without a device run that shows a burst of more than one.
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
                                onCaptured = { files -> flow = CaptureFlow.ReviewingSpread(files, emptyList()) },
                                onCancel = { flow = CaptureFlow.Hidden },
                            )

                            is CaptureFlow.CapturingMoreAnchors -> CaptureScreen(
                                outputDir = cacheDir,
                                logDir = getExternalFilesDir(null) ?: cacheDir,
                                autoArmed = autoArmed,
                                onAutoArmedChange = { autoArmed = it },
                                // Appends and STAYS, same reason as the
                                // close-up screen: taking several shots of one
                                // spread is the point, so each must not cost a
                                // round trip through review.
                                onCaptured = { files ->
                                    flow = CaptureFlow.CapturingMoreAnchors(f.anchors + files, f.closeups)
                                },
                                onCancel = { flow = CaptureFlow.ReviewingSpread(f.anchors, f.closeups) },
                                cancelLabel = "Done",
                                capturedCount = f.anchors.size,
                            )

                            is CaptureFlow.CapturingCloseup -> CloseupScreen(
                                outputDir = cacheDir,
                                closeupCount = f.closeups.size,
                                // STAYS on the close-up screen and appends.
                                // Returning to review after every shot made
                                // capturing several close-ups — the normal
                                // case — a re-entry per shot (owner, on the
                                // device, 2026-08-28). "Done" is the way back.
                                onCaptured = { file ->
                                    flow = CaptureFlow.CapturingCloseup(f.anchors, f.closeups + file)
                                },
                                onDone = { flow = CaptureFlow.ReviewingSpread(f.anchors, f.closeups) },
                            )

                            is CaptureFlow.ReviewingSpread -> SpreadReviewScreen(
                                anchors = f.anchors,
                                closeups = f.closeups,
                                uploading = s.uploading,
                                error = s.error,
                                onAddAnchor = { flow = CaptureFlow.CapturingMoreAnchors(f.anchors, f.closeups) },
                                onAddCloseup = { flow = CaptureFlow.CapturingCloseup(f.anchors, f.closeups) },
                                onUpload = {
                                    viewModel.uploadSpread(f.anchors, f.closeups)
                                    flow = CaptureFlow.Hidden
                                },
                                onDiscard = {
                                    f.anchors.forEach { it.delete() }
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
