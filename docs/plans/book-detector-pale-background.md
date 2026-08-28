# Fixing the book detector on a pale background

**Status:** Phase 0 DONE 2026-08-28 (fixtures banked, suite deliberately red at
19/21 — see RESULTS 2026-08-28 and section 3). **Phase 1 DONE 2026-08-28** (the
artifacts stop claiming things they did not measure; suite still 19/21 exit 1,
table identical row for row — see section 4 and RESULTS). Phases 2-3 not
started. **A10 was MEASURED 2026-08-28 and is NOT shipped** — the detector
half-works (fixes `paleset_02` outright, wrecks `paleset_01`) and the
precondition this plan correctly named as the real deliverable **does not exist
on this corpus**; see section 5's A10 entry. Nothing else in Phase 2 has been
attempted. Written
2026-08-28 at the end of the on-device session that found the defect; the
scouting numbers below were measured that day, the fix was deliberately not
attempted.

**Owner-visible symptom:** two real phone captures of a book on a pale sofa did
not split into pages. One was cut in the wrong place, one was not cut at all.
This is the only thing between the verified Android app and a usable scan
(RESULTS 2026-08-28, `docs/data/device_session_20260828.json`).

---

## 1. What actually breaks, in order

Five links; the fix could go in at any of them, which is why this is a plan and
not a patch.

1. **`paper_mask` merges the book with the room.** The rule is absolute HSV:
   `S < 0.25 and V > 0.55`. On the sofa capture the page is *dim* (V 0.534) and
   the sofa is *pale and grey* (V 0.524, S 0.256) — about 0.01 of separation on
   the brightness axis. 39.9 % of the whole frame passes the rule; only 56 % of
   the actual page does. The `close_k` morphology then welds the surviving page
   fragments to the surviving sofa fragments into one component.
2. **The percentile trim cannot save it.** `search_box` trims the 2nd/98th
   percentile to kill *thin bright leaks* (a cable, a chair edge) — leaks with
   almost no pixel mass. A sofa is not a leak; it is half the frame, and
   percentiles keep it.
3. **GrabCut inherits the contamination.** Seeded from that component, it grows
   over everything, so the emit box reaches 92 % (page_001) and 100 %
   (page_002) of the frame.
4. **The abstain gate then misreports the failure.** `abstain_area_frac` 0.83
   fires and the recorded reason is *"book fills 92 % of the frame — already
   tightly framed, not cropping"*. That sentence is a **framing verdict
   produced by a detection that never happened**, and it is wrong: both frames
   have a wide margin of room all round. It misled this session's operator into
   telling the owner to stand further back, which the owner correctly rejected.
5. **Stage 02 then searches the whole frame, and the cascade misfires.**
   * `page_001`: the ink-whitespace layer found a valley *inside* a page at
     x=2741 with ratio 0.525 — just under the 0.55 gate — and Layer 1 wins
     outright, so it shipped. Meanwhile the spine-pinch cue (x=1668) and the
     binding-shadow cue (x=1730) **agreed with each other** inside the 122 px
     tolerance, ~1000 px away, and were ignored.
   * `page_002`: ink ratio 0.701 (no valley) and pinch depth 0.012 — the pinch
     cue returns a meaningless number rather than declaring itself
     inapplicable. No gutter, so `single.png`. **The mechanism stated here was
     wrong; corrected by Phase 1 (section 4):** Otsu does *not* invert on the
     pale sofa — the sofa still reads dark (8.9 % of pixels outside the labelled
     book pass as bright). The profile is pinned at the image height because
     scattered bright specks reach the top and bottom edges of most columns.
     Since Phase 1 the cue declares itself inapplicable here and Layer 2 is
     skipped.

### The near-miss table (page_001)

| cue | value | gate | verdict | was it right? |
|---|---|---|---|---|
| ink valley | ratio **0.525** | < 0.55 | passed by 0.025 | **wrong** (x=2741, inside a page) |
| spine pinch | depth **0.106** | >= 0.11 | failed by 0.004 | **right** (x=1668) |
| binding shadow | x=1730 | corroboration only | agrees with pinch | right |

