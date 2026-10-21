# Pre-registration — does `figure_hires`' per-source likeness gate punish sharp sources? (2026-10-21)

Written before any smoothed number exists. The unsmoothed per-candidate numbers
of today's first test job were seen in a scratch probe (one candidate, coin,
NCC 0.59, coverage 0.75); nothing else.

## Question

`figure_hires.candidates()` accepts a capture as a source for a picture only if,
pulled back into the page crop's own frame, it correlates with the crop at
NCC ≥ `min_ncc` (0.60). The pull-back is `cv2.warpPerspective(img, Hi, (w, h))`
with default flags: **bilinear, no prefilter**, shrinking the source by its
local scale `s` (source px per crop px, 1.15–4.0 by the scale gate). A source
that resolves fine periodic detail the crop does not (a halftone screen, small
print) aliases on that shrink, and so can look *less* like the crop the sharper
it is. Hypothesis: the gate is biased against exactly the sources this module
exists for.

## Change under test (one line's worth; nothing else moves)

Before the pull-back at `figure_hires.py:447`, blur the source with a Gaussian
of **σ = ½·√(s² − 1)** source pixels (σ = 0 for s ≤ 1), where `s` is
`local_scale(H, w/2, h/2)` already computed two lines above. Theory, not tuned:
it is the extra blur that turns a σ = ½-pixel sampling kernel at the source's
scale into a σ = ½-pixel kernel at the crop's. `min_ncc` stays 0.60. The crop is
not touched. `_refine`/`_agree_at` (ECC alignment choice, also unfiltered) is
**out of scope** — changing it would move the alignment of every shipped
upgrade; recorded as a follow-up, not tested here.

## Population

Every FIGURE block (not deleted) of the three assembled jobs that have
captures, searched against its own spread's frames exactly as Stage 07 does
(`_capture_frames`, current `config.yaml` params, RANSAC seeded):

- `jobs/20260829-084115-de3c20d3` — the owner's book, 50 subpages, 157 figures,
  24 upgraded today;
- `jobs/20261021-103158-a7a95119` — first full-size close-up test, 6 figures, 0;
- `jobs/20261021-104424-6d43b587` — sweep/tap job, 15 figures, 7.

Unit of the per-source gates: a candidate (figure × frame) that reaches the NCC
gate (passes inliers, sanity, `min_piece`, scale). Unit of the outcome: a
figure's delivered asset.

## Recorded per candidate

scale, inliers, coverage, NCC as today (`ncc_now`), NCC with the prefilter
(`ncc_aa`), and for every candidate with `ncc_now ≥ 0.60` (the sources accepted
today) the NCC of **shifted copies**: H composed with a translation of the crop
by 5 % and 10 % of the crop's shorter side, in 4 directions (8 copies), both
arms.

## Gates (all must hold to ship the change)

- **G1 no regression.** Every candidate with `ncc_now ≥ 0.60` has
  `ncc_aa ≥ 0.60`, and every figure upgraded by the current arm is still
  upgraded by the prefiltered arm.
- **G2 shift control.** Over all shifted copies, the number with NCC ≥ 0.60
  under the prefilter is **≤** the number under today's statistic. (A smoother
  statistic forgives misplacement; this is the failure `min_ncc` was set to
  stop — wrong registrations scored 0.51–0.52, RESULTS 2026-08-29.)
- **G3 effect.** At least one figure's delivered asset changes (newly upgraded,
  or a different source set). Zero means the change has nothing to drive it:
  not shipped, recorded as such.
- **G4 by eye, every changed figure.** Checkerboard overlay (80 px tiles,
  asset shrunk to crop size against the crop) must line up; and the asset vs
  the page crop enlarged, at the same size, must not be visibly softer. Any
  misaligned one refuses the change outright; a softer one is reported (P7,
  focus is unmeasured in general) and counts against shipping if it is the
  majority of the changed figures.

## Also reported (not gates)

- The aliasing signature: among today's accepted sources, the relation between
  `s` and `ncc_aa − ncc_now` (expect the gain to grow with scale; ≈ 0 near 1.15).
- How many candidates are refused **only** by `min_ncc` under each arm.
- The coin of `20261021-103158-a7a95119`: stated in advance that it cannot
  upgrade from that close-up whatever this gate does (coverage 0.75 < the
  guarded `min_coverage` 0.90).

## What this cannot say

One book plus two scenes from one session; the shift control models
misplacement by translation only (not a wrong region with similar texture);
"not softer by eye" is the operator's eye standing in for a focus statistic
that does not exist yet (P7).
