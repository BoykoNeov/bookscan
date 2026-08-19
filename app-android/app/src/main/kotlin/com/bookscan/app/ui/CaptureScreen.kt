package com.bookscan.app.ui

import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat.getMainExecutor
import com.bookscan.capture.FrameLog
import com.bookscan.capture.FrameLogRow
import com.bookscan.capture.FrameScore
import com.bookscan.capture.FrameScorer
import com.bookscan.capture.HoverCommand
import com.bookscan.capture.HoverGate
import com.bookscan.capture.pickSharpest
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors

/**
 * M3 auto-capture thresholds. UNCALIBRATED — placeholder values, not derived
 * from the pipeline (variance-of-Laplacian on a downsampled on-device luma
 * buffer is not on the pipeline's absolute scale; see
 * [com.bookscan.capture.varianceOfLaplacian]'s doc comment). Must be tuned
 * against real on-device frames (see docs/plans/android-guided-capture.md M3)
 * before this UX is trusted; expect to revisit after first real device use.
 */
private const val SHARPNESS_THRESHOLD = 40.0
private const val STABILITY_THRESHOLD = 6.0
private const val REQUIRED_CONSECUTIVE_FRAMES = 8
private const val MIN_CAPTURE_INTERVAL_MS = 400L
private const val MAX_BURST_SIZE = 4
private val ANALYSIS_RESOLUTION = Size(320, 240)

/**
 * M2's manual shutter capture, plus M3's "hover to capture": an
 * `ImageAnalysis` stream scores every frame for sharpness + stability
 * (mirroring `pipeline/stage00_ingest.py`'s focus metric); once both pass for
 * [REQUIRED_CONSECUTIVE_FRAMES] frames in a row, stills are fired
 * automatically while the hover holds, and only the sharpest of the burst is
 * kept and handed to [onCaptured] — see docs/plans/android-guided-capture.md.
 *
 * Auto-trigger UX is unverified in this environment (no Android SDK here);
 * only the gate/burst decision logic (`:capture` module) has a real test run.
 *
 * Carries a **calibration readout**: the live sharpness/stability numbers, the
 * thresholds they are being compared against, and the pass streak, plus a
 * toggle that records every scored frame to a CSV under [logDir] (the app's
 * external files dir, so `adb pull` reaches it without `run-as`). This exists
 * because [SHARPNESS_THRESHOLD]/[STABILITY_THRESHOLD] are guesses: without
 * numbers on screen, a device session can only report that auto-capture "felt
 * wrong", not by how much.
 */
