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
import com.bookscan.app.ui.JobScreen
import com.bookscan.app.ui.ServerSetupScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val viewModel: BookscanViewModel = viewModel()
            val state by viewModel.state.collectAsState()
            var showCapture by remember { mutableStateOf(false) }

            val requestCameraPermission = rememberLauncherForActivityResult(
                ActivityResultContracts.RequestPermission(),
            ) { granted -> if (granted) showCapture = true }

            fun openCapture() {
                val granted = ContextCompat.checkSelfPermission(
                    this@MainActivity,
                    Manifest.permission.CAMERA,
                ) == PackageManager.PERMISSION_GRANTED
                if (granted) showCapture = true else requestCameraPermission.launch(Manifest.permission.CAMERA)
            }

            MaterialTheme {
                Surface(modifier = Modifier) {
                    when (val s = state) {
                        is UiState.ServerSetup -> ServerSetupScreen(onConnect = viewModel::setServerUrl)
                        is UiState.Ready -> if (showCapture) {
                            CaptureScreen(
                                outputDir = cacheDir,
                                onCaptured = { file ->
                                    showCapture = false
                                    viewModel.uploadFrame(file)
                                },
                                onCancel = { showCapture = false },
                            )
                        } else {
                            JobScreen(
                                state = s,
                                onCreateJob = viewModel::createJob,
                                onCapturePage = ::openCapture,
                            )
                        }
                    }
                }
            }
        }
    }
}
