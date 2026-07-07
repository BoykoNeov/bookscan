"""Unit tests for pipeline.run_all — the stage-chain orchestrator.

Every stage's own ``run()`` is stubbed out (this module's job is sequencing
and error handling, not stage internals — those are covered by each stage's
own test file), so these tests need no GPU, no Tesseract, no real images. Run
with pytest, or directly:
    python -m pipeline.tests.test_run_all
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.page_model import StageMeta
from pipeline import run_all as RA

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ALL_STAGES = RA.STAGE_ORDER


def _install_stubs(monkeypatch, warn_map: dict[str, list[str]] | None = None):
    """Stub all seven stage modules' run() to succeed; returns the shared
    call-order list so tests can assert exactly what ran."""
    warn_map = warn_map or {}
    call_order: list[str] = []
    modules = {
        "00_ingest": RA.S0, "01_fuse": RA.S1, "02_split": RA.S2,
        "03_dewarp": RA.S3, "04_layout": RA.S4, "05_ocr": RA.S5,
        "06_uncertain": RA.S6,
    }
    for name, mod in modules.items():
        def make(name=name, mod=mod):
            def _run(page_dir: Path, cfg: dict, **kwargs):
                call_order.append(name)
                out = page_dir / name
                out.mkdir(parents=True, exist_ok=True)
                meta = StageMeta(stage=name, version="0.0.0",
                                  warnings=warn_map.get(name, []))
                (out / "meta.json").write_text(
                    meta.model_dump_json(), encoding="utf-8")
                return object()
            return _run
        monkeypatch.setattr(mod, "run", make())
    return call_order


# ---- success path -----------------------------------------------------------


def test_runs_all_seven_stages_in_order(tmp_path: Path, monkeypatch):
    call_order = _install_stubs(monkeypatch)
    page_dir = tmp_path / "page_001"

    result = RA.run_page(page_dir, cfg={})

    assert call_order == list(ALL_STAGES)
    assert result.ok is True
    assert result.failed_stage is None
    assert [s.name for s in result.stages] == list(ALL_STAGES)
    assert all(s.ok for s in result.stages)


def test_summary_is_persisted_to_run_all_json(tmp_path: Path, monkeypatch):
    _install_stubs(monkeypatch)
    page_dir = tmp_path / "page_001"

    result = RA.run_page(page_dir, cfg={})

    on_disk = json.loads((page_dir / "run_all.json").read_text())
    assert on_disk["ok"] is True
    assert on_disk["page_dir"] == str(page_dir)
    assert result.model_dump()["stages"] == on_disk["stages"]


def test_warnings_are_pulled_from_each_stages_own_meta_json(tmp_path: Path, monkeypatch):
    _install_stubs(monkeypatch, warn_map={"03_dewarp": ["fell back to classical"]})
    page_dir = tmp_path / "page_001"

    result = RA.run_page(page_dir, cfg={})

    by_name = {s.name: s for s in result.stages}
    assert by_name["03_dewarp"].warnings == ["fell back to classical"]
    assert by_name["01_fuse"].warnings == []


# ---- failure path -------------------------------------------------------


def test_stops_at_first_failure_and_records_it(tmp_path: Path, monkeypatch):
    call_order = _install_stubs(monkeypatch)

    def _boom(page_dir: Path, cfg: dict, **kwargs):
        call_order.append("03_dewarp")
        raise RuntimeError("no UVDoc checkpoint")

    monkeypatch.setattr(RA.S3, "run", _boom)
    page_dir = tmp_path / "page_001"

    result = RA.run_page(page_dir, cfg={})

    # ran 00, 01, 02, then 03 which raised — never reached 04/05/06.
    assert call_order == ["00_ingest", "01_fuse", "02_split", "03_dewarp"]
    assert result.ok is False
    assert result.failed_stage == "03_dewarp"
    assert [s.name for s in result.stages] == [
        "00_ingest", "01_fuse", "02_split", "03_dewarp"]
    assert result.stages[-1].ok is False
    assert "no UVDoc checkpoint" in result.stages[-1].error
    assert all(s.ok for s in result.stages[:-1])


def test_failure_result_is_also_persisted(tmp_path: Path, monkeypatch):
    _install_stubs(monkeypatch)
    monkeypatch.setattr(
        RA.S5, "run",
        lambda page_dir, cfg, **kw: (_ for _ in ()).throw(ValueError("tesseract missing")))
    page_dir = tmp_path / "page_001"

    RA.run_page(page_dir, cfg={})

    on_disk = json.loads((page_dir / "run_all.json").read_text())
    assert on_disk["ok"] is False
    assert on_disk["failed_stage"] == "05_ocr"


# ---- CLI page_dir resolution ---------------------------------------------


def test_cli_builds_page_dir_from_job_and_page(tmp_path: Path, monkeypatch):
    captured = {}

    def _fake_run_page(page_dir, cfg, **kwargs):
        captured["page_dir"] = page_dir
        return RA.PageRunResult(page_dir=str(page_dir), ok=True, stages=[])

    monkeypatch.setattr(RA, "run_page", _fake_run_page)
    monkeypatch.setattr(RA, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(RA.S4, "load_config", lambda path: {})

    rc = RA.main(["--job", "demo", "--page", "page_003"])

    assert rc == 0
    assert captured["page_dir"] == tmp_path / "jobs" / "demo" / "page_003"


def test_cli_uses_literal_page_dir_when_given(tmp_path: Path, monkeypatch):
    captured = {}

    def _fake_run_page(page_dir, cfg, **kwargs):
        captured["page_dir"] = page_dir
        return RA.PageRunResult(page_dir=str(page_dir), ok=True, stages=[])

    monkeypatch.setattr(RA, "run_page", _fake_run_page)
    monkeypatch.setattr(RA.S4, "load_config", lambda path: {})
    literal = tmp_path / "some" / "page_dir"

    rc = RA.main([str(literal)])

    assert rc == 0
    assert captured["page_dir"] == literal


def test_cli_returns_nonzero_on_stage_failure(tmp_path: Path, monkeypatch):
    def _fake_run_page(page_dir, cfg, **kwargs):
        return RA.PageRunResult(page_dir=str(page_dir), ok=False,
                                 failed_stage="04_layout", stages=[])

    monkeypatch.setattr(RA, "run_page", _fake_run_page)
    monkeypatch.setattr(RA.S4, "load_config", lambda path: {})

    rc = RA.main([str(tmp_path / "page_001")])

    assert rc == 1


# ---- real chain (slow: real image, GPU models, Tesseract) -----------------


@pytest.mark.slow
def test_real_testset_image_runs_the_full_chain(tmp_path: Path):
    """The one test that proves the actual chain (no stubs) still produces the
    seven stage folders + run_all.json on a real page — the fast unit tests
    above only cover run_page's own sequencing/error-handling logic.

    Runs the CLI as a **subprocess**, not an in-process ``run_page()`` call.
    An in-process call was tried first and reliably segfaulted (Windows access
    violation deep in doclayout_yolo's lazy pandas/pyarrow import) when run
    alongside the rest of the suite in one pytest process — reproducing, in
    miniature, exactly the crash-isolation risk that is why the future server
    subprocesses this module rather than importing it. Subprocessing here
    isn't just safer, it's the faithful test of the real invocation shape.
    Skips gracefully where the heavy deps (torch/YOLO checkpoint/Tesseract)
    aren't set up, same idiom as the Playwright e2e test's runtime skip."""
    import json
    import subprocess
    import sys

    src = REPO_ROOT / "testset" / "en_coins_01.jpg"
    if not src.exists():
        pytest.skip("testset image not found")

    page_dir = tmp_path / "page_001"
    proc = subprocess.run(
        [sys.executable, "-m", "pipeline.run_all", str(page_dir),
         "--input", str(src), "--mode", "flag"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180,
    )
    combined = proc.stdout + proc.stderr
    if proc.returncode != 0:
        missing_markers = ("tesseract", "checkpoint", "modulenotfounderror",
                            "no such file", "not found")
        if any(m in combined.lower() for m in missing_markers):
            pytest.skip(f"real pipeline deps unavailable:\n{combined[-1000:]}")
        pytest.fail(f"run_all subprocess failed (rc={proc.returncode}):\n"
                    f"{combined[-2000:]}")

    for name in ALL_STAGES:
        assert (page_dir / name).is_dir(), f"missing {name}/"
    assert (page_dir / "run_all.json").exists()
    on_disk = json.loads((page_dir / "run_all.json").read_text())
    assert on_disk["ok"] is True


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    raise SystemExit(_pytest.main([__file__, *sys.argv[1:]]))
