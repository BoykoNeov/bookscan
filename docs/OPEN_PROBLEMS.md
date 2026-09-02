# Open problems — the register

What is still unsolved, ranked by what it costs the deliverable (a re-typeset
PDF of the owner's book that reads correctly), with the **next experiment** for
each and the **precondition** that gates it. This is the file to read before
choosing what to work on. `STATUS.md` has the story behind each entry;
`RESULTS.md` has the numbers; `plans/README.md` says which plan is live.

Conventions used below:

- **REFUSED** — measured and found not to work; do not re-attempt without new
  data or a different mechanism, and read the pointer first.
- **POSTPONED** — an owner decision, stated as a question, with the options.
- **BLOCKED ON DATA** — the idea is fine and the corpus cannot tell; the fixture
  needed is named.
- **n =** counts *scenes* (books × surfaces × lighting), not frames. Thirty-one
  photographs of one sofa are n = 1.

---

## P1. The book crop on a pale or cluttered surface (Stage 02) — costs the most

**Symptom.** The owner's book was photographed on a pale sofa; ten of the
fifteen defects they listed in the rendered PDF trace to the first four spreads
having the wrong crop: the dewarp ran on a frame containing fabric, so the text
*on the paper* (the route tables, the most valuable data in the book) came out
as junk. Not a text-filter problem (measured: 0 of 150 text blocks sit outside
the paper band), not a dictionary problem (the zero-dictionary-word blocks are
the route tables). It is the crop.

**Three distinct failure modes, and they need different fixes:**

| mode | what the detector does | example | status |
|---|---|---|---|
| (a) abstains | the paper mask merges book and background, area gate refuses | `paleset_01/02`, owner's spreads 1 and 3 | `vlm_box` aims the spine search (shipped, 21/21 with `--vlm`), nothing is cut |
| (b) unstable | GrabCut's random init decides between abstain and a 12 % clip | raw `de_02` (RESULTS 2026-09-02) | **caught 2026-09-02**: seeded draws must agree within the emit pad, else abstain |
| (c) confidently wrong, stable | every draw agrees on a box that clips content | raw `de_02`'s top edge (header band, 4.6 %); owner's spreads 2 and 4 (full-frame height) | **open** — no cue found; see below |

**What is REFUSED (do not re-attempt):**
- Retuning the HSV paper thresholds (plan §5; the pale surface *is* paper-coloured).
- Six cheap "was a book found?" statistics at the area gate (module docstring
  table): each puts a pale capture inside the range of a legitimately tight scan.
- A10 background-first (RESULTS 2026-08-28): fixes `paleset_02`, wrecks
  `paleset_01` (clips 20.85 %) because that book runs off the frame edge.
- Eight cue families for "is there a background at all" — structural failure:
  on a tight scan the printed area is also large, rectangular, compact and
  darker-bordered.
- Retuning `search_pad` (n = 1, recorded dead zone: covers −3.6 %, not −8.4 %).

**POSTPONED (owner's call, 2026-08-29):** may a *model's* box ever cut, and what
should the clipping bar grade? Three live options: an inward-only guard
(union the model box with the detector's paper mask; no metric change), grade
*content* rather than ink (undefined in the harness today — an ink-only bar
would pass a trimmed photograph edge), or keep `worst_clip == 0.0` and accept
that a model box cannot pass it. Nothing shipped depends on the answer.

**BLOCKED ON DATA:** every automatic route for (a) and (c) needs a precondition
calibrated against *negatives* — tightly framed handheld spreads on which the
rule must NOT fire — and the corpus has two pale scenes and no such negatives.
`plans/pale-background-fixture-shoot.md` is the shot list (16–24 spreads).

**Next experiments, cheapest first:**
1. **Owner, five minutes:** re-run `tools/split_eval` after the 2026-09-02
   seeding change and read `gc_jitter` on `de_02`'s real anchor. Expected 19/21,
   0.0 %. Then re-run Stage 02 on the sofa job and read `gc_jitter` on spreads
   2 and 4: if they jitter, mode (c) was mode (b) all along and is now handled.
2. **Owner, five minutes:** copy `jobs/orient_fix_de*/page_001/01_fuse/anchor.png`
   into `testset/` as PNG and point `gutter.json`'s `anchor` at them, as the
   zoomset rows already do — the guard then runs from a clean clone.
3. **Build, opt-in, off by default:** the inward-only guard for the model box
   (option 1 of the postponed decision) behind `vlm_box.cut: false`, measured on
   `split_eval --vlm` for clipping. It needs no owner decision to *exist*; it
   needs one to be turned on.
4. **A cue for mode (c) that is not a threshold:** a box whose top or bottom edge
   is the frame edge while its side edges are well inside is geometrically
   suspect on a spread (books are wider than tall). Not measured. Before
   building it, count how many of the 19 correct rows have that shape — if any
   do, it is dead.
5. Shoot the fixtures. Nothing above replaces this.

---

## P2. Text panels that render as photographs — 14 blocks, 12 % of the words by count

**What it is.** The English/Italian translation panels and hut-information
boxes. Stage 05 reads them as noise (median confidence 19 against a floor of
70), `unreadable_panel` correctly turns them into pictures. Only 4 of the
original 18 were a typing error (fixed by `text_panel`, then turned OFF because
the render was worse than the photograph — multi-column tables collapsed to one
paragraph; `table_grid` now fixes the rows).

**REFUSED:** re-reading them with the other language's OCR (2026-08-31) —
different garbage, not better. The panels are unreadable because of the
**pixels**, and on the owner's book the pixels are bad because of **P1**.

**Next experiment:** none independent of P1. After the crop is right on spreads
1–4, re-run Stage 05 and count how many of the 14 clear the `unreadable_panel`
floor. If they still do not, the question becomes capture (a close-up framed on
the panel), which is P5.

---

## P3. Pictures split in two — 45 pairs in the owner's book

35 stacked figure pairs with nothing between them (one picture, cut by the
layout detector) and 10 split by a caption printed on the photograph.

**REFUSED:** a whiteness-of-the-gap rule — merges 20 correctly and glues orange
text sidebars onto photographs on 5, visible by eye.

**Next build (the plan's top item now that panorama is parked):** a
**continuity** test — do the two halves' pixels continue across the gap? The
correlation machinery exists in `figure_hires` (`min_ncc` 0.60, measured:
wrong sources 0.51–0.52, right ones 0.63+). Measure it as a census over the
owner's job *before* it ships (a `tools/` script that lists every stacked pair
with its continuity score, adjudicated by eye on the overlays), then gate it
the way `figure_surface` is gated: a merge deletes nothing, it only re-groups,
so the bar is zero wrong merges on the 5 sidebar cases. **Precondition:** the
owner's assembled job; the testset has no split-figure fixture (`it_geo_06` has
four figures sharing a column, which is the *opposite* trap — do not merge those).

---

## P4. Panorama: painting close-ups onto the page — PARKED, not refused

**Where it stands.** Phase 0 (placement): flattening the close-up too is REFUSED;
raw close-up onto the dewarped page then `mesh_align` over its footprint passes
at 1.39 px median — but 42 % of placed close-ups have a worst-twentieth of 30 px
or more, a word width. Phase 2 (does it read better): **no verdict** — 5 of 40
sources clear the 10 px bar and 4 of those land on one map. The one text subpage
that did paint tied on confident words and won on the text diff (two hyphenated
words rejoined).

**What Phase 1 must be, if built:** per-**region** admission (the blocker is
the tail *inside* a source, not which sources), word-aligned seams, admission
by the worst of three seeded RANSAC draws. Not "paint every registered source".

**BLOCKED ON DATA:** a data famine, not a refusal. The sweep capture mode on
the phone (M7, 2026-08-31, unverified on a device) exists to feed it. **Next
experiment:** one spread of dense text, swept at 2–3×, through Phase 2 —
before any Phase 1 code. Confident-word count AND a text diff, never the count
alone (four times now a confidence number rose while the text got worse).

**REFUSED on the way (do not re-attempt):** lowering Stage 01's `min_inliers`
below 8; reading each close-up separately and merging words (a wash at 1.3×
page framing); enlarging the anchor so close-ups land at their own size (the
text doubles — a homography cannot express a cylinder); the per-block
alternative (a paragraph is not locally unique, it matches the wrong paragraph).

---

## P5. Capture is the cheapest lever, and it is unmeasured on a phone

Three independent measurements ended at "the photograph was framed wrong": the
close-ups that carry no extra resolution (median 1.30× on the page, not on the
block), the 103 figures with no candidate source, and the book on the sofa.

**Open:** auto-capture measured at four stills per hover delivered one on a real
spread (demoted to opt-in); the sweep gate is fitted to a hold and a re-frame,
never to a sweep; the motion signal is a rate control, not an overlap guarantee.
**Next experiment:** record one real sweep log off `SweepScreen` (it writes the
CSV) and replay it through `tools/calibrate_sweep`. Until then no threshold in
`SweepGate` is a measurement.

---

## P6. Tables — the grid is right, the cells are not

`table_grid` grids 4 of 7 TABLE blocks (rows from a `psm 6` re-read as an oracle,
text from the page pass). **Honest limit, pre-registered:** `2,2 → 22`,
`4½ → 4Y`, `170 → I70` survive a perfect grid, so whether the two route tables
beat their photographs is still the owner's call by eye.

**Known miss:** `it_geo_07` #5, a real 3-column chart read well, refused because
the page pass splits a word across the printed rule. Two column fixes swept
and both change nothing. **Next build:** take the *columns* from the oracle read
too, not only the rows — not attempted. **REFUSED:** working out rows from
geometry (the stagger aliases — the wrong answer fits better; deskewing does not
help); `deu` for the numeric cells.

---

## P7. Figure upgrades — one reproducible discrepancy, now diagnosable

An offline sweep upgrades 25 figures and the shipped run 24; one block upgrades
in isolation and is refused in the batch. Two candidate causes, **both made
visible 2026-09-02**: a frame decode returning None under memory pressure (now
listed as `frame_decode_failures` in `document.meta.json`) and RANSAC drawing
from the unseeded global RNG (now seeded). **Next experiment:** re-run assemble
on the owner's book twice; identical upgrade lists plus an empty
`frame_decode_failures` closes it. **REFUSED:** lowering `min_coverage` below
0.90 (an under-covered figure needs another photograph); `min_ncc` below 0.60.
Verify pictures by checkerboard, never side by side.

---

## P8. Multilingual pages — a label ships, everything else is unmeasured

`Block.language` (Hunspell vote) has exactly one consumer, Stage 08's
de-hyphenation, graded on the render (38 broken words → 26, 0 newly broken).
**Deliberately not wired:** the EasyOCR disagreement gate and Stage 06's
threshold also key on a lexicon. **REFUSED:** a page-level `deu+ita` string
(loses umlauts while raising confidence — confident-word counts are not
comparable across language sets). **Next experiment:** wire the EasyOCR gate to
the block label *behind a flag*, grade on a text diff over the Bulgarian
fixtures, the only ones where that gate runs.

---

## P9. Reproducibility debts (cheap, and each one has bitten)

- **RNG.** `cv::theRNG()` is now seeded before GrabCut (multi-draw) and before
  the two `findHomography` calls; the *gates* on those homographies are still
  single-draw. Any new call into OpenCV's RANSAC, k-means, or GrabCut must seed
  or draw several times. Never threshold one draw.
- **Anchors outside the repo.** `de_01`/`de_02` grade gitignored pixels (P1,
  experiment 2).
- **Cross-arm comparisons.** `layout_order_eval` with and without `--no-stage05`
  are different quantities; the tau column especially. Never compare across.
- **The clipping metric divides by the label area**, so a 20 px label error
  reads as 3 % on the paleset rows. Any clip under ~2 % in an edge band is
  adjudicated by looking at the band, and the adjudication is written down.

---

## P10. Planned, not started

- **PDF import** (`plans/pdf-import.md`): fills `00_ingest/`, the PDF's text
  layer is a second opinion through `second_opinion.py`, never the text source.
- **Multi-view curvature** (`plans/multiview-curvature.md`): Phase 0 passed at
  N = 3, Phase 1 pre-registered, nothing in the pipeline reads it.
- **Caption↔figure grouping review in the editor** (ranked above exact order by
  the owner): the linear-order review half exists; the grouping half does not.

---

## How to add to this file

An entry has: the symptom in the deliverable, the modes if there are several,
what is REFUSED with the RESULTS pointer, what is POSTPONED and on whom, what is
BLOCKED ON DATA and which fixture, and the next experiment with its cost. When
an experiment runs, the entry is edited and a RESULTS row is appended — the
register is the one document here that is *rewritten* rather than appended.
