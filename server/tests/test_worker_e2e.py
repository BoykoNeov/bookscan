"""The one test that proves the REAL chain end to end through the HTTP API:
upload a real testset image -> worker subprocesses pipeline.run_all against
it -> 06_uncertain/ lands on disk -> assemble -> render. No stage is mocked
and no document is pre-seeded — this is exactly Build-sequence step 4's own
verification requirement ("the existing editor UI works end to end against a
job created via upload, not pre-seeded via CLI"), checked at the HTTP-API
level (assemble/render responses + on-disk artifacts) rather than manually.

This specifically exercises two paths nothing else in the suite covers:
  * the upload endpoint writes frames into <page_dir>/raw/ and the worker
    invokes ``run_all <page_dir>`` with no --input, relying on Stage 00's
    src=None -> read-existing-raw/ branch (Step 1's real-chain test only
    proved the --input <file> branch);
  * assemble + render run against a document.json that stage07_assemble
    itself produced from real pipeline output, not the synthetic
    06_uncertain fixtures test_routes_assemble.py / test_routes_editor.py
    hand-seed for their (fast, mocked-data) route tests.

Uses httpx.ASGITransport directly (not FastAPI's TestClient) so the test can
await worker.queue.join() instead of polling on a wall-clock timer — join()
returns exactly when the enqueued page has finished processing, no earlier.
ASGITransport does not run FastAPI's lifespan, so the worker is started and
stopped explicitly here instead of relying on server.app's lifespan hook.

Skips gracefully if the heavy deps (torch/YOLO checkpoint/Tesseract) aren't
set up, same idiom as pipeline/tests/test_run_all.py's slow test.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from server.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_MISSING_DEP_MARKERS = (
    "tesseract", "checkpoint", "modulenotfounderror", "no such file", "not found",
)


async def _full_chain(tmp_path: Path, src: Path) -> dict:
    app = create_app()
    app.state.jobs_root = tmp_path
    await app.state.worker.start()
    result: dict = {}
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                      base_url="http://test") as client:
            job_id = (await client.post("/api/jobs")).json()["job_id"]
            with open(src, "rb") as f:
                r = await client.post(
                    f"/api/jobs/{job_id}/pages",
                    files={"files": ("en_coins_01.jpg", f, "image/jpeg")})
            assert r.status_code == 200, r.text
            page_dir = tmp_path / job_id / r.json()["page"]
            result["job_id"] = job_id
            result["page_dir"] = page_dir

            await asyncio.wait_for(app.state.worker.queue.join(), timeout=180)

            log_path = page_dir / "worker.log"
            result["log"] = (log_path.read_text(encoding="utf-8")
                              if log_path.exists() else "")
            run_all_path = page_dir / "run_all.json"
            result["run_all"] = (
                json.loads(run_all_path.read_text(encoding="utf-8"))
                if run_all_path.exists() else None)

            if result["run_all"] and result["run_all"]["ok"]:
                asm = await client.post(f"/api/jobs/{job_id}/assemble")
                result["assemble_status"] = asm.status_code
                result["assemble_body"] = asm.text

                rnd = await client.post(f"/jobs/{job_id}/api/render")
                result["render_status"] = rnd.status_code
                result["render_body"] = rnd.text
    finally:
        await app.state.worker.stop()
    return result


@pytest.mark.slow
def test_real_upload_runs_through_worker_then_assemble_and_render(tmp_path: Path):
    src = REPO_ROOT / "testset" / "en_coins_01.jpg"
    if not src.exists():
        pytest.skip("testset image not found")

    result = asyncio.run(_full_chain(tmp_path, src))
    page_dir, job_id, log = result["page_dir"], result["job_id"], result["log"]
    assert log, "worker never ran the page (queue.join() lied?)"

    run_all = result["run_all"]
    if run_all is None:
        if any(m in log.lower() for m in _MISSING_DEP_MARKERS):
            pytest.skip(f"real pipeline deps unavailable:\n{log[-1000:]}")
        pytest.fail(f"run_all.py never wrote run_all.json:\n{log[-2000:]}")
    if not run_all["ok"]:
        if any(m in log.lower() for m in _MISSING_DEP_MARKERS):
            pytest.skip(f"real pipeline deps unavailable:\n{log[-1000:]}")
        pytest.fail(f"run_all failed at {run_all['failed_stage']}:\n{log[-2000:]}")

    assert (page_dir / "06_uncertain").is_dir()
    assert (page_dir / "raw" / "frame_00.jpg").exists(), \
        "upload must have written into raw/ for run_all's src=None branch to work"

    job_dir = tmp_path / job_id
    assert result["assemble_status"] == 200, result["assemble_body"]
    doc_path = job_dir / "document.json"
    assert doc_path.is_file() and doc_path.stat().st_size > 0

    assert result["render_status"] == 200, result["render_body"]
    render_path = job_dir / "render" / "page.html"
    assert render_path.is_file() and render_path.stat().st_size > 0
