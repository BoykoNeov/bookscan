# Multi-view curvature correction — SCOPE (not started)

**Owner ask (2026-07-11):** big books won't lie flat; a page folds/curves and
OCR suffers near the gutter. Owner shot a **skew set** — the same curved page
from multiple angles — and asked to **scope this as its own effort** (separate
from the [max-quality-fusion](max-quality-fusion.md) feature), and explicitly
**not to start building yet**.

Status: **SCOPE.** Phase 0 (make-or-break gate) RUN on the N=1 skew set 2026-07-11
— see `docs/RESULTS.md` "Multi-view curvature Phase 0". Verdict: (0a) UVDoc alone does
NOT recover the innermost gutter word on the best single view (flat-band conf +10-13,
innermost gutter unchanged/worse) → not moot; (#1) **premise verified as an existence
proof** — a different angle (151105) legibly captures gutter line-starts ("Lines in the
sand…") the face-on frame foreshortens into smear; (0b) BUT a global ORB homography
cannot fuse them — the gutter is *unregisterable-by-features to a face-on anchor*, so a
naive-registration Phase 1 is **research, not a cheap build**. Phase 0 does NOT greenlight
Phase 1. Held at scope pending the data-gap ask (validates the *solution*, not just the
premise) + an outer-gutter-band contrast spike. See end.

## What multi-view actually buys (do not oversell)

Multi-view's honest value is **recovering gutter text that any single view
foreshortens away** — near a steep curl, one camera sees the page almost
edge-on, so that region gets very few pixels; another angle sees it more
face-on. It is **NOT** "flatten better." **Flattening stays Stage 03's job**
(UVDoc, already measured single-image bg_02 31.5→1.7%). If Stage 03 already
flattens the curl acceptably from one frame, the only residual multi-view value
is resolution recovery in the deepest gutter — a narrow win. This effort must
prove that gap exists before building for it.

## The skew data (why N=1 is the binding constraint)

Two regimes in the shot set — only one justifies the effort:
- **example 1 & 2** (sequoia / temple photo-book): curvature is *severe* but the
  page is almost all **photo**; the only text is a thin caption column on the
  **flat outer margin**, away from the curl. Curvature barely hurts OCR here →
  these are **"don't break the photo/caption" regression cases, not
  validation.**
- **example 3** ("A New World" paperback, p.797): **dense single-column prose
  with strong gutter curl** compressing lines toward the spine. **The only page
  in the set that actually exercises curvature-hurts-OCR** — and it is N=1.

**You cannot validate an OCR-gain claim on one page.** Writing this scope is
fine; **starting Phase 1 (build) is blocked** on more data (see Data gap).

## Capture mode (architecture note)

Single-page-×-N-angles is a **different capture mode** from the fusion sets
(spread + area-smaller close-ups). It **breaks** Stage 01's area-based
burst/close-up partition and Stage 02's spread-split assumption. So it needs its
**own mode flag / ingest path**, not a bolt-on to `stage01_fuse`. Contract stays
intact: multi-view produces the **best anchor**, then **Stage 03 unchanged** does
the geometric flatten.

## Phases (each gated — do not skip a gate)

### Phase 0 — make-or-break gate (cheap, runnable on N=1 today) — RAN 2026-07-11
Two measurements decide whether the effort is worth anything and how hard it is.
**Result: 0a → UVDoc doesn't recover the innermost gutter on the best single view (not
moot); +an added cross-frame check → another angle DOES legibly capture that gutter text
(premise verified, existence proof); 0b → but ORB can't register the gutter to a face-on
anchor → Phase 1 is research, not a quick build. Full numbers in docs/RESULTS.md.**
- **0a — does Stage 03 already solve it?** Run Stage 03 UVDoc on the single
  sharpest example-3 frame; OCR the dewarped result vs. the raw frame (reuse the
  `tools/dewarp_ab.py` + `tools/ocr_metrics.py` path). **If UVDoc already
  recovers the curled gutter lines → the effort is moot → document in
  docs/RESULTS.md and STOP.**
- **0b — cross-angle registration residual (sizes Phase 1).** Measure ORB
  homography residual across the skew angle sets, exactly like the fusion
  feature's Check B did for bursts — but expect it to concentrate at the gutter,
  because these are viewpoints of a **non-planar** surface where a single global
  homography is geometrically wrong. **Low residual → global homography suffices
  → Phase 1 is cheap. High residual → Phase 1 needs piecewise / optical-flow
  registration → Phase 1 is itself research, not a quick build.**

### Phase 1 — multi-view best-region composite (only if 0a shows a real gap)
Register the angle set; per gutter region, pick the **least-foreshortened /
sharpest** view to recover text the single best frame loses to foreshortening;
blend into one composite anchor. Feed that composite to Stage 03 (unchanged).
No 3D reconstruction. Registration method chosen by 0b's residual. Measurable
OCR gain on the (expanded) dense-text skew fixture, or it is not shipped.

### Phase 2 — parametric developable-surface unwrap (only if Phase 1 falls short)
Book pages curl as a **generalized cylinder** (straight ruling lines along the
spine, curvature only across) — example 3 is a clean single-axis curl. Fit the
surface from cross-view correspondences and metric-unwrap. This is genuine
research; enter ONLY if Phases 0–1 leave OCR gains on the table, and scope it
as its own multi-session effort then.

## Invariants
- Stage contract intact: multi-view → best anchor; **Stage 03 does flattening**,
  not this effort. No stage modifies another stage's artifacts.
- Every OCR-gain claim measured on real curved-text pages, dated row in
  docs/RESULTS.md — never assert a flattening win unmeasured.
- examples 1/2 are regression guards: curvature handling must not wreck a
  mostly-photo page or its thin flat-margin caption.

## First next actions
1. ~~**Phase 0a + 0b** on the existing skew set.~~ **DONE 2026-07-11** (docs/RESULTS.md):
   gap real but narrow; gutter feature-poor → Phase 1 is research, not a cheap build.
   Phase 0 does NOT greenlight Phase 1.
2. **Data gap ask (still owed):** to validate any Phase-1 OCR gain, owner shoots **~3–5
   more paperback-style strong-curl dense-text pages, each from multiple angles** (like
   example 3, not the photo-book pages). Then a real `testset/skewset_*` fixture can be
   curated (append-only). Blocks any Phase-1 build.
3. **Cheap preprocessing spike (new, do before multi-view):** 0a showed part of the
   gutter gap is spine *shadow*, not just foreshortening. Test local contrast /
   shadow-flatten (CLAHE etc.) on the deepest gutter of frame 151056 — it may recover
   part of the gap for free and shrink or remove the multi-view case.
4. **If multi-view is still pursued:** budget for non-feature (ECC / optical-flow) or
   geometric (developable-surface) registration from the start — 0b proved ORB cannot
   align the feature-poor gutter.
