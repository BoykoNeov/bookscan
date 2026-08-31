package com.bookscan.app.ui

import android.util.Size
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
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
import androidx.compose.material3.OutlinedButton
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
import com.bookscan.app.downscaleCloseupInPlace
import com.bookscan.capture.FrameLog
import com.bookscan.capture.FrameLogRow
import com.bookscan.capture.FrameScore
import com.bookscan.capture.FrameScorer
import com.bookscan.capture.SweepCommand
import com.bookscan.capture.SweepGate
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors

/**
 * Sharpness floor for a sweep frame, on the same metric and the same 320x240
 * luma buffer [CaptureScreen] scores — so this is [CaptureScreen]'s own fitted
 * 400.0, reused, not a new guess. On the 2026-08-19 *moving* recording (633
 * frames, 21 s of deliberate hand motion) **45 %** of frames clear it, so it
 * rejects roughly the blurrier half of a hand sweep while leaving a shot
 * available several times a second.
 *
 * It is NOT re-fitted for motion, because nothing in that session recorded a
 * sweep: the calibration logs are a hold, a re-frame and mixed use. Fitting it
 * properly needs a sweep log off this screen — which is what the "Log frames"
 * button is for.
 */
private const val SWEEP_SHARPNESS_THRESHOLD = 400.0

/**
 * Accumulated travel required between shots, in units of [FrameScore.stability]
 * excess (see [SweepGate] for what that proxy can and cannot say). Replayed
 * through the shipped rule over the three 2026-08-19 recordings
 * (`tools/calibrate_sweep.py`, `docs/data/sweep_calibration_20260831.json`):
 * on 21 s of real hand motion it fills the whole [SWEEP_MAX_FRAMES] budget in
 * **20.5 s**, a median **834 ms** apart, which is a sweep of a spread rather
 * than a burst.
 *
 * **200 is where a standing phone goes silent, and that is why it is 200 and
 * not 150.** On the 23 s steady recording 150 still fires a second shot — a
 * duplicate of one patch out of 24 — and 200 fires only the mandatory first.
 * On the moving log 100/150/200 are indistinguishable (all hit the cap), so
 * nothing is paid for the margin.
 *
 * **This is a rate, not an overlap guarantee.** The proxy cannot say how far
 * the page moved, only that the picture changed; a threshold that guarantees
 * a given overlap needs registration, which is the large build.
 */
private const val SWEEP_MOTION_THRESHOLD = 200.0

/**
 * Per-frame motion below this is hand tremor at a standing phone, not travel,
 * and banks nothing — 3.1 is the value `HoverGate`'s 2026-08-19 fit separates
 * still from moving at, reused for exactly the thing it measured. Without it
 * a held phone accumulates ~1.06 a frame and fires a duplicate every few
 * seconds; with it, six spurious shots across the steady recording become zero.
 */
private const val SWEEP_IDLE_STABILITY_FLOOR = 3.1

/** Shutter cadence floor, same as the hover burst's. */
private const val SWEEP_MIN_INTERVAL_MS = 400L

/**
 * Interval for the time-only fallback (motion gating off) — deliberately
 * slower than [SWEEP_MIN_INTERVAL_MS], because with nothing watching the view
 * a 400 ms cadence would spend the whole frame budget in ten seconds
 * regardless of whether the phone moved at all.
 */
private const val SWEEP_TIMED_INTERVAL_MS = 800L

/**
 * Close-up budget for a whole **spread**, not for one sweep run — and it is a
 * budget because it bounds an HTTP request, not just storage.
 * `BookscanViewModel.sendSpread` puts every file of a spread into a single
 * multipart POST because `server/routes_jobs.py::upload_page` names pages
 * `page_NNN` by arrival order, so a spread cannot be split across requests
 * without renumbering every page after it. At the ~1-2 MB a downscaled close-up
 * weighs, 24 of them plus the anchor is a request in the tens of megabytes,
 * inside the client's 60 s write timeout over local Wi-Fi. A whole book's worth
 * also sits in `filesDir` until it is uploaded.
 *
 * **Per-spread is load-bearing.** A spread normally gets several passes (left
 * half, right half, one at a tighter zoom) and [SweepGate.start] resets its own
 * count, so a per-run cap would bound nothing: three runs would be 72 frames in
 * one POST. Every close-up already on the spread is counted against this,
 * tapped ones included, because they travel in the same request.
 */
private const val SWEEP_MAX_FRAMES = 24

