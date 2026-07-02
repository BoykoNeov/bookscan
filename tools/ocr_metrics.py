"""Pure, IO-free OCR accuracy + confidence metrics for the Gate 1 harness.

Everything here takes plain data (strings, token lists, number lists) and
returns numbers. NO file IO, NO Tesseract, NO plotting — so it is trivially
unit-testable with hand-built inputs where the answer is known by hand. The
harness (``tools.gate1_harness``) does the IO and calls into here.

The load-bearing pieces are:
  * ``label_ocr_words`` — align OCR tokens to ground truth and mark each OCR
    word correct/incorrect. This mapping is what the whole confidence metric
    rides on.
  * ``auroc`` — how well low confidence predicts a wrong word (the number the
    gate cares about). Direction matters: LOW conf must score as MORE wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz.distance import Levenshtein

# --------------------------------------------------------------------------
# Text normalization — MUST be applied identically to OCR output and GT so
# that WER reflects recognition errors, not formatting differences.
# --------------------------------------------------------------------------

_HYPHEN_LINEBREAK = re.compile(r"(\w)[-­]\s*\n\s*(\w)")
_WHITESPACE = re.compile(r"\s+")


def join_hyphenated(text: str) -> str:
    """Join a line-end hyphen with the start of the next line.

    GT is already stored with hyphenated line-breaks joined, so on GT this is
    an (idempotent) no-op; on raw OCR text it removes the line-break hyphen.
    Applying the same function to both keeps the comparison fair.
    """
    # Loop because adjacent hyphenations can chain.
    prev = None
    while prev != text:
        prev = text
        text = _HYPHEN_LINEBREAK.sub(r"\1\2", text)
    return text


def normalize_text(text: str) -> str:
    """Canonical form for alignment: hyphens joined, whitespace collapsed."""
    return _WHITESPACE.sub(" ", join_hyphenated(text)).strip()


def tokenize(text: str) -> list[str]:
    """Whitespace tokenization after normalization."""
    norm = normalize_text(text)
    return norm.split(" ") if norm else []


# --------------------------------------------------------------------------
# Tesseract TSV parsing
# --------------------------------------------------------------------------


@dataclass
class TWord:
    """One recognized word parsed from a Tesseract TSV row (level==5)."""

    text: str
    conf: float
    left: int
    top: int
    width: int
    height: int
    block_num: int
    par_num: int
    line_num: int
    word_num: int


# Standard column order emitted by `tesseract ... tsv`.
_TSV_HEADER = [
    "level", "page_num", "block_num", "par_num", "line_num", "word_num",
    "left", "top", "width", "height", "conf", "text",
]


def parse_tsv(tsv: str) -> list[TWord]:
    """Parse Tesseract TSV into word rows only.

    Filters out non-word rows: only ``level==5`` are words. Tesseract also
    emits ``conf==-1`` and empty/whitespace ``text`` for structural rows —
    drop those or they pollute every metric.
    """
    lines = tsv.splitlines()
    if not lines:
        return []
    # Tolerate a header row (real tesseract emits one); detect by first field.
    start = 1 if lines[0].split("\t")[:1] == ["level"] else 0
    words: list[TWord] = []
    for raw in lines[start:]:
        cols = raw.split("\t")
        if len(cols) < len(_TSV_HEADER):
            continue
        try:
            level = int(cols[0])
        except ValueError:
            continue
        if level != 5:
            continue
        text = cols[11]
        if not text or not text.strip():
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        if conf < 0:  # -1 marks non-recognized structural rows
            continue
        words.append(
            TWord(
                text=text.strip(),
                conf=conf,
                left=int(cols[6]), top=int(cols[7]),
                width=int(cols[8]), height=int(cols[9]),
                block_num=int(cols[2]), par_num=int(cols[3]),
                line_num=int(cols[4]), word_num=int(cols[5]),
            )
        )
    return words


def tsv_words_to_text(words: list[TWord]) -> str:
    """Reconstruct line-structured text from TSV words (for hyphen joining).

    Words on the same (block, par, line) join with spaces; a new line starts a
    newline, so ``join_hyphenated`` can act on real line-breaks.
    """
    out: list[str] = []
    last_key: tuple[int, int, int] | None = None
    for w in words:
        key = (w.block_num, w.par_num, w.line_num)
        if last_key is None:
            out.append(w.text)
        elif key == last_key:
            out.append(" " + w.text)
        else:
            out.append("\n" + w.text)
        last_key = key
    return "".join(out)


# --------------------------------------------------------------------------
# Alignment + per-word correct/incorrect labeling
# --------------------------------------------------------------------------


def label_ocr_words(gt_tokens: list[str], ocr_tokens: list[str]) -> list[bool]:
    """Return, per OCR token, True if it is correct against GT.

    Uses word-level Levenshtein opcodes with GT as source and OCR as dest:
      * ``equal``   → those OCR tokens are correct
      * ``replace`` → substituted OCR tokens are wrong
      * ``insert``  → spurious OCR tokens (not in GT) are wrong
      * ``delete``  → GT token missing from OCR: no OCR word to label
    Result length == len(ocr_tokens).
    """
    correct = [False] * len(ocr_tokens)
    for tag, _i1, _i2, j1, j2 in Levenshtein.opcodes(gt_tokens, ocr_tokens):
        if tag == "equal":
            for j in range(j1, j2):
                correct[j] = True
        # replace / insert → wrong (already False); delete → no dest token
    return correct


def wer(gt_tokens: list[str], ocr_tokens: list[str]) -> float:
    """Word error rate = token edit distance / #GT tokens."""
    if not gt_tokens:
        return 0.0 if not ocr_tokens else 1.0
    dist = Levenshtein.distance(gt_tokens, ocr_tokens)
    return dist / len(gt_tokens)


