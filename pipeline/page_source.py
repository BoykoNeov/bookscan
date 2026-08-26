"""Per-page frame selection — choose a DIFFERENT photograph for each half-page.

Today one photograph becomes both pages of a spread: Stage 01 elects the
sharpest full-spread frame as ``anchor.png`` and Stage 02 cuts *that* frame in
two. A capture that holds the left page flat while the right one curls into
shadow therefore has no way to contribute only its good half. This module is
the opt-in machinery that lets the left page come from frame A and the right
from frame B.

**It is OFF by default, and the reason is measured, not cautious.**
``tools/perpage_choice_probe.py`` (RESULTS 2026-08-26, evidence
``docs/data/perpage_choice_probe_20260826.json``) asked whether this is worth
doing on the committed corpus. Three findings shape everything below:

  1. The two sides really do prefer different photographs — on 3 of 7 scored
     sets. So this is a real operation, not a no-op by construction.
  2. Nothing clears the bar. 0 of 7. The largest per-side lead is +37 words /
     +11.8 confidence; the whole per-page ORACLE is 59 high-confidence words
     across ~4400, over two sets.
  3. **No cheap criterion ranks frames the way OCR does.** Five statistics were
     scored against the OCR winner over 15 decided side races: chance is 6.8,
     the best (ink density) got 11, the incumbent's own variance-of-Laplacian
     got 9 flat / 10 dewarped. Worse, on the one race with real headroom the
     *loser* is both the sharper and the inkier image. That is why this module
     ships exactly one criterion and no sharpness knob: a sharpness-based
     per-page selector is measured to pick the loser on the only case worth
     winning.

So the only criterion here is the metric itself — dewarp each candidate's side
and OCR it — which cannot lose because it *is* what the bar is written in. It
costs a Stage 03 dewarp plus a Tesseract pass per candidate per side, and that
cost is the reason for the default.

**The bar is a validity boundary, not conservatism.** ``min_word_gain`` defaults
to 60, the reframing-churn floor: the measured amount this instrument's word
count moves when the framing changes at all (RESULTS 2026-08-19). Below it a
word-count difference does not mean anything, so a lower default would be
choosing between photographs on noise. At the default, on the committed corpus,
this changes nothing — that is the honest expectation, not a validation. What it
is for is multi-view capture, where two oblique frames trade sides
(``skewset_de_01``: 173/62 words against 136/105).

**Stage-boundary note (a documented exception to CLAUDE.md).** A stage reads
only the previous stage's artifacts. This selector needs the gutter (Stage 02)
to know where a page is, and the candidate pixels (Stage 00) to choose between.
So in ``ocr`` mode Stage 02 reads the full-spread frames back out of
``00_ingest/``, named by ``01_fuse/fuse.json``'s ``fullspread_frames``. The
rule's purpose — immutability and re-runnability — is untouched: ``00_ingest``
is upstream, is never written here, and nothing is cached. The alternative
(Stage 01 duplicating every candidate into ``01_fuse/``) costs ~100 MB of 12 Mpx
PNG per spread to avoid a read that is already safe.

The speculative dewarp + OCR is entirely IN MEMORY. It writes no artifacts, so
it cannot violate the stage contract's immutability rule, and Stage 03/05 still
run normally afterwards on whatever pixels were chosen.

Config (``config.yaml``, top level)::

    per_page_source:
      mode: off            # off | ocr
      min_word_gain: 60    # churn floor; below this a word difference is noise
      require_conf_gain: true
      dewarp_method: auto  # probe dewarp arm (auto | uvdoc | classical)
      max_candidates: 4    # cost guard: candidates scored per spread
      lang: null           # null -> languages.default
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, Field

from pipeline import book_boundary as BB
from pipeline import stage03_dewarp as S3
# Same import direction Stage 05 already uses and documents: ``tools.gate1_harness``
# is the Tesseract IO harness and imports no ``pipeline`` module, so there is no
# cycle. Reusing it keeps this probe on the exact oem/psm path the measurement
# used, so a selection made here tracks the numbers in RESULTS.
from tools.gate1_harness import find_tesseract, resolve_tessdata_dir, run_tesseract

MODES = ("off", "ocr")

DEFAULTS = {
    "mode": "off",
    # The reframing-churn floor (RESULTS 2026-08-19): this instrument's own
    # word-count noise when the framing changes. NOT a comfort margin — below it
    # the criterion is not measuring anything.
    "min_word_gain": 60,
    "require_conf_gain": True,
    "dewarp_method": "auto",
    "max_candidates": 4,
    "lang": None,
}


def resolve_params(cfg: dict) -> dict:
    params = dict(DEFAULTS)
    params.update(cfg.get("per_page_source", {}) or {})
    mode = params["mode"]
    # YAML 1.1 reads a bare ``off`` as the boolean False (and ``on`` as True), so
    # the most natural way to write this setting arrives here as a bool. Accept
    # it rather than failing with a message about 'false' not being a mode.
    if isinstance(mode, bool):
        mode = "off" if mode is False else "ocr"
    mode = str(mode).lower()
    if mode not in MODES:
        raise ValueError(
            f"per_page_source.mode: {params['mode']!r} — expected one of "
            f"{' | '.join(MODES)}. Cheap statistics (sharpness, ink density) are "
            f"deliberately NOT offered: measured at chance overall and wrong on "
            f"the one case with headroom (RESULTS 2026-08-26)."
        )
    params["mode"] = mode
    return params


# --------------------------------------------------------------------------
# Geometry — Stage 02's own cut, in memory, keeping every box
# --------------------------------------------------------------------------


def split_geometry(bgr: np.ndarray, cfg: dict):
    """``stage02_split.run``'s geometry, in memory, keeping every box.

    Same three steps in the same order as the stage: find the book, detect the
    gutter inside the SEARCH box, cut the EMIT box with the margin the stage
    would use for that detector layer (``pinch_margin_frac`` on a Layer-2 split,
    which is wider — a harness that forgot this read whole pages short, see
    RESULTS 2026-08-26). Returns ``(pieces, gutter_x, book, method, diag)`` where
    ``pieces`` is ``[(name, img, box_in_original_frame_coords), ...]`` and
    ``diag`` is ``detect_gutter``'s diagnostics, so a caller can draw this
    candidate's own Stage 02 overlay without re-detecting.

    This is the single definition of "how a candidate frame would be cut": the
    production selector and ``tools/perpage_choice_probe`` both call it, so the
    thing that ships is the thing that was measured.
    """
    # Imported HERE, not at module scope: Stage 02 imports this module for its
    # schema, so a module-level import back into Stage 02 would be a cycle. This
    # function is the only place that needs it.
    from pipeline import stage02_split as S2

    p = S2.resolve_params(cfg)
    book = BB.find_book(bgr, BB.resolve_params(cfg))
    ex0, ey0, ex1, ey1 = book.emit
    sx0, sy0, sx1, sy1 = book.search
    gray = cv2.cvtColor(bgr[sy0:sy1, sx0:sx1], cv2.COLOR_BGR2GRAY)
    gutter_local, diag = S2.detect_gutter(gray, p)
    gutter_x = None if gutter_local is None else gutter_local + sx0

    method = diag["method"]
    margin_frac = (p["pinch_margin_frac"] if method == "pinch" else p["margin_frac"])
    emit = bgr[ey0:ey1, ex0:ex1]
    margin = int(emit.shape[1] * margin_frac)
    pieces = S2.cut_pages(emit, None if gutter_x is None else gutter_x - ex0, margin)
    out = [(name, img, (box.x + ex0, box.y + ey0, box.w, box.h))
           for name, img, box in pieces]
    return out, gutter_x, book, method, diag


# --------------------------------------------------------------------------
# The criterion
# --------------------------------------------------------------------------


def score_tsv(tsv: str) -> tuple[int, float, int]:
    """(words at conf >= 80, mean conf over all words, n words) from Tesseract TSV.

    The census instrument, unchanged: a high-confidence word count is what the
    bar is written in, and the mean confidence is the second statistic a
    challenger must also win so that "more words" cannot be bought with junk.
    """
    confs: list[float] = []
    for line in tsv.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or not parts[11].strip():
            continue
        try:
            confs.append(float(parts[10]))
        except ValueError:
            continue
    if not confs:
        return 0, 0.0, 0
    return (sum(1 for c in confs if c >= 80.0),
            round(float(np.mean(confs)), 1), len(confs))


class SideScore(BaseModel):
    """One candidate's reading of one side, after the speculative dewarp."""

    frame: str
    words_ge_80: int
    mean_conf: float
    n_words: int
    dewarp_method: str = ""


