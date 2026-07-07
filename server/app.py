"""server.app — FastAPI app factory (Gate 5 skeleton).

Loads ``config.yaml`` once at startup, reusing the same ``load_config`` every
pipeline stage already uses, and stashes ``{cfg, jobs_root}`` on ``app.state``
so routes never hard-code a filesystem root.

No pipeline stage is imported or called in-process here. See
``pipeline/run_all.py``'s docstring and
``docs/plans/partitioned-questing-pillow.md`` for why: all pipeline execution
happens as a subprocess, wired onto the upload endpoint in Step 3
(``server/worker.py``, not yet built).

Usage:
    uvicorn server.app:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from pipeline.stage04_layout import load_config
from server import jobs as J
from server.routes_jobs import router as jobs_router

REPO_ROOT = Path(__file__).resolve().parent.parent


def create_app(config_path: Path | None = None) -> FastAPI:
    config_path = config_path or (REPO_ROOT / "config.yaml")
    cfg = load_config(config_path)

    app = FastAPI(title="bookscan", version="0.1.0")
    app.state.repo_root = REPO_ROOT
    app.state.cfg = cfg
    app.state.jobs_root = J.jobs_root(cfg, REPO_ROOT)

    app.include_router(jobs_router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "jobs_root": str(app.state.jobs_root)}

    return app


app = create_app()
