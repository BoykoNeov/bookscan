# Multi-view Phase 1 — PRE-REGISTRATION on the 2026-08-18 fixture

**Written and committed BEFORE any ground truth was keyed on these pages, and
before any policy was scored on them.** That ordering is the entire point of the
document: Phase 1's headline limit is that *five merge policies were compared on
the same three pages that carry the GT*, so "v5 is best" is a hypothesis
generated at N=3, not a validated choice (docs/RESULTS.md, STEP 4 → Limits).
Curating a new fixture and then scoring all five policies on it again would
reproduce exactly the invalid thing at N=9. So the choice is spent here, in
advance, in writing.

Companion documents: `docs/plans/multiview-curvature.md` (the effort's scope),
`docs/RESULTS.md` rows "Multi-view Phase 1 — STEP 1 gate + STEP 2 headroom" and
"STEP 3/4" (the N=3 measurements this predicts a replication of).

---

## The data

Owner delivered 97 multi-angle phone captures on 2026-08-18
(`temp/zoomset_raw/batch_20260818/`, 344 MB, kept out of git). 20 sets across
three books — an Italian via-ferrata atlas (a *new* book, distinct from the
existing `it_geo_*` geology fixtures), the German via-ferrata guide behind the
existing `de_*` fixtures, and the English *Chopmarked Coins* behind `en_coins_*`.
Set membership is recorded in `temp/mv_batch18/sets.py`.

**Two properties differ from every page measured so far, and both are stated here
as risks rather than discovered later as surprises:**

1. **These are SPREADS.** All prior Phase 1 numbers came from single pages,
   de-contaminated by hand-cutting the facing-page sliver at the spine valley
   before dewarp. **Resolution: these are prepared the same way** — page crop,
   cut at the detected gutter, keep the one page, sliver margin removed — so the
   replication is like-for-like. See "Preparation" below for why the alternative
   (score the spread as a spread, gated on a frame-stable Stage 02 split) was
   measured and abandoned.
2. **Four sets are multi-SCALE as well as multi-angle** (a full spread plus
   progressively closer partial views: `en_coin_f/g/h/i`). The transform-family
   selector is already the flagged weak link — it took a 97%-of-bar model on
   curl5 — and scale change is where it should be expected to break. Which family
   it picks is logged per set so a failure is diagnosable rather than just a bad
   number.

**No Bulgarian in this batch.** The original data ask was Bulgarian / Italian /
German; this batch delivers Italian, German and English. The Cyrillic arm is
therefore **not validated by this fixture** — specifically, v5's dictionary-veto
behaviour on Cyrillic is untested here, and no claim below extends to it. This is
recorded as a stated limit on the claim, not as a gap to be filled: the owner
delivered this batch as sufficient for the purpose.

---

## Gates — a set must pass all three to enter the fixture

Keying band GT by hand is the budget sink, so each gate is cheap and can kill a
candidate before any GT is typed. Gate results: `temp/mv_batch18/gates.json`,
`gate_c.json`.

| gate | question | bar | why this bar |
|---|---|---|---|
| **A — orientation** | do all frames of a set resolve to the same upright? | one `applied_rotate` and `landscape` for every frame in the set | EXIF flips 6↔8 *inside* single bursts in this batch. Two frames of one spread arriving 180° apart would corrupt word-stream alignment silently, and would surface only as a bad number after the GT was already paid for. |
| **B — viewpoint diversity + fittability** | is this real re-angling, and are there enough matched words to fit a transform at all? | **≥ 40 word correspondences** with **≥ 12 of them in the gutter band**, from the aligned OCR token streams; median centroid displacement reported as the diversity number | See "Why Gate B changed instrument" — ORB is unusable here. The counts mirror what STEP 3 actually fitted and held out (43/16, 102/64, 79/24). A set below them cannot fit a held-out transform, so it cannot enter the fixture no matter how much headroom it has. |

**Gate C was specified, measured, and withdrawn — as a mis-specification, not a
result.** It asked whether Stage 02 puts the gutter in the same *fraction of the
frame* in every view. It cannot: a fraction-of-frame position **must** differ
across viewpoints, and the measured sequences are perspective behaving exactly as
perspective does (`it_ferr_a` 0.634 → 0.545 → 0.478; `en_coin_a` 0.593 → 0.432 →
0.358). A frame-relative bar is satisfiable only by frames that share a viewpoint,
which is the opposite of what this fixture is for. Repairing it in a common
coordinate frame would need the transform, which needs the correspondences, which
is downstream of what the gate was supposed to protect. Numbers kept in
`temp/mv_batch18/gate_c.json` for the record; the `0.3` entries look like a
search-range clamp rather than a detection and are **not** quoted as positions.

**What survives from it** is a narrower check that can genuinely destroy the
measurement, and it needs no probe: **does a frame's page crop cut off text that
another frame retains?** Cutting into the gutter on the oblique frame would delete
precisely the words the merge exists to recover. Checked by eye on the crops
produced for the selected sets, while keying GT. Stage 02 frame-stability across
viewpoints is recorded as a **pipeline-integration** question, not a measurement
one — nothing here is wired into the pipeline yet anyway.

A **headroom triage** then ranks the survivors without consulting GT: OCR both
extreme frames and count dictionary-valid tokens present in the oblique and
absent in the face-on (`temp/mv_batch18/triage.py`). That is a free proxy for the
union ceiling STEP 2 measured, and it decides which sets are worth keying. It
touches no merge policy, so it does not spend the pre-registration. The reverse
count (face-on-only tokens) is printed beside it as the far-side risk indicator.

### Why Gate B changed instrument (a result in its own right)

Phase 0 gated viewpoint diversity on **ORB** median frame-to-frame displacement
(80–900 px). Run on this batch, that gate would disqualify exactly the sets the
effort exists for. On the strong-curl English sets ORB returns **3–13 RANSAC
inliers** between the extreme frames — it does not register them at all — and a
median displacement computed from 3 inliers is noise, not diversity (`en_coin_b`
reports 1246.9 px off 3 inliers; the probe later crashed outright on a null
homography mask, which is the same failure with the politeness removed).

This is **Phase 0's finding 0b reproducing on new pages, outside the original set,
for the first time** — and it separates cleanly by book and curl severity rather
than randomly: every Italian and German set registers (36–701 inliers), 7 of the 9
English strong-curl coin sets do not. It is also exactly why the Phase 1 route
changed from a pixel composite to a text merge. The ORB numbers are therefore
reported as a **secondary observation with inlier counts attached**, never as an
entry gate.

The replacement measures the same property with the mechanism the merge actually
uses — the aligned OCR token streams (`temp/mv_batch18/wordstream.py`).

### Preparation (fixed here, before any GT)

Per frame: upright with the orientation **pinned per set** → page crop (Otsu +
largest contour, as `headroom.py::auto_page_crop`) → cut at the detected gutter,
keep the one page of interest, with a 1.5%-of-width sliver margin so the facing
page cannot contaminate → UVDoc dewarp. Frames where no gutter is detected are
already single pages (every partial close-up in the long sets is) and are used
whole; that is correct behaviour, not a detection failure. The page of interest is
chosen **once per set, on the anchor frame**, as the half carrying more text.

**Anchor choice is measured, not assumed.** The merge is defined as *insert what
the oblique view recovered into the face-on page*, so which frame is the anchor
decides the sign of the whole measurement. Frame order is **not** a reliable
guide: on `it_ferr_g`, frame 0 (134759) is the oblique view whose inner column is
foreshortened into a smear, and frame 2 (134804) is the face-on one that reads it
— the opposite of what capture order suggests. The anchor is therefore the frame
reading the most **dictionary-valid tokens** (`temp/mv_batch18/anchors.py`), the
same GT-free legibility proxy the triage uses, applied within a set; the candidate
is the frame contributing the most valid tokens the anchor misses. Every number
produced before this correction assumed frame 0 and is superseded by it.

**Orientation pin, and the shipped defect it exposes.** Gate A found two Italian
sets whose frames disagree on upright: `it_ferr_b` (frame 134655 → OSD 180° at
conf **2.58**, the other two → 0° at conf 16.6/10.4) and `it_ferr_e` (134731 →
180° at conf **3.09**, the other two below threshold and kept raw). Both are the
same defect in shipped code: `DEFAULT_MIN_OSD_CONF = 2.0` trusts an OSD call at
conf 2.6–3.1, which on a book spread is noise — and a **180° error is invisible to
the cascade's layer-5 landscape prior**, because a spread rotated 180° is still
landscape. The prior distinguishes portrait from landscape only. `it_ferr_e` is
the worst case by construction: a full-bleed panorama with almost no text, so OSD
has nothing to work with (conf 0.24).

Resolved fixture-side by **per-set majority** of the applied rotation, recorded
per set in `temp/mv_batch18/orient.py`. Majority is defensible because every frame
of a set photographs one physical spread held one way up — that is an assumption
about the *capture*, not a property of the images, and it is stated in the
manifest as such. `tools/normalize` is **reported, not patched** in this session;
both sets are added to `testset/gt/orientation.json`, which exists for exactly
this, with `it_ferr_e` as the sharper fixture (text-free spread, prior cannot
help, EXIF distrusted).

---

### Selection rule (fixed here, so the choice is not made by the numbers)

From the sets that pass gates A and B, key GT on **at least one Italian and at
least one German set**, even where an English coin set ranks higher on the
headroom proxy. Reason: if the keyed sets are mostly `en_coins`, Claim A
replicates on more pages of *the same paperback*, not across books — which is
weaker than the page count suggests, and would have to be said that way in
RESULTS. Cross-book replication is worth more than a fourth page of one book.
Within that constraint, rank by the headroom proxy.

## Claim A — the merge policy (needs GT)

**Under test: `v5` — per-slot confidence decides each contested slot, but a valid
dictionary word is never traded for a non-word** (`merge.py`,
`winners="slot_veto"`). This is the single policy named in advance.

**The other four policies (v1 dict-gate, v2 region/height, v3 region/conf, v4
per-slot conf) will NOT be run on these pages.** That option is spent the moment
they are looked at, and running them would recreate the N=3 defect at a larger N.

**Prior (what N=3 measured), for reference — gutter sequence recall Δ vs face-on:**
skew **+0.244**, curl3 **−0.025** (the declared no-headroom control), curl5
**+0.074**; far-side *bag* recall Δ: 0.000 / 0.000 / −0.047.

**Predictions, registered now:**

| # | prediction | pass condition |
|---|---|---|
| **A1** | v5 raises gutter recall on pages that have headroom | mean gutter sequence-recall Δ over the **headroom** pages (triage proxy > 0) is **> +0.05**, and **strictly positive on a majority** of them |
| **A2** | the veto holds the far side | mean far-side **bag** recall Δ is **≥ −0.05**, and no single page loses more than **0.10** |
| **A3** | the no-headroom control stays flat | on any page the triage proxy calls zero-headroom, gutter Δ is within **±0.05** |

**Addendum, added the same day, before any scoring run** (RESULTS "Correction 4"): A1 says
"the headroom pages (triage proxy > 0)" without pinning whether the proxy means *gain* or
*net*. It means **gain** — gain is the quantity STEP 2's ceiling measures, and A1 asks about
pages where there is something to win, not pages where a naive whole-band swap would win. The
resulting bucket assignment, fixed now rather than after a result: **`skewset_en_01` and
`skewset_it_01` are win cases, `skewset_en_02` is the guard case (a large but symmetric
exchange, which is what A2 exists to catch), and `skewset_de_01` is the declared no-headroom
control for A3** — its target page offers only 7 tokens of gain, the role curl3 plays in the
original trio. Gate B's floor is also now verified on the selected frames and hand crops
(326 / 260 / 94 / 120 correspondences, 14 / 13 / 22 / 12 in the gutter — all pass, with
`skewset_de_01` exactly on the floor).

**A1 or A2 failing is a real negative result and will be reported as one.** If v5
does not replicate, Phase 1's word merge is not shippable and that is the
finding; the fixture is worth exactly as much either way.

**Scoring is like-for-like with the existing three pages, deliberately:** token
recall scored by difflib as the verdict, order-free **bag** recall printed beside
it as the diagnostic (sequence-only loss = words present but mis-ordered; bag
loss = words genuinely replaced), decoy recall as the noise floor, and band GT
keyed in **text-column coordinates, not page fractions** — `gt_far.json`'s README
records that the naive page-width mirror `[.76–.88]` dumped blank paper because
these columns stop around x = .63–.76. Band definitions and the geometry code
path are reused rather than re-derived; a differently-defined band would make the
replication unreadable.

---

## Claim B — the transform family (needs NO GT)

STEP 3 left an explicit debt: *"A **fixed affine** model would have scored 5.2 /
5.4 / 11.4 — comfortably under bar on all three — but that choice is post-hoc on
N=3 and does not count until it is pre-registered on a fixture that has not been
looked at."* This is that pre-registration.

**Under test: a fixed `affine` (RANSAC) transform, against the incumbent blind
inner-band selector**, on held-out median |Δy| — fit on non-gutter
correspondences, scored on gutter ones, so the model must **extrapolate**. This
needs no ground truth at all, so it runs on **every** set that passes gates A–C,
not only the GT-keyed ones.

| # | prediction | pass condition |
|---|---|---|
| **B1** | fixed affine is under bar | median held-out &#124;Δy&#124; < **half the median word height** on ≥ 80% of sets |
| **B2** | fixed affine is no worse than the selector | mean held-out &#124;Δy&#124; over all sets is **≤** the blind selector's, and affine loses by more than 2 px on **no more than one** set |
| **B3** | scale change is where it breaks, if it breaks | the four multi-scale sets are reported separately; a failure concentrated there is a *scale* finding, not a family finding |

If B1 and B2 both hold, the selector is replaced by fixed affine and the weak
link named in STEP 3 is closed. If B2 fails, the selector stays and the debt is
recorded as settled-negative.

---

## What counts as done

1. Gates A–C run on all 20 sets; results committed.
2. This file committed **before** the first GT token is keyed.
3. GT keyed (gutter + far-side bands) on the selected sets.
4. **One** scoring run: v5 only, plus the GT-free Claim B sweep.
5. A dated `docs/RESULTS.md` row reporting A1–A3 and B1–B3 **as pre-registered**,
   pass or fail, with the failures kept rather than explained away.
6. Selected frames copied into `testset/skewset_*` (append-only) with a manifest;
   raw batch stays in `temp/zoomset_raw/batch_20260818/`, out of git.

Anything measured on these pages that is *not* in this document is exploratory
and must be labelled as such in RESULTS.
