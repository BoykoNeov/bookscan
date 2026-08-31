package com.bookscan.network

import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.RequestBody.Companion.asRequestBody
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.io.File
import java.util.concurrent.TimeUnit

/** Builds a [BookscanApi] against a manually-entered `http://ip:port/` base URL. */
object BookscanClientFactory {
    private val json = Json { ignoreUnknownKeys = true }

    fun create(baseUrl: String, client: OkHttpClient = defaultHttpClient()): BookscanApi {
        val normalized = if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/"
        val retrofit = Retrofit.Builder()
            .baseUrl(normalized)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
        return retrofit.create(BookscanApi::class.java)
    }

    /**
     * Long read timeout: pipeline runs (00_ingest..06_uncertain) take real
     * wall-clock time server-side, but callers poll getJobStatus() rather than
     * holding a request open for that, so this only needs to cover normal
     * request/response latency over local Wi-Fi, not a pipeline run.
     */
    fun defaultHttpClient(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()
}

/**
 * Origin markers a local capture filename may carry into the upload. The server
 * keeps the marker in the saved frame's name and Stage 00 records that name in
 * `ingest.json`'s `source` field, so a later measurement can ask which frames a
 * result came from.
 *
 * Only "sweep" is marked, and only because it is the one origin whose effect is
 * an open question: a sweep frame and a tapped close-up are otherwise the same
 * kind of file, and without the marker "a sweep helped" cannot be told apart
 * from "more close-ups helped". Anchors and tapped close-ups stay untagged, so
 * every filename an existing job produces is byte-for-byte what it was.
 */
private val ORIGIN_TAGS = setOf("sweep")

/**
 * One capture frame ready to upload; [index] 0 is always the anchor
 * ("frame_00"). A file whose name begins with a known origin marker is named
 * `frame_NN_<marker>.<ext>` — see [ORIGIN_TAGS] for why only one exists, and
 * `server/routes_jobs.py::upload_page` for the half that preserves it.
 */
fun multipartPart(index: Int, file: File, mediaType: String = "image/jpeg"): MultipartBody.Part {
    val body = file.asRequestBody(mediaType.toMediaType())
    val ext = file.extension.ifBlank { "jpg" }
    val tag = ORIGIN_TAGS.firstOrNull { file.name.startsWith("${it}_") }?.let { "_$it" } ?: ""
    return MultipartBody.Part.createFormData("files", "frame_%02d%s.%s".format(index, tag, ext), body)
}