Both gates were within ~5 % of flipping, in opposite directions. This is the
single strongest argument for a consensus rule, and the reason the cascade work
in section 5 is on the list at all.

---

## 2. Baseline and constraints (measured 2026-08-28; re-run before trusting)

`python -m tools.split_eval` gave **19/19 spreads correct, worst clipping
0.0 %** before Phase 0. It is now **19/21, exit 1**, because Phase 0 added the
two failing frames as ordinary graded rows (owner's call; see section 3). The
19 pre-existing spreads are untouched and worst clipping is still 0.0 %, so the
non-regression bar is unchanged in substance: **those 19 must stay correct and
clipping must stay 0.0 %**, and a fix is what turns 19/21 into 21/21. That
harness already grades both things the fix must not break, and exits non-zero on
either. It is the acceptance gate; nothing here ships without it.

The crop is only *applied* on 4 of the 19 (the `zoomset_*` lap captures);
`de_01`/`de_02` abstain at 85 %/89 %, the 13 flat spreads at 97-100 %.

**Headroom, so next session does not re-derive it:**

| knob | current | must keep passing | must start failing | headroom |
|---|---|---|---|---|
| `valley_ratio` | 0.55 | en_coins_02 and zoomset_de_01 at **0.47** | page_001 at **0.525** | 0.055, midpoint ~0.50 |
| `pinch_min_depth` | 0.11 | de_01 **0.15**, de_02 **0.18** | page_002 **0.012** (since Phase 1 this is not a depth at all — the cue is inapplicable there and Layer 2 is skipped) | wide, but page_001's **0.106** sits just under |
| `abstain_area_frac` | 0.83 | de_02 at 0.89 must abstain | — | cropping de_02 was measured to move its gutter from 7 px to 96 px off |

**Trap on `valley_ratio`:** en_coins_02 is the floor, and its pinch depth is
only **0.05**. If a tightened ink gate ever drops it through to Layer 2, Layer 2
cannot catch it and it becomes a single-page regression. zoomset_de_01 has a
net (pinch 0.22); en_coins_02 does not.

**Cost:** `find_book` is 258-1375 ms on a 12 Mpx frame. Anything evaluated
per-candidate multiplies that.

---

## 3. Phase 0 — bank the fixture — **DONE 2026-08-28**

**Outcome:** `testset/paleset_01.jpg` and `testset/paleset_02.jpg`, both with
book-box and gutter ground truth, both failing in the documented way. Full row in
`docs/RESULTS.md` 2026-08-28; machine-readable in
`docs/data/paleset_fixture_20260828.json`.

The premise below was **already stale when this ran**: the same day's
`tools/archive_photos.py` had copied all 31 captures to
`M:/claud_projects/bookscan_captures`, so the pixels were not at risk. What
Phase 0 actually delivered is the other half — *committed, labelled* fixtures, so
an experiment is reproducible from the repo alone. (Original framing, kept for
the record: the two frames existed only in gitignored `jobs/`, 565 MB + 178 MB of
job folder, one `git clean` from gone.)

```
jobs/20260828-092505-15c41a76/page_001/01_fuse/anchor.png   4080x3060, wrong split at 2741
jobs/20260828-092505-15c41a76/page_002/01_fuse/anchor.png   4080x3060, no split at all
```

Each committed JPEG decodes **pixel-identical** to its anchor above (Stage 00
applied no rotation to either), so the new rows read nothing from `jobs/`.

**What the labels are, and what they are not.** Hand-read off the committed
full-resolution JPEGs with ruler overlays at 1:1 and 1.4-1.6x on every edge, then
re-checked by drawing them back onto the frame — independent of every quantity
the detector computes, and read before any fix was attempted. They agree with the
same day's background-first probe to within ~2 points of frame area (0.577 vs
0.561, 0.436 vs 0.438), which is corroboration from an independent route, **not**
a label fitted to a candidate detector. **That corroboration is AREA-ONLY, and
2026-08-28's faithful re-run showed why the distinction matters:** it puts
paleset_01's blob at 0.716 of frame, and that blob misses the left page entirely
while leaking to the bottom-right corner. A box can agree on area and still be
badly wrong in position. The labels stay independent for the other reasons given
here - hand-read with rulers, off the committed pixels, before any fix. The book-box convention is unchanged, so
`gt/book_box.json` is still diagnostic-only: do not fit a detector to these boxes.

