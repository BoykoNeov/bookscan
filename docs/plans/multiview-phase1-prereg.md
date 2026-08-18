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

---

## Addendum 2 — widening Claim B's population (2026-08-18, written AFTER the scoring run, BEFORE any widened number exists)

The scoring run measured Claim B on **four** sets. This document says Claim B
"runs on **every** set that passes gates A–C, not only the GT-keyed ones", and
the `docs/RESULTS.md` row declares the shortfall in those terms: the four
GT-keyed sets were used because only they had a valid page crop, and hand-reading
crops for the rest would have competed with the GT budget. B2's FAIL is therefore
a comparison of two four-set means, and B1's "≥ 80% of sets" collapsed to a
4-of-4 bar.

This addendum closes that deviation. **It is post-hoc in timing and
pre-registered in specification:** the population was always "every set that
passes gates A–C", and the B1/B2/B3 bars above are untouched. But B2's failure at
N=4 is already known, so every remaining degree of freedom is outcome-informed
and is fixed here, in writing, before the widened numbers exist. Committed before
the first widened fit is run.

**1. The instrument that defines eligibility: the automatic-crop word-stream
screen** (`temp/mv_batch18/wordstream.py`), re-run with the **corrected anchors**
of `anchors.py` rather than the superseded frame-0 assumption. This is the
instrument Gate B was defined, measured and reported on for all 20 sets, so it is
the one that decides who is eligible. Every set it excludes is published with its
numbers, so the reader can see what was dropped rather than infer it.

**2. The pair rule: the anchor and candidate of `anchors.json`** — anchor = the
frame reading the most dictionary-valid tokens, candidate = the frame
contributing the most valid tokens the anchor misses. That is the pair the four
measured sets used. It is **not** `b3.py`'s "any frame pair clearing Gate B",
which is a different rule answering a different question (B3's "can this set be
fitted at all"), and which must not be silently borrowed here.

**3. Eligibility is CONFIRMED on the hand crop, and attrition is published.** A
set that clears the screen but misses Gate B's floor (**≥ 40 correspondences,
≥ 12 of them in the gutter band**) on its own hand crop is **excluded**, and
reported with both numbers. This is expected, and the direction is known in
advance: on the four measured sets the hand crop raised total correspondences
1.4–3.8× and **lowered** gutter correspondences in three of four (67→14, 38→22,
32→12). The screen therefore **over-counts the binding constraint**. Attrition at
the gutter floor shrinks the population and makes B1's "≥ 80% of sets" easier to
satisfy; that is a bias of this procedure and is stated in the row, not hidden.
The reverse error is live too — a set the screen rejects on *total* count could
clear 40 on a hand crop — and is accepted as the price of using the screen the
gates were reported on.

**4. A set that passes Gate B on its hand crop but cannot be split into a fit and
a held-out half** (`score.py`'s existing floor: ≥ 12 fit, ≥ 5 held-out
correspondences under the inner-24%-of-span rule) is reported as
**eligible-but-not-fittable**, with its counts, and contributes to no mean. The
split rule is reused verbatim; it is not re-tuned to admit a set.

**5. The multi-scale sets ENTER B1 and B2's population** if they clear the screen
and the hand-crop confirmation, **and are additionally broken out for B3**. This
is the literal reading of the bars above — B1/B2 say "over all sets", B3 says the
multi-scale four are "reported separately" — and it is fixed now because it is
the choice most available for shopping after the fact.

**6. The widened population is the authoritative Claim B verdict.** The four-set
result stands as a published subset, not as a competing answer. The consequence
above applies unchanged: **if B1 and B2 both hold on the widened population, the
blind inner-band selector IS replaced by a fixed affine transform** in the merge's
transform choice, and STEP 3's debt is closed. If B2 fails again, the selector
stays and the debt remains settled-negative. No third option is reserved.

**7. Widening is not assumed to favour affine.** B2's second clause ("affine
loses by more than 2 px on **no more than one** set") was nearly vacuous at N=4
and gets *harder* as N grows; B1's "≥ 80% of sets" becomes a real bar for the
first time. Recorded here so the row cannot be read as widening-until-it-passes.

**8. Mechanics that protect the number rather than the story.**
   * The gutter **side** of every new set is derived from the screen's own `side`
     (`target_page: left` → the gutter is the **right** edge), never guessed. The
     held-out band's x-range is printed as a fraction of page width and
     **asserted to be spine-side before any fit runs** — a side error silently
     turns the held-out set into the *outer* margin, and the fit still converges.
   * The widened run writes to a **new** directory (`temp/mv_phase1c`).
     `temp/mv_phase1b` is frozen by its own docstring: GT was keyed on those exact
     files, and re-running its `prep.py` would overwrite them.
   * `score.py`'s `_fit` — the incumbent selector and the fixed-affine
     challenger — is reused **by import, unmodified**.

