package com.bookscan.network

import java.io.File
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * The upload part's filename is the ONLY channel a capture's origin has to the
 * server: `upload_page` replaces the name with `frame_NN` and Stage 00 records
 * whatever it saved as `ingest.json`'s `source`. So these assertions are the
 * contract, matched by `server/tests/test_routes_jobs.py`.
 */
class MultipartPartTest {

    private fun temp(name: String): File {
        val dir = Files.createTempDirectory("bookscan-part").toFile()
        dir.deleteOnExit()
        return File(dir, name).apply { writeBytes(byteArrayOf(1, 2, 3)); deleteOnExit() }
    }

    private fun nameOf(index: Int, file: File): String =
        multipartPart(index, file).headers!!["Content-Disposition"]!!
            .substringAfter("filename=\"").substringBefore("\"")

    @Test
    fun `an ordinary capture keeps the plain frame name`() {
        assertEquals("frame_00.jpg", nameOf(0, temp("capture_1787119754755.jpg")))
        assertEquals("frame_03.jpg", nameOf(3, temp("closeup_1787119754755.jpg")))
        assertEquals("frame_07.jpg", nameOf(7, temp("auto_1787119754755_2.jpg")))
    }

    @Test
    fun `a sweep frame carries its origin marker`() {
        assertEquals("frame_01_sweep.jpg", nameOf(1, temp("sweep_1787119754755_0.jpg")))
        assertEquals("frame_24_sweep.jpg", nameOf(24, temp("sweep_1787119754755_23.jpg")))
    }

    @Test
    fun `the extension is preserved and a missing one defaults to jpg`() {
        assertEquals("frame_02.png", nameOf(2, temp("capture_1.png")))
        assertEquals("frame_02_sweep.png", nameOf(2, temp("sweep_1_0.png")))
        assertEquals("frame_02.jpg", nameOf(2, temp("capture")))
    }

    @Test
    fun `a name that merely contains the marker is not tagged`() {
        // The marker is a PREFIX, so an unrelated name cannot smuggle one in.
        assertEquals("frame_05.jpg", nameOf(5, temp("resweep_1.jpg")))
        assertEquals("frame_05.jpg", nameOf(5, temp("capture_sweep_1.jpg")))
    }
}
