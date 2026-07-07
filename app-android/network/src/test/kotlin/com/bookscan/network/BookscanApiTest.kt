package com.bookscan.network

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Exercises [BookscanApi] against fixture responses shaped exactly like
 * server/routes_jobs.py + server/jobs.py + pipeline/run_all.py actually emit
 * (see those files' docstrings/models). This is the M1 "CI-able" proof from
 * docs/plans/android-guided-capture.md: no device, no real server, just this
 * client parsing real response shapes correctly.
 */
class BookscanApiTest {

    private fun server(body: String, code: Int = 200): MockWebServer {
        val s = MockWebServer()
        s.enqueue(MockResponse().setResponseCode(code).setBody(body))
        s.start()
        return s
    }

    @Test
    fun `createJob parses job_id`() = runTest {
        val s = server("""{"job_id": "20260707-153000-ab12cd34"}""")
        try {
            val api = BookscanClientFactory.create(s.url("/").toString())
            val res = api.createJob()
            assertEquals("20260707-153000-ab12cd34", res.job_id)

            val recorded = s.takeRequest()
            assertEquals("POST", recorded.method)
            assertEquals("/api/jobs", recorded.path)
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun `listJobs parses empty and populated lists`() = runTest {
        val s = server("""{"jobs": [{"job_id": "job-a"}, {"job_id": "job-b"}]}""")
        try {
            val api = BookscanClientFactory.create(s.url("/").toString())
            val res = api.listJobs()
            assertEquals(listOf("job-a", "job-b"), res.jobs.map { it.job_id })
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun `getJobStatus parses a mix of null, ok, and failed stages`() = runTest {
        // Shaped exactly like server.jobs.job_status(): a page with 00_ingest
        // and 01_fuse done, 02_split failed, 03_dewarp..06_uncertain not yet run.
        val body = """
            {
              "job_id": "job-a",
              "pages": [
                {
                  "name": "page_001",
                  "stages": {
                    "00_ingest": {"ok": true, "warnings": [], "timings_ms": {"total": 120.5}},
                    "01_fuse": {"ok": true, "warnings": ["low sharpness on frame_01"], "timings_ms": {"total": 340.0}},
                    "02_split": {"ok": false, "error": "unreadable meta.json"},
                    "03_dewarp": null,
                    "04_layout": null,
                    "05_ocr": null,
                    "06_uncertain": null
                  },
                  "run_all": {
                    "page_dir": "jobs/job-a/page_001",
                    "ok": false,
                    "failed_stage": "02_split",
                    "stages": [
                      {"name": "00_ingest", "ok": true, "warnings": [], "timing_ms": 120.5},
                      {"name": "01_fuse", "ok": true, "warnings": ["low sharpness on frame_01"], "timing_ms": 340.0},
                      {"name": "02_split", "ok": false, "error": "gutter not found", "timing_ms": 12.1}
                    ]
                  }
                }
              ],
              "has_document": false,
              "has_render": false
            }
        """.trimIndent()
        val s = server(body)
        try {
            val api = BookscanClientFactory.create(s.url("/").toString())
            val status = api.getJobStatus("job-a")

            assertEquals("job-a", status.job_id)
            assertEquals(1, status.pages.size)
            val page = status.pages.single()
            assertEquals("page_001", page.name)
            assertTrue(page.stages.getValue("00_ingest")!!.ok)
            assertEquals(120.5, page.stages.getValue("00_ingest")!!.timings_ms["total"])
            assertEquals(
                listOf("low sharpness on frame_01"),
                page.stages.getValue("01_fuse")!!.warnings,
            )
            assertEquals(false, page.stages.getValue("02_split")!!.ok)
            assertNull(page.stages.getValue("03_dewarp"))

            requireNotNull(page.run_all).let { runAll ->
                assertEquals(false, runAll.ok)
                assertEquals("02_split", runAll.failed_stage)
                assertEquals(3, runAll.stages.size)
                assertEquals("gutter not found", runAll.stages.last().error)
            }
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun `getJobStatus tolerates unknown fields for forward compatibility`() = runTest {
        val body = """
            {
              "job_id": "job-a",
              "pages": [],
              "has_document": false,
              "has_render": false,
              "server_version": "0.2.0"
            }
        """.trimIndent()
        val s = server(body)
        try {
            val api = BookscanClientFactory.create(s.url("/").toString())
            val status = api.getJobStatus("job-a")
            assertEquals(emptyList(), status.pages)
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun `uploadPage posts multipart and parses response`() = runTest {
        val s = server("""{"page": "page_002", "files": ["frame_00.jpg", "frame_01.jpg"]}""")
        try {
            val api = BookscanClientFactory.create(s.url("/").toString())
            val tmp0 = kotlin.io.path.createTempFile(suffix = ".jpg").toFile().apply { writeBytes(byteArrayOf(1, 2, 3)) }
            val tmp1 = kotlin.io.path.createTempFile(suffix = ".jpg").toFile().apply { writeBytes(byteArrayOf(4, 5, 6)) }

            val res = api.uploadPage("job-a", listOf(multipartPart(0, tmp0), multipartPart(1, tmp1)))

            assertEquals("page_002", res.page)
            assertEquals(listOf("frame_00.jpg", "frame_01.jpg"), res.files)

            val recorded = s.takeRequest()
            assertEquals("POST", recorded.method)
            assertEquals("/api/jobs/job-a/pages", recorded.path)
            assertTrue(recorded.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
        } finally {
            s.shutdown()
        }
    }
}
