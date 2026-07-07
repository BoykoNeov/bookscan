package com.bookscan.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Manual server IP:port entry — v1 has no auto-discovery (see the plan doc's rationale). */
@Composable
fun ServerSetupScreen(onConnect: (String) -> Unit) {
    var address by remember { mutableStateOf("192.168.1.") }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Enter the desktop server's address")
        Text("Shown by the server's landing page / console output on startup.")
        OutlinedTextField(
            value = address,
            onValueChange = { address = it },
            label = { Text("host:port, e.g. 192.168.1.42:8000") },
            singleLine = true,
        )
        Button(onClick = { onConnect(address) }, enabled = address.isNotBlank()) {
            Text("Connect")
        }
    }
}