**Free control:** both frames are the same two pages as `en_coins_03`
(`Chopmarked Coins` pp.104-105), which is flat, well framed and passes today.
Content held constant, only the surface changes.

1. [x] Copied both anchors into `testset/` as `paleset_01` / `paleset_02`,
   append-only, from the photo archive. No `ANCHOR_OVERRIDE` wart was added.
2. [x] Hand-labelled `testset/gt/book_box.json` (6 -> 8 labelled spreads, first
   pale-background lighting setup) and `testset/gt/gutter.json` (1680 and 1778,
   tol 200), plus rows in `testset/manifest.csv`.
3. [x] `testset/README.md` has a `paleset` section saying what each one traps.

**Red-suite mechanism — decided by the owner 2026-08-28: let the suite go red.**
The rows are ordinary graded rows, `split_eval` reports 19/21 and exits 1, and it
stays that way until the detector is fixed. The two alternatives (an expected-fail
list, or a second arm on the `layout_order_eval --no-stage05` precedent) were put
to the owner and refused: a real failure should not be parked somewhere it stops
being visible. **Do not "fix" the suite by removing, excusing or re-labelling
these rows.** The `known_failing` string in `gutter.json` is documentation only —
`split_eval` does not read it.

---

## 4. Phase 1 — make the failure honest — **DONE 2026-08-28**

Cheapest work on the list, and the part that actually burned the owner. Shipped
with `split_eval` still at **19/21, exit 1**, worst clipping 0.0 %, and the table
identical to the previous commit row for row (verified by diffing an eval run at
`HEAD` against one after the change). Suite 554. Full row in `docs/RESULTS.md`
2026-08-28; machine-readable in `docs/data/phase1_honest_failure_20260828.json`.

* [x] **B1. The abstain reason stops asserting a framing verdict.** The 83 %
  gate now reports only what it measured, and a new `BookBoundary.evidence` (→
  `split.json.book_crop_evidence`, `meta.warnings`, and the overlay) carries the
  caveat. `paleset_02`, whose box is the whole frame, gets the stronger clause
  *"the region IS the entire frame - no edge was found anywhere in it."*
  Conclusive refusals (no mask, a speck) deliberately carry NO evidence string.
* [x] **B1's other half — the classifier — was attempted and FAILED. Do not
  re-attempt these six.** The plan asked for positive evidence that a book was
  found. Six candidate signals were measured on all 21 fixtures and **every one
  puts a pale capture inside the range of `de_01`/`de_02`**, which abstain
  through the same gate and are legitimately near-tight (overshoot of the
  labelled book 1.26×/1.14×, against 1.59×/2.30× for the pale pair): component ÷
  emit-box area (0.39/0.32 vs 0.59/0.81 — *inverted*), component growth on
  close, component fills its own bbox, component coverage of the frame ring,
  emit ÷ search box, component ÷ raw mask area. The reason is structural: **on a
  tight scan the book really does reach the frame border, so "the box is the
  frame" is the correct answer and the failure's answer at once.** Separating
  them needs the question none of these ask — *is there a background at all?* —
  i.e. **A10's precondition is not just a nice pairing with B1, it is the only
  known route to B1's stronger form.** Build it there; B1's reason string can
  then be upgraded to use its verdict.
