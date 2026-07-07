"""The one test that proves the REAL chain end to end through the HTTP API:
upload a real testset image -> worker subprocesses pipeline.run_all against
it -> 06_uncertain/ lands on disk. No stage is mocked.

This specifically exercises the path Step 1's real-chain test did NOT: the
upload endpoint writes frames into <page_dir>/raw/ and the worker invokes
``run_all <page_dir>`` with no --input, relying on Stage 00's src=None ->
read-existing-raw/ branch. Step 1 only proved the --input <file> branch.

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
from pathlib import Path

import httpx
import pytest

from server.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_MISSING_DEP_MARKERS = (
    "tesseract", "checkpoint", "modulenotfounderror", "no such file", "not found",
)


async def _upload_and_wait(tmp_path: Path, src: Path) -> tuple[Path, str]:
    app = create_app()
    app.state.jobs_root = tmp_path
    await app.state.worker.start()
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
            page_name = r.json()["page"]

        await asyncio.wait_for(app.state.worker.queue.join(), timeout=180)
    finally:
        await app.state.worker.stop()
    return tmp_path / job_id / page_name, job_id


@pytest.mark.slow
def test_real_upload_runs_through_worker_to_uncertain(tmp_path: Path):
    src = REPO_ROOT / "testset" / "en_coins_01.jpg"
    if not src.exists():
        pytest.skip("testset image not found")

    page_dir, job_id = asyncio.run(_upload_and_wait(tmp_path, src))

    log_path = page_dir / "worker.log"
    assert log_path.exists(), "worker never ran the page (queue.join() lied?)"
    log = log_path.read_text(encoding="utf-8")

    run_all_path = page_dir / "run_all.json"
    if not run_all_path.exists():
        if any(m in log.lower() for m in _MISSING_DEP_MARKERS):
            pytest.skip(f"real pipeline deps unavailable:\n{log[-1000:]}")
        pytest.fail(f"run_all.py never wrote run_all.json:\n{log[-2000:]}")

    import json
    result = json.loads(run_all_path.read_text(encoding="utf-8"))
    if not result["ok"]:
        combined = log.lower()
        if any(m in combined for m in _MISSING_DEP_MARKERS):
            pytest.skip(f"real pipeline deps unavailable:\n{log[-1000:]}")
        pytest.fail(f"run_all failed at {result['failed_stage']}:\n{log[-2000:]}")

    assert (page_dir / "06_uncertain").is_dir()
    assert (page_dir / "raw" / "frame_00.jpg").exists(), \
        "upload must have written into raw/ for run_all's src=None branch to work"
