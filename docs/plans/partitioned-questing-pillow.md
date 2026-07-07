# Gate 5 — Desktop Server Plan

## Context

Gate 4 (editable `document.json` + visual editor) is done. CLAUDE.md's status
checklist names Gate 5 — server + Android app — as next, with the Android app
explicitly built *after* the desktop pipeline is proven. This plan scopes the
**server only**.

The server's job: receive page-spread uploads (eventually from the Android
capture app, for now from curl/a test client), drive the existing per-page
pipeline (stages 00–06) and job-level stages (07 assemble, 08 render) end to
end, and expose the editable-document API so the existing visual editor
(`pipeline/editor.py`'s UI) works against server-created jobs too.

Research confirmed every stage module (`pipeline/stage00_ingest.py` through
`stage08_render.py`) already exposes a clean, tested entry point separate from
its CLI: `run(page_dir_or_job_dir, cfg, ..., debug=False) -> Result`. The
server's job is orchestration and HTTP, not touching stage internals.

**Key decision — pipeline execution runs as a subprocess, not in-process in
FastAPI.** Stages 03 (dewarp/UVDoc) and 04 (layout/DocLayout-YOLO) are the only
GPU-model stages; both already free VRAM per call via `close()` +
`torch.cuda.empty_cache()` in a `finally` block, so in-process calling saves
nothing over subprocess (no warm-model reuse to gain — the stage contract
already reloads every call). In-process *does* cost: a native CUDA/torch crash
would take down the whole server (every job, the editor, everything), and
hundreds of load/free cycles inside one long-lived process risk CUDA-context
fragmentation that `empty_cache()` doesn't fully clear. CLAUDE.md's existing
rule — "release VRAM when a stage CLI exits" — is written for exactly this:
process exit is the only guaranteed full release. So the server subprocesses
the pipeline.

## Architecture

### New: `pipeline/run_all.py`

The orchestrator CLAUDE.md's own Commands section already documents but that
doesn't exist on disk yet (confirmed). Two responsibilities:

1. A per-page runner: given a `page_dir` + `cfg` (+ uncertainty mode), calls
   `stage00_ingest.run` → `stage06_uncertainty.run` in sequence, stopping on
   the first hard failure but recording per-stage success/warnings, returns a
   summary. This is the one reusable seam both the CLI and the server call.
2. A CLI wrapper matching the documented command:
   `python -m pipeline.run_all --input <dir> --job <job_id> --mode <flag|best_guess|patch>`.

This is what the server subprocesses — one `python -m pipeline.run_all ...`
per uploaded page/spread.

**Per-page subprocess granularity (not per-job).** Chosen over one subprocess
per whole book because it matches CLAUDE.md's "release VRAM when a stage CLI
exits" model most closely (only two GPU load/free cycles — dewarp, layout —
per process before exit) and gives clean resume semantics: if page 47 of a
300-page job crashes, pages 1–46 stay done and only 47 needs retry, instead of
losing an entire in-flight job subprocess. Revisitable: if per-page spawn
overhead (~1–3s Python+torch import) becomes a throughput bottleneck on long
books, collapse to per-job subprocess later — that's a server-side change
only, `run_all.py` doesn't need to change.

### New: `server/` (FastAPI)

- `server/app.py` — app factory; mounts routers; serves the existing editor
  SPA (`pipeline/assets/editor/`) as static files at `/`; loads `config.yaml`
  once at startup (reuse `load_config` helper already used by every stage).
- `server/jobs.py` — job lifecycle. Job identity is just the folder name
  (confirmed: `stage07_assemble.py` sets `document_id=job_dir.name`), so the
  server mints an id (timestamp-slug or uuid4) and creates `jobs/<id>/` on
  `POST /api/jobs`. **No database** — status is derived by scanning
  `page_*/*/meta.json` presence + `document.json`/`render/` presence, matching
  the repo's existing artifact-driven design (the filesystem already *is* the
  state; every stage already writes `meta.json`).