* [x] **C2. The pinch cue declares itself inapplicable**, and Layer 2 is skipped
  when it does, so a meaningless number can never cut a page. **This plan's model
  of the failure was wrong and is corrected:** Otsu does *not* invert on a pale
  background — on `paleset_02` the sofa still reads dark (8.9 % of pixels outside
  the labelled book pass as bright). The profile is pinned at full height because
  scattered bright specks reach the top and bottom edges of most columns. The
  test is therefore mean column extent over the band ÷ image height: outline
  visible 0.798–0.840 (`paleset_01`, `de_01`, `de_02`, `zoomset_de_01`), pinned
  0.924–0.991 (the other 17, `paleset_02` at 0.977), gate at the midpoint
  **0.88**. Non-regression here is **measured, not structural** — the two
  pinch-deciding spreads stay applicable with room to spare, but
  `zoomset_de_01` would newly be refused the cue if ink ever stopped deciding
  there, which is the correct call (its search box is inside the book).
* [x] **B3. `corroborated` → `pinch_corroborated`** (its real scope), plus new
  `corroborated_by` (cues agreeing with the column that actually **shipped** —
  `[]` on `paleset_01`) and `band_x` (the search band in original coordinates).
* [x] **A dissent flag, reported only.** `other_cues_agree_elsewhere` fires when
  the two non-deciding cues agree with each other and not with the winner.
  Measured: **fires 5/21, and 4 of those are correct splits** — in every one of
  the four, both agreeing cues sit pinned at an *end of the search band*, which
  is exactly the artifact **C3** below is for. The warning therefore states its
  own hit rate and prints the band rather than smuggling C3 into a phase that
  promised no accuracy change.

---

## 5. Phase 2 — cheap cues, in the order the evidence supports

**Recommended order after the 2026-08-28 probes: A10 first** (it already solves
both failing frames and reuses existing GrabCut code), then A11's ranking idea
if A10's precondition proves hard to state, then A1'/A4 as fallbacks.

### Already closed by measurement this session — do not re-attempt

* **Retuning `val_min` (brightness).** Swept 0.55 down to 0.35 on both failing
  captures: the emit box does not move at all (page_001 stays 0.918, page_002
  stays 1.0). The brightness axis carries no signal here. An *adaptive*
  brightness threshold is equally dead — page and sofa are 0.01 apart, so no
  per-image cutoff on V separates them either.
* **Retuning `sat_max` (saturation) globally.** Saturation *is* the
  discriminating axis: dropping `sat_max` to 0.12 flips both captures from
  abstain to a real crop (0.70 and 0.63 of frame). But measured against the
  suite it is a catastrophe — **`sat_max` 0.18 gives 17/19 and 42.1 % clipping;
  `sat_max` 0.12 gives 12/19 and 100 % clipping** (zoomset_en_01 loses its
  entire labelled book). One global saturation constant cannot serve both
  corpora.

That negative is the most useful thing this scouting produced: **the fix cannot
be a threshold retune.** It has to be per-image adaptivity, a different cue, or
escalation.

### A10. Background-first: model the surface, not the page (owner's proposal, 2026-08-28)

**The idea.** Every method above asks *"what does a page look like?"* — bright,
colourless, covered in text. Each of those assumptions dies on a real book: a
full-page photograph is neither bright nor colourless, a coloured border is not
paper-white, and a plate-only page has no text. Turn the question around and ask
*"what does the surface look like?"* The sofa or desk is **relatively
homogeneous and touches the frame border**, so it can be modelled without
knowing anything about books at all — the book is then simply the large thing
that is *not* the surface, and it is roughly rectangular.

This is assumption-light in exactly the place the current detector is
assumption-heavy, and it is **the recommended first experiment of Phase 2.**

**It is also nearly free to build.** `grabcut_box` already declares the frame
border to be background (`GC_BGD`); what it gets wrong is the *foreground* seed,
which comes from the broken paper mask. Replacing that seed with "everything far
from the border's colour model" is a change to code that already exists.

**MEASURED PROPERLY 2026-08-28 — read the verdict at the end of this section
before building anything here.** The scouting numbers immediately below are the
original throwaway probe's and are kept because they are what motivated the work;
the faithful re-run and its verdict follow.