class SideChoice(BaseModel):
    """Which photograph won one side, and by what."""

    name: str                  # left.png | right.png
    source: str                # the frame whose pixels are emitted
    changed: bool              # source is not the incumbent anchor
    reason: str
    scores: list[SideScore] = Field(default_factory=list)


class SelectionResult(BaseModel):
    """Contents of ``split.json``'s ``per_page_source`` block."""

    mode: str
    incumbent: str
    considered: list[str] = Field(default_factory=list)
    ineligible: list[str] = Field(default_factory=list)   # "name: why"
    sides: list[SideChoice] = Field(default_factory=list)
    min_word_gain: int = 60
    require_conf_gain: bool = True
    probe_ms: float = 0.0
    changed_any: bool = False
    # Why nothing was chosen, when nothing was. Empty once a race actually ran.
    # A selector that silently does nothing is indistinguishable from a broken
    # one, so every no-op path names itself here AND in meta.warnings.
    note: str = ""


class Candidate:
    """A frame that could supply a page, with its own cut. Runtime only."""

    def __init__(self, name: str, image: np.ndarray, cfg: dict):
        self.name = name
        self.image = image
        pieces, gutter_x, book, method, diag = split_geometry(image, cfg)
        self.pieces = {n: (img, box) for n, img, box in pieces}
        self.gutter_x = gutter_x
        self.book = book
        self.method = method
        self.diag = diag        # kept so Stage 02 can draw this frame's overlay

    @property
    def side_names(self) -> set[str]:
        return set(self.pieces)


