"""Stage 01 — fuse.

Turns the ingested frames for one spread into a single best ``anchor.png`` that
Stage 02 (split) consumes. Two jobs, per CLAUDE.md:

  1. **Pick the sharpest** full-spread frame (handheld bursts give several near
     duplicates; the sharpest wins — sharpness comes from Stage 00's manifest,
     no re-measure).
  2. **Stitch multi-zoom close-ups** onto that anchor: a close-up is a higher
     resolution photo of part of the spread; we locate it on the anchor by
     feature matching (ORB + RANSAC homography) and blend it in so that region
     gets its detail back.

Three-artifact contract (CLAUDE.md): ``01_fuse/anchor.png`` + ``fuse.json``
(which frame became the anchor, each close-up's match result) + ``meta.json`` +
``debug/01_fuse.png`` (anchor with the stitched regions outlined).

Input: reads ONLY ``00_ingest/ingest.json`` + ``00_ingest/frame_NN.png``.

**v0.2 (2026-08-19) — the gate was the bug, not the feature budget.**

v0.1 stitched 0 of the 11 real close-ups in ``testset/zoomset_*``. The recorded
diagnosis was that ORB was starved (4000 features over a 12 Mpx frame) and that
raising the budget to 20000 took it to 4 of 11. Re-measuring with a correctness
check that does not come from the matcher overturned both halves of that:

  * **5 of the 11 were located CORRECTLY by v0.1's own settings** — 9 to 21
    RANSAC inliers, confirmed by eye on full-resolution checkerboard overlays —
    and then thrown away, because ``min_inliers`` was 25. Every correct
    registration in the corpus scores below the gate that was supposed to admit
    it. Lowering the gate to 8 recovers all five at v0.1's cost.
  * **The 20000-feature variant registers the same five and adds a false
    positive.** ``zoomset_en_01_f03`` reaches 27 inliers with the bigger budget —
    over the old gate — on a warp that puts grass and sky where the anchor has
    text. Shipping the budget change alone would have started blending wrong
    pixels into pages. It is NOT shipped; ``orb_features`` stays at 4000.

The lesson is in ``registration_ncc``: inlier count is produced by the matcher,
so it cannot referee a change to the matcher. Acceptance is now photometric —
warp the close-up and ask whether its ink agrees with the anchor's (correct
0.495-0.765, wrong -0.228 to 0.280 on this corpus, no overlap). The old single
``min_inliers`` constant, which gated two different quantities at once, is split
into a precondition, a consensus gate, a ratio floor and that photometric test.

**And then the registrations turned out not to be worth having.** Blending those
five correctly-located close-ups in made OCR WORSE on all three spreads that had
any: de_01 lost 178 high-confidence words (435 -> 257), de_02 lost 63, en_02 lost
58. The cause is not the matcher. A close-up is closer to the page but shot
handheld at longer focal length, and it must be warped DOWN into the anchor's
coordinate frame to be blended; the measured linear scale is 0.71-0.94, so there
was almost no extra resolution to bank, and resampling spends more than that. Over
the identical footprint pixels all five are softer than what they replace
(sharpness ratio 0.49-0.83). Hence ``min_sharpness_ratio``: a close-up now has to
prove it IMPROVES the region, not merely that it belongs there. On this corpus
that leaves 0 of 11 blended — but by a stated measurement rather than by accident,
and Stage 01's output is now byte-identical to the anchor instead of worse than it.

**Where the close-ups' value actually is, measured.** OCR each frame on its own
and the anchor wins 3 of 4 sets — but on ``zoomset_de_02`` the close-ups read 270
and 249 high-confidence words against the anchor's 183.

  *CORRECTION 2026-08-19 (later).* This paragraph used to say those close-ups are
  "whole-spread re-zooms, so it is a fair comparison", and concluded that a
  close-up is sometimes "a better photograph of the whole page" which
  ``partition_frames`` cannot elect. **The premise is false**, which was found by
  the elementary step of looking at the images: ``zoomset_de_02_f01`` frames the
  right page plus a clipped strip of the left, and ``f02`` is essentially the
  right page alone (0.337 of the anchor's footprint, on its own correct
  registration). They are PER-PAGE zooms. So 270/249-vs-183 is not like-for-like,
  and no anchor rule may elect either — making ``f02`` the anchor would delete the
  left page from the job.

  The honest reading is stronger than the wrong one. A frame covering a third of
  the spread out-reads the anchor covering all of it, because the anchor is a
  distant obliquely-shot photograph and the close-up has roughly double the pixels
  per text line. **The anchor is bad; the close-up is not eligible to replace it.**
  What that argues for is per-page frame selection, which needs to know where the
  gutter is and therefore cannot live in Stage 01 at all. See ``docs/RESULTS.md``
  2026-08-19 "Anchor choice: the window was not the problem".

``fullspread_area_frac`` is the guard that makes this safe, and it is load-bearing:
``zoomset_de_01_f01`` scores 1329 against its anchor's 564 (2.4x sharper by the
selector's own metric) while covering 0.39 of the spread and reading 221 words
against the anchor's 435. **Any future relaxation of that gate needs a COVERAGE
test, not a sharpness test.** Related: ``partition_frames`` still discards extra
full-spread frames outright (``zoomset_en_02_f00``), so they cannot compete either.

**And the anchor RANKING was re-measured 2026-08-19; the obvious fix is refuted.**
The open item here and in ``book_boundary``'s docstring was that sharpness is
variance-of-Laplacian over the WHOLE frame, which on a lap capture that is 40-55 %
room rewards cluttered backgrounds over legible text — so rank inside the book box
once the crop exists. ``tools/anchor_choice_census.py`` asks that of all 13
committed multi-frame fixtures (10 have more than one anchor candidate) and the
answer is no:

  * On **6 of the 10** the crop abstains on *every* candidate, so the book box IS
    the frame and any windowing variant is a no-op **by construction** — including
    on two of the three sets where the selector picks the worse photograph. On a
    seventh both candidates crop, the comparison is fair, and the pick does not
    move. Only the three sets that MIX a cropped candidate with an abstaining one
    are left, and those are the sets where the score is not comparable.
  * Scoring inside ``find_book``'s emit box flips exactly one set (``de_02``) and
    flips it the right way, but only through an artefact: variance of Laplacian
    rises when smooth pixels are removed, so a candidate whose crop applied is
    scored on page-only pixels while one that abstained still carries its room.
    Score every candidate on its own box regardless of the abstain gate — the fair
    comparison — and ``de_02`` reverts, while ``bg_taleb_01`` breaks.

So the window is not where the problem is; the criterion is. ``partition_frames``
is unchanged, deliberately.

**And the criterion is not the problem either — measured 2026-08-26.** The
sentence above stood on Tesseract run on the RAW FRAME, flat, before the book
crop and before Stage 03 flattens the page, and two of the three sets it
complained about are the multi-VIEW fixture, i.e. deliberately oblique shots
whose confidence Stage 03 exists to restore (the third, ``de_02``, is a 1.7 %
sharpness margin — a tie, not an error). ``tools/anchor_downstream_census.py``
re-asks it through this pipeline's own geometry, same Tesseract settings, three
arms (flat / crop+split / +dewarp), with the bar written down before the run: a
loser must lead on BOTH statistics, by more than the 60-word reframing churn
floor. Errors by arm over the 9 non-degenerate sets: flat 1, crop+split 2,
**+dewarp 0**. ``skewset_it_01`` reverses outright (challenger +59 words flat ->
-55 after dewarp). Splitting alone makes it WORSE; the flattening is what does
the work. Read the SIGN REVERSALS, not the counts: ``skewset_it_01`` and
``de_02`` are the two the previous row called solid and both change direction
once flat, which no choice of floor can undo. Reported against the incumbent too:
on 2 of the 9 a loser still leads on both statistics below the floor, largest
``de_01`` +43 / +8.4 — and that one is a STAGE 03 defect, not a Stage 01 one: the
dewarper gains +58 and +104 words on that set's two losers and loses 18 words /
12.7 conf on the winner, the only frame in the corpus dewarp makes worse. The
honest claim is *no error survives at the stated bar*, not *the selector is
perfect*. See
``docs/RESULTS.md`` 2026-08-26. Do not re-open this by re-measuring flat frames.

**Left unsolved, with the mechanism now identified.** The 6 close-ups that no
setting registers (``en_01`` f01-f03, ``en_02`` f02-f04) are all oblique views of
a strongly curved page — a cylinder seen near edge-on. A homography assumes a
plane, and Stage 01 runs BEFORE Stage 03 flattens, so those frames are outside
the model rather than badly matched. Fixing that means capture guidance (shoot
close-ups square-on) or registering after dewarp, not matcher tuning. SIFT is
wired behind ``feature_engine`` because it registers one of the six (6/11 vs
5/11) at ~1.6x the time; ORB stays the default because CLAUDE.md documents it as
this stage's tool and swapping it is the owner's call, not a silent change.

Usage:
    python -m pipeline.stage01_fuse jobs/<job>/<page>/ [--debug]
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

from pipeline.page_model import StageMeta

STAGE = "stage01_fuse"
VERSION = "0.2.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    # A frame counts as a full-spread candidate (eligible to be the sharpest
    # anchor) if its area >= this fraction of the largest frame's area. Smaller
    # frames are treated as close-ups to stitch.
    "fullspread_area_frac": 0.70,

    # --- feature matching ---
    # Engine. ORB is the documented tool for this stage (CLAUDE.md) and the
    # default. SIFT is wired as a swap because it measurably registers one more
    # close-up (6/11 vs 5/11 on the zoomset spreads) — that is an owner call, not
    # a silent change, so it stays behind this knob. See the module docstring.
    "feature_engine": "orb",        # orb | sift
    "orb_features": 4000,
    # Detect on a downscaled copy and rescale the homography back. 1.0 = the
    # shipped behaviour and what ORB wants. SIFT wants 0.5: same registrations,
    # 3261 ms -> 433 ms per close-up, because SIFT's keypoint count is not capped.
    "detect_scale": 1.0,
    "ratio_test": 0.75,
    "ransac_reproj_px": 5.0,

    # --- acceptance gates (three different questions, three different knobs) ---
    # 1. Is there enough to fit at all? A PRECONDITION, not a quality judgement:
    #    findHomography needs 4 points mathematically. Measured on the zoomset,
    #    the good-match count does NOT separate right from wrong registrations
    #    (correct pairs ran 21-58 good matches, wrong ones 16-36 — fully
    #    overlapping), which is exactly why it must not be used as a quality gate.
    "min_good_matches": 10,
    # 2. Did RANSAC find a consensus? At the shipped ORB settings this DOES
    #    separate: correct registrations scored 9, 12, 13, 21, 21 inliers and
    #    wrong ones 3, 4, 4, 5, 5, 7. The gate sits in that gap. It used to be 25
    #    — above every correct value — which is why Stage 01 stitched 0 of 11.
    "min_inliers": 8,
    # 3. Is that consensus a real fraction of the evidence? Scale-free guard
    #    against "40 inliers out of 4000 good matches". Honest note: this floor
    #    discriminates NOTHING on the zoomset corpus (correct 0.196-0.571 vs wrong
    #    0.083-0.368 overlap) — it is insurance against a failure mode these 11
    #    pairs do not contain, set low enough to reject no measured true positive.
    "min_inlier_ratio": 0.10,
    # 4. THE acceptance gate, and the only one that asks the actual question:
    #    once warped, does the close-up's ink AGREE with the anchor's? Normalized
    #    cross-correlation over the warped footprint. This is independent of the
    #    matcher, so it cannot be fooled by a feature budget that manufactures
    #    inliers. Measured separation is wide: correct 0.495-0.765, wrong -0.228
    #    to 0.280, and it was confirmed by eye on full-resolution checkerboard
    #    overlays. 0.35 sits in the middle of that gap.
    "min_ncc": 0.35,
    # 5. DO NO HARM. A close-up is only worth blending if it is SHARPER than what
    #    it would replace, measured over the identical footprint pixels
    #    (variance of Laplacian, mask eroded so the warp's hard border does not
    #    count as detail). This is the gate the zoomset actually needed: all five
    #    correctly-registered close-ups there are BLURRIER than the anchor
    #    (ratios 0.49-0.83), and blending them in cost de_01 178 high-confidence
    #    OCR words. A close-up is closer but handheld-longer-lens, and warping it
    #    down into the anchor's coordinate frame resamples away what little extra
    #    resolution it had (measured linear scale 0.71-0.94 — almost none).
    #    Set below 1.0 to allow a marginally softer patch; 1.0 means "must not
    #    make the page worse", which is the only defensible default.
    "min_sharpness_ratio": 1.0,

    "feather_px": 40.0,     # blend feather width at the warped close-up border
}


class StitchResult(BaseModel):
    """One close-up's stitch attempt. Every gate's input is recorded, not just
    the verdict, so a rejection can be diagnosed from the artifact alone."""

    name: str
    matched: bool
    inliers: int = 0
    note: str = ""
    kp_base: int = 0
    kp_closeup: int = 0
    good_matches: int = 0
    inlier_ratio: float = 0.0
    ncc: float = 0.0            # photometric agreement after warping; proves it is in the RIGHT PLACE
    sharpness_ratio: float = 0.0  # warped close-up vs anchor over the same pixels; proves it HELPS
    corners: list[list[float]] | None = None   # warped footprint on the anchor


class FuseResult(BaseModel):
    """Contents of ``01_fuse/fuse.json``."""

    n_frames: int
    anchor_source: str          # frame_NN.png chosen as the base
    method: str                 # single | sharpest | sharpest+stitch
    fullspread_frames: list[str] = Field(default_factory=list)
    closeups: list[StitchResult] = Field(default_factory=list)


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
    params.update(cfg.get("fuse", {}) or {})
    return params


# --------------------------------------------------------------------------
# Frame roles
# --------------------------------------------------------------------------


def partition_frames(frames: list[dict], area_frac: float
                     ) -> tuple[int, list[int], list[int]]:
    """Split frames into (base_idx, fullspread_idxs, closeup_idxs).

    Base = the SHARPEST among the full-spread-sized frames (area >= area_frac of
    the max). Everything smaller is a close-up to stitch. With one frame this
    trivially returns (0, [0], []).
    """
    areas = [f["width"] * f["height"] for f in frames]
    max_area = max(areas)
    fullspread = [i for i, a in enumerate(areas) if a >= area_frac * max_area]
    closeups = [i for i in range(len(frames)) if i not in fullspread]
    # sharpest full-spread frame is the base
    base_idx = max(fullspread, key=lambda i: frames[i].get("sharpness", 0.0))
    return base_idx, fullspread, closeups


# --------------------------------------------------------------------------
# Stitch (features + RANSAC homography + photometric check + feathered blend)
# --------------------------------------------------------------------------


# Below this many footprint pixels neither the photometric check nor the
# sharpness comparison means anything, so both decline to answer rather than
# return a number that looks like a verdict. ~0.04% of a 12 Mpx frame.
_MIN_JUDGEABLE_PX = 5000


def _detector(p: dict):
    """(detector, BFMatcher norm) for the configured engine."""
    kind = str(p.get("feature_engine", "orb")).lower()
    if kind == "orb":
        return cv2.ORB_create(nfeatures=int(p["orb_features"])), cv2.NORM_HAMMING
    if kind == "sift":
        if not hasattr(cv2, "SIFT_create"):
            raise RuntimeError(
                "feature_engine: sift, but this OpenCV build has no SIFT_create. "
                "Install opencv-contrib-python (or opencv-python >= 4.4)."
            )
        return cv2.SIFT_create(), cv2.NORM_L2
    raise ValueError(f"unknown feature_engine: {kind!r} (expected orb | sift)")


def registration_ncc(base: np.ndarray, warped: np.ndarray,
                     mask: np.ndarray) -> float:
    """Normalized cross-correlation of ``base`` and ``warped`` over ``mask``.

    THE acceptance test, and the reason it exists: every other statistic Stage 01
    can compute (good matches, inliers, inlier ratio) is produced BY the matcher,
    so using one to judge a change to the matcher is circular — raising the
    feature budget inflates the inlier count whether or not the fit got better.
    This asks the independent question instead: after warping, does the
    close-up's ink actually sit on top of the anchor's?

    Grayscale, mean-subtracted, so exposure and white-balance differences between
    a zoomed frame and the anchor do not count against a correct registration
    (they differ by a lot in practice — the close-ups are visibly warmer).
    Returns 0.0 when the footprint is too small to mean anything.
    """
    m = mask > 0
    if int(m.sum()) < _MIN_JUDGEABLE_PX:
        return 0.0
    a = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32)[m]
    b = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype(np.float32)[m]
    a -= a.mean()
    b -= b.mean()
    denom = float(np.sqrt(float((a * a).sum()) * float((b * b).sum())))
    return float((a * b).sum() / denom) if denom > 0 else 0.0


def footprint_sharpness_ratio(base: np.ndarray, warped: np.ndarray,
                              mask: np.ndarray) -> float | None:
    """How much sharper the warped close-up is than the anchor, same pixels.

    Variance of the Laplacian on each, over an eroded footprint mask — eroded
    because the warp's border is a hard black edge that reads as enormous detail,
    and it is in the WARPED image only, so leaving it in would flatter every
    candidate. >1 means blending improves the region; <1 means it degrades it.

    Returns ``None`` for "cannot judge" — a distinct answer from a low ratio, and
    the caller must not report it as one. The erosion is sized to the footprint
    rather than fixed, because a fixed 25x25 kernel eats a small patch entirely:
    an 80x80 footprint dropped from 6400 to 3136 px and the function used to
    return 0.0, which the gate then read as "softer than the anchor" and refused
    for a reason that was not sharpness. The zoomset cannot reach that case (every
    frame there is a whole-spread re-zoom), but a close-up of PART of a page is
    what this stage is for, so it is handled rather than assumed away.

    Separate from ``registration_ncc`` on purpose: NCC asks whether the close-up
    is in the RIGHT PLACE, this asks whether putting it there HELPS. On the
    zoomset spreads every close-up passes the first and fails the second.
    """
    raw = (mask > 0).astype(np.uint8)
    area = int(raw.sum())
    if area < _MIN_JUDGEABLE_PX:
        return None
    k = int(np.clip((area ** 0.5) // 8, 3, 25)) | 1      # odd, scaled, capped
    m = cv2.erode(raw, np.ones((k, k), np.uint8)) > 0
    if int(m.sum()) < _MIN_JUDGEABLE_PX // 2:
        return None
    def sharp(img: np.ndarray) -> float:
        lap = cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_64F)
        return float(lap[m].var())
    a = sharp(base)
    return (sharp(warped) / a) if a > 0 else None


def blend(base: np.ndarray, warped: np.ndarray, wmask: np.ndarray, p: dict,
          dest: np.ndarray | None) -> np.ndarray:
    """Feather the warped close-up into ``dest`` so it has no hard seam."""
    dist = cv2.distanceTransform((wmask > 0).astype(np.uint8), cv2.DIST_L2, 5)
    alpha = np.clip(dist / max(1.0, p["feather_px"]), 0.0, 1.0)[..., None]
    into = base if dest is None else dest
    return (into * (1.0 - alpha) + warped * alpha).astype(np.uint8)


def _accept(r: StitchResult) -> StitchResult:
    r.matched = True
    return r


def stitch_closeup(base: np.ndarray, closeup: np.ndarray, p: dict,
                   dest: np.ndarray | None = None
                   ) -> tuple[np.ndarray | None, StitchResult, str]:
    """Locate ``closeup`` on ``base`` and blend it in at full base resolution.

    Returns (blended_or_None, partial StitchResult, note). None means the
    close-up was not confidently located and nothing is modified; the
    StitchResult still carries every gate's input so the rejection is diagnosable
    from ``fuse.json`` without re-running anything.

    ``base`` is what the close-up is matched and photometrically compared
    AGAINST; ``dest`` is what it is blended INTO, defaulting to ``base``. The
    runner passes the pristine anchor as ``base`` and the accumulating image as
    ``dest`` so several close-ups compose without each one changing the reference
    the next one is matched to.

    The gates run cheapest-first — match count, then RANSAC consensus, then the
    photometric check, which needs a full-resolution warp (the same warp the
    blend needs, so an ACCEPTED close-up pays for it only once).
    """
    r = StitchResult(name="", matched=False)
    scale = float(p.get("detect_scale", 1.0))
    if scale != 1.0:
        gb = cv2.cvtColor(cv2.resize(base, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
        gc = cv2.cvtColor(cv2.resize(closeup, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
    else:
        gb = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY)
        gc = cv2.cvtColor(closeup, cv2.COLOR_BGR2GRAY)

    det, norm = _detector(p)
    kb, db = det.detectAndCompute(gb, None)
    kc, dc = det.detectAndCompute(gc, None)
    r.kp_base, r.kp_closeup = len(kb or []), len(kc or [])
    if db is None or dc is None or len(kc) < 4 or len(kb) < 4:
        return None, r, "too few features"

    knn = cv2.BFMatcher(norm).knnMatch(dc, db, k=2)  # query = close-up, train = base
    good = [m for m, n in (pair for pair in knn if len(pair) == 2)
            if m.distance < p["ratio_test"] * n.distance]
    r.good_matches = len(good)
    # Gate 1 — precondition only. The good-match count does not tell right from
    # wrong (measured: it overlaps completely), so it must not be a quality gate.
    if len(good) < int(p["min_good_matches"]):
        return None, r, f"only {len(good)} good matches (need {p['min_good_matches']} to fit)"

    src = np.float32([kc[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, float(p["ransac_reproj_px"]))
    if H is None:
        return None, r, "no homography"
    if scale != 1.0:                      # rescale the fit back to full resolution
        S = np.diag([scale, scale, 1.0])
        H = np.linalg.inv(S) @ H @ S
    r.inliers = int(mask.sum()) if mask is not None else 0
    r.inlier_ratio = round(r.inliers / len(good), 3)
    # Gate 2 — RANSAC consensus.
    if r.inliers < int(p["min_inliers"]):
        return None, r, f"only {r.inliers} inliers (need {p['min_inliers']})"
    # Gate 3 — that consensus as a fraction of the evidence.
    if r.inlier_ratio < float(p["min_inlier_ratio"]):
        return None, r, (f"inlier ratio {r.inlier_ratio} below "
                         f"{p['min_inlier_ratio']} ({r.inliers}/{len(good)})")
    # Sanity: reject degenerate/flipped warps (non-positive or extreme scale).
    det_h = float(np.linalg.det(H[:2, :2]))
    if not (0.05 < abs(det_h) < 20.0) or det_h <= 0:
        return None, r, f"degenerate homography (det={det_h:.3f})"

    bh, bw = base.shape[:2]
    warped = cv2.warpPerspective(closeup, H, (bw, bh))
    wmask = cv2.warpPerspective(
        np.full(closeup.shape[:2], 255, np.uint8), H, (bw, bh))
    ch, cw = closeup.shape[:2]
    corners = cv2.perspectiveTransform(
        np.float32([[0, 0], [cw, 0], [cw, ch], [0, ch]]).reshape(-1, 1, 2), H)
    r.corners = [[round(float(x), 1), round(float(y), 1)]
                 for x, y in corners.reshape(-1, 2)]
    # Gate 4 — the one that actually asks whether the registration is RIGHT.
    r.ncc = round(registration_ncc(base, warped, wmask), 3)
    if r.ncc < float(p["min_ncc"]):
        return None, r, (f"warped close-up does not agree with the anchor "
                         f"(ncc {r.ncc} < {p['min_ncc']}) despite {r.inliers} inliers")
    # Gate 5 — correctly placed, but does it help? Last because it is the only
    # gate a correctly-registered close-up can still fail, and on real data it is
    # the one that fires.
    ratio = footprint_sharpness_ratio(base, warped, wmask)
    if ratio is None:
        # Cannot judge, and saying "softer" would be a lie. Too small to judge is
        # also too small to do damage, so it goes in — visibly, not silently.
        return blend(base, warped, wmask, p, dest), _accept(r), (
            "ok (footprint too small to judge sharpness; blended anyway)")
    r.sharpness_ratio = round(ratio, 3)
    if r.sharpness_ratio < float(p["min_sharpness_ratio"]):
        return None, r, (f"correctly located (ncc {r.ncc}) but SOFTER than the "
                         f"anchor there (sharpness ratio {r.sharpness_ratio} < "
                         f"{p['min_sharpness_ratio']}) - blending it would make "
                         f"the page worse, so it is left out")

    return blend(base, warped, wmask, p, dest), _accept(r), "ok"


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(page_dir: Path, cfg: dict, debug: bool = False) -> FuseResult:
    t0 = time.perf_counter()
    params = resolve_params(cfg)
    warnings: list[str] = []

    ingest_json = page_dir / "00_ingest" / "ingest.json"
    if not ingest_json.exists():
        raise FileNotFoundError(
            f"missing {ingest_json} — Stage 01 reads Stage 00's output. Run "
            f"stage00_ingest on this page first."
        )
    manifest = json.loads(ingest_json.read_text(encoding="utf-8"))
    frames = manifest.get("frames", [])
    if not frames:
        raise RuntimeError(f"no frames in {ingest_json}; nothing to fuse.")

    ingest_dir = page_dir / "00_ingest"

    def load(i: int) -> np.ndarray:
        img = cv2.imread(str(ingest_dir / frames[i]["name"]), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"unreadable frame: {frames[i]['name']}")
        return img

    base_idx, fullspread, closeups = partition_frames(
        frames, float(params["fullspread_area_frac"]))
    base = load(base_idx)

    stitch_results: list[StitchResult] = []
    t_stitch = time.perf_counter()
    n_stitched = 0
    # Match every close-up against the PRISTINE anchor, not against the base as
    # previous stitches have modified it. The anchor is the common coordinate
    # frame; matching into a progressively repainted one makes the outcome depend
    # on frame order. Measured on zoomset_en_02: blending f03 first repainted the
    # region f05 needed and dropped f05 from 21 inliers to 5, losing a correct
    # registration purely because of the order the phone happened to shoot in.
    anchor = base.copy()
    for i in closeups:
        cu = load(i)
        blended, res, note = stitch_closeup(anchor, cu, params, dest=base)
        res.name = frames[i]["name"]
        res.note = note
        if blended is not None:
            base = blended
            n_stitched += 1
        else:
            warnings.append(f"close-up {frames[i]['name']} not stitched: {note}")
        stitch_results.append(res)
    stitch_ms = (time.perf_counter() - t_stitch) * 1000.0

    if len(frames) == 1:
        method = "single"
    elif n_stitched > 0:
        method = "sharpest+stitch"
    else:
        method = "sharpest"

    # Artifacts.
    out_dir = page_dir / "01_fuse"
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "anchor.png"), base)

    result = FuseResult(
        n_frames=len(frames), anchor_source=frames[base_idx]["name"],
        method=method,
        fullspread_frames=[frames[i]["name"] for i in fullspread],
        closeups=stitch_results,
    )
    (out_dir / "fuse.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")

    # Debug overlay: anchor with a banner (+ stitched-region outlines if any).
    debug_dir = page_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(debug_dir / "01_fuse.png"), _overlay(base, result))

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={k: params[k] for k in DEFAULTS},
        timings_ms={"stitch": round(stitch_ms, 1), "total": round(total_ms, 1)},
        warnings=warnings + [
            "v0.2: multi-zoom stitch validated on the 11 real close-ups in "
            "testset/zoomset_* (5 register, 0 wrong). A close-up is accepted on "
            "PHOTOMETRIC agreement after warping (min_ncc), not on the inlier "
            "count alone. The 6 that never register are oblique views of a "
            "strongly curved page, which a planar homography cannot fit — that "
            "is a capture-guidance and/or dewarp-before-stitch problem, not a "
            "matcher tuning one. ECC sub-pixel refine is still a follow-up.",
        ],
    )
    (out_dir / "meta.json").write_text(
        meta.model_dump_json(indent=2), encoding="utf-8")
    return result


def _overlay(anchor: np.ndarray, result: FuseResult) -> np.ndarray:
    """Anchor + every close-up's footprint, green if blended in, red if rejected.

    The docstring has always promised outlines; until v0.2 this drew only a
    banner. Now that a rejection can be a WRONG registration rather than simply a
    weak one, seeing where a close-up thought it belonged is the whole point of
    the overlay — the en_01 false positive landed on grass, and that is obvious
    at a glance and invisible in a number.
    """
    canvas = anchor.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
    for c in result.closeups:
        if not c.corners:
            continue
        pts = np.int32(c.corners).reshape(-1, 1, 2)
        colour = (0, 220, 0) if c.matched else (0, 0, 235)
        cv2.polylines(canvas, [pts], True, colour, 6)
        x, y = c.corners[0]
        cv2.putText(canvas, f"{c.name} ncc={c.ncc} sharp={c.sharpness_ratio}",
                    (int(x) + 12, int(y) + 52), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    colour, 3)
    n_ok = sum(1 for c in result.closeups if c.matched)
    label = (f"fuse: {result.n_frames} frame(s)  anchor={result.anchor_source}  "
             f"method={result.method}  stitched={n_ok}/{len(result.closeups)}")
    cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 90), (40, 40, 40), -1)
    cv2.putText(canvas, label, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                (255, 200, 0), 3)
    return canvas


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stage 01 — fuse / pick anchor")
    ap.add_argument("page_dir", type=Path,
                    help="page folder, e.g. jobs/<job>/<page_NNN>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    result = run(args.page_dir, cfg, debug=args.debug)
    print(f"{args.page_dir}: {result.n_frames} frame(s) -> anchor "
          f"{result.anchor_source} ({result.method})")
    for c in result.closeups:
        print(f"  close-up {c.name}: {'stitched' if c.matched else 'skipped'} "
              f"(good={c.good_matches} inliers={c.inliers} "
              f"ratio={c.inlier_ratio} ncc={c.ncc} sharp={c.sharpness_ratio}) "
              f"{c.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