**Probed on 2026-08-28** (throwaway prototype: Lab colour, a Gaussian model
fitted to a 2 % border strip, Mahalanobis distance, Otsu, largest blob):

| frame | detector today | background-first | |
|---|---|---|---|
| real page_001 | 0.918 of frame (abstains) | **0.561** | would crop |
| real page_002 | 1.000 of frame (abstains) | **0.438** | would crop, and the box is visually tight and correct |

So it **solves the case that motivated this plan**, on the first try, with no
tuning. But run across the existing fixtures it produces nonsense:

| fixture | box area | |
|---|---|---|
| en_coins_01 / zoomset_en_01 / de_02 / zoomset_de_02 | 0.054 - 0.094 | absurd; already caught by the `min_area_frac` 0.10 guard |
| it_geo_01 | 0.387 | **would crop wrongly — not caught** |
| de_01 | 0.683 | **would crop wrongly — not caught** |
| bg_01 | 0.705 | **would crop wrongly — not caught** |

**Why, and this is the load-bearing insight:** on a tightly-framed spread *the
frame border IS the page*. The background model gets fitted to paper, and the
largest "unlike the border" blob becomes a figure **inside** the book. The method
does not degrade gracefully; it inverts.

**The sharpest possible test of that precondition is already in the testset, for
free:** `en_coins_03` is the *same two pages* as `paleset_01`/`paleset_02`, shot
flat and tightly framed. Same content, opposite background condition — the
precondition must **fire** on the paleset pair and **abstain** on `en_coins_03`,
and if it cannot tell those three frames apart it is not a precondition. Check it
there first; it is cheaper than the whole fixture sweep and it isolates exactly
the failure mode above (border-is-the-page).

**So the deliverable is not the detector, it is the precondition.** Phase 1
raised the stakes on this: it measured six cheap ways to ask "was a book actually
found?" and none works, precisely because none asks whether there is a
background. So this precondition is now the only known route to an honest answer
at the abstain gate too — B1's reason string should be upgraded to quote its
verdict once it exists. Before trusting a background-first box, test *whether
there is a background at all*:

* is the border strip homogeneous (low variance within it)?
* is the frame interior actually different from it (a real distance gap, not
  Otsu splitting noise)?
* does the resulting blob avoid touching the frame edge?

If the answer is no, abstain — which is already the correct, byte-identical
behaviour for all 13 flat fixtures. Note this pairs perfectly with Phase 1's B1:
"there is no background, so I cannot locate the book" is exactly the honest
reason string that item is about.

**Can we detect borders directly?** Measured on the pale-sofa frame, gradient
magnitude at 900 px width: grayscale median 24.1 / p99 242.3, saturation 14.8 /
159.5, and the Lab colour-opponent channels are nearly flat (a: 1.4 / 8.0,
b: 3.2 / 17.3). There *is* a usable step in luminance and saturation, so a
contour method is not hopeless here — but the edge is not dramatically stronger
than the page's own internal texture, so bare Canny plus "largest quadrilateral"
would be fragile. The literature's answer to precisely this is below.

**Known limit to record:** a background-first box encloses the *whole physical
book*, including the fanned block of closed pages beside the spread.
`testset/gt/book_box.json` deliberately excludes that block. Harmless for the
search box, wrong for the emit box, so the two-box split still matters.

#### A10 — VERDICT, measured 2026-08-28 (RESULTS; `docs/data/a10_background_first_20260828.json`)

**Not shipped. The detector half-works; the precondition does not exist.** Full
row in `docs/RESULTS.md`; the essentials, so nobody re-derives them:

* **It reproduces, with two traps.** Normalising the Mahalanobis map by its own
  *max* lets one outlier pixel squash the bulk of the distribution into ~20 of
  256 levels; and adding morphology (not in the recipe above) moved `paleset_02`
  from 0.452 to 0.845. Percentile-clip, no morphology.
* **It fixes `paleset_02` outright** — box (312,498)-(3222,2436) against a
  labelled (340,495)-(3150,2430), gutter 1752 against 1778 ±200, **0.00 %**
  clipping. The row would go green.
