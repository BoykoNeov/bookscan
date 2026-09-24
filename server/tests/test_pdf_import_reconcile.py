"""An imported PDF is picked up by the console's startup scan — all of it, and
never half of it.

``pipeline/pdf_import.py`` does not talk to a running server: the worker queue
lives in memory and ``server/reconcile.py`` fills it only at STARTUP. So an import
is processed when the console next starts. These pin the two halves of that
contract: after an import every page is found, and while frames still sit under
``raw.importing/`` (mid-publish) none is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fitz")

from pipeline import pdf_import as PI  # noqa: E402
from pipeline.tests.test_pdf_import import DPI, _scan_pdf  # noqa: E402
from server import jobs as J  # noqa: E402
from server import reconcile as R  # noqa: E402


def test_startup_scan_finds_every_imported_page(tmp_path: Path):
    pdf, _ = _scan_pdf(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    PI.import_pdf(pdf, jobs, dpi=DPI, lang="deu", job_id="20260924-000000-abcdef12",
                  staging_root=tmp_path / "st")
    job = jobs / "20260924-000000-abcdef12"
    assert R.pages_needing_work(jobs) == [job / "page_001", job / "page_002"]
    # the job reads like one the console made itself
    assert [j["job_id"] for j in J.list_jobs(jobs)] == [job.name]
    assert J.job_lang(job) == "deu" and J.job_mode(job) == "flag"
    assert J.resolve_job_dir(jobs, job.name) == job


def test_a_half_published_import_is_invisible_to_the_startup_scan(tmp_path: Path):
    pdf, _ = _scan_pdf(tmp_path)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    PI.import_pdf(pdf, jobs, dpi=DPI, job_id="imp", staging_root=tmp_path / "st")
    for page_dir in (jobs / "imp").glob("page_*"):          # rewind to mid-copy
        (page_dir / "raw").rename(page_dir / "raw.importing")
    (jobs / "imp" / "job.json").unlink()
    assert R.pages_needing_work(jobs) == []
    assert json.loads((jobs / "imp" / "import.json").read_text())["page_count"] == 2
