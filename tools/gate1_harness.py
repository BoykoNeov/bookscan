"""Gate 1 OCR quality harness.

Runs Tesseract 5 on the ``testset/`` images (lightly preprocessed), measures
word/char accuracy against ground truth, and — the point of the gate — how
well Tesseract's per-word confidence separates correct from wrong words. Writes
a dated section to ``docs/RESULTS.md`` plus per-image debug overlays and
confidence histograms.

This tool stays INDEPENDENT of ``pipeline/`` so it remains a regression check
whenever OCR settings change (CLAUDE.md).

Usage:
    python -m tools.gate1_harness --testset testset/ --report docs/RESULTS.md
    python -m tools.gate1_harness --self-test        # synthetic end-to-end
    python -m tools.gate1_harness --preprocess otsu   # one variant only

The IO lives here; the number-crunching lives in ``tools.ocr_metrics`` and is
unit-tested separately.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import yaml

from tools import ocr_metrics as M

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PREPROCESS_VARIANTS = ("none", "otsu", "adaptive")
FLAG_RATES = (0.05, 0.10, 0.20)

# Confidence display bands for the overlay (visualization only — NOT decision
# thresholds; real thresholds are per-document adaptive).
BAND_HIGH = 80.0
BAND_LOW = 50.0

# Map friendly manifest language names to Tesseract codes.
LANG_CODES = {
    "english": "eng", "eng": "eng", "en": "eng",
    "bulgarian": "bul", "bul": "bul", "bg": "bul",
    "italian": "ita", "ita": "ita", "it": "ita",
    "german": "deu", "deu": "deu", "de": "deu",
}


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_tessdata_dir(cfg: dict) -> str | None:
    """Absolute tessdata dir; relative config paths resolve against repo root."""
    raw = cfg.get("tesseract", {}).get("tessdata_dir")
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(p) if p.exists() else None


def find_tesseract(cfg: dict) -> str | None:
    """Return a working tesseract binary path, or None if unavailable."""
    cand = cfg.get("tesseract", {}).get("binary")
    if cand and Path(cand).exists():
        return cand
    on_path = shutil.which("tesseract")
    return on_path


def tesseract_version(binary: str) -> str:
    try:
        out = subprocess.run(
            [binary, "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        first = (out.stdout or out.stderr).splitlines()[0].strip()
        # e.g. "tesseract v5.4.0.20240606" -> "5.4.0.20240606"
        return first.split()[-1].lstrip("v") if first else "?"
    except Exception:
        return "?"


def lang_code(name: str) -> str:
    return LANG_CODES.get(name.strip().lower(), name.strip().lower())


# --------------------------------------------------------------------------
# Tesseract invocation
# --------------------------------------------------------------------------


def run_tesseract(
    binary: str,
    image: np.ndarray,
    lang: str,
    tessdata_dir: str | None,
    oem: int,
    psm: int,
) -> str:
    """Write ``image`` to a temp PNG and run Tesseract, returning TSV text."""
    with tempfile.TemporaryDirectory() as td:
        img_path = Path(td) / "in.png"
        cv2.imwrite(str(img_path), image)
        cmd = [binary, str(img_path), "stdout", "--oem", str(oem),
               "--psm", str(psm), "-l", lang]
        if tessdata_dir and Path(tessdata_dir).exists():
            cmd += ["--tessdata-dir", tessdata_dir]
        cmd += ["tsv"]
        # Tesseract emits UTF-8; force it or Windows cp1252 crashes on Cyrillic
        # / accented Latin output (headline languages bul/ita/deu).
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(
                f"tesseract failed (code {proc.returncode}): {proc.stderr.strip()}"
            )
        return proc.stdout


# --------------------------------------------------------------------------
# Preprocessing (light — this gate measures OCR, not enhancement)
# --------------------------------------------------------------------------


def to_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def binarize(gray: np.ndarray, method: str) -> np.ndarray:
    if method == "none":
        return gray
    if method == "otsu":
        _, out = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return out
    if method == "adaptive":
        return cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, blockSize=31, C=15,
        )
    raise ValueError(f"unknown preprocess method: {method}")


def median_word_height(words: list[M.TWord]) -> float:
    heights = [w.height for w in words if w.height > 0]
    return float(np.median(heights)) if heights else 0.0


def upscale(image: np.ndarray, factor: float) -> np.ndarray:
    if factor == 1.0:
        return image
    return cv2.resize(
        image, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC
    )


# --------------------------------------------------------------------------
# Debug artifacts
# --------------------------------------------------------------------------


def band_color(conf: float) -> tuple[int, int, int]:
    """BGR color for a confidence band (green high, yellow mid, red low)."""
    if conf >= BAND_HIGH:
        return (0, 180, 0)
    if conf >= BAND_LOW:
        return (0, 200, 220)
    return (0, 0, 220)


def draw_conf_overlay(image: np.ndarray, words: list[M.TWord]) -> np.ndarray:
    canvas = image.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    for w in words:
        c = band_color(w.conf)
        cv2.rectangle(canvas, (w.left, w.top),
                      (w.left + w.width, w.top + w.height), c, 2)
    return canvas


def conf_histogram(correct: list[float], wrong: list[float], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 4))
    bins = np.linspace(0, 100, 21)
    if correct:
        ax.hist(correct, bins=bins, alpha=0.6, label=f"correct (n={len(correct)})",
                color="#2a9d3f")
    if wrong:
        ax.hist(wrong, bins=bins, alpha=0.6, label=f"wrong (n={len(wrong)})",
                color="#d1495b")
    ax.set_xlabel("Tesseract word confidence")
    ax.set_ylabel("count")
    ax.set_title("Confidence: correct vs. wrong words")
    ax.legend()
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110)
    plt.close(fig)


# --------------------------------------------------------------------------
# Per-image evaluation
# --------------------------------------------------------------------------


@dataclass
class ImageResult:
    image_id: str
    language: str          # tesseract code
    category: str
    preprocess: str
    upscaled: float
    n_words: int
    has_gt: bool
    wer: float | None = None
    cer: float | None = None
    auroc: float | None = None
    flag_stats: dict[float, M.FlagStats] = field(default_factory=dict)
    confs_correct: list[float] = field(default_factory=list)
    confs_wrong: list[float] = field(default_factory=list)


def evaluate_image(
    binary: str, cfg: dict, image_bgr: np.ndarray, lang: str, gt_text: str | None,
    preprocess: str, image_id: str, category: str, debug_dir: Path,
) -> ImageResult:
    tcfg = cfg.get("tesseract", {})
    tessdata = resolve_tessdata_dir(cfg)
    oem, psm = int(tcfg.get("oem", 1)), int(tcfg.get("psm", 3))

    gray = to_gray(image_bgr)

    # Probe pass to decide upscale (median text height < 20px -> 2x).
    probe_tsv = run_tesseract(binary, gray, lang, tessdata, oem, psm)
    probe_words = M.parse_tsv(probe_tsv)
    med_h = median_word_height(probe_words)
    scale = 2.0 if 0 < med_h < 20 else 1.0

    proc = binarize(upscale(gray, scale), preprocess)
    tsv = run_tesseract(binary, proc, lang, tessdata, oem, psm)
    words = M.parse_tsv(tsv)

    # Debug overlay drawn on the (possibly upscaled) processed image.
    debug_dir.mkdir(parents=True, exist_ok=True)
    overlay = draw_conf_overlay(upscale(image_bgr, scale), words)
    cv2.imwrite(str(debug_dir / f"{image_id}_{preprocess}_conf.png"), overlay)

    res = ImageResult(
        image_id=image_id, language=lang, category=category,
        preprocess=preprocess, upscaled=scale, n_words=len(words),
        has_gt=gt_text is not None,
    )
    if gt_text is None:
        return res

    ocr_text = M.tsv_words_to_text(words)
    gt_tokens = M.tokenize(gt_text)
    # Headline accuracy: compare hyphen-joined, whitespace-normalized text so
    # WER reflects recognition errors, not line-break formatting.
    res.wer = M.wer(gt_tokens, M.tokenize(ocr_text))
    res.cer = M.cer(gt_text, ocr_text)

    # Confidence separation needs a correct/incorrect label per Tesseract word,
    # paired 1:1 with that word's confidence. Label the RAW per-word tokens
    # (not the hyphen-joined stream) so the counts always match the conf list.
    ocr_word_tokens = [w.text for w in words]
    labels_correct = M.label_ocr_words(gt_tokens, ocr_word_tokens)
    confs = [w.conf for w in words]
    is_wrong = [not c for c in labels_correct]
    res.auroc = M.auroc(confs, is_wrong)
    for fs in M.flag_rate_stats(confs, is_wrong, list(FLAG_RATES)):
        res.flag_stats[fs.flag_rate] = fs
    res.confs_correct = [c for c, ok in zip(confs, labels_correct) if ok]
    res.confs_wrong = [c for c, ok in zip(confs, labels_correct) if not ok]

    conf_histogram(res.confs_correct, res.confs_wrong,
                   debug_dir / f"{image_id}_{preprocess}_hist.png")
    return res


# --------------------------------------------------------------------------
# Aggregation + report
# --------------------------------------------------------------------------


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _fmt(x: float | None, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x * 100:.1f}%" if pct else f"{x:.3f}"


def aggregate_by(results: list[ImageResult], key) -> dict[str, dict]:
    groups: dict[str, list[ImageResult]] = {}
    for r in results:
        groups.setdefault(key(r), []).append(r)
    out = {}
    for name, rs in sorted(groups.items()):
        gt = [r for r in rs if r.has_gt]
        out[name] = {
            "images": len(rs),
            "wer": _mean([r.wer for r in gt]),
            "cer": _mean([r.cer for r in gt]),
            "auroc": _mean([r.auroc for r in gt]),
            "recall10": _mean([
                r.flag_stats[0.10].recall for r in gt if 0.10 in r.flag_stats
            ]),
        }
    return out


def write_report(
    report_path: Path, results: list[ImageResult], preprocess: str,
    tver: str, run_date: str,
) -> None:
    by_lang = aggregate_by(results, lambda r: r.language)
    by_cat = aggregate_by(results, lambda r: r.category or "uncategorized")

    lines: list[str] = []
    lines.append(f"\n## Gate 1 run — {run_date}, tesseract {tver}, "
                 f"preprocessing={preprocess}\n")
    lines.append("| language | images | WER | CER | conf AUROC | "
                 "err-recall @10% flagged |")
    lines.append("|---|---|---|---|---|---|")
    for lang, m in by_lang.items():
        lines.append(
            f"| {lang} | {m['images']} | {_fmt(m['wer'], True)} | "
            f"{_fmt(m['cer'], True)} | {_fmt(m['auroc'])} | "
            f"{_fmt(m['recall10'], True)} |"
        )
    lines.append("\n**By category:**\n")
    lines.append("| category | images | WER | CER | conf AUROC |")
    lines.append("|---|---|---|---|---|")
    for cat, m in by_cat.items():
        lines.append(
            f"| {cat} | {m['images']} | {_fmt(m['wer'], True)} | "
            f"{_fmt(m['cer'], True)} | {_fmt(m['auroc'])} |"
        )

    verdict = interpret(by_lang)
    lines.append(f"\nVerdict: {verdict}\n")
    lines.append(
        "> Caveat: confidence is labeled per raw Tesseract word (1:1 with the "
        "conf value), while WER uses hyphen-joined text. Line-end hyphenations "
        "(e.g. `encyclo-`+`pedia` vs GT `encyclopedia`) therefore count as two "
        "HIGH-confidence wrong tokens, which inflates WER and depresses AUROC on "
        "hyphen-heavy pages. A borderline MIXED verdict on real English pages "
        "may be this artifact rather than genuine OCR failure.\n"
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    header = ""
    if not report_path.exists():
        header = "# Gate results (append-only history)\n"
    with open(report_path, "a", encoding="utf-8") as f:
        if header:
            f.write(header)
        f.write("\n".join(lines) + "\n")


def interpret(by_lang: dict[str, dict]) -> str:
    """Rough PASS/MIXED/FAIL heuristic per GATE1_SPEC decision criteria."""
    en = by_lang.get("eng")
    if not en or en["wer"] is None or en["auroc"] is None:
        return "INCONCLUSIVE — insufficient ground-truth pages to judge."
    en_acc = 1 - en["wer"]
    auroc_ok = en["auroc"] >= 0.80
    others = [m for l, m in by_lang.items() if l != "eng" and m["wer"] is not None]
    others_ok = all((1 - m["wer"]) >= 0.95 for m in others) if others else True
    if en_acc >= 0.98 and auroc_ok and others_ok:
        return ("PASS — clean English ≥98% word accuracy, other languages within "
                "striking distance, confidence AUROC ≥0.80. Proceed to Gate 2.")
    if auroc_ok:
        return ("MIXED — accuracy below bar but confidence signal is usable "
                "(AUROC ≥0.80). Proceed with Gate 2 (fusion/dewarp) as priority.")
    return ("FAIL — confidence does not separate errors (AUROC <0.80) and/or "
            "accuracy poor. Benchmark MinerU/Surya before building stages.")


# --------------------------------------------------------------------------
# Test-set driver
# --------------------------------------------------------------------------


def read_manifest(testset: Path) -> list[dict]:
    manifest = testset / "manifest.csv"
    if not manifest.exists():
        return []
    with open(manifest, newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f)]


def run_testset(binary: str, cfg: dict, testset: Path, report: Path,
                variants: list[str]) -> list[ImageResult]:
    rows = read_manifest(testset)
    debug_dir = testset / "debug"
    tver = tesseract_version(binary)
    run_date = datetime.date.today().isoformat()
    all_results: list[ImageResult] = []
    for variant in variants:
        results: list[ImageResult] = []
        for row in rows:
            img_file = testset / row["file"]
            if not img_file.exists():
                print(f"  ! missing image: {img_file}", file=sys.stderr)
                continue
            image = cv2.imread(str(img_file), cv2.IMREAD_COLOR)
            if image is None:
                print(f"  ! unreadable: {img_file}", file=sys.stderr)
                continue
            lang = lang_code(row.get("language", "eng"))
            gt_text = None
            gt_file = (row.get("gt_file") or "").strip()
            if gt_file:
                gp = testset / gt_file
                if gp.exists():
                    gt_text = gp.read_text(encoding="utf-8")
            res = evaluate_image(
                binary, cfg, image, lang, gt_text, variant,
                row["image_id"], row.get("category", ""), debug_dir,
            )
            results.append(res)
            print(f"  [{variant}] {row['image_id']}: {res.n_words} words"
                  + (f", WER={_fmt(res.wer, True)}, AUROC={_fmt(res.auroc)}"
                     if res.has_gt else " (no GT)"))
        if results:
            write_report(report, results, variant, tver, run_date)
        all_results += results
    return all_results


# --------------------------------------------------------------------------
# Synthetic self-test (end-to-end without the user's photos)
# --------------------------------------------------------------------------


def render_text_image(text: str, width: int = 1000) -> np.ndarray:
    """Render text to a clean black-on-white BGR image with PIL."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        font = ImageFont.load_default()
    lines = text.split("\n")
    line_h = 46
    img = Image.new("RGB", (width, line_h * (len(lines) + 1) + 20), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((30, 20 + i * line_h), line, fill="black", font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def self_test(binary: str, cfg: dict) -> int:
    """Render known text, run the full chain, assert the numbers are sane."""
    gt = ("The quick brown fox jumps over the lazy dog.\n"
          "Pack my box with five dozen liquor jugs.\n"
          "Sphinx of black quartz judge my vow.")
    image = render_text_image(gt)
    out_dir = REPO_ROOT / "jobs" / "_gate1_selftest"
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = True
    for variant in PREPROCESS_VARIANTS:
        res = evaluate_image(
            binary, cfg, image, "eng", gt, variant, "selftest", "synthetic",
            out_dir,
        )
        print(f"[self-test:{variant}] words={res.n_words} "
              f"WER={_fmt(res.wer, True)} CER={_fmt(res.cer, True)} "
              f"AUROC={_fmt(res.auroc)}")
        if res.wer is None or res.wer > 0.10:
            print(f"  ! WER too high for clean synthetic text ({res.wer})")
            ok = False
    print("\nSELF-TEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 1 OCR quality harness")
    ap.add_argument("--testset", type=Path, default=REPO_ROOT / "testset")
    ap.add_argument("--report", type=Path, default=REPO_ROOT / "docs" / "RESULTS.md")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--preprocess", choices=(*PREPROCESS_VARIANTS, "all"),
                    default="all", help="binarization variant(s) to run")
    ap.add_argument("--self-test", action="store_true",
                    help="render synthetic text and run the full chain")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    binary = find_tesseract(cfg)
    if not binary:
        print(
            "ERROR: Tesseract not found. Set tesseract.binary in config.yaml or\n"
            "install it (Windows): winget install --id UB-Mannheim.TesseractOCR\n"
            "then install eng/bul/ita/deu traineddata (tessdata_best).",
            file=sys.stderr,
        )
        return 2
    print(f"tesseract: {binary} (v{tesseract_version(binary)})")

    if args.self_test:
        return self_test(binary, cfg)

    variants = list(PREPROCESS_VARIANTS) if args.preprocess == "all" else [args.preprocess]
    results = run_testset(binary, cfg, args.testset, args.report, variants)
    if not results:
        print("No images evaluated. Populate testset/manifest.csv first.",
              file=sys.stderr)
        return 1
    print(f"\nDone. {len(results)} evaluations. Report appended to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