* **It wrecks `paleset_01`** — gutter 3045 against 1680, and it **clips 20.85 %
  of the labelled book**. *Named mechanism:* that book **runs off the left frame
  edge**, so the 2 % border strip the model is fitted to contains page pixels;
  paper then reads as background, the left page drops out, and the blob leaks
  along a cable to the bottom-right corner. When the border is not background
  this method does not degrade, **it inverts**.
* **Half the precondition IS solved, and cheaply:** *how many frame sides the
  candidate blob touches.* `paleset_01` = 2, `paleset_02` = 0, `zoomset_de_01`
  and `zoomset_en_01` = 1, the other seventeen = 0. Two or more sides means the
  candidate is not enclosed or the model was fitted to the book. Keep this.
* **The other half — "is there a background at all" — has no cheap answer.**
  Eight families measured across all 21: paper-mask statistics (six, closed in
  Phase 1); Mahalanobis scalars; absolute ring homogeneity in Lab σ
  (`paleset_02` 19.52 against `it_geo_06` **19.81** — a 0.29 gap on a 50-unit
  scale); blob compactness (0.91 against `bg_01` 0.87, and *inverted* at 0.92
  against 0.94 on the connectivity variant); connectivity (ring coverage 0.995
  inside 0.849–1.000; enclosure degenerate at 1.000 for all 21); a text-ink veto
  (fabric texture reads as glyphs — 63.75 % of "ink" outside a box that clips
  0.00 %); brightness polarity (ΔL 72 against `bg_01/02/03` at 71/71/69); and
  border texture (Sobel median 69.87 against `bg_01` 71.34 — the weave is
  indistinguishable from page texture, which **A3/A6 below predicted and is now
  measured**). **Do not re-attempt these eight.**
* **Why it is structural.** On a tightly framed scan the border *is* the page, so
  this method finds the **printed area** instead of the book — and a printed area
  is also large, also rectangular, also compact, also bordered by something
  darker, and at the ring also textured. Every property that makes a book look
  like a book is shared by the thing this method finds when it inverts.
* **Beware `ring_p90`-style measures.** Mahalanobis of the ring under the ring's
  *own* model is self-normalising and reads 2.14–3.11 on every frame. It looks
  like a homogeneity measure; it is not one.
* **What an unguarded fallback would cost.** `min_area_frac` 0.10 refuses
  `en_coins_01/02/03` for free — **including this section's nominated "sharpest
  test" `en_coins_03`, which therefore discriminates nothing** — and
  `abstain_area_frac` 0.83 refuses `bg_02`/`bg_03`/`it_geo_04`. **Seven of the 13
  flat fixtures survive both guards** and would lose 17.6 %, 46.0 %, 92.5 %,
  57.7 %, 39.1 %, 39.6 % and 69.6 % of their text-like ink (`bg_01`,
  `it_geo_01/02/03/05/06/07`). **None of the seven has a labelled book box, so
  `split_eval`'s clipping column is blank for all of them** — an unguarded A10
  could destroy page content on seven fixtures and still print a green table.
  Check per row, never infer safety from the harness here.
* **"Bank more pale fixtures" is not available.** The 31 archived
  pale-background files are 11 frames of `page_001` (lap), 18 of `page_002`
  (sofa) and 2 more of the lap scene — **two scenes, one session, one book**, not
  31 examples. Question 1 has exactly **one** usable positive. The route to
  n > 1 is **new photographs of new surfaces**.
* **Cost is not the obstacle:** 23 ms on a 4080×3060 frame against `find_book`'s
  own 318 ms, and it would run only where the paper route already abstained.

### A11. Contour hypotheses ranked by contrast (from the literature)

