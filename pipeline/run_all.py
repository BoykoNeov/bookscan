"""``run_all`` — chain stages 00 (ingest) through 06 (uncertainty) for ONE
page/spread, in order, in a single process.

This is the orchestration seam CLAUDE.md's Commands section already documents
(``python -m pipeline.run_all --input ... --job ... --mode ...``) but that did
not exist on disk until now. It is not itself a numbered pipeline stage — like
``pipeline/editor.py`` it sits one level above the per-page stage contract —
but it never modifies what a stage writes: it only calls each stage's own
``run()`` in the documented order and does not touch bboxes/text/decisions.

**Why this exists (Gate 5).** Every stage module already exposes a clean
``run(page_dir, cfg, ..., debug=False) -> Result`` distinct from its CLI
``main()``, so a caller COULD import all seven and call them inline. The
future FastAPI server (Gate 5) does exactly that, but as a **subprocess**
(``python -m pipeline.run_all ...``) rather than in-process: Stage 03 (UVDoc)
and Stage 04 (DocLayout-YOLO) are the only GPU-model stages, and both already
free VRAM per call via ``close()`` + ``torch.cuda.empty_cache()`` in a
``finally`` — so calling them in-process buys nothing (no warm-model reuse)
while risking a native CUDA/torch crash taking down a long-lived server
process. CLAUDE.md's "release VRAM when a stage CLI exits" is exactly the
process-exit guarantee subprocessing preserves. This module is what gets
subprocessed, one invocation per page/spread.

**Stops at the first hard failure.** A page whose Stage 03 (say) raises does
not go on to run Stage 04 against stale/absent input — the chain halts and
reports which stage failed. Stages already run are untouched (the stage
contract: a re-run only overwrites its own folder), so the page can be
retried from the top once the cause is fixed.

**Per-stage warnings are not duplicated here** — every stage already writes
them to its own ``<NN_name>/meta.json`` (the shared ``StageMeta`` schema).
``run_page`` reads them back into the summary for convenience, so a caller
doesn't need to know seven different folder names to see what a page's run
produced.

**Output**: alongside letting each stage write its own artifacts, ``run_page``
also persists a ``<page_dir>/run_all.json`` summary (pass/fail + timing per
stage) — a single file the future server can poll instead of re-deriving
progress from seven separate stage folders.

Usage:
    python -m pipeline.run_all jobs/<job>/<page_NNN>/            # reads <page>/raw/
    python -m pipeline.run_all --input testset/en_coins_01.jpg --job demo --mode flag
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

from pipeline.page_model import StageMeta
from pipeline import stage00_ingest as S0
from pipeline import stage01_fuse as S1
from pipeline import stage02_split as S2
from pipeline import stage03_dewarp as S3
from pipeline import stage04_layout as S4
from pipeline import stage05_ocr as S5
from pipeline import stage06_uncertainty as S6

STAGE = "run_all"
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Stage output folder names, in run order — the one place this chain is
# spelled out. Matches the stage contract's numbered folders exactly.
STAGE_ORDER = (
    "00_ingest", "01_fuse", "02_split", "03_dewarp",
    "04_layout", "05_ocr", "06_uncertain",
)


class StageOutcome(BaseModel):
    """One stage's result within a ``run_page`` pass."""

    name: str                      # e.g. "01_fuse" — matches its output folder
    ok: bool
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    timing_ms: float | None = None


class PageRunResult(BaseModel):
    """Contents of ``<page_dir>/run_all.json`` — the orchestration summary."""

    page_dir: str
    ok: bool                       # True iff every stage in the chain succeeded
    failed_stage: str | None = None
    stages: list[StageOutcome] = Field(default_factory=list)


def _stage_warnings(page_dir: Path, dirname: str) -> list[str]:
    """Re-read a stage's own ``meta.json`` (shared ``StageMeta`` schema) for its
    warnings rather than duplicating them here — the stage already recorded them."""
    meta_path = page_dir / dirname / "meta.json"
    if not meta_path.exists():
        return []
    try:
        return StageMeta.model_validate_json(
            meta_path.read_text(encoding="utf-8")).warnings
    except Exception:
        return []


