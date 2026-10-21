package com.bookscan.app

/**
 * JPEG quality for every still the app takes — anchors, tapped close-ups and
 * sweep frames alike — set explicitly so it is a recorded choice, not whatever
 * the device's CameraX default happens to be.
 *
 * 100 because the owner ranks the quality of the source photographs first
 * (2026-10-21): every later stage, and any model that reads the page, can only
 * lose detail the photograph did not keep. The cost is bytes — roughly double
 * a quality-95 file — paid once, over local Wi-Fi.
 *
 * Until 2026-10-21 close-ups were also decoded, shrunk to half their area and
 * re-encoded at 92 so Stage 01 would tell them from a whole-spread shot by
 * size. They are now uploaded exactly as the camera wrote them (EXIF intact,
 * so Stage 00's `exif_transpose` still uprights them) and named
 * `frame_NN_closeup` / `frame_NN_sweep` instead; `pipeline/stage01_fuse.py::
 * partition_frames` keys on that name.
 */
const val CAPTURE_JPEG_QUALITY = 100