- `server/worker.py` — one serialized background worker (`asyncio.Queue` +
  a single drain task) that pops queued page jobs and runs
  `asyncio.create_subprocess_exec("python", "-m", "pipeline.run_all", ...)`
  one at a time. Hard-serialized on purpose: one consumer GPU, no concurrent
  pipeline runs. The same worker/queue also handles the render-PDF export
  (`python -m pipeline.stage08_render` subprocess) — this incidentally also
  solves GATE4_SPEC's documented Gate-5 caveat that `sync_playwright()` can't
  run on the FastAPI event-loop thread, since a subprocess has its own loop.
- `server/routes_jobs.py`:
  - `POST /api/jobs` — create job, mint id.
  - `GET /api/jobs` / `GET /api/jobs/{id}` — list / per-page stage-progress
    status, parsed from each stage's `meta.json` (warnings, timings).
  - `POST /api/jobs/{id}/pages` — multipart upload (anchor frame + optional
    multi-zoom close-ups for one spread) → writes `page_NNN/raw/`, enqueues
    it on the worker.
  - `POST /api/jobs/{id}/assemble` — subprocesses `stage07_assemble`. Runs
    with `force=false` by default and **refuses** if `document.json` already
    has user edits unless `?force=true` is explicitly passed — mirrors
    stage07's own clobber guard; the server must never silently discard edits
    by auto-firing assemble.
  - `POST /api/jobs/{id}/render` — queues `stage08_render` on the worker.
- `server/routes_document.py` — lifts `load_document` / `normalize_edits` /
  `save_document` from `pipeline/editor.py` **unchanged** (this is exactly the
  reusable seam `docs/GATE4_SPEC.md` calls out — "the HTTP layer is a thin
  swap") into `GET/PUT /api/jobs/{id}/document` and
  `GET /api/jobs/{id}/assets/{relpath}` (path-traversal guarded, same as
  `editor.py`'s existing handler).

**Status delivery is plain polling** (`GET /api/jobs/{id}`), not
WebSocket/SSE. The Android app doesn't exist yet, so there is no real client
to push to or test a socket against; CLAUDE.md's "pushes status ... back to
the phone" is an architecture-summary line, not a transport mandate. Polling
against on-disk state is fully verifiable today (browser or curl); add
push once there's an actual client to build the contract against.

### Explicit non-goals here

- Android app (CLAUDE.md sequences it after the desktop server).
- WebSocket/SSE (deferred to when a real client exists).
- Auth / multi-user (single desktop, local-Wi-Fi trust model per CLAUDE.md;
  flag if that assumption needs revisiting).
- Concurrent multi-job GPU execution (hard-serialized; one GPU).

### New dependencies (`requirements.txt`)

`fastapi`, `uvicorn[standard]`, `python-multipart` (upload parsing). Note:
`playwright` is already installed and used by `stage08_render.py` but is
missing from `requirements.txt` — worth a one-line fix alongside this work.

## Build sequence

Roughly one Claude Code session per step, matching the repo's "one stage per
session" convention:

1. **`pipeline/run_all.py`** + tests — pure orchestration, no HTTP. Validate
   against a real `testset/` spread end to end (00→06), plus the documented
   CLI form.
2. **`server/` skeleton** — app factory, job create/list, filesystem-derived
   status endpoint, dependency additions. Smoke-test with a manual multipart
   upload (curl/httpx) against one test image.
3. **Background worker + subprocess wiring** to the upload endpoint — verify
   a full spread goes from upload to `06_uncertain/` on disk via the API
   alone (no CLI).
4. **Assemble + render endpoints** (subprocessed stage07/08) + document
   GET/PUT lifted from `editor.py` + static-serve the editor SPA at `/` —
   verify the existing editor UI works end to end against a job created via
   upload, not pre-seeded via CLI.

## Verification

- `run_all.py`: pytest running a real testset spread through 00–06 via direct
  import (not subprocess), asserting each stage's artifacts land; CLI smoke
  test matching the documented invocation.
- Server: FastAPI `TestClient`/httpx route tests (job create → status shape);
  one real end-to-end test that uploads a real testset image through the API,
  polls status to completion, calls assemble + render, and asserts
  `document.json` + `render/page.html` are non-empty — this is the test that
  actually proves the subprocess wiring works, not a mocked one.
- Manual: `uvicorn server.app:app`, open the editor at `/` for a job created
  purely through the upload API, confirm edit + save + re-render round-trips
  the same way `pipeline/tests/test_editor.py`'s Playwright e2e already proves
  for the CLI-created case.