**9. What this addendum does NOT re-open.** Claim A is closed. The v1–v4 policies
remain off-limits on every page of this fixture, including the sets added here.
No GT is keyed, read, or needed. Nothing about the merge policy is re-measured:
this is the transform family alone.

### Amendment to Addendum 2 — the cheap screen cannot define the population (same day, still before any widened fit)

Addendum 2 item 1 named the automatic-crop word-stream screen as the instrument
that decides eligibility, on the precedent that the gates were reported on it.
That screen was then re-run on all 20 sets with the corrected anchors and the
`anchors.json` pair rule (`temp/mv_phase1c/screen.py`, `screen.json`) — and it
**disagreed with the hand crop, at the binding floor, on half the sets where both
instruments exist**:

| set | screen (corr / gutter) | hand crop (corr / gutter) | screen verdict |
|---|---|---|---|
| `en_coin_e` (`en_01`) | 287 / 74 | 326 / 14 | pass |
| `en_coin_a` (`en_02`) | 283 / **11** | 260 / 13 | **FAIL** |
| `it_ferr_g` (`it_01`) | 146 / 52 | 94 / 22 | pass |
| `de_ferr_a` (`de_01`) | 85 / **11** | 120 / 12 | **FAIL** |

Two of the four sets the scoring run actually measured on hand crops — and
published — do not clear the screen. The gutter count is the binding constraint
(≥ 12) and the screen misses it by one on both. It also over-counts wildly in the
other direction (74 against 14 on `en_coin_e`). The `docs/RESULTS.md` row already
recorded a one-set instance of this ("the floor is marginal and
instrument-sensitive"); at four sets it is not marginal, it is the instrument.

A rule that excludes two of the fixture's own published sets is not a population
rule. **Item 1 of Addendum 2 is replaced:**

> **Every set that passes Gate A is hand-cropped, and Gate B is evaluated ONLY on
> the hand crop.** Gate A (orientation, `gates.json`) is unaffected by the anchor
> correction and stands as committed: 18 of the 20 sets pass; `it_ferr_b` and
> `it_ferr_e` do not, and are out. Four of the 18 already have hand crops from the
> scoring run and are carried over unchanged. The remaining **14 are cropped now**.

Why this direction and not a margin: widening the screen's floor by "the largest
observed disagreement" would mean picking a number after seeing which sets sit
just under it, which is the one thing Addendum 2 exists to prevent. Hand-cropping
every Gate-A set removes the choice instead of tuning it — it costs 28 more crop
readings and no ground truth, and it cannot be steered toward a result because no
transform has been fitted yet on any of them.

**The screen's numbers are kept and published anyway**, as what they now are: a
measurement of how badly a frame-relative automatic crop misreports gutter
correspondences. That is a finding about the instrument the gates were reported
on, and it belongs in the row.

**One consequence for item 8's "the side is never guessed":** the screen's `side`
is a real measurement only where it detected a gutter on the anchor. On six sets
it did not (`it_ferr_e`, `en_coin_c`, and the four multi-scale sets) and returned
its single-page fallback, which is a constant, not a reading. For those sets the
spine side is **hand-read off the same grid sheet as the crop box and recorded
per set**; the spine-side assertion on the held-out band still runs for every set,
and any set whose hand-read side contradicts a screen-detected side is reported.

**Outcome (same day).** Done and reported: `docs/RESULTS.md` → "Multi-view
Phase 1 — Claim B on the widened population". 20 sets → 18 pass Gate A → 14 new
hand crops → **11 clear Gate B on their hand crop**. **B1 passes 11/11** (a real
bar for the first time; it was 4-of-4 before). **B2 fails on both clauses** —
mean 6.32 px for affine against 5.44 for the selector, and affine loses by more
than 2 px on three sets where at most one is allowed, where at N=4 that second
clause had held. **The selector stays; STEP 3's debt stays settled-negative.**
The widening did not change the verdict, it sharpened it — and the amendment
above earned its cost in both directions: the screen would have dropped
`en_coin_g` (30/4 on the screen, 40/15 on the hand crop) as well as two of the
fixture's own published sets.

**Correction to item 8 of Addendum 2, found on review after the run.** That item
promised the held-out band would be "asserted to be spine-side before any fit
runs". The obvious form of that assertion is a **tautology** — `held` is defined
as the spine-side 24% by the same variable the assertion reads — and it was
replaced, after the run and with no number changing, by a check against an
independent witness: the screen's separately measured spread side, available for
six of the seven newly measured sets, all six agreeing. The risk item 8 named is
real and was demonstrated rather than assumed (a deliberately flipped `it_ferr_h`
returns a clean-looking 3.23 px). The remaining defence for sides with no witness
is the rendered-overlay pass, which caught the one real inversion.