def _load_frame(path: Path) -> np.ndarray:
    # IMREAD_IGNORE_ORIENTATION for the same reason Stage 02 reads the anchor
    # that way: orientation is Stage 00's job and has already been applied to
    # the file; letting cv2 re-apply an EXIF tag here would rotate it twice.
    img = cv2.imread(str(path), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if img is None:
        raise RuntimeError(f"unreadable frame: {path}")
    return img


def candidate_names(page_dir: Path) -> tuple[str, list[str]]:
    """(incumbent anchor frame name, other full-spread frame names).

    Reads ``01_fuse/fuse.json`` — Stage 01 already records exactly this: which
    frame became the anchor, and which frames were full-spread-sized enough to
    have competed for it. Close-ups are NOT candidates: measured page coverage
    of the 11 real ones is 0.80 / 0.64 / 0.64 / 0.54 / 0.48 (six do not register
    at all) against a bar of 0.98, so none of them contains a whole page.
    """
    fuse_json = page_dir / "01_fuse" / "fuse.json"
    if not fuse_json.exists():
        return "", []
    fuse = json.loads(fuse_json.read_text(encoding="utf-8"))
    anchor = str(fuse.get("anchor_source", ""))
    others = [n for n in fuse.get("fullspread_frames", []) if n != anchor]
    return anchor, others


def select(page_dir: Path, cfg: dict, params: dict, anchor: np.ndarray,
           warnings: list[str]) -> tuple[SelectionResult, dict]:
    """Choose a source frame per side. Returns (result, {side_name: Candidate}).

    An empty ``chosen`` dict means every page comes from the anchor, exactly as
    with the mode off. That can happen because no challenger cleared the bar, or
    because the probe never ran at all; the two are NOT the same and are told
    apart by ``result.note`` (empty iff a race actually ran) as well as by
    meta.warnings. A selector that silently does nothing is indistinguishable
    from a broken one, so no path here returns quietly.
    """
    t0 = time.perf_counter()
    incumbent_name, other_names = candidate_names(page_dir)
    incumbent = Candidate(incumbent_name or "01_fuse/anchor.png", anchor, cfg)

    def _stop(note: str) -> tuple[SelectionResult, dict]:
        warnings.append(f"per_page_source: {note}")
        return SelectionResult(
            mode=params["mode"], incumbent=incumbent.name,
            considered=other_names, min_word_gain=int(params["min_word_gain"]),
            require_conf_gain=bool(params["require_conf_gain"]), note=note,
            probe_ms=round((time.perf_counter() - t0) * 1000.0, 1)), {}

    if incumbent.gutter_x is None:
        return _stop("the anchor has no confident gutter (single page), so there "
                     "are no per-page sides to choose between; using the anchor.")
    if not other_names:
        return _stop("mode is ON but Stage 01 reports no other full-spread frame "
                     "for this spread — nothing to choose between. Per-page "
                     "selection needs at least two frames covering the whole "
                     "spread; using the anchor.")

    ingest = page_dir / "00_ingest"
    limit = max(0, int(params["max_candidates"]))
    challengers: list[Candidate] = []
    ineligible: list[str] = []
    for name in other_names[:limit]:
        path = ingest / name
        if not path.exists():
            ineligible.append(f"{name}: frame not in 00_ingest/")
            continue
        try:
            cand = Candidate(name, _load_frame(path), cfg)
        except Exception as exc:                     # a bad frame is not fatal
            ineligible.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        # The probe's eligibility rule, carried across: a frame that does not
        # split confidently into the same sides cannot be a page source. Its
        # "left page" would be an unknown fraction of the spread.
        if cand.gutter_x is None:
            ineligible.append(f"{name}: no confident gutter (would emit single.png)")
            continue
        if cand.side_names != incumbent.side_names:
            ineligible.append(
                f"{name}: cuts into {sorted(cand.side_names)}, anchor cuts into "
                f"{sorted(incumbent.side_names)}")
            continue
        challengers.append(cand)
    if len(other_names) > limit:
        ineligible.append(
            f"{len(other_names) - limit} further frame(s) not scored "
            f"(per_page_source.max_candidates={limit})")

    for line in ineligible:
        warnings.append(f"per_page_source: candidate excluded — {line}")

    base_result = SelectionResult(
        mode=params["mode"], incumbent=incumbent.name, considered=other_names,
        ineligible=ineligible, min_word_gain=int(params["min_word_gain"]),
        require_conf_gain=bool(params["require_conf_gain"]),
    )

    def _stop_with_record(note: str) -> tuple[SelectionResult, dict]:
        warnings.append(f"per_page_source: {note}")
        base_result.note = note
        base_result.probe_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        return base_result, {}

    if not challengers:
        return _stop_with_record(
            "no eligible challenger for any side; using the anchor.")

    # Checked only now: complaining that Tesseract is missing when there was
    # nothing to choose between would be noise, and the eligibility record above
    # is worth keeping either way.
    binary = find_tesseract(cfg)
    if not binary:
        return _stop_with_record(
            "Tesseract not found, so the only supported criterion cannot run; "
            "using the anchor. Set tesseract.binary in config.yaml or run "
            "`python -m tools.setup_tessdata`.")

    lang = params["lang"] or (cfg.get("languages", {}) or {}).get("default", "eng")
    tessdata = resolve_tessdata_dir(cfg)
    tcfg = cfg.get("tesseract", {}) or {}
    oem, psm = int(tcfg.get("oem", 1)), int(tcfg.get("psm", 3))
    dmethod = str(params["dewarp_method"])
    dparams = S3.resolve_params(cfg)

    everyone = [incumbent] + challengers
    sides: list[SideChoice] = []
    dwarns: list[str] = []
    # UVDoc loaded ONCE for the whole probe and released in ``finally``, exactly
    # as the stage runner does — a mid-probe error must not leak the model.
    uv = S3.make_dewarper(dmethod, cfg, dwarns)
    try:
        for side in sorted(incumbent.side_names):
            scores: list[SideScore] = []
            for cand in everyone:
                img = cand.pieces[side][0]
                flat, pd, _ = S3.dewarp_page(img, dmethod, cfg, dparams, dwarns, uv)
                ge80, mean, n = score_tsv(
                    run_tesseract(binary, cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY),
                                  lang, tessdata, oem, psm))
                scores.append(SideScore(frame=cand.name, words_ge_80=ge80,
                                        mean_conf=mean, n_words=n,
                                        dewarp_method=pd.method))
            sides.append(decide_side(side, incumbent.name, scores, params))
    finally:
        if uv is not None:
            uv.close()

    chosen: dict[str, Candidate] = {}
    by_name = {c.name: c for c in everyone}
    for choice in sides:
        if choice.changed:
            chosen[choice.name] = by_name[choice.source]
            warnings.append(
                f"per_page_source: {choice.name} taken from {choice.source} "
                f"instead of the anchor {incumbent.name} — {choice.reason}")

    base_result.sides = sides
    base_result.changed_any = bool(chosen)
    base_result.probe_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    if not chosen:
        conf_clause = " AND higher mean confidence" if base_result.require_conf_gain else ""
        warnings.append(
            f"per_page_source: probed {len(everyone)} frame(s) on "
            f"{len(sides)} side(s); no challenger cleared the bar "
            f"(> {base_result.min_word_gain} words{conf_clause}), so every page "
            f"comes from the anchor.")
    return base_result, chosen