/**
 * At most this many stills may be in flight at once. `takePicture` is async
 * and queues; at a 400 ms cadence with
 * [ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY] (which does multi-frame work
 * per shot) requests can arrive faster than they complete, and an unbounded
 * queue would keep firing long after the operator stopped sweeping.
 */
private const val MAX_IN_FLIGHT = 2

/**
 * Zoom steps, starting at 2x rather than 1x: a sweep exists to gather pixels
 * the whole-spread shot does not have, and at 1x it would gather none. The
 * measured framing of the close-ups shot so far is a median 1.30x linear,
 * which is the reason reading them separately gains almost nothing
 * (docs/RESULTS.md 2026-08-29) — so 3x is the default here.
 */
private val SWEEP_ZOOM_STEPS = listOf(2f, 3f, 4f, 6f)
private const val DEFAULT_SWEEP_ZOOM = 3f

private val ANALYSIS_RESOLUTION = Size(320, 240)

private const val BYTES_PER_MB = 1024.0 * 1024.0

/**
 * Continuous "sweep" capture: hold a zoom, slide the phone across the spread,
 * and a still is taken every time the view has travelled far enough — instead
 * of one tap per close-up ([CloseupScreen]).
 *
 * **This is the capture half only, and it deliberately stitches nothing.** The
 * frames it produces are ordinary close-ups: they go into the same
 * `PendingSpread`, the same single multipart upload, and the same Stage 01
 * area classifier as a tapped one, and they are downscaled by the same
 * [downscaleCloseupInPlace] for the same reason (an un-downscaled frame is
 * over `fullspread_area_frac` and would compete to be the *anchor*). There is
 * no panorama consumer in the pipeline to build against: Phase 2 of
 * `docs/plans/panorama-and-next-steps.md` returned **no verdict** on 2026-08-31
 * — of 40 close-ups only 5 cleared the admission bar and 4 of those landed on
 * one topographic map — and Phase 1 is explicitly not licensed. What this
 * screen exists to remove is the reason there is no better data: gathering
 * close-ups over *text* currently costs one tap each, so nobody gathers them.
 *
 * **The gate is [SweepGate], never [com.bookscan.capture.HoverGate].** The
 * hover gate is fitted to fire because the phone is *still* (zero bursts across
 * a 21 s moving recording); a sweep is motion. See [SweepGate] on why the two
 * calibrations must not be merged.
 *
 * Carries the same calibration readout and CSV logging as [CaptureScreen], for
 * the same reason: [SWEEP_MOTION_THRESHOLD] is anchored to a recording of hand
 * motion, not of a page sweep, so the first device session has to be able to
 * report *by how much* it is wrong rather than that it "felt wrong".
 *
 * Camera/UX behaviour here is unverified without a device, same caveat as the
 * other two capture screens; only [SweepGate]'s decision logic has a real test
 * run.
 */