@Composable
fun CaptureScreen(
    outputDir: File,
    logDir: File,
    onCaptured: (File) -> Unit,
    onCancel: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember { PreviewView(context) }
    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }
    var capturing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    var autoStatus by remember { mutableStateOf("hold steady over the page…") }
    var lastScore by remember { mutableStateOf<FrameScore?>(null) }
    var streak by remember { mutableStateOf(0) }
    var logging by remember { mutableStateOf(false) }
    var logStatus by remember { mutableStateOf<String?>(null) }
    val frameLog = remember { FrameLog() }
    // Writing the CSV touches the disk; the analyzer runs on main. One
    // background thread does the write, mirroring CloseupScreen's executor.
    val ioExecutor = remember { Executors.newSingleThreadExecutor() }
    // Plain remembered list, not Compose State: it's mutated in place from the
    // analyzer callback and never read directly by composition — burst
    // progress is surfaced to the UI via autoStatus (a real State) instead.
    val burstCandidates = remember { mutableListOf<Pair<File, Double>>() }
    val frameScorer = remember { FrameScorer() }
    val hoverGate = remember {
        HoverGate(
            sharpnessThreshold = SHARPNESS_THRESHOLD,
            stabilityThreshold = STABILITY_THRESHOLD,
            requiredConsecutiveFrames = REQUIRED_CONSECUTIVE_FRAMES,
            minCaptureIntervalMs = MIN_CAPTURE_INTERVAL_MS,
            maxBurstSize = MAX_BURST_SIZE,
        )
    }

    fun finalizeBurst() {
        val winner = pickSharpest(burstCandidates)
        burstCandidates.filter { it.first != winner }.forEach { it.first.delete() }
        burstCandidates.clear()
        autoStatus = "hold steady over the page…"
        capturing = false
        // winner can be null if the burst's takePicture callback(s) haven't
        // landed yet when hover breaks (finalize races the async capture) —
        // nothing to hand off; the UI stays interactive for the next hover.
        if (winner != null) {
            onCaptured(winner)
        }
    }

    fun captureAutoFrame(currentSharpness: Double) {
        val capture = imageCapture ?: return
        capturing = true
        val file = File(outputDir, "auto_${System.currentTimeMillis()}_${burstCandidates.size}.jpg")
        capture.takePicture(
            ImageCapture.OutputFileOptions.Builder(file).build(),
            getMainExecutor(context),
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                    burstCandidates.add(file to currentSharpness)
                    autoStatus = "captured ${burstCandidates.size}/$MAX_BURST_SIZE — keep holding…"
                }

                override fun onError(exc: ImageCaptureException) {
                    error = "auto-capture failed: ${exc.message}"
                }
            },
        )
    }

    /**
     * Renders whatever has been recorded so far to a CSV under [logDir] and
     * empties the buffer. The buffer is drained on the main thread (the
     * analyzer's only writer, so no lock is needed) and only the finished
     * string crosses to [ioExecutor] for the actual write.
     */
    fun flushLog() {
        val rows = frameLog.size
        if (rows == 0) {
            logStatus = "nothing recorded yet"
            return
        }
        val dropped = frameLog.dropped
        val csv = frameLog.toCsv()
        frameLog.clear()
        val file = File(logDir, "framelog_${System.currentTimeMillis()}.csv")
        ioExecutor.execute {
            val result = runCatching {
                logDir.mkdirs()
                file.writeText(csv)
            }
            getMainExecutor(context).execute {
                logStatus = result.fold(
                    onSuccess = {
                        val extra = if (dropped > 0) " (+$dropped dropped)" else ""
                        "saved $rows frames$extra → ${file.name}"
                    },
                    onFailure = { "log write failed: ${it.message}" },
                )
            }
        }
    }

    // Keyed on Unit, NOT on the camera effect's lifecycleOwner: if that effect
    // ever restarts without the screen leaving composition, a shutdown executor
    // would make the next flush throw RejectedExecutionException.
    DisposableEffect(Unit) {
        onDispose {
            // Leaving the screen mid-recording must not silently discard the
            // session's frames; shutdown() still runs an already-queued write.
            if (logging && frameLog.size > 0) flushLog()
            ioExecutor.shutdown()
        }
    }

    DisposableEffect(lifecycleOwner) {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
        cameraProviderFuture.addListener(
            {
                val cameraProvider = cameraProviderFuture.get()
                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }
                val capture = ImageCapture.Builder()
                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
                    .build()
                val resolutionSelector = ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(ANALYSIS_RESOLUTION, ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER),
                    )
                    .build()
                val analysis = ImageAnalysis.Builder()
                    .setResolutionSelector(resolutionSelector)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                // Runs on the main executor: frames are decision inputs to Compose
                // state (autoStatus/capturing/burstCandidates), which must only be
                // mutated from the main thread. STRATEGY_KEEP_ONLY_LATEST above
                // drops backlog if a frame ever takes longer than the camera's
                // frame interval, so this doesn't need its own thread pool.
                analysis.setAnalyzer(getMainExecutor(context)) { imageProxy ->
                    try {
                        val (luma, width, height) = imageProxy.toLuma()
                        val score = frameScorer.score(luma, width, height, timestampMs = imageProxy.imageInfo.timestamp / 1_000_000)
                        val passes = hoverGate.passes(score)
                        val command = hoverGate.onFrame(score)
                        lastScore = score
                        streak = hoverGate.consecutivePassCount
                        if (logging) {
                            frameLog.record(
                                FrameLogRow(
                                    timestampMs = score.timestampMs,
                                    sharpness = score.sharpness,
                                    stability = score.stability,
                                    passes = passes,
                                    streak = hoverGate.consecutivePassCount,
                                    command = command.name(),
                                ),
                            )
                        }
                        // Logging is an OBSERVATION mode: the gate still runs and
                        // the CSV records what it would have done, but nothing
                        // fires. Otherwise calibration is impossible — a burst
                        // finalizes in ~1.5s and hands off to the review screen,
                        // so "hold steady for 15s" would only ever yield 1.5s of
                        // data, and would yield a full 15s only when the
                        // thresholds are so tight they never fire (the one case
                        // that teaches nothing about where they should sit).
                        if (!logging) {
                            when (command) {
                                HoverCommand.CaptureNow -> captureAutoFrame(score.sharpness)
                                HoverCommand.FinalizeBurst -> finalizeBurst()
                                HoverCommand.None -> Unit
                            }
                        }
                    } finally {
                        imageProxy.close()
                    }
                }
                cameraProvider.unbindAll()
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    capture,
                    analysis,
                )
                imageCapture = capture
            },
            getMainExecutor(context),
        )
        onDispose { cameraProviderFuture.get().unbindAll() }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        AndroidView(modifier = Modifier.fillMaxSize(), factory = { previewView })

        Column(
            modifier = Modifier.fillMaxSize().padding(24.dp),
            verticalArrangement = Arrangement.Bottom,
        ) {
            // On a scrim, in white: the default theme colour is dark-on-dark
            // over the camera preview, which made the readout unreadable on the
            // first real device — and an unreadable readout is a useless one,
            // since its whole job is to be read while hovering over a page.
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Color.Black.copy(alpha = 0.55f), RoundedCornerShape(8.dp))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(calibrationReadout(lastScore, streak), color = Color.White)
                logStatus?.let { Text(it, color = Color.White) }
                Text(autoStatus, color = Color.White)
                error?.let { Text(it, color = Color(0xFFFF6B6B)) }
            }
            // Own row: three buttons side by side clip on a narrow phone.
            Button(
                enabled = !capturing,
                onClick = {
                    if (logging) {
                        logging = false
                        hoverGate.reset()
                        flushLog()
                    } else {
                        frameLog.clear()
                        logStatus = null
                        hoverGate.reset()
                        logging = true
                    }
                },
            ) {
                Text(if (logging) "Stop log (auto-capture paused)" else "Log frames (calibration)")
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onCancel, enabled = !capturing) { Text("Cancel") }
                Button(
                    enabled = imageCapture != null && !capturing,
                    onClick = {
                        val capture = imageCapture ?: return@Button
                        capturing = true
                        error = null
                        val file = File(outputDir, "capture_${System.currentTimeMillis()}.jpg")
                        capture.takePicture(
                            ImageCapture.OutputFileOptions.Builder(file).build(),
                            getMainExecutor(context),
                            object : ImageCapture.OnImageSavedCallback {
                                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                                    capturing = false
                                    onCaptured(file)
                                }

                                override fun onError(exc: ImageCaptureException) {
                                    capturing = false
                                    error = "capture failed: ${exc.message}"
                                }
                            },
                        )
                    },
                ) {
                    Text(if (capturing) "Capturing…" else "Capture page (manual)")
                }
            }
        }
    }
}

