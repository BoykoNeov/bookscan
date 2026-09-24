"""Tests for pipeline.pdf_import — a scanned PDF becomes one page folder per page.

Hermetic: every PDF is built here with PyMuPDF from synthetic pixels. Each page is
sized so a render at the test DPI returns the image at its own pixel size
(points = px * 72 / dpi), so what comes out can be compared with what went in.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

fitz = pytest.importorskip("fitz")

from pipeline import pdf_import as PI  # noqa: E402

DPI = 150


def _png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _picture(w: int, h: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 235, np.uint8)
    for y in range(20, h - 20, 18):                 # "text" rows
        img[y:y + 8, 20:w - 20] = rng.integers(0, 60)
    return img


def _add_scan_page(doc, img: np.ndarray, *, invisible_text: str | None = None,
                   tiles: int = 1) -> None:
    h, w = img.shape[:2]
    page = doc.new_page(width=w * 72 / DPI, height=h * 72 / DPI)
    step = h // tiles
    for t in range(tiles):                          # a tiled scan: horizontal strips
        y0, y1 = t * step, (h if t == tiles - 1 else (t + 1) * step)
        rect = fitz.Rect(0, y0 * 72 / DPI, w * 72 / DPI, y1 * 72 / DPI)
        page.insert_image(rect, stream=_png(img[y0:y1]))
    if invisible_text:                              # a producer's OCR layer
        page.insert_text((20, 40), invisible_text, render_mode=3)


def _add_text_page(doc) -> None:
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Born digital: nothing here was photographed.")


def _scan_pdf(tmp: Path, name: str = "book.pdf") -> tuple[Path, list[np.ndarray]]:
    spread, single = _picture(400, 260, 1), _picture(200, 280, 2)
    doc = fitz.open()
    _add_scan_page(doc, spread)
    _add_scan_page(doc, single, invisible_text="Hidden OCR layer")
    path = tmp / name
    doc.save(path)
    doc.close()
    return path, [spread, single]


def _job_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir()) if root.exists() else []


def test_scanned_pdf_becomes_one_page_folder_per_page(tmp_path: Path):
    pdf, imgs = _scan_pdf(tmp_path)
    jobs, staging = tmp_path / "jobs", tmp_path / "staging"
    jobs.mkdir()
    res = PI.import_pdf(pdf, jobs, dpi=DPI, mode="patch", lang="deu",
                        job_id="imp1", staging_root=staging)
    job = jobs / "imp1"
    assert _job_dirs(jobs) == [job]
    assert json.loads((job / "job.json").read_text()) == {"mode": "patch", "lang": "deu"}
    assert [p.page for p in res.pages] == ["page_001", "page_002"]
    for p, img in zip(res.pages, imgs):
        page_dir = job / p.page
        assert sorted(x.name for x in page_dir.iterdir()) == ["page_layout.json", "raw"]
        out = cv2.imread(str(page_dir / "raw" / "frame_00.png"), cv2.IMREAD_COLOR)
        assert out.shape == img.shape                 # rendered at the image's own size
        assert np.abs(out.astype(int) - img.astype(int)).mean() < 2.0
    lay = [json.loads((job / p / "page_layout.json").read_text())
           for p in ("page_001", "page_002")]
    assert [(x["layout"], x["source"]) for x in lay] == [
        ("spread", "pdf_import_aspect"), ("single", "pdf_import_aspect")]
    rec = json.loads((job / "import.json").read_text())
    assert rec["dpi"] == DPI and rec["page_count"] == 2 and len(rec["pdf_sha256"]) == 64
    # a page carrying an invisible OCR text layer is still a scan
    assert all(p["is_scan"] and p["image_coverage"] == 1.0 for p in rec["pages"])
    assert not (staging / "imp1").exists()


def test_a_tiled_scan_is_a_scan(tmp_path: Path):
    """Coverage is the UNION of the placed images: a page cut into strips is whole.
    (Pixels are not compared here: MuPDF may place a strip a pixel off.)"""
    doc = fitz.open()
    _add_scan_page(doc, _picture(200, 280, 5), tiles=3)
    pdf = tmp_path / "tiled.pdf"
    doc.save(pdf)
    doc.close()
    pages, _ = PI.survey(pdf, DPI)
    assert pages[0].is_scan and pages[0].image_coverage >= PI.SCAN_COVERAGE


def test_layout_override_is_recorded_as_the_operators(tmp_path: Path):
    pdf, _ = _scan_pdf(tmp_path)
    res = PI.import_pdf(pdf, tmp_path / "jobs", dpi=DPI, layout="single",
                        job_id="imp2", staging_root=tmp_path / "st")
    assert {(p.layout, p.layout_source) for p in res.pages} == {("single", "operator")}


def test_a_page_made_by_software_refuses_the_whole_import(tmp_path: Path):
    doc = fitz.open()
    _add_scan_page(doc, _picture(200, 280, 3))
    _add_text_page(doc)
    pdf = tmp_path / "mixed.pdf"
    doc.save(pdf)
    doc.close()
    jobs = tmp_path / "jobs"
    with pytest.raises(PI.ImportRefused, match=r"1 of 2 pages are not scans.*PDF page 2"):
        PI.import_pdf(pdf, jobs, dpi=DPI, job_id="imp3", staging_root=tmp_path / "st")
    assert _job_dirs(jobs) == []
    res = PI.import_pdf(pdf, jobs, dpi=DPI, job_id="imp3", allow_vector=True,
                        staging_root=tmp_path / "st")
    assert res.page_count == 2 and any("--allow-vector" in w for w in res.warnings)


def test_password_protected_pdf_is_refused(tmp_path: Path):
    doc = fitz.open()
    _add_scan_page(doc, _picture(200, 280, 4))
    pdf = tmp_path / "locked.pdf"
    doc.save(pdf, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    with pytest.raises(PI.ImportRefused, match="password"):
        PI.import_pdf(pdf, tmp_path / "jobs", dpi=DPI, staging_root=tmp_path / "st")


def test_not_a_pdf_is_refused(tmp_path: Path):
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pytest.raises(PI.ImportRefused):
        PI.import_pdf(bad, tmp_path / "jobs", dpi=DPI, staging_root=tmp_path / "st")


def test_an_existing_job_is_never_added_to(tmp_path: Path):
    pdf, _ = _scan_pdf(tmp_path)
    jobs = tmp_path / "jobs"
    (jobs / "taken" / "page_001").mkdir(parents=True)
    with pytest.raises(PI.ImportRefused, match="already exists"):
        PI.import_pdf(pdf, jobs, dpi=DPI, job_id="taken", staging_root=tmp_path / "st")
    assert sorted(x.name for x in (jobs / "taken").iterdir()) == ["page_001"]


def test_a_failure_while_publishing_leaves_nothing_in_jobs(tmp_path: Path, monkeypatch):
    """Half an import would be processed as a shorter book by the console's
    startup scan, so a failure after the copy began must remove the copy."""
    pdf, _ = _scan_pdf(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()

    def copy_then_die(staging: Path, final: Path, job: dict) -> None:
        import shutil
        shutil.copytree(staging, final)
        raise OSError("disk full")

    monkeypatch.setattr(PI, "_publish", copy_then_die)
    with pytest.raises(OSError, match="disk full"):
        PI.import_pdf(pdf, jobs, dpi=DPI, job_id="imp4", staging_root=tmp_path / "st")
    assert _job_dirs(jobs) == []
    assert not (tmp_path / "st" / "imp4").exists()


def test_frames_are_invisible_to_the_console_until_every_page_is_in(tmp_path: Path):
    """While copying, frames sit under raw.importing/ — the console only ever
    enqueues a page whose raw/ has files."""
    pdf, _ = _scan_pdf(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    seen = {}
    real = PI.shutil.copytree

    def spy(src, dst, *a, **k):
        out = real(src, dst, *a, **k)
        seen["raw"] = sorted(p.name for p in Path(dst).glob("page_*/raw"))
        seen["importing"] = len(list(Path(dst).glob("page_*/raw.importing/frame_00.png")))
        seen["job_json"] = (Path(dst) / "job.json").exists()
        return out

    PI.shutil.copytree = spy
    try:
        PI.import_pdf(pdf, jobs, dpi=DPI, job_id="imp5", staging_root=tmp_path / "st")
    finally:
        PI.shutil.copytree = real
    assert seen == {"raw": [], "importing": 2, "job_json": False}
    assert len(list((jobs / "imp5").glob("page_*/raw/frame_00.png"))) == 2


def test_dry_run_writes_nothing(tmp_path: Path, capsys):
    pdf, _ = _scan_pdf(tmp_path)
    jobs = tmp_path / "jobs"
    rc = PI.main([str(pdf), "--dpi", str(DPI), "--dry-run", "--jobs-root", str(jobs),
                  "--staging", str(tmp_path / "st")])
    out = capsys.readouterr().out
    assert rc == 0 and "-> spread" in out and "-> single" in out and "dry run" in out
    assert not jobs.exists() or _job_dirs(jobs) == []
