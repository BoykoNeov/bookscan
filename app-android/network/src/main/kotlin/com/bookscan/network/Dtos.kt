package com.bookscan.network

import kotlinx.serialization.Serializable

/**
 * Wire types for the desktop server's job API (`server/routes_jobs.py`,
 * `server/jobs.py`). Field names and nesting mirror those modules exactly —
 * `job_status()`'s dict shape becomes [JobStatus], `PageRunResult`/
 * `StageOutcome` (pipeline/run_all.py) become [PageRunResult]/[StageOutcome],
 * and `StageMeta` (pipeline/page_model.py) becomes [StageStatus].
 */

@Serializable
data class CreateJobResponse(val job_id: String)

@Serializable
data class JobSummary(val job_id: String)

@Serializable
data class ListJobsResponse(val jobs: List<JobSummary>)

/** One stage's own meta.json, as server.jobs._stage_status() reshapes it. */
@Serializable
data class StageStatus(
    val ok: Boolean,
    val warnings: List<String> = emptyList(),
    val timings_ms: Map<String, Double> = emptyMap(),
)

/** One stage's outcome within a run_all.json pass (pipeline/run_all.py StageOutcome). */
@Serializable
data class StageOutcome(
    val name: String,
    val ok: Boolean,
    val error: String? = null,
    val warnings: List<String> = emptyList(),
    val timing_ms: Double? = null,
)

/** Contents of <page_dir>/run_all.json (pipeline/run_all.py PageRunResult). */
@Serializable
data class PageRunResult(
    val page_dir: String,
    val ok: Boolean,
    val failed_stage: String? = null,
    val stages: List<StageOutcome> = emptyList(),
)

/**
 * One page's status. [stages] keys are the STAGE_ORDER folder names
 * ("00_ingest".."06_uncertain"); a null value means that stage hasn't run yet
 * (server.jobs._stage_status() returns None, distinct from an ok=false entry).
 */
@Serializable
data class PageStatus(
    val name: String,
    val stages: Map<String, StageStatus?>,
    val run_all: PageRunResult? = null,
)

@Serializable
data class JobStatus(
    val job_id: String,
    val pages: List<PageStatus>,
    val has_document: Boolean,
    val has_render: Boolean,
)

@Serializable
data class UploadPageResponse(
    val page: String,
    val files: List<String>,
)
