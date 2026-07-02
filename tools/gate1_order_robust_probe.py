"""Order-robust AUROC probe for Gate 1 (diagnostic, not part of the gate).

On the raw spreads, Tesseract scrambles reading order (figure-caption sidebars
create false column boundaries; some spreads interleave the two facing pages).
The gate's confidence metric labels words via ``label_ocr_words`` — a
Levenshtein alignment over token *order* — so correctly-recognized-but-displaced
words get marked wrong at high confidence, depressing AUROC. That makes the
English/Italian numbers a *layout* artifact, not an OCR-quality result.

This probe recomputes AUROC with an order-FREE label: a word is correct iff it
exists in the ground-truth bag (multiset membership). Comparing the two isolates
the reading-order effect from genuine recognition/confidence quality.

    python -m tools.gate1_order_robust_probe

See ``docs/RESULTS.md`` (Gate 1 interpretation) for how this is read. The proper
fix — an order-robust labeling option inside ``ocr_metrics`` with unit tests —
is tracked as a follow-up; this stays a standalone diagnostic.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import cv2

from tools import gate1_harness as H
from tools import ocr_metrics as M

REPO_ROOT = Path(__file__).resolve().parent.parent

# GT spreads worth probing: one English (scrambled) + both Bulgarian.
CASES = [("en_coins_01", "eng"), ("bg_01", "bul"), ("bg_02", "bul")]


def multiset_labels(gt_tokens: list[str], ocr_tokens: list[str]) -> list[bool]:
    """True per OCR token iff present in the GT bag (order ignored)."""
    bag = Counter(gt_tokens)
    out = []
    for t in ocr_tokens:
        if bag.get(t, 0) > 0:
            bag[t] -= 1
            out.append(True)
        else:
            out.append(False)
    return out


def main() -> int:
    cfg = H.load_config(REPO_ROOT / "config.yaml")
    binary = H.find_tesseract(cfg)
    if not binary:
        print("Tesseract not found (see config.yaml).")
        return 2
    tessdata = H.resolve_tessdata_dir(cfg)
    oem, psm = 1, 3

    print(f"{'image':<14}{'words':>6}{'seq-AUROC':>11}{'ms-AUROC':>10}"
          f"{'seq-acc':>9}{'ms-acc':>8}")
    print("-" * 58)
    for img_id, lang in CASES:
        img = cv2.imread(str(REPO_ROOT / "testset" / f"{img_id}.jpg"),
                         cv2.IMREAD_COLOR)
        tsv = H.run_tesseract(binary, H.to_gray(img), lang, tessdata, oem, psm)
        words = M.parse_tsv(tsv)
        ocr_tokens = [w.text for w in words]
        confs = [w.conf for w in words]
        gt_tokens = M.tokenize(
            (REPO_ROOT / "testset" / "gt" / f"{img_id}.txt").read_text("utf-8")
        )

        seq_ok = M.label_ocr_words(gt_tokens, ocr_tokens)
        ms_ok = multiset_labels(gt_tokens, ocr_tokens)
        seq_auroc = M.auroc(confs, [not c for c in seq_ok])
        ms_auroc = M.auroc(confs, [not c for c in ms_ok])
        seq_acc = sum(seq_ok) / len(seq_ok) if seq_ok else 0.0
        ms_acc = sum(ms_ok) / len(ms_ok) if ms_ok else 0.0

        def f(x: float | None) -> str:
            return f"{x:.3f}" if x is not None else "  -  "

        print(f"{img_id:<14}{len(words):>6}{f(seq_auroc):>11}{f(ms_auroc):>10}"
              f"{seq_acc:>9.1%}{ms_acc:>8.1%}")

    print("\nseq-* = harness method (order-sensitive); "
          "ms-* = multiset/order-free (recognition ceiling)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