def run_page(page_dir: Path, cfg: dict, *, src: Path | None = None,
             lang: str | None = None, mode: str | None = None,
             threshold_override: float | None = None,
             debug: bool = False) -> PageRunResult:
    """Run stages 00-06 on ONE page/spread, in order, in this process.

    Stops at the first stage whose own ``run()`` raises; stages already run
    are left exactly as they wrote themselves (stage contract). Returns —
    and persists to ``<page_dir>/run_all.json`` — a summary a caller (CLI or
    the future server) can act on without re-deriving state from seven
    separate stage folders.
    """
    steps: list[tuple[str, Callable[[], object]]] = [
        ("00_ingest", lambda: S0.run(page_dir, cfg, src=src, debug=debug)),
        ("01_fuse", lambda: S1.run(page_dir, cfg, debug=debug)),
        ("02_split", lambda: S2.run(page_dir, cfg, debug=debug)),
        ("03_dewarp", lambda: S3.run(page_dir, cfg, debug=debug)),
        ("04_layout", lambda: S4.run(page_dir, cfg, debug=debug)),
        ("05_ocr", lambda: S5.run(page_dir, cfg, lang=lang, debug=debug)),
        ("06_uncertain", lambda: S6.run(
            page_dir, cfg, mode=mode, threshold_override=threshold_override,
            debug=debug)),
    ]
    assert tuple(name for name, _ in steps) == STAGE_ORDER

    outcomes: list[StageOutcome] = []
    failed_stage: str | None = None
    for name, call in steps:
        t0 = time.perf_counter()
        try:
            call()
        except Exception as exc:   # one page's failure must not crash the caller
            outcomes.append(StageOutcome(
                name=name, ok=False, error=f"{type(exc).__name__}: {exc}",
                timing_ms=round((time.perf_counter() - t0) * 1000.0, 1)))
            failed_stage = name
            break
        outcomes.append(StageOutcome(
            name=name, ok=True, warnings=_stage_warnings(page_dir, name),
            timing_ms=round((time.perf_counter() - t0) * 1000.0, 1)))

    result = PageRunResult(page_dir=str(page_dir), ok=failed_stage is None,
                            failed_stage=failed_stage, stages=outcomes)
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "run_all.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run stages 00 (ingest) through 06 (uncertainty) on one "
                     "page/spread, in sequence, in a single process.")
    ap.add_argument("page_dir", type=Path, nargs="?", default=None,
                     help="page folder, e.g. jobs/<job>/<page_NNN>/ (reads "
                          "<page_dir>/raw/ unless --input is given)")
    ap.add_argument("--input", type=Path, default=None,
                     help="capture file or folder of frames for Stage 00 "
                          "(equivalent to stage00_ingest's --src)")
    ap.add_argument("--job", default=None,
                     help="job id; combined with --page to build "
                          "jobs/<job>/<page> when page_dir is omitted")
    ap.add_argument("--page", default="page_001",
                     help="page folder name under jobs/<job>/, used only "
                          "with --job instead of a literal page_dir "
                          "(default: page_001)")
    ap.add_argument("--mode", default=None, choices=["flag", "best_guess", "patch"],
                     help="Stage 06 uncertainty mode; default from config")
    ap.add_argument("--lang", default=None, help="Stage 05 OCR language override")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    if args.page_dir is not None:
        page_dir = args.page_dir
    elif args.job is not None:
        page_dir = REPO_ROOT / "jobs" / args.job / args.page
    else:
        ap.error("give a page_dir, or --job (with optional --page)")
        return 2  # unreachable — ap.error() exits, but satisfies type checkers

    cfg = S4.load_config(args.config)
    result = run_page(page_dir, cfg, src=args.input, lang=args.lang,
                       mode=args.mode, debug=args.debug)

    for s in result.stages:
        status = "ok" if s.ok else f"FAILED: {s.error}"
        extra = f"  warnings={s.warnings}" if s.warnings else ""
        print(f"  {s.name}: {status} ({s.timing_ms}ms){extra}")
    if result.ok:
        print(f"{page_dir}: all stages complete (00_ingest -> 06_uncertain)")
        return 0
    print(f"{page_dir}: FAILED at {result.failed_stage}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
