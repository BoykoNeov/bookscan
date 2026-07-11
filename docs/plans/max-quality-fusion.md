# Max-quality fusion — stitching + rezoom (Stage 01 fuse, v0.2+)

**Owner ask (2026-07-11):** develop the feature for *stitching and rezooming
different images to get maximum quality*. Owner selected **all three**
capabilities below, explicitly wants them **done in separate slices / sessions
(no mega-session)**, and **can shoot real photos now**.

## Goal

Combine the multiple photographs of one spread — a handheld **burst** of the
full spread plus user-triggered **multi-zoom close-ups** — into a single
maximum-quality `01_fuse/anchor.png` that carries the best available detail
everywhere, feeding cleaner pixels into Stage 02+ and ultimately better OCR.

## Where we start (current Stage 01, v0.1)

`pipeline/stage01_fuse.py` already:
- picks the **sharpest** full-spread frame as the anchor (from Stage 00's
  sharpness), and **discards** every other full-spread frame;
- stitches smaller (higher pixel-density) close-ups onto the anchor via
  **ORB + RANSAC homography + feathered blend**, with quality gates
  (min inliers, degenerate-homography rejection).

It is marked **v0.1, "unvalidated on real captures"**: the testset has one
full-spread frame per page, so only the degenerate single-frame path runs on
real photos; the stitch is exercised by **synthetic unit tests only**. ECC
sub-pixel refine is a noted-but-undone follow-up.

## The binding constraint: data, not code (advisor)

Every capability below can only be *validated* once real multi-zoom captures
exist — otherwise we rebuild the v0.1 synthetic-only trap at larger scale.
Owner can shoot now, so **Slice 0 is data + harness first**; it unblocks real
validation for every later slice. No slice may declare "maximum quality" on
synthetic tests alone.

## Slices (each = its own session + commit)

### Slice 0 — real capture fixture + fusion A/B harness  ← IN PROGRESS
- **Input:** owner shot 4 sources (`source 1..4`), each = a full-spread
  **burst** (4–6 frames) + 4 **quadrant** close-ups + a 2-frame **zoom** pair,
  plus a **skew** set (3 examples × 4 angles of a curved big-book page).
  Staged in `M:/claud_projects/temp/zoomset_raw/`. 12MP (4000×3000), EXIF
  orientation 6. Real conditions: handheld, angled (perspective), background
  clutter, mild curl — NOT clean fronto-parallel.
- **Feasibility measured (2026-07-11, `temp/fuse_probe.py`)** — gates the slices:
  - **B burst parallax → GREEN:** 1000–2600 ORB inliers, homography residual
    0.6–1.2px @1600 long-side → planar, no meaningful non-planar parallax →
    Slice 2 denoise/super-res feasible, low ghosting risk.
  - **C zoom scale → GREEN:** zoom pairs differ 1.26×–2.13× (source 4's 1.26×
    marginal) → Slice 3 has real multi-scale data.
  - **D quadrant stitch → GREEN (caveat):** quadrants re-locate + tile anchor,
    union coverage 0.73–0.97; some sets marginal inliers (30) + source 1 has a
    coverage gap → ECC refine + tighter gates matter in Slice 1.
  - **A glare motion → NOT A SLICE:** bursts 2/3 + ALL skew have ZERO blown
    highlights (>235); source 1/4 glare is tiny (0.35% of page) and only
    ~21–25% moving. Hard specular glare isn't a real problem here → general
    lighting = single-image illumination normalization (Stage 00/03/05
    preprocessing), NOT multi-frame fusion. Deglare dropped from this feature.
- **Still to do:** curate `temp/zoomset_raw/` → `testset/zoomset_NN/`
  (append-only, clean names, manifest rows); build `tools/fuse_ab.py` scoring
  fusion **locally** — sharpness/detail on registered regions AND OCR on a
  hand-cropped clean single-column strip. Full-pipeline WER is NOT usable yet:
  these angled/cluttered spreads will break Stage 02's gutter assumption, so an
  end-to-end WER would conflate a Stage-02 break with a fusion result (advisor).
- **Deliverable:** committed real `zoomset` fixture + a local-metric harness.
  No fusion changes yet.

### Slice 1 — harden + validate the existing close-up stitch
- **Do:** ECC sub-pixel refine after the ORB homography (the noted follow-up);
  **multi-band (Laplacian) blending** instead of the single feather; tighter,
  per-capture quality gates; keep the three-artifact contract intact.
- **Validate:** Slice 0 harness on the real quadrant close-ups — stitched
  regions must gain local detail with **no OCR regression** elsewhere.
- **Lowest risk; builds directly on existing code.**

### Slice 2 — fuse the discarded burst frames (multi-frame denoise / super-res)
- **Do:** stop throwing away the non-sharpest full-spread frames. Register all
  full-spread frames to the anchor (ORB/ECC), then **robust-merge** them
  (temporal denoise; optional integer-factor super-resolution from sub-pixel
  shifts). New capability — its own module seam behind the same stage contract.
- **Validate:** Slice 0 burst — fused anchor vs. single sharpest frame; expect
  noise ↓ and small detail ↑, verified by the harness, not asserted.
- **Risk:** ghosting on any hand-tremor parallax; needs a robust (not mean)
  combine + a motion/alignment reject path.

### Slice 3 — multi-scale / tiled super-res composite
- **Do:** combine the anchor + several zoom levels of the **same** region into
  one composite that keeps the best available detail per tile (beyond a single
  close-up overlay). Depends on Slice 1's stitch + Slice 2's fusion.
- **Validate:** Slice 0's two-zoom-level region shots.
- **Most ambitious; sequenced last.**

## Owner's two extra asks — resolved as hypotheses, NOT build slices
Owner (2026-07-11) added **curvature (book fold in big books)** and
**glare/lighting correction**. Advisor + Slice-0 pixels resolve both:
- **Curvature → already Stage 03's job.** UVDoc measured single-image
  bg_02 31.5→1.7%. Multi-*view* flattening from the skew set is research-hard.
  The skew set's role is a **test** of "does multi-image fusion add anything
  Stage 03 doesn't?" and a robustness probe for Stage 03 — not a committed
  multi-view-flattening build. (Pre-committing to that is the one move that
  sinks this feature.)
- **Glare → single-image preprocessing, not fusion** (Check A above: no
  meaningful specular glare in this data). General uneven-lighting-for-OCR
  belongs in Stage 00/03/05 illumination normalization, tracked separately.
- If owner genuinely wants multi-view curvature/deglare as real build work,
  it's scoped as its own effort — flagged to them, awaiting redirect.

## Cross-slice invariants (do not break)
- Stage-contract compliance: `01_fuse/anchor.png` + `fuse.json` + `meta.json`
  + `debug/01_fuse.png`; reads ONLY Stage 00's output; re-runnable.
- Every quality claim is **measured on the real `zoomset` fixture**, appended to
  `docs/RESULTS.md` (dated row, never overwrite) — same discipline as dewarp.
- Fusion must be a strict improvement or a flagged no-op; never silently degrade
  a clean single frame (mirror Stage 03's flagged-identity rule).
