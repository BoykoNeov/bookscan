package com.bookscan.app.ui

import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
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
import com.bookscan.app.downscaleCloseupInPlace
import java.io.File

/**
 * Fixed zoom-ratio steps rather than a pinch gesture or a CameraX
 * zoomState-bound slider — deliberately the simplest thing that lets a user
 * "zoom in, tap to capture" (docs/plans/android-guided-capture.md M4)
 * without adding gesture-detection or LiveData-observation surface that
 * can't be tuned without a device in this environment. CameraX clamps any
 * ratio outside a device's supported range, so an unreachable step is
 * harmless.
 */
private val ZOOM_STEPS = listOf(1f, 2f, 3f, 4f)

/**
 * M4's user-triggered close-up capture: pick a zoom step, tap to capture —
 * one close-up per tap, repeatable. Each still is downscaled in place (see
 * [downscaleCloseupInPlace]) before being handed to [onCaptured] so its saved
 * pixel area reads as a close-up (not a second anchor) to Stage 01 Fuse.
 * Deliberately separate from [CaptureScreen]'s M2/M3 hover-to-capture flow —
 * that state machine stays untouched.
 *
 * Auto-trigger is NOT used here (user-triggered only, per the plan's
 * conservative v1 scope); unverified UX without a device, same caveat as
 * [CaptureScreen].
 */
@Composable
fun CloseupScreen(
    outputDir: File,
    closeupCount: Int,
    onCaptured: (File) -> Unit,
    onDone: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember { PreviewView(context) }
    var imageCapture by remember { mutableStateOf<ImageCapture?>(null) }
    var camera by remember { mutableStateOf<Camera?>(null) }
    var capturing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

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
                cameraProvider.unbindAll()
                camera = cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    CameraSelector.DEFAULT_BACK_CAMERA,
                    preview,
                    capture,
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
            Text("$closeupCount close-up(s) captured — zoom in on a region, then tap to capture")
            error?.let { Text(it, color = Color.Red) }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ZOOM_STEPS.forEach { ratio ->
                    Button(onClick = { camera?.cameraControl?.setZoomRatio(ratio) }) {
                        Text("${ratio.toInt()}x")
                    }
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = onDone, enabled = !capturing) { Text("Done") }
                Button(
                    enabled = imageCapture != null && !capturing,
                    onClick = {
                        val capture = imageCapture ?: return@Button
                        capturing = true
                        error = null
                        val file = File(outputDir, "closeup_${System.currentTimeMillis()}.jpg")
                        capture.takePicture(
                            ImageCapture.OutputFileOptions.Builder(file).build(),
                            getMainExecutor(context),
                            object : ImageCapture.OnImageSavedCallback {
                                override fun onImageSaved(output: ImageCapture.OutputFileResults) {
                                    try {
                                        downscaleCloseupInPlace(file)
                                        capturing = false
                                        onCaptured(file)
                                    } catch (e: Exception) {
                                        capturing = false
                                        error = "close-up processing failed: ${e.message}"
                                    }
                                }

                                override fun onError(exc: ImageCaptureException) {
                                    capturing = false
                                    error = "close-up capture failed: ${exc.message}"
                                }
                            },
                        )
                    },
                ) {
                    Text(if (capturing) "Capturing…" else "Capture close-up")
                }
            }
        }
    }
}
