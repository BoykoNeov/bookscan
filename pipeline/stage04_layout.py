"""Stage 04 — layout + reading order.

Detects the layout BLOCKS of each dewarped half-page (title / paragraph /
figure / caption / table / footnote / header / page-number) and assigns each a
READING-ORDER rank, so the downstream stages get a correct block structure and
sequence. This is the first stage whose primary output is *reading order* — the
exact failure Gate 1 surfaced (Tesseract interleaves facing pages). Stage 02
(split) already fixed the cross-gutter half of that scramble; Stage 04 handles
the INTRA-page remainder: multi-column flow, figure/caption placement,
footnotes. See docs/GATE3_SPEC.md.

Reads ONLY ``03_dewarp/dewarp.json`` (the per-subpage manifest) + the images it
names (``left.png`` / ``right.png`` / ``single.png``); runs PER half-page.
Writes ``04_layout/layout.json`` (per subpage: width/height + a list of
``page_model.Block``), ``meta.json``, and ``debug/04_layout.png`` (blocks drawn,
numbered by reading order, colored by type). Never modifies earlier artifacts;
re-running overwrites only ``04_layout/`` (stage contract, CLAUDE.md).

Stage 04 is OCR-INDEPENDENT — layout is detected from pixels; words are attached
later at Stage 05. (The Gate 3 eval ``tools/layout_ab.py`` brings in Tesseract
only to MEASURE the resulting order; the stage itself does not depend on it.)

Two arms behind one loader seam (CLAUDE.md ``models.layout: doclayout-yolo``),
mirroring Stage 03:

  * **DocLayout-YOLO** (default) — a document layout detector giving typed block
    boxes, lazy-loaded ONCE per spread, VRAM released on CLI exit. Reading order
    is then computed over its boxes by recursive XY-Cut. ``--method auto`` uses
    it when torch + the checkpoint are present, else falls back to classical.
  * **Classical projection-profile fallback** (no torch / model absent) — column
    detection by vertical-projection valleys, block segmentation by
    horizontal-projection gaps, reading order by the same XY-Cut. It is a SAFETY
    NET, not a co-contender: projection profiles fail on exactly the complex
    pages the gate cares about. Honesty rule (as in Stage 03): if it can only
    produce a single page-covering block, that is FLAGGED in meta.warnings —
    never a silent passthrough dressed up as a real layout.

Usage:
    python -m pipeline.stage04_layout jobs/<job>/<page>/ [--method auto|doclayout|classical] [--debug]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np
import yaml
from pydantic import BaseModel, Field

from pipeline.page_model import BBox, Block, BlockType, StageMeta

STAGE = "stage04_layout"
VERSION = "0.1.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Detector + geometry knobs. These are LAYOUT-GEOMETRY heuristics (detector
# confidence floor, NMS overlap, XY-cut gap sizes) tuned to the handheld book
# photos — NOT the adaptive OCR-confidence thresholds CLAUDE.md forbids
# hard-coding (those live in Stage 06).
DEFAULTS = {
    "imgsz": 1024,               # DocLayout-YOLO inference size
    "conf_thresh": 0.25,         # drop detections below this confidence
    "nms_iou": 0.45,             # class-agnostic NMS: merge boxes overlapping >= this
    "contain_frac": 0.80,        # drop a box this-fraction-contained in a stronger one
    "xy_gap_frac": 0.012,        # min projection gap (frac of the cut dimension) = a separator
    # Classical fallback:
    "cls_col_gap_frac": 0.06,    # min vertical valley width (frac of W) to call a column boundary
    "cls_row_gap_frac": 0.012,   # min horizontal gap (frac of H) between blocks in a column
    "cls_ink_floor": 0.002,      # projection ink floor (frac) below which a row/col is "white"
    "cls_min_block_h_frac": 0.010,  # ignore blocks shorter than this (frac of H)
}

# DocLayout-YOLO (DocStructBench) class id -> our page_model BlockType. The model
# lumps running-header + page-number + margin junk into ONE class, "abandon"; we
# split it back by vertical position (top -> HEADER, bottom -> PAGE_NUMBER) so
# the Stage 07 "strip headers/page numbers" toggle has something to key on. That
# heuristic is applied in _map_abandon, not here.
YOLO_TYPE_MAP = {
    "title": BlockType.HEADING,
    "plain text": BlockType.PARAGRAPH,
    "figure": BlockType.FIGURE,
    "figure_caption": BlockType.CAPTION,
    "table": BlockType.TABLE,
    "table_caption": BlockType.CAPTION,
    "table_footnote": BlockType.FOOTNOTE,
    "isolate_formula": BlockType.OTHER,
    "formula_caption": BlockType.CAPTION,
    # "abandon" handled specially (position-dependent) — see _map_abandon.
}

# Overlay colors per block type (BGR).
TYPE_COLOR = {
    BlockType.TITLE: (0, 215, 255),
    BlockType.HEADING: (0, 215, 255),
    BlockType.PARAGRAPH: (0, 220, 0),
    BlockType.LIST: (0, 220, 120),
    BlockType.TABLE: (255, 160, 0),
    BlockType.FIGURE: (255, 80, 200),
    BlockType.CAPTION: (255, 220, 0),
    BlockType.FOOTNOTE: (120, 200, 255),
    BlockType.HEADER: (128, 128, 128),
    BlockType.PAGE_NUMBER: (128, 128, 128),
    BlockType.OTHER: (200, 200, 200),
}


# --------------------------------------------------------------------------
# Output schema (stage-local wrapper; the blocks themselves are page_model.Block)
# --------------------------------------------------------------------------


class RawDet(BaseModel):
    """One raw detection before typing/ordering (detector-agnostic)."""

    label: str
    bbox: BBox
    conf: float


class PageLayout(BaseModel):
    """Per-subpage layout: the image it came from + ordered blocks."""

    name: str                 # left.png | right.png | single.png
    width: int
    height: int
    arm: str                  # doclayout | classical
    blocks: list[Block] = Field(default_factory=list)
    note: str = ""


class LayoutResult(BaseModel):
    """Contents of ``04_layout/layout.json``."""

    source: str = "03_dewarp/dewarp.json"
    engine: str                       # requested method (auto|doclayout|classical)
    pages: list[PageLayout] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_params(cfg: dict) -> dict:
    params = dict(DEFAULTS)
    params.update(cfg.get("layout", {}) or {})
    return params


# --------------------------------------------------------------------------
# Geometry helpers (box math + NMS + reading order) — pure, detector-agnostic
# --------------------------------------------------------------------------


def _iou(a: BBox, b: BBox) -> float:
    ix1, iy1 = max(a.x, b.x), max(a.y, b.y)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


def _contain_frac(inner: BBox, outer: BBox) -> float:
    """Fraction of ``inner``'s area that lies inside ``outer``."""
    ix1, iy1 = max(inner.x, outer.x), max(inner.y, outer.y)
    ix2, iy2 = min(inner.x2, outer.x2), min(inner.y2, outer.y2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    area = inner.w * inner.h
    return (iw * ih) / area if area > 0 else 0.0


def nms_and_dedup(dets: list[RawDet], p: dict) -> list[RawDet]:
    """Class-agnostic NMS + containment prune, keeping the higher-confidence box.

    DocLayout-YOLO emits per-class NMS only, so the same region can surface under
    two labels (e.g. plain-text conf .61 AND figure_caption conf .33 on the same
    box — seen on en_coins_01). We sort by confidence and drop any later box that
    overlaps a kept one by >= nms_iou, OR is >= contain_frac swallowed by it.
    """
    kept: list[RawDet] = []
    for d in sorted(dets, key=lambda d: d.conf, reverse=True):
        if any(_iou(d.bbox, k.bbox) >= p["nms_iou"]
               or _contain_frac(d.bbox, k.bbox) >= p["contain_frac"]
               for k in kept):
            continue
        kept.append(d)
    return kept


def _separators(intervals: list[tuple[float, float]], min_gap: float
                ) -> list[list[int]]:
    """Group interval indices by gaps along one axis.

    ``intervals`` are (start, end) 1-D projections of the boxes onto the cut
    axis. Sweeping lo->hi with a running max end, a next-start minus running-end
    of at least ``min_gap`` is a separator (new group); anything closer joins the
    current group. Returns groups of the ORIGINAL indices, ordered lo->hi. One
    group == no clean cut on this axis.
    """
    idx = sorted(range(len(intervals)), key=lambda i: intervals[i][0])
    groups: list[list[int]] = []
    cur: list[int] = []
    cur_end: float | None = None
    for i in idx:
        s, e = intervals[i]
        if cur_end is None or s - cur_end >= min_gap:   # first box, or a real gap
            if cur:
                groups.append(cur)
            cur = [i]
            cur_end = e
        else:                                           # overlaps/touches -> same group
            cur.append(i)
            cur_end = max(cur_end, e)
    if cur:
        groups.append(cur)
    return groups


def _reading_rows(items: list[int], boxes: list[BBox]) -> list[int]:
    """Tie-break ordering when no clean projection cut exists: group boxes into
    reading ROWS by vertical overlap (a box joins a row if it overlaps the row's
    y-span by more than half its own height — SIZE-RELATIVE, so a line of jittery
    words groups but two tall stacked blocks do not), rows top->bottom, each row
    left->right."""
    rows: list[dict] = []
    for i in sorted(items, key=lambda i: boxes[i].y):
        b = boxes[i]
        placed = False
        for row in rows:
            ov = min(b.y2, row["ymax"]) - max(b.y, row["ymin"])
            if ov > 0.5 * min(b.h, row["ymax"] - row["ymin"]):
                row["members"].append(i)
                row["ymin"] = min(row["ymin"], b.y)
                row["ymax"] = max(row["ymax"], b.y2)
                placed = True
                break
        if not placed:
            rows.append({"ymin": b.y, "ymax": b.y2, "members": [i]})
    out: list[int] = []
    for row in sorted(rows, key=lambda r: r["ymin"]):
        out += sorted(row["members"], key=lambda i: boxes[i].x)
    return out


def xy_cut_order(boxes: list[BBox], p: dict, page_w: int, page_h: int
                 ) -> list[int]:
    """Recursive XY-Cut reading order over block boxes; returns box indices in
    reading order.

    At each node we try a HORIZONTAL cut first (peel full-width bands top->bottom:
    header, spanning figures, body paragraphs), then a VERTICAL cut (split a band
    into columns left->right, e.g. figure|caption). Because a horizontal band has
    no internal horizontal gap by construction, recursion self-alternates H/V.
    When neither axis has a clean separator (overlapping boxes) we sort the
    remainder by (top, left) — a stable, sensible fallback.
    """
    h_gap = p["xy_gap_frac"] * page_h
    v_gap = p["xy_gap_frac"] * page_w

    def rec(items: list[int]) -> list[int]:
        if len(items) <= 1:
            return list(items)
        # Horizontal cut: gaps in Y -> stacked bands.
        yiv = [(boxes[i].y, boxes[i].y2) for i in items]
        hgroups = _separators(yiv, h_gap)
        if len(hgroups) > 1:
            out: list[int] = []
            for g in hgroups:                       # already top->bottom
                out += rec([items[k] for k in g])
            return out
        # Vertical cut: gaps in X -> side-by-side columns.
        xiv = [(boxes[i].x, boxes[i].x2) for i in items]
        vgroups = _separators(xiv, v_gap)
        if len(vgroups) > 1:
            out = []
            for g in vgroups:                       # already left->right
                out += rec([items[k] for k in g])
            return out
        # No clean separator (overlapping/same-region boxes). A pure y-sort would
        # scramble same-line words left-to-right ("Eastern Exchange" -> "Exchange
        # Eastern") when OCR-box tops jitter; a fixed-tolerance row bucket would
        # instead collapse large stacked BLOCKS into one row. So group by VERTICAL
        # OVERLAP (size-relative: works for tiny words AND tall blocks) into
        # reading rows top->bottom, then order each row left->right.
        return _reading_rows(items, boxes)

    return rec(list(range(len(boxes))))


def _map_abandon(bbox: BBox, page_h: int) -> BlockType:
    """Split the model's catch-all 'abandon' class by vertical position: a box in
    the top fifth is a running HEADER, in the bottom fifth a PAGE_NUMBER, else
    OTHER (margin junk). Both header/page-number are the 'strip by default'
    categories (CLAUDE.md); the split just lets Stage 07 key on them."""
    cy = bbox.y + bbox.h / 2.0
    if cy < 0.20 * page_h:
        return BlockType.HEADER
    if cy > 0.80 * page_h:
        return BlockType.PAGE_NUMBER
    return BlockType.OTHER


def dets_to_blocks(dets: list[RawDet], page_w: int, page_h: int, p: dict
                   ) -> list[Block]:
    """NMS the raw detections, type them, order by XY-Cut, emit page_model.Block
    with reading_order set (0-based, reading sequence)."""
    dets = nms_and_dedup(dets, p)
    if not dets:
        return []
    boxes = [d.bbox for d in dets]
    order = xy_cut_order(boxes, p, page_w, page_h)
    blocks: list[Block] = []
    for rank, di in enumerate(order):
        d = dets[di]
        btype = (_map_abandon(d.bbox, page_h) if d.label == "abandon"
                 else YOLO_TYPE_MAP.get(d.label, BlockType.OTHER))
        blocks.append(Block(id=rank, type=btype, bbox=d.bbox, reading_order=rank))
    return blocks


# --------------------------------------------------------------------------
# DocLayout-YOLO arm (the config default)
# --------------------------------------------------------------------------

DEFAULT_YOLO_CKPT = "models/doclayout_yolo/doclayout_yolo_docstructbench_imgsz1024.pt"

# Errors from which the dispatcher falls back to classical rather than aborting.
YOLO_FALLBACK_ERRORS = (ImportError, FileNotFoundError, RuntimeError, KeyError)


class DocLayoutDetector:
    """DocLayout-YOLO detector — lazy-loaded, VRAM released on close (CLAUDE.md).

    ``load()`` imports doclayout_yolo, builds the model on CUDA (falls back to
    CPU). ``detect()`` runs one forward pass and returns raw detections in FULL
    image pixels. ``close()`` drops the model + empties the CUDA cache. Loaded
    ONCE per stage run and reused across a spread's half-pages.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.model = None
        self.device = None

    def _ckpt_path(self) -> Path:
        raw = (self.cfg.get("layout", {}) or {}).get("yolo_ckpt", DEFAULT_YOLO_CKPT)
        pth = Path(raw)
        return pth if pth.is_absolute() else REPO_ROOT / pth

    def load(self) -> None:
        import torch  # local import: the classical arm must not need torch

        from doclayout_yolo import YOLOv10

        ckpt = self._ckpt_path()
        if not ckpt.exists():
            raise FileNotFoundError(
                f"DocLayout-YOLO checkpoint missing: {ckpt}. Download "
                f"doclayout_yolo_docstructbench_imgsz1024.pt (~40 MB) from HF "
                f"'juliozhao/DocLayout-YOLO-DocStructBench' into "
                f"models/doclayout_yolo/."
            )
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = YOLOv10(str(ckpt))

    def detect(self, bgr: np.ndarray, p: dict) -> list[RawDet]:
        res = self.model.predict(
            bgr, imgsz=int(p["imgsz"]), conf=float(p["conf_thresh"]),
            device=self.device, verbose=False,
        )[0]
        names = self.model.names
        out: list[RawDet] = []
        b = res.boxes
        for i in range(len(b)):
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[i].tolist())
            out.append(RawDet(
                label=names[int(b.cls[i])],
                bbox=BBox(x=int(round(x1)), y=int(round(y1)),
                          w=int(round(x2 - x1)), h=int(round(y2 - y1))),
                conf=float(b.conf[i]),
            ))
        return out

    def close(self) -> None:
        if self.model is not None:
            self.model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass


def make_detector(method: str, cfg: dict, warnings: list[str]
                  ) -> DocLayoutDetector | None:
    """Load DocLayout-YOLO ONCE for the run if ``method`` wants it; return the
    loaded detector, or None to signal the classical arm (either
    method=='classical' or the model was unavailable and we fell back)."""
    if method == "classical":
        return None
    det = DocLayoutDetector(cfg)
    try:
        det.load()
        return det
    except YOLO_FALLBACK_ERRORS as e:
        msg = f"DocLayout-YOLO unavailable ({type(e).__name__}: {e}); using classical."
        warnings.append(msg if method == "doclayout"
                        else "DocLayout-YOLO unavailable; used classical (auto).")
        return None


# --------------------------------------------------------------------------
# Classical projection-profile fallback (SAFETY NET, not a co-contender)
# --------------------------------------------------------------------------


def _ink_projection(gray: np.ndarray) -> np.ndarray:
    """Binary ink mask (text=1) via Otsu, for projection profiles."""
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return (th > 0).astype(np.float32)


def _split_by_gaps(profile: np.ndarray, floor: float, min_gap: int
                   ) -> list[tuple[int, int]]:
    """Segments (start,end) of above-floor runs in a 1-D profile, merging runs
    separated by a gap shorter than ``min_gap``."""
    on = profile > floor
    segs: list[tuple[int, int]] = []
    i, n = 0, len(on)
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < n and on[j]:
            j += 1
        if segs and i - segs[-1][1] < min_gap:
            segs[-1] = (segs[-1][0], j)          # merge across a small gap
        else:
            segs.append((i, j))
        i = j
    return segs


def detect_classical(bgr: np.ndarray, p: dict) -> tuple[list[RawDet], str]:
    """Column + block segmentation by projection profiles. Returns
    (raw dets, note). All blocks are typed PARAGRAPH (this arm can't tell type);
    the caller flags a degenerate single-page-covering result."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    h, w = gray.shape
    ink = _ink_projection(gray)

    col_prof = ink.mean(axis=0)                  # vertical projection -> columns
    col_floor = float(p["cls_ink_floor"])
    col_gap = max(1, int(p["cls_col_gap_frac"] * w))
    cols = _split_by_gaps(col_prof, col_floor, col_gap)
    if not cols:
        cols = [(0, w)]

    row_gap = max(1, int(p["cls_row_gap_frac"] * h))
    min_bh = int(p["cls_min_block_h_frac"] * h)
    dets: list[RawDet] = []
    for (cx0, cx1) in cols:
        row_prof = ink[:, cx0:cx1].mean(axis=1)  # horizontal proj within column
        for (ry0, ry1) in _split_by_gaps(row_prof, col_floor, row_gap):
            if ry1 - ry0 < min_bh:
                continue
            dets.append(RawDet(
                label="plain text",
                bbox=BBox(x=cx0, y=ry0, w=cx1 - cx0, h=ry1 - ry0),
                conf=1.0,
            ))
    note = f"classical: {len(cols)} column(s), {len(dets)} block(s)"
    return dets, note


# --------------------------------------------------------------------------
# Per-page dispatch (arm selection + fallback)
# --------------------------------------------------------------------------


def layout_page(bgr: np.ndarray, cfg: dict, p: dict, warnings: list[str],
                det: DocLayoutDetector | None) -> PageLayout:
    """Lay out one half-page. If a loaded ``det`` is passed use it (per-page
    detector errors still fall back to classical for that page); else classical.
    The honesty rule (Stage 03): a classical result that is a single
    page-covering block is FLAGGED, never passed off as a real layout."""
    h, w = bgr.shape[:2]
    arm = "doclayout"
    note = ""
    if det is not None:
        try:
            raw = det.detect(bgr, p)
        except YOLO_FALLBACK_ERRORS as e:
            warnings.append(f"DocLayout-YOLO failed on a page "
                            f"({type(e).__name__}: {e}); classical for this page.")
            raw, note = detect_classical(bgr, p)
            arm = "classical"
    else:
        raw, note = detect_classical(bgr, p)
        arm = "classical"

    blocks = dets_to_blocks(raw, w, h, p)

    if not blocks:
        note = (note + "; " if note else "") + "no blocks detected — emitting a " \
               "single page-covering block (FLAGGED: layout unusable on this page)"
        blocks = [Block(id=0, type=BlockType.PARAGRAPH,
                        bbox=BBox(x=0, y=0, w=w, h=h), reading_order=0)]
        warnings.append(f"{arm}: {note}")
    elif arm == "classical" and len(blocks) == 1 and \
            blocks[0].bbox.w >= 0.95 * w and blocks[0].bbox.h >= 0.95 * h:
        note = (note + "; " if note else "") + "single page-covering block " \
               "(FLAGGED: classical could not segment this page)"
        warnings.append(f"classical: {note}")

    return PageLayout(name="", width=w, height=h, arm=arm, blocks=blocks, note=note)


# --------------------------------------------------------------------------
# Debug overlay
# --------------------------------------------------------------------------


def _page_panel(bgr: np.ndarray, pl: PageLayout, panel_w: int = 1100) -> np.ndarray:
    """One page's blocks drawn + numbered by reading order, colored by type,
    with connecting arrows tracing the sequence."""
    vis = bgr.copy()
    if vis.ndim == 2:
        vis = cv2.cvtColor(vis, cv2.COLOR_GRAY2BGR)
    centers: list[tuple[int, int]] = []
    for blk in sorted(pl.blocks, key=lambda b: b.reading_order):
        c = TYPE_COLOR.get(blk.type, (200, 200, 200))
        x, y, x2, y2 = blk.bbox.x, blk.bbox.y, blk.bbox.x2, blk.bbox.y2
        cv2.rectangle(vis, (x, y), (x2, y2), c, 4)
        cx, cy = (x + x2) // 2, (y + y2) // 2
        centers.append((cx, cy))
        tag = f"{blk.reading_order}:{blk.type.value[:4]}"
        cv2.putText(vis, tag, (x + 6, y + 46), cv2.FONT_HERSHEY_SIMPLEX, 1.4, c, 4)
    for a, b in zip(centers, centers[1:]):
        cv2.arrowedLine(vis, a, b, (0, 0, 255), 3, tipLength=0.02)

    hh, ww = vis.shape[:2]
    s = panel_w / ww
    vis = cv2.resize(vis, (panel_w, max(1, int(hh * s))))
    banner = np.full((54, panel_w, 3), 30, np.uint8)
    cv2.putText(banner, f"{pl.name}: arm={pl.arm} blocks={len(pl.blocks)}",
                (14, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 220, 0), 2)
    return np.vstack([banner, vis])


def build_debug(panels: list[np.ndarray]) -> np.ndarray:
    if not panels:
        return np.zeros((100, 100, 3), np.uint8)
    w = max(pn.shape[1] for pn in panels)
    padded = [cv2.copyMakeBorder(pn, 0, 10, 0, w - pn.shape[1],
                                 cv2.BORDER_CONSTANT, value=(30, 30, 30))
              for pn in panels]
    return np.vstack(padded)


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(page_dir: Path, cfg: dict, method: str = "auto", debug: bool = False
        ) -> LayoutResult:
    t0 = time.perf_counter()
    p = resolve_params(cfg)
    warnings: list[str] = []

    dewarp_json = page_dir / "03_dewarp" / "dewarp.json"
    if not dewarp_json.exists():
        raise FileNotFoundError(
            f"missing {dewarp_json} — Stage 04 reads Stage 03's manifest. Run "
            f"stage03_dewarp on this page first."
        )
    manifest = json.loads(dewarp_json.read_text(encoding="utf-8"))
    pages = manifest.get("pages", [])
    if not pages:
        raise RuntimeError(f"no pages in {dewarp_json}; nothing to lay out.")

    dewarp_dir = page_dir / "03_dewarp"
    out_dir = page_dir / "04_layout"
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[PageLayout] = []
    panels: list[np.ndarray] = []
    # Load DocLayout-YOLO ONCE for the whole spread; release in finally so VRAM
    # is freed even if a page errors (CLAUDE.md release-on-exit).
    det = make_detector(method, cfg, warnings)
    t_lay = time.perf_counter()
    try:
        for page in pages:
            name = page["name"]
            src = dewarp_dir / name
            img = cv2.imread(str(src), cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError(f"unreadable subpage image: {src}")
            pl = layout_page(img, cfg, p, warnings, det)
            pl.name = name
            results.append(pl)
            panels.append(_page_panel(img, pl))
    finally:
        if det is not None:
            det.close()
    lay_ms = (time.perf_counter() - t_lay) * 1000.0

    result = LayoutResult(engine=method, pages=results)
    (out_dir / "layout.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")

    debug_dir = page_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(debug_dir / "04_layout.png"), build_debug(panels))

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={k: p[k] for k in DEFAULTS},
        timings_ms={"layout": round(lay_ms, 1), "total": round(total_ms, 1)},
        warnings=warnings + [
            "v0.1: DocLayout-YOLO (default) + classical projection-profile "
            "fallback. Reading order by recursive XY-Cut (H-cut peels full-width "
            "bands top->bottom, V-cut splits columns left->right). Block TYPES "
            "come from the neural arm only; the classical arm types every block "
            "PARAGRAPH and is a flagged safety net, not a co-contender.",
            "Stage 04 is OCR-independent; words attach at Stage 05. Reading order "
            "is MEASURED by tools/layout_ab.py (block-ordered vs whole-page OCR "
            "WER). See docs/GATE3_SPEC.md — multi-column order is UNPROVEN until "
            "multi-column GT is added.",
        ],
    )
    (out_dir / "meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8")
    return result


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 04 — layout + reading order")
    ap.add_argument("page_dir", type=Path,
                    help="page folder, e.g. jobs/<job>/<page_NNN>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--method", choices=("auto", "doclayout", "classical"),
                    default="auto", help="layout arm (auto tries doclayout, "
                    "falls back to classical)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    result = run(args.page_dir, cfg, method=args.method, debug=args.debug)
    print(f"{args.page_dir}: layout engine={result.engine}")
    for pl in result.pages:
        types = ", ".join(f"{b.reading_order}:{b.type.value}" for b in pl.blocks)
        print(f"  {pl.name}: arm={pl.arm} blocks={len(pl.blocks)} [{types}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
