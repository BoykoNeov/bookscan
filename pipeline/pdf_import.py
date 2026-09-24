"""PDF import — fill ``00_ingest``'s input from a PDF instead of a phone.

``docs/plans/pdf-import.md`` Slice 1. A scanned PDF (someone else's scan, a
photographed book already bound into a file) becomes a job whose pages the
existing chain processes unchanged: each PDF page is RENDERED to a PNG and written
as ``page_NNN/raw/frame_00.png``, exactly where the upload path puts a phone's
frames. Nothing downstream knows the pixels came from a PDF.

**Render, never extract.** A scanned PDF often stores one JPEG per page, and
pulling it out is lossless and tempting — but it is not reliably the whole page
(several images, masks, the page's own rotation and transform). Rendering is
correct by construction. DPI is a recorded parameter, 300 by default because
that is roughly what Tesseract wants for body text.

**What a page is.** The pipeline's unit is a spread; a PDF page may be one book
page or a whole spread. The importer decides from the rendered page's shape —
wider than tall is a spread, otherwise a single page — writes that verdict to
``page_NNN/page_layout.json`` with its provenance (``pdf_import_aspect``), prints
it, and records it in ``import.json``. ``--layout single|spread`` overrides it
(provenance ``operator``). Stage 02 reads the file: a single page is never
searched for a spine and never cropped (see ``stage02_split.PageLayout``). The
shape rule is a guess and says so: an oblong book's single page is wider than
tall, and is then searched for a spine that is not there (Stage 02 emits
``single.png`` when it finds none, but that path is not proven on such a page).

**Only scans.** A page is a scan when the union of its placed images covers at
least ``SCAN_COVERAGE`` of the visible page. A born-digital page (a LaTeX paper,
an ebook export) fails that and the import is REFUSED, naming the pages:
re-typesetting one is a different problem, and this pipeline's dewarp, spine
search and figure cropping are dead weight there. A text layer does NOT count
against a page — many scans carry an invisible OCR layer. Its words are saved per
page as ``page_NNN/pdf_text_layer.json`` (Slice 3): Stage 05 compares them with
Tesseract and may only ADD a marker, never text (``pipeline/pdf_text_layer.py``).
Every page's ``page_layout.json`` also says ``"origin": "pdf_import"``, which is
how Stage 03 knows to put a white border round a flat scan before flattening it.

**All or nothing.** The console's startup scan enqueues any page folder with
files in ``raw/`` and no ``run_all.json``, so a half-written import would be
processed as a shorter book, and a skipped page would shift every page after it.
So the whole job is rendered into a staging folder first; any failure leaves
nothing in ``jobs/``. Publishing copies it in with each page's frames under
``raw.importing/`` — invisible to that scan — and only then renames every one to
``raw/`` and writes ``job.json``.

**From the command line, processing starts when the console does.** This CLI
does not talk to a running server: the console's queue lives in memory and is
filled from disk only at startup (``server/reconcile.py``), so an import made
here while the console is open waits for its next start. The console's own
**Import PDF** button (``server/routes_import.py``, Slice 2) calls
``import_pdf`` in-process and enqueues every page the moment the job is
published, so it needs no restart. A runtime "rescan for new pages" was
deliberately NOT added instead: the phone upload writes ``raw/`` a moment before
it enqueues, and a rescan landing in that gap would run the page twice.

Usage::

    python -m pipeline.pdf_import book.pdf [--dpi 300] [--layout detect|single|spread]
        [--mode flag] [--lang deu] [--job-id ID] [--dry-run] [--allow-vector]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
from pydantic import BaseModel, Field

from pipeline import pdf_text_layer as TL

REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION = "0.1.0"
SCAN_COVERAGE = 0.90         # union of placed images / visible page area
SPREAD_ASPECT = 1.0          # width / height above which a page is a spread
MODES = ("flag", "best_guess", "patch")          # same values as server/jobs.py
LANG_RE = re.compile(r"^[a-z]{3}(?:\+[a-z]{3})*$")  # same rule as server/jobs.py
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # server/jobs.py's rule, length-capped
COVERAGE_GRID = 256          # raster used to union image rectangles


class ImportedPage(BaseModel):
    page: str                 # page_NNN
    pdf_page: int             # 1-based page number in the PDF
    width: int                # rendered pixels
    height: int
    aspect: float             # width / height
    layout: str               # single | spread
    layout_source: str        # pdf_import_aspect | operator
    image_coverage: float     # union of placed images / page area
    is_scan: bool


class ImportResult(BaseModel):
    importer_version: str = VERSION
    job_id: str
    pdf: str
    pdf_sha256: str
    page_count: int
    dpi: int
    layout_mode: str
    mode: str
    lang: str | None = None
    estimated_bytes: int = 0  # uncompressed RGB, the upper bound a user is told
    created_at: str = ""
    pages: list[ImportedPage] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ImportRefused(RuntimeError):
    """The PDF cannot be imported as it stands; the message says why."""


def new_job_id() -> str:
    """Same shape as ``server.jobs.new_job_id`` (pipeline must not import server)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_coverage(page) -> float:
    """Fraction of the visible page covered by the UNION of its placed images.

    A union, not a sum: a compressed scan often stacks a background image under
    a mask of the same size, and a tiled scan cuts the page into strips — a sum
    over-counts the first and a largest-image rule under-counts the second.

    Image boxes come back in the page's UNROTATED space while ``page.rect`` is the
    displayed (rotated) one, so each box is turned by ``rotation_matrix`` first —
    without that a scan stored with ``/Rotate 90`` measured 71 % and was refused.
    """
    import fitz

    rect = page.rect
    if rect.width <= 0 or rect.height <= 0:
        return 0.0
    grid = np.zeros((COVERAGE_GRID, COVERAGE_GRID), bool)
    sx, sy = COVERAGE_GRID / rect.width, COVERAGE_GRID / rect.height
    for info in page.get_image_info():
        x0, y0, x1, y1 = fitz.Rect(info["bbox"]) * page.rotation_matrix
        x0, x1 = max(x0, rect.x0), min(x1, rect.x1)
        y0, y1 = max(y0, rect.y0), min(y1, rect.y1)
        if x1 <= x0 or y1 <= y0:
            continue
        grid[int((y0 - rect.y0) * sy):int(np.ceil((y1 - rect.y0) * sy)),
             int((x0 - rect.x0) * sx):int(np.ceil((x1 - rect.x0) * sx))] = True
    return float(grid.mean())


