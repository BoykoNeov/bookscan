# Panorama Phase 0 — pre-registration, written 2026-08-31 BEFORE the run

`docs/plans/panorama-and-next-steps.md` §1 Phase 0. Registered before any number
exists, because the result licenses a large build and the same document records
four occasions where a number improved while the text got worse.

## The question

Stitching close-ups into the spread was measured and refused (RESULTS
2026-08-29): the text comes out **doubled**, and the cause named there is that a
homography is a plane-to-plane map while a photographed page is a cylinder seen
off-axis. The plan's premise is a **reorder** — flatten first, stitch second.
Does registering onto flattened pixels remove the leftover displacement that
produced the doubling?

## What the earlier run actually did, and why this is not a repeat

`M:\claud_projects\temp\stitch2\superres.py` registered each close-up onto the
**anchor** (unflattened) and *already applied* `figure_hires._mesh_refine`
against an enlarged anchor. So "add the local-bend correction" is not the open
question. The open question is the **target**: anchor, flattened page, or
flattened page with the close-up flattened too.

The published numbers (median 6.5 px, max 59 px, neighbour-tile disagreement
median 5.3 px / p95 45 px) come from **one** close-up. They are context, not a
baseline. Every arm here is compared against arm A on the same population.

## Population

All **317** close-ups of `jobs/20260829-084115-de3c20d3` (the owner's 25-spread
via-ferrata guide) — every frame of a page that `01_fuse/fuse.json` does not list
in `fullspread_frames`. Spreads `page_001`–`page_004` are the ones photographed
on a pale sofa, whose flattened pages are geometrically wrong for an unrelated,
already-recorded reason; they are **tagged and reported separately**, never
silently mixed in.

## Arms — one matcher, one acceptance rule, six placements

Registration is a single function for every arm (SIFT at 0.5 scale, ratio 0.75,
RANSAC 4 px — the one that produced 227/317 where the shipped ORB got 6).
Acceptance is a single rule for every arm: **inliers >= 20 and masked NCC >=
0.45**. Scale is recorded, never gated on, so a close-up below 1.15x stays in the
population and residual-vs-scale is answerable.

| arm | source | target | correction |
|---|---|---|---|
| A | raw close-up | `01_fuse/anchor.png` | homography |
| B | raw close-up | anchor | homography + `_mesh_refine` |
| C | raw close-up | `03_dewarp/{left,right}.png` | homography |
| D | raw close-up | dewarped page | homography + `_mesh_refine` |
| E | **UVDoc-flattened** close-up | dewarped page | homography |
| F | UVDoc-flattened close-up | dewarped page | homography + `_mesh_refine` |

A/B reproduce the failed route on the full population. C/D are "flatten the
target". E/F are the plan's actual premise, **flatten both**. Arms C–F are only
in scope because a feasibility probe run today showed UVDoc flattens a borderless
close-up in 0.2–0.5 s with a plausible correction, not a hallucinated page quad.

`figure_hires.candidates()` is deliberately NOT used: its gate stack is
figure-tuned and would admit a different subset per arm, which would destroy the
comparison.

## The statistic

Between the placed source and the target, over the source's footprint:

* tile the footprint into **128 px** tiles (the size the earlier row reports),
  admit a tile on the same rule `_mesh_refine` uses (both sides textured,
  phase-correlation response >= 0.05), and take the tile's displacement
  magnitude;
* **residual** = median (and p95, max) of those magnitudes;
* **neighbour disagreement** = median and p95 of the difference between
  4-adjacent tiles' displacements;
* **tile-answer coverage** = the fraction of candidate tiles that answered,
  reported beside every residual. A field inpainted from a handful of answering
  tiles is a global translation wearing a mesh's clothes.

Arms C–F measure in dewarped-page pixels. They are converted to
**anchor-equivalent pixels** per close-up by the ratio of the two arms' own local
scales, so the gate is applied in one unit. Residual is additionally reported in
**x-heights**, from the page's median Stage 05 word height, because that is the
unit that means something for text.

Measuring a phase-correlation correction with phase correlation is circular at
the correction's own grid, so measurement tiles (128 px) are much finer than
`_mesh_refine`'s 12x12 grid, and the grid is also measured at a half-tile offset.
The claim is only that the *smooth* field captured the deformation at a finer
scale than it was estimated at.

## Diagnostic, not just pass/fail

The same registrations are re-fitted over **sub-windows** of the footprint (1, 2
and 4 divisions per side) from the inlier correspondences inside each window, and
the statistic re-measured there. If residual crosses the bar below full-frame,
the answer is not "the route is dead" but "register whole-frame for the prior,
then re-fit per window" — which is also the search prior the per-block experiment
died without.

## The gate — fixed here, not to be moved afterwards

**PASS = median residual under 2 px AND neighbour disagreement under 5 px**, at
anchor-equivalent scale, on the non-sofa population, for at least one arm.

## What a pass licenses, and what it does not

A pass licenses **Phase 1 and Phase 2 of the plan, and nothing else**. It is a
statement about placement, which is further from the deliverable than a
confidence number is — and this repo has been burned four times by a number
improving while the text got worse. Whether a composite page reads better is
decided in Phase 2, by more confident words **and** a text diff showing no
degradation. A fail on arms A–D alone is **inconclusive for the plan's premise**
and must be written up as such; only a fail that includes E/F speaks to
"flatten both, then register".

---

*Post-hoc pointer, added after the run and changing nothing above (a
pre-registration is not amended once results exist): the claim that the 128 px
measurement tiles are "much finer" than `_mesh_refine`'s grid holds in one axis
and not the other — on the footprint scope the correction's grid lands at 53-191
px on this book. The corrected arms therefore rest on the dense-flow estimator
and on the `--control` floor measurement, both of which are reported in RESULTS
2026-08-31.*
