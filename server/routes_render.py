"""server.routes_render — POST /api/jobs/{job_id}/render, GET .../render/pdf.

Subprocesses ``python -m pipeline.stage08_render <job_dir>``, never
in-process: unlike routes_assemble.py's stage07 call (no GPU, no event-loop
conflict), Stage 08's own docstring on its Chromium/Playwright path warns the
sync Playwright API raises if called inside a running asyncio loop — a plain
``async def`` route body would hit exactly that, so this mirrors
server/worker.py's subprocess pattern instead.

Deliberately NOT queued through server/worker.py's serialized page-pipeline
queue: rendering reads only document.json + document_assets/ (never a page
folder the pipeline might still be writing), so it can run independently of
page processing rather than waiting behind it. Two concurrent render requests
for the SAME job could race on writing render/{page.html,page.pdf,meta.json}
— accepted for this single-user desktop tool (same tradeoff class as the
Android upload-retry duplicate-page gap noted in gate5-progress memory);
revisit only if it ever actually bites.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from server import jobs as J

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["render"])


def _job_dir(request: Request, job_id: str) -> Path:
    job_dir = J.resolve_job_dir(request.app.state.jobs_root, job_id)
    if job_dir is None:
        raise HTTPException(404, f"no such job: {job_id}")
    return job_dir


@router.post("/render")
async def render(job_id: str, request: Request) -> dict:
    job_dir = _job_dir(request, job_id)
    if not (job_dir / "document.json").exists():
        raise HTTPException(
            400, "no document.json yet — POST .../assemble first")

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pipeline.stage08_render", str(job_dir),
        cwd=request.app.state.repo_root,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(
            500,
            f"stage08_render exited {proc.returncode}: "
            f"{stderr.decode(errors='replace')[-2000:]}")

    meta_path = job_dir / "render" / "meta.json"
    params = (json.loads(meta_path.read_text(encoding="utf-8"))["params"]
              if meta_path.exists() else {})
    wrote_pdf = bool(params.get("wrote_pdf", False))
    return {
        "ok": True,
        # served by routes_editor.py, not this router — that's the only GET
        # route for the HTML render (this router only adds the PDF route).
        "href": f"/jobs/{job_id}/render/page.html",
        "pdf_href": "render/pdf" if wrote_pdf else None,
        "wrote_pdf": wrote_pdf,
        "pages": params.get("pages"),
        "words": params.get("words"),
        "figures": params.get("figures"),
        "mode": params.get("mode"),
    }


@router.get("/render/pdf")
def get_render_pdf(job_id: str, request: Request) -> FileResponse:
    job_dir = _job_dir(request, job_id)
    path = job_dir / "render" / "page.pdf"
    if not path.is_file():
        raise HTTPException(
            404, "no PDF yet — POST .../render first (and confirm "
            "config.yaml's reconstruct.pdf_backend isn't 'none')")
    return FileResponse(path, media_type="application/pdf",
                         filename=f"{job_id}.pdf")