def _render_size(page, dpi: int) -> tuple[int, int]:
    """Pixel size a render at ``dpi`` will have (page rotation included)."""
    r = page.rect   # already the displayed (rotated) rectangle
    return int(round(r.width * dpi / 72.0)), int(round(r.height * dpi / 72.0))


def survey(pdf_path: Path, dpi: int = 300, layout: str = "detect",
           page_layouts: dict[int, str] | None = None) -> tuple[list[ImportedPage], list[str]]:
    """Every page's verdict, WITHOUT rendering anything — what ``--dry-run`` and
    the console's Import PDF check show.

    ``page_layouts`` maps a 1-based PDF page number to ``single``/``spread`` and
    wins over ``layout`` for that page (provenance ``operator``): the console's
    per-page toggle. A page number the PDF does not have is an error, not ignored.
    """
    import fitz

    if layout not in ("detect", "single", "spread"):
        raise ValueError(f"layout must be detect|single|spread, not {layout!r}")
    page_layouts = dict(page_layouts or {})
    bad = {k: v for k, v in page_layouts.items() if v not in ("single", "spread")}
    if bad:
        raise ValueError(f"a page's layout must be single|spread, not {bad}")
    unreadable = None
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        unreadable = f"cannot open {pdf_path.name} as a PDF: {e}"
    if unreadable is not None:
        # Raised outside the except block and unchained on purpose: MuPDF's
        # exception keeps the half-opened file alive through its traceback, and
        # on Windows that file cannot be deleted while it is (WinError 32) — the
        # console deletes a refused upload right after this returns.
        raise ImportRefused(unreadable)
    try:
        if doc.needs_pass:
            raise ImportRefused(f"{pdf_path.name} is password-protected; remove the "
                                f"password first (nothing was imported)")
        if doc.page_count == 0:
            raise ImportRefused(f"{pdf_path.name} has no pages")
        outside = sorted(k for k in page_layouts if not 1 <= k <= doc.page_count)
        if outside:
            raise ValueError(f"{pdf_path.name} has {doc.page_count} pages; no page {outside}")
        pages, warnings = [], []
        for i, page in enumerate(doc):
            w, h = _render_size(page, dpi)
            aspect = w / h if h else 0.0
            if layout == "detect":
                verdict, source = ("spread" if aspect > SPREAD_ASPECT else "single"), "pdf_import_aspect"
            else:
                verdict, source = layout, "operator"
            if i + 1 in page_layouts:
                verdict, source = page_layouts[i + 1], "operator"
            cov = image_coverage(page)
            pages.append(ImportedPage(
                page=f"page_{i + 1:03d}", pdf_page=i + 1, width=w, height=h,
                aspect=round(aspect, 4), layout=verdict, layout_source=source,
                image_coverage=round(cov, 4), is_scan=cov >= SCAN_COVERAGE))
        return pages, warnings
    finally:
        doc.close()