The published state of the art for this exact problem — locating a document in a
phone photo against an unhelpful background — does not pick one boundary. It
**generates many candidate borders and then ranks them by a contrast criterion**:
how different the region *just inside* a candidate edge is from the region *just
outside* it. Tropin et al., *Approach for Document Detection by Contours and
Contrasts* (arXiv:2008.02615), report ~40 % fewer alternative-ordering errors and
~10 % fewer detection errors than contour-only methods, and name occlusion,
complex backgrounds and blur as what contour-only approaches fail on. The same
group's *Advanced Hough-based method for on-device document localization*
combines edge and colour features under a projective model and is built to run
on a phone. Benchmarks in this literature are MIDV-500 and SmartDoc.

Two things transfer directly:

1. **Rank, do not threshold.** Our failure is a thresholding failure — one global
   constant asked to serve two corpora. A scoring function over candidate
   rectangles ("strong edge support along the border, homogeneous outside,
   inhomogeneous inside") is a global fit that tolerates a weak or broken edge,
   and it subsumes A10 as one candidate generator among several.
2. **The rectangle prior is strong evidence and we are not using it at all.**
   Today's mask is per-pixel and shape-blind. A book is a quadrilateral; scoring
   candidate quadrilaterals uses that fact.

This is more work than A10 and should follow it, but it is the direction that
ends the whack-a-mole. Older work in the same vein — page-frame detection for
border-noise removal, and scanning inward from the image border for the first
statistically different pixels — supports the same "start from the outside"
instinct.

### A1'. Per-image adaptive saturation (most promising cheap lever)

The sweep shows the *right* threshold exists for each image — it simply is not
constant (~0.12 for the sofa frames, ~0.25 for the fixtures). So derive it per
image instead of fixing it: Otsu, or a valley-seek, on the S channel, perhaps
restricted to reasonably bright pixels. Keeps the whole two-box architecture.
Risk: on a tightly-framed spread the S histogram is nearly unimodal, so it must
degrade gracefully to today's behaviour rather than inventing a split.

### A4. Locate the book by *ink*, not by paper

The pages are the part of the frame with text on them; a sofa has none. Run the
existing adaptive threshold, aggregate ink density on a coarse grid, and take
the largest connected region of text-bearing cells as the book. Reuses
machinery Stage 02 already has, and aims at the actual discriminator.
Weaknesses to guard: a figure-only region has no ink, and patterned fabric can
look inky — so filter for *text-like* ink (stroke width, component size), not
any ink.

### A3/A6. Texture and detail energy

A page is smooth at large scale and busy at text scale; upholstery is smooth at
both. A multi-scale local-variance or gradient-energy map would separate them
without referencing colour at all. Slightly more work than A4, aimed at the
same physical fact.

### A2. Illumination normalization first, then today's rule

Divide by a heavily blurred copy, or CLAHE the V channel, so "bright" becomes
relative to the neighbourhood. **Explicitly not foreclosed** by the negative
CLAHE spike in the project memory: that measured *OCR recall on the gutter
band*, a different question, and its own leftover lead was named as "global
illumination normalization". Ranked below A1' because the V axis carries so
little signal here.

### C1/C3. Cascade work — deliberately last

Do this **after** the crop works, because a correct crop may make it moot.

* **C1. Consensus override.** When pinch and shadow agree with each other and
  the ink answer is far away *and* the ink call is marginal, do not let ink win
  outright. Must be a narrow tie-break, not a reordering — Layer 1 winning
  outright is exactly what guarantees the 13 flat non-regressions.
* **C3. Band-edge guard.** A minimum pinned near the edge of the `[0.30, 0.70]`
  search band is usually the band clipping the profile, not a real valley.
  **Phase 1 supplied independent evidence that this artifact is real and
  common:** the new dissent flag fires on 5 of 21 fixtures and 4 of those are
  *correct* splits, and in all four both non-deciding cues are pinned at a band
  end (`en_coins_01/02/03` pinch+shadow at 2744-2799 against a band ending at
  2800; `de_01` ink 2703 + shadow 2790). A band-edge guard cleans those up as a
  side effect.
  Measured on the shipped path: the bad call sits **0.070** of the band from the
  edge, and the closest *ink-deciding* fixture is zoomset_en_02 at **0.225** — a
  clean gap, candidate gate ~0.15. **Scope it to the cue that decides:** de_01's
  ink argmin is at 0.061, closer to the edge than the bad call, but de_01
  resolves by pinch, so a guard on the deciding cue leaves it untouched. A guard
  applied to the ink argmin regardless of who decides would break de_01.
* Also check whether `[0.30, 0.70]` of an *uncropped* frame can even contain the
  true gutter when 40 % of that frame is room.

---

## 6. Phase 3 — escalation, if no cheap cue separates

| option | what it is | cost | ceiling |
|---|---|---|---|
| **A9. The phone supplies the box** | user drags a rectangle, or the app sends a rough crop | low: UI work, no new CV | **guaranteed** |
| **A8. Multi-hypothesis + arbitration** | generate boxes from several cues, pick by downstream evidence | high — multiplies 258-1375 ms per candidate | unknown |
| **A7. Learned segmentation** | pretrained salient-object / document segmentation | GPU; lazy-load + VRAM release per the repo rule | high, unmeasured |
| **A5. Edge/quad detection** | Hough/LSD line segments, fit the page quadrilateral | medium | poor here — low page/sofa contrast is the whole problem |

**A9 is first-class, not a footnote.** It is the only option with a guaranteed
ceiling, it fits the manual-capture flow the owner chose this session, and it
pairs naturally with Phase 1: once the detector can say *"I did not find the
book"* honestly, the app can ask instead of guessing.

**A8 carries a base-rate warning.** Two neighbouring results are already closed:
anchor choice by cheap criteria ("do not re-attempt") and per-page frame
selection (measured null; best cheap criterion 11/15 against chance 6.8).
Choosing a *box* by downstream evidence is not the same question, but in this
repo cheap criteria have been coin flips. Weigh that, do not rediscover it.

---

## 7. Acceptance criteria

1. `python -m tools.split_eval` keeps all **19 pre-existing** spreads correct
   (the run reads 19/21 today because of the two banked failures; a fix takes it
   to 21/21, and any drop below 19-of-the-old-19 is a regression).
2. **Worst clipping stays 0.0 % on the 19 pre-existing spreads** — losing page
   content is the one failure this stage treats as real. **On the two `paleset`
   rows the exact-zero reading is a trap, and Phase 0 measured why:** the metric
   divides by the labelled box area, so on `paleset_01` one pixel off the left or
   right edge costs 0.033 % (0.042 % top/bottom) and on `paleset_02` 0.036 %
   (0.052 %) — a 20-px inset all round prints ~3 % and shouts PAGE CONTENT LOST.
   Worse, `paleset_01`'s book **runs off the left edge of its frame** (the page
   reaches x=0 around y=2620-2660), so its label starts at x=0 and *any* crop
   starting further right clips it — 25 px in is already 1.4 %. The label was not
   softened by inventing an inset, because the book really does leave the frame
   there. So on those two rows: if a clip is under ~2 % and lands in an edge band,
   look at the band. **Blank outer margin with no ink = label precision, and the
   result is the number plus that adjudication, written down. Any clip that
   removes ink is a real failure at any size.** The older six rows never hit this
   because their emitted crops are bigger than their labels.
3. Both new pale-background fixtures split within tolerance (`paleset_01` 1680,
   `paleset_02` 1778, tol 200 each), **or** the detector abstains for a
   correctly-stated reason (Phase 1 is what makes that outcome honest, and
   therefore acceptable — but note the suite stays red either way, since the
   rows grade the split, not the excuse).
4. `find_book` cost stays inside a stated budget; if a phase multiplies it, the
   multiplier is written down.
5. A dated row in `docs/RESULTS.md` with machine-readable inputs and outputs
   under `docs/data/`, per the house rule.

**Stated refuse-outcome:** if no cheap cue separates page from background on
this corpus, that is a **measured negative to record and escalate to A9/A7** —
not a number to force. This repo has shipped negatives before (per-page frame
selection, the CLAHE spike, loosening the caption proximity rule), and doing so
again is a valid end state for Phase 2.
