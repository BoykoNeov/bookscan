package com.bookscan.app

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.bookscan.app.ui.JobScreen
import com.bookscan.app.ui.ServerSetupScreen
import java.io.File
import java.util.UUID

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val viewModel: BookscanViewModel = viewModel()
            val state by viewModel.state.collectAsState()

            val pickImage = rememberLauncherForActivityResult(
                ActivityResultContracts.GetContent(),
            ) { uri: Uri? ->
                if (uri != null) {
                    val file = copyUriToCacheFile(uri)
                    viewModel.uploadFrame(file)
                }
            }

            MaterialTheme {
                Surface(modifier = Modifier) {
                    when (val s = state) {
                        is UiState.ServerSetup -> ServerSetupScreen(onConnect = viewModel::setServerUrl)
                        is UiState.Ready -> JobScreen(
                            state = s,
                            onCreateJob = viewModel::createJob,
                            onPickAndUploadFrame = { pickImage.launch("image/*") },
                        )
                    }
                }
            }
        }
    }

    /**
     * Content picker gives a content:// Uri, but Retrofit's multipart body
     * needs a real java.io.File (see network module's multipartPart()) — copy
     * into cacheDir once per pick. Fine for the M1 gallery-picker stand-in;
     * M2 replaces this whole path with a CameraX-captured file directly.
     */
    private fun copyUriToCacheFile(uri: Uri): File {
        val dest = File(cacheDir, "pick_${UUID.randomUUID()}.jpg")
        contentResolver.openInputStream(uri)?.use { input ->
            dest.outputStream().use { output -> input.copyTo(output) }
        }
        return dest
    }
}
