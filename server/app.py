"""server.app — FastAPI app factory (Gate 5 skeleton).

Loads ``config.yaml`` once at startup, reusing the same ``load_config`` every
pipeline stage already uses, and stashes ``{cfg, jobs_root}`` on ``app.state``
so routes never hard-code a filesystem root.

No pipeline stage is imported or called in-process here. See
``pipeline/run_all.py``'s docstring and
``docs/plans/partitioned-questing-pillow.md`` for why: all pipeline execution
happens as a subprocess. ``server/worker.py``'s single serialized background
task (started/stopped via this app's lifespan) is what actually invokes it,
one page at a time, after the upload endpoint enqueues it.

Usage:
    uvicorn server.app:app --reload
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from pipeline.stage04_layout import load_config
from server import jobs as J
from server.routes_jobs import router as jobs_router
from server.worker import Worker

REPO_ROOT = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def _lifespan(app: FastAPI):
    await app.state.worker.start()
    yield
    await app.state.worker.stop()


def create_app(config_path: Path | None = None) -> FastAPI:
    config_path = config_path or (REPO_ROOT / "config.yaml")
    cfg = load_config(config_path)

    app = FastAPI(title="bookscan", version="0.1.0", lifespan=_lifespan)
    app.state.repo_root = REPO_ROOT
    app.state.cfg = cfg
    app.state.jobs_root = J.jobs_root(cfg, REPO_ROOT)
    app.state.worker = Worker(REPO_ROOT)
    # Guards next_page_dir()'s compute-name-then-mkdir span in routes_jobs.py:
    # the Android app's whole model is rapid concurrent-upload traffic to one
    # job, and page numbering must never race (see gate5-progress memory).
    app.state.upload_lock = asyncio.Lock()

    app.include_router(jobs_router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "jobs_root": str(app.state.jobs_root)}

    return app


app = create_app()