/** Short tag for the CSV's `command` column. */
private fun HoverCommand.name(): String = when (this) {
    HoverCommand.None -> "none"
    HoverCommand.CaptureNow -> "capture"
    HoverCommand.FinalizeBurst -> "finalize"
}

/**
 * The live numbers behind the gate's decision, in the order they matter:
 * is the frame sharp enough, is the phone still enough, how many frames in a
 * row have cleared both. Formatted with [Locale.US] so a comma-decimal device
 * still shows values that match the CSV.
 */
private fun calibrationReadout(score: FrameScore?, streak: Int): String {
    if (score == null) return "sharp — / still — / streak 0/$REQUIRED_CONSECUTIVE_FRAMES"
    val sharpMark = if (score.sharpness >= SHARPNESS_THRESHOLD) "✓" else "✗"
    // The first frame has no predecessor to diff against and reports MAX_VALUE.
    val stillText = if (score.stability >= Double.MAX_VALUE) "—" else String.format(Locale.US, "%.1f", score.stability)
    val stillMark = if (score.stability <= STABILITY_THRESHOLD) "✓" else "✗"
    val sharpText = String.format(Locale.US, "%.1f", score.sharpness)
    return "sharp $sharpText $sharpMark (≥${SHARPNESS_THRESHOLD.toInt()})  " +
        "still $stillText $stillMark (≤${STABILITY_THRESHOLD.toInt()})  " +
        "streak $streak/$REQUIRED_CONSECUTIVE_FRAMES"
}

/**
 * Extracts the Y (luma) plane as a tightly packed `width * height` buffer,
 * honoring row/pixel stride (YUV_420_888 planes are not guaranteed to be
 * contiguous). Row-by-row copy is cheap at [ANALYSIS_RESOLUTION].
 */
private fun ImageProxy.toLuma(): Triple<ByteArray, Int, Int> {
    val yPlane = planes[0]
    val buffer = yPlane.buffer
    val rowStride = yPlane.rowStride
    val pixelStride = yPlane.pixelStride
    val w = width
    val h = height
    val out = ByteArray(w * h)
    val rowBytes = ByteArray(rowStride)
    var outPos = 0
    for (row in 0 until h) {
        buffer.position(row * rowStride)
        val available = buffer.remaining().coerceAtMost(rowStride)
        buffer.get(rowBytes, 0, available)
        for (col in 0 until w) {
            out[outPos++] = rowBytes[col * pixelStride]
        }
    }
    return Triple(out, w, h)
}