def decide_side(side: str, incumbent_name: str, scores: list[SideScore],
                params: dict) -> SideChoice:
    """Apply the bar to one side's race. The incumbent wins ties and near-ties.

    A challenger must lead on BOTH statistics — high-confidence words by more
    than the churn floor, and mean confidence — which is the census's rule
    applied per side, unrescaled. A side holds about half a spread's words, so
    the floor is deliberately STRICTER here; halving it would be inventing a
    number rather than measuring one.
    """
    floor = int(params["min_word_gain"])
    need_conf = bool(params["require_conf_gain"])
    base = next(s for s in scores if s.frame == incumbent_name)
    gains = [s for s in scores if s.frame != incumbent_name
             and (s.words_ge_80 - base.words_ge_80) > floor
             and (not need_conf or s.mean_conf > base.mean_conf)]
    if not gains:
        best = max((s for s in scores if s.frame != incumbent_name),
                   key=lambda s: s.words_ge_80, default=None)
        gap = "" if best is None else (
            f"; best challenger {best.frame} {best.words_ge_80 - base.words_ge_80:+d} "
            f"words / {best.mean_conf - base.mean_conf:+.1f} conf")
        return SideChoice(
            name=side, source=incumbent_name, changed=False, scores=scores,
            reason=f"no challenger clears the bar{gap}")
    win = max(gains, key=lambda s: s.words_ge_80)
    return SideChoice(
        name=side, source=win.frame, changed=True, scores=scores,
        reason=(f"{win.words_ge_80 - base.words_ge_80:+d} words at conf>=80 "
                f"(floor {floor}) and {win.mean_conf - base.mean_conf:+.1f} "
                f"mean conf over the anchor"))
