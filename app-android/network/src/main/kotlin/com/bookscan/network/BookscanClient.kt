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

/** One capture frame ready to upload; [index] 0 is always the anchor ("frame_00"). */
fun multipartPart(index: Int, file: File, mediaType: String = "image/jpeg"): MultipartBody.Part {
    val body = file.asRequestBody(mediaType.toMediaType())
    val ext = file.extension.ifBlank { "jpg" }
    return MultipartBody.Part.createFormData("files", "frame_%02d.%s".format(index, ext), body)
}
