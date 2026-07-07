package com.bookscan.network

import okhttp3.MultipartBody
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path

/**
 * The four endpoints server/routes_jobs.py exposes. No auth, no push
 * transport — status is plain polling via [getJobStatus]
 * (docs/plans/android-guided-capture.md's "manual first" server model).
 */
interface BookscanApi {

    @POST("api/jobs")
    suspend fun createJob(): CreateJobResponse

    @GET("api/jobs")
    suspend fun listJobs(): ListJobsResponse

    @GET("api/jobs/{id}")
    suspend fun getJobStatus(@Path("id") jobId: String): JobStatus

    /**
     * [files] are one spread's capture frames in one request — the anchor
     * frame (index 0, "frame_00" server-side) plus any multi-zoom close-ups,
     * NOT one page per file. See server/routes_jobs.py's upload_page().
     */
    @Multipart
    @POST("api/jobs/{id}/pages")
    suspend fun uploadPage(
        @Path("id") jobId: String,
        @Part files: List<MultipartBody.Part>,
    ): UploadPageResponse
}

/** STAGE_ORDER from pipeline/run_all.py — the fixed key order in [JobStatus.pages]'s stages map. */
val STAGE_ORDER: List<String> = listOf(
    "00_ingest", "01_fuse", "02_split", "03_dewarp",
    "04_layout", "05_ocr", "06_uncertain",
)