def import_pdf(pdf_path: Path, jobs_root: Path, *, dpi: int = 300,
               layout: str = "detect", mode: str = "flag", lang: str | None = None,
               job_id: str | None = None, allow_vector: bool = False,
               staging_root: Path | None = None,
               page_layouts: dict[int, str] | None = None,
               on_page: Callable[[int, int], None] | None = None) -> ImportResult:
    """Render every page of ``pdf_path`` into a new job under ``jobs_root``.

    Raises ``ImportRefused`` (and writes nothing to ``jobs_root``) when the PDF is
    unreadable, encrypted, empty, or has a page that is not a scan (unless
    ``allow_vector``). Any other failure also leaves nothing in ``jobs_root``.

    ``page_layouts`` is ``survey``'s per-page override. ``on_page(done, total)``
    is called after each page is rendered into staging — progress only: the job
    stays invisible until the last page is in and ``_publish`` has run.
    """
    import fitz

    pdf_path = Path(pdf_path)
    if mode not in MODES:
        raise ValueError(f"invalid mode: {mode!r} (choices: {MODES})")
    if lang is not None and not LANG_RE.match(lang):
        raise ValueError(f"invalid lang: {lang!r}")
    if not 72 <= dpi <= 1200:
        raise ValueError(f"dpi {dpi} outside 72..1200")
    job_id = job_id or new_job_id()
    if not JOB_ID_RE.match(job_id):
        raise ValueError(f"invalid job id: {job_id!r}")
    final = jobs_root / job_id
    if final.exists():
        raise ImportRefused(f"{final} already exists; importing never adds pages "
                            f"to an existing job")

    pages, warnings = survey(pdf_path, dpi, layout, page_layouts)
    not_scans = [p for p in pages if not p.is_scan]
    if not_scans and not allow_vector:
        listed = ", ".join(f"{p.pdf_page} ({p.image_coverage:.0%} image)"
                           for p in not_scans[:20])
        more = f" and {len(not_scans) - 20} more" if len(not_scans) > 20 else ""
        raise ImportRefused(
            f"{len(not_scans)} of {len(pages)} pages are not scans — their images "
            f"cover less than {SCAN_COVERAGE:.0%} of the page, so they were made by "
            f"software, not photographed: PDF page {listed}{more}. This pipeline "
            f"re-typesets photographs of pages; nothing was imported. "
            f"(--allow-vector renders them anyway.)")
    if not_scans:
        warnings.append(f"--allow-vector: {len(not_scans)} page(s) that are not "
                        f"scans were rendered and imported anyway: PDF page "
                        + ", ".join(str(p.pdf_page) for p in not_scans))

    result = ImportResult(
        job_id=job_id, pdf=pdf_path.name, pdf_sha256=_sha256(pdf_path),
        page_count=len(pages), dpi=dpi, layout_mode=layout, mode=mode, lang=lang,
        estimated_bytes=sum(p.width * p.height * 3 for p in pages),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        pages=pages, warnings=warnings)

    staging = (staging_root or staging_dir({})) / job_id
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    ours = False            # True once ``final`` is a folder this call created
    try:
        doc = fitz.open(pdf_path)
        try:
            producer = (doc.metadata or {}).get("producer", "") or ""
            for p, page in zip(pages, doc):
                pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=fitz.csRGB)
                if (pix.width, pix.height) != (p.width, p.height):
                    # the survey's size is what import.json promises; say so if not
                    p.width, p.height = pix.width, pix.height
                page_dir = staging / p.page
                (page_dir / "raw.importing").mkdir(parents=True)
                pix.save(str(page_dir / "raw.importing" / "frame_00.png"))
                (page_dir / "page_layout.json").write_text(json.dumps({
                    "layout": p.layout, "source": p.layout_source,
                    "aspect": p.aspect,
                    "note": f"{pdf_path.name} page {p.pdf_page} at {dpi} dpi",
                    "origin": "pdf_import",
                }, indent=1), encoding="utf-8")
                # The hidden text layer, saved now because the console deletes the
                # uploaded PDF once the import is done (Slice 3: a second opinion
                # that can only ADD a marker; see pipeline/pdf_text_layer.py).
                words = TL.layer_words(page)
                if words:
                    TL.write_layer(page_dir, words, pdf_name=pdf_path.name,
                                   pdf_page=p.pdf_page, producer=producer)
                if on_page is not None:
                    on_page(p.pdf_page, len(pages))
        finally:
            doc.close()
        (staging / "import.json").write_text(result.model_dump_json(indent=2),
                                             encoding="utf-8")
        job = {"mode": mode, **({"lang": lang} if lang is not None else {})}
        if final.exists():   # appeared while rendering: never touch someone else's job
            raise ImportRefused(f"{final} appeared during the import; nothing was published")
        ours = True
        _publish(staging, final, job)
    except BaseException:
        if ours:
            shutil.rmtree(final, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return result


def staging_dir(cfg: dict) -> Path:
    """``paths.import_staging`` from config.yaml (relative to the repo root), or
    the OS temp dir when it is unset or its drive does not exist here."""
    raw = ((cfg or {}).get("paths") or {}).get("import_staging")
    if raw:
        p = Path(raw)
        p = p if p.is_absolute() else REPO_ROOT / p
        if Path(p.anchor or ".").exists():
            return p
    return Path(tempfile.gettempdir()) / "bookscan_pdf_import"


def jobs_dir(cfg: dict) -> Path:
    """``paths.jobs`` from config.yaml, resolved the way server/jobs.py does."""
    p = Path(((cfg or {}).get("paths") or {}).get("jobs", "jobs"))
    return p if p.is_absolute() else REPO_ROOT / p


def _publish(staging: Path, final: Path, job: dict) -> None:
    """Copy the staged job into place so that no page becomes processable until
    every page is there: frames travel under ``raw.importing/`` and are renamed to
    ``raw/`` only after the whole copy succeeded; ``job.json`` is written last."""
    shutil.copytree(staging, final)
    for page_dir in sorted(final.glob("page_*")):
        (page_dir / "raw.importing").rename(page_dir / "raw")
    (final / "job.json").write_text(json.dumps(job), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Import a scanned PDF as a new job: one page folder per PDF page.")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--dpi", type=int, default=300,
                    help="render resolution (recorded in import.json); default 300")
    ap.add_argument("--layout", choices=["detect", "single", "spread"], default="detect",
                    help="detect = wider-than-tall pages are spreads, others single "
                         "pages; single/spread forces every page")
    ap.add_argument("--mode", choices=list(MODES), default="flag",
                    help="the job's uncertainty mode (job.json)")
    ap.add_argument("--lang", default=None, help="the job's OCR language, e.g. deu")
    ap.add_argument("--job-id", default=None)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--jobs-root", type=Path, default=None,
                    help="default: paths.jobs from config.yaml")
    ap.add_argument("--staging", type=Path, default=None,
                    help="default: paths.import_staging from config.yaml")
    ap.add_argument("--allow-vector", action="store_true",
                    help="also import pages that are not scans (made by software)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print each page's verdict and the size estimate, write nothing")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    import yaml
    cfg = (yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
           if args.config.exists() else {})
    args.jobs_root = args.jobs_root or jobs_dir(cfg)
    args.staging = args.staging or staging_dir(cfg)

    try:
        if args.dry_run:
            pages, _ = survey(args.pdf, args.dpi, args.layout)
            est = sum(p.width * p.height * 3 for p in pages)
            for p in pages:
                print(f"  PDF page {p.pdf_page:4d} -> {p.page}: {p.width}x{p.height} "
                      f"aspect {p.aspect:.2f} -> {p.layout} ({p.layout_source}), "
                      f"images cover {p.image_coverage:.0%}"
                      + ("" if p.is_scan else "  NOT A SCAN"))
            print(f"{len(pages)} pages, about {est / 1e6:.0f} MB of pixels before "
                  f"PNG compression; dry run, nothing written")
            return 0
        t0 = time.perf_counter()
        res = import_pdf(args.pdf, args.jobs_root, dpi=args.dpi, layout=args.layout,
                         mode=args.mode, lang=args.lang, job_id=args.job_id,
                         allow_vector=args.allow_vector, staging_root=args.staging)
    except ImportRefused as e:
        print(f"REFUSED: {e}")
        return 2
    for p in res.pages:
        print(f"  PDF page {p.pdf_page:4d} -> {p.page}: {p.width}x{p.height} "
              f"-> {p.layout} ({p.layout_source})")
    for w in res.warnings:
        print(f"  warning: {w}")
    print(f"imported {res.page_count} pages into {args.jobs_root / res.job_id} "
          f"in {time.perf_counter() - t0:.1f}s. The console picks up pages imported "
          f"HERE only when it STARTS: start it (bookscan.bat), or restart it if it is "
          f"already open (the console's own Import PDF button needs no restart). "
          f"One page by hand: python -m pipeline.run_all "
          f"{args.jobs_root / res.job_id / 'page_001'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
