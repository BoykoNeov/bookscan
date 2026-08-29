"""Tests for the job-level OCR language (server/jobs.py + routes)."""
from pathlib import Path
import json
import pytest
from server import jobs as J


def test_a_job_with_no_recorded_language_reads_back_as_none(tmp_path: Path):
    """The pre-2026-08-29 shape. `None` must mean "let Stage 05 decide", not
    "eng" — a server that guessed a default here would silently pin every old
    job to whatever config said today."""
    jid = J.create_job(tmp_path)
    assert J.job_lang(tmp_path / jid) is None
    assert "lang" not in json.loads((tmp_path / jid / "job.json").read_text())


def test_the_language_survives_a_mode_read_and_vice_versa(tmp_path: Path):
    jid = J.create_job(tmp_path, mode="patch", lang="deu")
    d = tmp_path / jid
    assert (J.job_mode(d), J.job_lang(d)) == ("patch", "deu")
    J.set_job_lang(d, "bul")
    assert (J.job_mode(d), J.job_lang(d)) == ("patch", "bul")


def test_clearing_the_language_returns_to_the_config_default(tmp_path: Path):
    jid = J.create_job(tmp_path, lang="deu")
    J.set_job_lang(tmp_path / jid, None)
    assert J.job_lang(tmp_path / jid) is None


def test_a_combination_is_allowed_but_a_shell_argument_is_not(tmp_path: Path):
    """The value becomes an argv element, so the shape is checked. Tesseract
    really does take `deu+ita`, so the check cannot be a membership test
    against config's list."""
    jid = J.create_job(tmp_path, lang="deu+ita")
    assert J.job_lang(tmp_path / jid) == "deu+ita"
    for bad in ["de", "deu;rm -rf /", "--oem", "", "DEU", "deu+"]:
        with pytest.raises(ValueError):
            J.create_job(tmp_path, lang=bad)


def test_a_corrupt_language_field_falls_back_rather_than_raising(tmp_path: Path):
    """Reading a job must never be the thing that fails: an unreadable setting
    means "no override", exactly as job_mode does for the mode."""
    jid = J.create_job(tmp_path)
    (tmp_path / jid / "job.json").write_text('{"mode":"flag","lang":123}')
    assert J.job_lang(tmp_path / jid) is None
    (tmp_path / jid / "job.json").write_text("not json")
    assert J.job_lang(tmp_path / jid) is None


def test_processed_page_count_is_what_a_language_change_does_not_reach(tmp_path: Path):
    jid = J.create_job(tmp_path)
    d = tmp_path / jid
    assert J.count_processed_pages(d) == 0
    for n, ocr in (("page_001", True), ("page_002", True), ("page_003", False)):
        (d / n / "05_ocr").mkdir(parents=True)
        if ocr:
            (d / n / "05_ocr" / "ocr.json").write_text("{}")
    assert J.count_processed_pages(d) == 2