@Composable
fun SweepScreen(
    outputDir: File,
    logDir: File,
    /**
     * Close-ups already banked on this spread — the whole list, not a count, so
     * the screen can show the operator the size of the upload they are building
     * as well as budget against [SWEEP_MAX_FRAMES]. See that constant on why
     * both are per-spread.
     */
    existingCloseups: List<File>,
    onCaptured: (List<File>) -> Unit,
    onDone: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember { PreviewView(context) }
    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }
    var camera by remember { mutableStateOf<Camera?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    var sweeping by remember { mutableStateOf(false) }
    var motionGated by remember { mutableStateOf(true) }
    var zoom by remember { mutableStateOf(DEFAULT_SWEEP_ZOOM) }
    var lastScore by remember { mutableStateOf<FrameScore?>(null) }
    var banked by remember { mutableStateOf(0) }
    var bankedBytes by remember { mutableStateOf(0L) }
    var dropped by remember { mutableStateOf(0) }

    // Recomputed whenever the caller hands the screen a longer list, which it
    // does after every completed run — this is the whole-spread view that both
    // the frame budget and the upload size are about.
    val priorCount = existingCloseups.size
    val priorBytes = remember(existingCloseups) { existingCloseups.sumOf { it.length() } }
    val remainingBudget = (SWEEP_MAX_FRAMES - priorCount).coerceAtLeast(0)
    var motionNow by remember { mutableStateOf(0.0) }
    var logging by remember { mutableStateOf(false) }
    var logStatus by remember { mutableStateOf<String?>(null) }
    var status by remember { mutableStateOf("pick a zoom, aim at one end of the page, then Start sweep") }

    val frameScorer = remember { FrameScorer() }
    val frameLog = remember { FrameLog() }
    // Mutated in place from the analyzer (main thread) and from the capture
    // callback marshalled back to main; never read by composition, which reads
    // the `banked`/`bankedBytes` State mirrors instead.
    val shots = remember { mutableListOf<File>() }
    var inFlight by remember { mutableStateOf(0) }

    // downscaleCloseupInPlace is a full decode + rotate + scale + re-encode of
    // a full-resolution still — hundreds of ms that must not land on main,
    // where the analyzer runs. Same split as CloseupScreen.
    val ioExecutor = remember { Executors.newSingleThreadExecutor() }

    // Two gates are never alive at once, but the parameters differ per mode,
    // so the gate is rebuilt at each Start rather than reconfigured.
    var gate by remember { mutableStateOf<SweepGate?>(null) }

    /**
     * [cap] is what is LEFT of the spread's budget, not [SWEEP_MAX_FRAMES] — the
     * gate resets its own count at every [SweepGate.start], so budgeting across
     * runs is the caller's job.
     *
     * A logging gate gets no cap at all. Its fires are virtual, and a capped one
     * would disarm itself partway through a recording: every row after that
     * would report a stopped gate, quietly turning the rest of a calibration
     * session into rows describing nothing.
     */
    fun newGate(motion: Boolean, cap: Int) = SweepGate(
        sharpnessThreshold = SWEEP_SHARPNESS_THRESHOLD,
        motionThreshold = if (motion) SWEEP_MOTION_THRESHOLD else null,
        idleStabilityFloor = SWEEP_IDLE_STABILITY_FLOOR,
        minCaptureIntervalMs = if (motion) SWEEP_MIN_INTERVAL_MS else SWEEP_TIMED_INTERVAL_MS,
        maxFrames = cap,
    )

    /**
     * Renders whatever has been recorded to a CSV under [logDir] and empties
     * the buffer — copied in shape from [CaptureScreen.flushLog]: the buffer is
     * drained on main (its only writer) and only the finished string crosses to
     * [ioExecutor].
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
        val file = File(logDir, "sweeplog_${System.currentTimeMillis()}.csv")
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

    /**
     * Ends the sweep and hands every frame taken so far to [onCaptured].
     *
     * Frames still in flight are NOT waited for: `takePicture` is async and the
     * operator's Stop is immediate, so a shot whose callback has not landed is
     * dropped by the same rule [CaptureScreen] uses (the callback deletes its
     * file when the sweep is over). Losing the last frame of 24 is cheaper than
     * a screen that will not close.
     */
    fun finishSweep(reason: String) {
        gate?.stop()
        sweeping = false
        val taken = shots.toList()
        shots.clear()
        banked = 0
        bankedBytes = 0L
        motionNow = 0.0
        status = if (taken.isEmpty()) "$reason — nothing captured" else "$reason — ${taken.size} frame(s) added"
        if (taken.isNotEmpty()) onCaptured(taken)
    }

    /**
     * The callback is delivered on the MAIN executor and only the pixel work is
     * pushed to [ioExecutor] — not the other way round. Deciding whether to
     * keep the shot means reading `sweeping`/`logging`, and Compose state has
     * no cross-thread guarantee; doing that read on a background thread would
     * be a race that only shows up as an occasional stray frame.
     */
    fun captureSweepFrame() {
        val capture = imageCapture
        // takePicture queues, and MAXIMIZE_QUALITY shots can take longer than
        // the gate's cadence; without this the queue outlives the sweep. The
        // frame goes back to the budget rather than being spent on a shot that
        // was never taken — otherwise a device that cannot hold the cadence
        // ends its sweep early with far fewer files than the cap, and says
        // nothing about why.
        if (capture == null || inFlight >= MAX_IN_FLIGHT) {
            gate?.abandonShot()
            dropped++
            return
        }
        inFlight++
        val file = File(outputDir, "sweep_${System.currentTimeMillis()}_${shots.size}.jpg")
        val mainExecutor = getMainExecutor(context)
        capture.takePicture(
            ImageCapture.OutputFileOptions.Builder(file).build(),
            mainExecutor,
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                    // A shot started just before Stop can land after it. Keeping
                    // it would attach a frame from a finished sweep to the next
                    // one, silently — the same race CaptureScreen's abortBurst
                    // guards against.
                    if (!sweeping || logging) {
                        inFlight--
                        ioExecutor.execute { file.delete() }
                        return
                    }
                    ioExecutor.execute {
                        val outcome = runCatching { downscaleCloseupInPlace(file) }
                        mainExecutor.execute {
                            inFlight--
                            outcome.fold(
                                onSuccess = {
                                    shots.add(file)
                                    banked = shots.size
                                    bankedBytes += file.length()
                                    status = "swept $banked/$SWEEP_MAX_FRAMES — keep moving across the page"
                                },
                                onFailure = {
                                    file.delete()
                                    error = "sweep frame processing failed: ${it.message}"
                                },
                            )
                        }
                    }
                }

                override fun onError(exc: ImageCaptureException) {
                    inFlight--
                    error = "sweep capture failed: ${exc.message}"
                }
            },
        )
    }

    // Keyed on Unit, not on the camera effect's lifecycleOwner: if that effect
    // restarts without the screen leaving composition, a shutdown executor
    // would make the next capture throw RejectedExecutionException.
    DisposableEffect(Unit) {
        onDispose {
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
                // MAXIMIZE_QUALITY, same as the anchor and close-up paths, and
                // that consistency is the point: a sweep frame has to be
                // comparable with a tapped close-up or the device run cannot
                // tell the two apart on anything but count. It is slower per
                // shot, which is what MAX_IN_FLIGHT bounds; if cadence turns
                // out to be the binding constraint on a device,
                // CAPTURE_MODE_MINIMIZE_LATENCY is the one-line knob to try —
                // and it needs its own comparison, not just a faster sweep.
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
                // Main executor: every frame's decisions land in Compose state.
                analysis.setAnalyzer(getMainExecutor(context)) { imageProxy ->
                    try {
                        val (luma, width, height) = imageProxy.toSweepLuma()
                        val score = frameScorer.score(
                            luma, width, height,
                            timestampMs = imageProxy.imageInfo.timestamp / 1_000_000,
                        )
                        val active = gate
                        val command = active?.onFrame(score) ?: SweepCommand.None
                        lastScore = score
                        motionNow = active?.motionSinceLastCapture ?: 0.0
                        if (logging) {
                            frameLog.record(
                                FrameLogRow(
                                    timestampMs = score.timestampMs,
                                    sharpness = score.sharpness,
                                    stability = score.stability,
                                    passes = score.sharpness >= SWEEP_SHARPNESS_THRESHOLD,
                                    // The `streak` column carries banked motion
                                    // for a sweep log: a sweep has no streak,
                                    // and the fitter reads sharpness/stability
                                    // only (tools/calibrate_hover.py's note on
                                    // why the diagnostic columns are never fit
                                    // inputs) — so this column is free and this
                                    // is the number a sweep needs to see.
                                    streak = (active?.motionSinceLastCapture ?: 0.0).toInt(),
                                    command = command.tag(),
                                ),
                            )
                        }
                        // Logging is an OBSERVATION mode, exactly as on the
                        // capture screen: the gate runs and the CSV records
                        // what it would have done, but nothing fires. A sweep
                        // ends after 24 frames, so a threshold session that
                        // also captured would end before it had recorded
                        // anything worth fitting.
                        if (!logging) {
                            when (command) {
                                SweepCommand.CaptureNow -> captureSweepFrame()
                                SweepCommand.SweepFull -> finishSweep("frame cap reached")
                                SweepCommand.None -> Unit
                            }
                        }
                    } finally {
                        imageProxy.close()
                    }
                }
                cameraProvider.unbindAll()
                camera = cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    capture,
                    analysis,
                )
                camera?.cameraControl?.setZoomRatio(zoom)
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
            // White on a scrim: the theme's default text is dark-on-dark over a
            // camera preview, which made the capture screen's readout
            // unreadable on the first real device.
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Color.Black.copy(alpha = 0.55f), RoundedCornerShape(8.dp))
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(sweepReadout(lastScore, motionNow, motionGated), color = Color.White)
                // Whole-spread totals, not this run's: they are what the frame
                // budget and the single upload request are both about.
                Text(
                    "close-ups ${priorCount + banked}/$SWEEP_MAX_FRAMES on this spread · " +
                        String.format(Locale.US, "%.1f MB to upload", (priorBytes + bankedBytes) / BYTES_PER_MB) +
                        (if (dropped > 0) " · $dropped frame(s) the camera could not keep up with" else ""),
                    color = Color.White,
                )
                logStatus?.let { Text(it, color = Color.White) }
                Text(if (logging) "recording — nothing will be captured" else status, color = Color.White)
                error?.let { Text(it, color = Color(0xFFFF6B6B)) }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SWEEP_ZOOM_STEPS.forEach { ratio ->
                    OutlinedButton(
                        // Changing zoom mid-sweep is allowed: it re-frames the
                        // remaining frames, and the gate does not care.
                        onClick = {
                            zoom = ratio
                            camera?.cameraControl?.setZoomRatio(ratio)
                        },
                    ) {
                        Text(if (zoom == ratio) "[${ratio.toInt()}x]" else "${ratio.toInt()}x")
                    }
                }
            }

            Button(
                enabled = !sweeping,
                onClick = { motionGated = !motionGated },
            ) {
                Text(
                    if (motionGated) {
                        "Trigger: movement (≥${SWEEP_MOTION_THRESHOLD.toInt()}) — tap for timed"
                    } else {
                        "Trigger: every ${SWEEP_TIMED_INTERVAL_MS}ms — tap for movement"
                    },
                )
            }

            Button(
                enabled = !sweeping,
                onClick = {
                    if (logging) {
                        logging = false
                        flushLog()
                        gate?.stop()
                        gate = null
                        status = "log saved — Start sweep to capture"
                    } else {
                        frameLog.clear()
                        logStatus = null
                        // The gate must run so the CSV records what it WOULD
                        // have done; captureSweepFrame is what the logging
                        // branch above suppresses.
                        // Uncapped: see newGate.
                        gate = newGate(motionGated, cap = Int.MAX_VALUE).also { it.start() }
                        logging = true
                    }
                },
            ) {
                Text(if (logging) "Stop log" else "Log frames (calibration)")
            }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onDone, enabled = !sweeping) { Text("Done") }
                Button(
                    // Refuses to arm with no budget left: the spread's close-ups
                    // all travel in one request, so "one more pass" past the cap
                    // grows a POST nobody is watching.
                    enabled = imageCapture != null && !logging && (sweeping || remainingBudget > 0),
                    onClick = {
                        error = null
                        if (sweeping) {
                            finishSweep("stopped")
                        } else {
                            shots.clear()
                            banked = 0
                            bankedBytes = 0L
                            dropped = 0
                            gate = newGate(motionGated, cap = remainingBudget).also { it.start() }
                            sweeping = true
                            status = "sweeping — move steadily across the page"
                        }
                    },
                ) {
                    Text(
                        when {
                            sweeping -> "Stop sweep"
                            remainingBudget > 0 -> "Start sweep ($remainingBudget left)"
                            else -> "Budget full — upload this spread"
                        },
                    )
                }
            }
        }
    }
}

