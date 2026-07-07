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
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
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
import com.bookscan.capture.FrameScorer
import com.bookscan.capture.HoverCommand
import com.bookscan.capture.HoverGate
import com.bookscan.capture.pickSharpest
import java.io.File

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
 */
@Composable
fun CaptureScreen(
    outputDir: File,
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
                        when (hoverGate.onFrame(score)) {
                            HoverCommand.CaptureNow -> captureAutoFrame(score.sharpness)
                            HoverCommand.FinalizeBurst -> finalizeBurst()
                            HoverCommand.None -> Unit
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
            Text(autoStatus)
            error?.let { Text(it, color = Color.Red) }
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
