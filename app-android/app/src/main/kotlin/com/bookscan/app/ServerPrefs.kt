package com.bookscan.app

import android.content.Context

private const val PREFS_NAME = "bookscan_prefs"
private const val KEY_SERVER_URL = "server_url"

/** Manual server IP:port entry, persisted across launches (see M1/M5 in the plan). */
class ServerPrefs(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var serverUrl: String?
        get() = prefs.getString(KEY_SERVER_URL, null)
        set(value) = prefs.edit().putString(KEY_SERVER_URL, value).apply()
}