/** Short tag for the CSV's `command` column. */
private fun SweepCommand.tag(): String = when (this) {
    SweepCommand.None -> "none"
    SweepCommand.CaptureNow -> "capture"
    SweepCommand.SweepFull -> "full"
}

/**
 * The live numbers behind the gate's decision: is this frame sharp enough to
 * keep, and how much travel is banked towards the next shot. Formatted with
 * [Locale.US] so a comma-decimal device shows values matching the CSV.
 */
private fun sweepReadout(score: FrameScore?, motion: Double, motionGated: Boolean): String {
    val sharpPart = if (score == null) {
        "sharp — (≥${SWEEP_SHARPNESS_THRESHOLD.toInt()})"
    } else {
        val mark = if (score.sharpness >= SWEEP_SHARPNESS_THRESHOLD) "✓" else "✗"
        "sharp ${String.format(Locale.US, "%.0f", score.sharpness)} $mark (≥${SWEEP_SHARPNESS_THRESHOLD.toInt()})"
    }
    val movePart = if (!motionGated) {
        "moved — (timed trigger)"
    } else {
        val mark = if (motion >= SWEEP_MOTION_THRESHOLD) "✓" else "…"
        "moved ${String.format(Locale.US, "%.0f", motion)} $mark (≥${SWEEP_MOTION_THRESHOLD.toInt()})"
    }
    return "$sharpPart  $movePart"
}

/**
 * Extracts the Y (luma) plane as a tightly packed `width * height` buffer,
 * honoring row/pixel stride (YUV_420_888 planes are not guaranteed contiguous).
 *
 * Deliberately a copy of [CaptureScreen]'s private extension rather than a
 * shared one: the `:capture` module is pure JVM on purpose (no Android SDK, so
 * the gates stay unit-testable without a device), and `ImageProxy` is an
 * Android type that cannot go there.
 */
private fun androidx.camera.core.ImageProxy.toSweepLuma(): Triple<ByteArray, Int, Int> {
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