def cer(gt_text: str, ocr_text: str) -> float:
    """Character error rate over normalized text = char edit dist / #GT chars."""
    gt = normalize_text(gt_text)
    ocr = normalize_text(ocr_text)
    if not gt:
        return 0.0 if not ocr else 1.0
    return Levenshtein.distance(gt, ocr) / len(gt)


def word_accuracy(gt_tokens: list[str], ocr_tokens: list[str]) -> float:
    """1 - WER, floored at 0."""
    return max(0.0, 1.0 - wer(gt_tokens, ocr_tokens))


# --------------------------------------------------------------------------
# Confidence separation
# --------------------------------------------------------------------------


def auroc(confs: list[float], is_wrong: list[bool]) -> float | None:
    """AUROC of confidence as a WRONG-word detector.

    Positive class = wrong word; the detector score is wrongness, i.e. LOW
    confidence => high score. Equivalently we compute P(conf_correct >
    conf_wrong) + 0.5*ties via the rank-based (Mann-Whitney U) statistic,
    which equals AUROC with score = -conf, positive=wrong.

    Returns None if either class is empty (AUROC undefined).
    """
    n = len(confs)
    if n == 0 or len(is_wrong) != n:
        return None
    pos = sum(1 for w in is_wrong if w)      # wrong words
    neg = n - pos                             # correct words
    if pos == 0 or neg == 0:
        return None

    # Rank confidences ascending, averaging ties. Low conf -> low rank.
    order = sorted(range(n), key=lambda i: confs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and confs[order[j + 1]] == confs[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based average rank
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1

    # Mann-Whitney U for the WRONG group: pairs where a wrong word has HIGHER
    # conf than a correct word (ties count 0.5 via average ranks).
    rank_sum_wrong = sum(ranks[i] for i in range(n) if is_wrong[i])
    u_wrong_higher = rank_sum_wrong - pos * (pos + 1) / 2.0
    # We want the opposite: low conf predicts wrong, i.e. P(conf_wrong <
    # conf_correct). That is the complement of U_wrong_higher.
    return (pos * neg - u_wrong_higher) / (pos * neg)


@dataclass
class FlagStats:
    flag_rate: float      # fraction of words flagged
    threshold: float      # conf cutoff used (flag conf <= threshold)
    recall: float         # fraction of actual wrong words caught
    precision: float      # fraction of flagged words that were actually wrong
    n_flagged: int


def flag_rate_stats(
    confs: list[float], is_wrong: list[bool], rates: list[float]
) -> list[FlagStats]:
    """For each target flag rate, flag the lowest-confidence words and report
    recall (errors caught) and precision (flags that were real errors).

    This models the per-document ADAPTIVE threshold: flag the bottom X% by
    confidence, no fixed global cutoff.
    """
    n = len(confs)
    total_wrong = sum(1 for w in is_wrong if w)
    order = sorted(range(n), key=lambda i: confs[i])  # ascending conf
    out: list[FlagStats] = []
    for rate in rates:
        k = round(rate * n)
        flagged = set(order[:k])
        # Include any words tied in conf with the last flagged one? Keep simple:
        # exactly k lowest-confidence words.
        caught = sum(1 for i in flagged if is_wrong[i])
        recall = caught / total_wrong if total_wrong else 0.0
        precision = caught / k if k else 0.0
        threshold = confs[order[k - 1]] if k else float("-inf")
        out.append(
            FlagStats(
                flag_rate=rate, threshold=threshold, recall=recall,
                precision=precision, n_flagged=k,
            )
        )
    return out
