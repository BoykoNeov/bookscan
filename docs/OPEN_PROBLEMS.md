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
| (b) unstable | GrabCut's random init decides between abstain and a 12 % clip | raw `de_02` (RESULTS 2026-09-02); the real anchor confirmed 2026-09-24, draws disagree by 12.9 % | **caught 2026-09-02**: seeded draws must agree within the emit pad, else abstain |
| (c) confidently wrong, stable (also on a dark chair: spread 21, two edges) | every draw agrees on a wrong box | raw `de_02`'s top edge (header band, 4.6 %, clips content); owner's spreads 2 and 4: identical box on 8 of 8 seeds (RESULTS 2026-09-24), starting at the frame's left edge at full height, so sofa is kept on **three** sides; the right edge sits in open sofa 150–350 px past the book, set by something not yet established. The detector's own paper mask runs to the left, top and bottom frame edges — it reads the sofa as paper there — and GrabCut, seeded from it, agrees. Spread 3 has the same GrabCut box and escaped only because its search box is the whole frame, so the area gate fired | **open** — confirmed 2026-09-24 that seeding does not reach it; no cue found; see below |

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
1. **DONE 2026-09-24** (RESULTS 2026-09-24): `split_eval` 19/21, 0.0 %; the
   real `de_02` anchor is unstable (12.9 %) and abstains; sofa spreads 2 and 4
   do **not** jitter (0.0 over 8 seeds). Mode (c) is real. **The fix available
   today for those two spreads is a hand-drawn box** (`tools/book_box_editor`).
2. **DONE 2026-09-24**, with no new file: the committed `de_01.jpg`/`de_02.jpg`
   are pixel-identical to those anchors, so both rows now name them. Verified
   from a clean worktree with no `jobs/`: 21 of 21 rows graded, 19/21, 0.0 %.
3. **REFUSED 2026-09-24 as written** (RESULTS 2026-09-24, offline,
   pre-registered): "model box ∪ paper mask" is ≥ 83 % of the frame or the same
   three-sided sofa crop on every target frame (both pale rows, sofa spreads
   1–4), because the mask is what merged with the surface; and it leaves
   `de_02`'s 1.89 % clip exactly where it was. No code. Do not replace it on
   these frames with a per-edge surface test (dead cue family) or a wider
   cutting pad (a pad retune by another name). A model box that cuts now waits
   on the postponed decision above and on the fixture shoot. For the record, the
   model's box on spread 4 (asked 2026-09-24 for the first time) is right and
   tight.
4. **DONE 2026-09-24 — the "three frame edges" cue** (RESULTS 2026-09-24,
   pre-registered). Passes all gates, fires on spreads 2 and 4 only, 0 false
   fires; shipped as `book_crop.three_edge_abstain`, **off**. Why off: every
   frame that could false-fire (a book really filling three sides) abstains at
   the area gate first, so the cue has never met one; the positives are one
   scene. It is not a fix either — it turns a wrong crop into no crop. With
   experiment 3 refused there is nothing yet for the abstain to hand the frame
   to except the model's search window and a hand-drawn box; turning it on waits
   for a model box that may cut (the owner's decision) and for tight frames from
   the fixture shoot that reach it. **New, found on the way:** spread 21 (dark chair) is a wrong
   crop touching **two** edges (a cushion kept on the left) — mode (c) is not
   only a pale-surface failure, and this cue cannot see it. No content lost.
5. Shoot the fixtures. Nothing above replaces this. The shot list should now
   include tight frames where the book fills three sides (the cue's missing
   negatives).

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

## P3. Pictures split in two — 21 stacked splits found; the operator can now rejoin them, no automatic merge survives

**Size, re-counted 2026-09-24** (RESULTS 2026-09-24, census). The earlier "45
pairs" had no committed method and does not reproduce. The pre-registered rule
— *vertical* stacks only, gap ≤ 5 % of page height — finds 52 pairs; by eye
**21 are one picture cut in two**, which are **13 distinct pictures** (7 of the
pairs are fragments of one map); 18 are two separate pictures, 10 are a picture
touching a text panel (hut-information boxes, icon sidebars, English-version
panels), 3 are sofa. None of the 21 has a higher-resolution figure asset, so a
merge loses no upgrade. The adjudicated set and the picture grouping are
committed (`data/figure_continuity_labels_20260924.json`,
`data/figure_split_vlm_groups_20260924.json`) and are reusable as a test bed —
but **both methods below have now been read against it**, so it can no longer
license a combination of them.

**REFUSED:**
- a whiteness-of-the-gap rule — glues text sidebars onto photographs;
- the **continuity statistic** (worst seam row, fraction of columns stepping
  past the pair's own 95th percentile) — catches 18 of 20 but wrongly merges 4
  separate pairs; loose detector boxes put the real boundary 6–9 px outside the
  band. **No threshold rescues it** (RESULTS 2026-09-24).
- the **local model asked twice** ("one picture or two?" on the crop, "does the
  picture continue across the arrowed line?" on a wider window; all four
  answers must agree) — restores 10 of 13 pictures and every control, but
  wrongly merges **10 of 34** separate pairs, **4 of them off the sofa**
  (RESULTS 2026-09-24). Two mechanisms:
  - it reads a hut photo plus its orange information panel as one captioned
    picture;
  - on a pair with a 21–24 px sliver, "ONE" describes the big block.

  The seam question barely discriminates (17 of 34 wrong alone). **Do not
  re-tune these prompts on these pairs.**

**Hypothesis, not a result:** the pixel rule's 4 wrong merges and the model's 4
are **disjoint**. Requiring both gives 16/21 pairs, 9/13 pictures and 0 of the
23 gated separate pairs on these labels, plus 2 on sofa pairs, which excluding
`is_surface` blocks would remove. The combination was chosen *after* seeing
the errors, so it needs pairs neither method was read off.

**SHIPPED 2026-09-24 — the operator's lever.** The editor has "Merge with the
picture below" (plus a picker for any picture on the page). The selected piece
keeps its id and takes the joined box, captions follow, nothing else is
renumbered, and the joined box is drawn before the click. A picture the joined
box overlaps is taken in by the same click and named on the button — the map's
big detector box lies across all its strips, so refusing would deadlock. Driven
through the real page over a copy of the owner's job
(`tools/figure_merge_check.py`, RESULTS 2026-09-24): **13 of 13 pictures
rejoined exactly in 15 clicks, 0 pieces taken in by mistake**, 143 → 123
rendered pictures. Known wart, now fixed by hand: on `page_023__right` a junk OCR block (#15)
ends up inside the map, gets painted out as a pale patch and still prints; the
button warns, and **Delete block** (below) removes it.

**Next experiment, ranked:**
1. **Suggest merges** as markers the operator accepts or dismisses, from the
   pixel ∧ model agreement. A flag is not a merge, so a wrong suggestion costs
   a click, not a picture. Worth building only if the owner finds 15 clicks
   per book too many — their call, not a measurement.

**Gap found while building the merge — CLOSED 2026-09-24:** the block inspector
now has a "not part of the book — do not print" checkbox on every picture and
every surface-flagged block. Unticking restores the block (and makes it
mergeable); ticking hides a picture the model missed. It is a hand edit
(`structure_edited`), so a re-assemble will not silently undo it.

**Junk-block wart — CLOSED 2026-09-24:** the editor has **Delete block**, a
reversible hide (`Block.deleted`; Restore puts it back). Stage 08 drops a deleted
block before pairing and masking, so on a copy of the owner's job deleting
`page_023__right` #15 removes its text and gives the merged map its own pixels
back (the patch had hidden "15A"; RESULTS 2026-09-24). Other map-lettering
blocks are the operator's to delete, one click each.
2. **The automatic merge**, only after 1: pre-register pixel ∧ model (and
   `is_surface` excluded) on a new population. That needs a second book with
   stacked figures, adjudicated by eye before either method runs. **Blocked on
   data.** The testset's other books hold about 17 stacked pairs over 7
   spreads (counted 2026-09-24, unlabelled). Of those, `it_geo_06`'s 3 are
   already this test's negative control, and `it_geo_07`'s 7 were used to
   develop the prompts; the four seen are separate diagrams. `tablegrid_e2e`
   *is* the owner's book. So the testset has too few real splits to grade
   recall, and some of its pairs are already contaminated.

**Precondition:** none for 1. For 2, a second scanned book.

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
The step-by-step session (install, shoot, sweep log, pre-registration, what
each outcome licenses) is `plans/sweep-to-panorama-handoff.md`, written
2026-09-24; it needs the owner with the phone.

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
and both change nothing. **Columns from the oracle read: REFUSED 2026-09-24**
(pre-registered): the re-read bridges the same gutter (still 1 column), and it
invents a 2 × 6 grid on `page_003__right` #23, which must abstain. No next build
is known that reaches this block. **REFUSED:** working out rows from
geometry (the stagger aliases — the wrong answer fits better; deskewing does not
help); `deu` for the numeric cells.

---

## P7. Figure upgrades — the 24-vs-25 gap is explained; the upgrades themselves are in question

**Explained 2026-09-24:** the missing 25th (`page_022__left` #5) is an icon
panel that `unreadable_panel` turns into a picture after the hires pass ran —
not a decode failure, not the RANSAC draw (both runs identical to 2026-08-29).
A fix that searched converted panels was built and **reverted the same day**:
the only upgrade it added is softer than the page crop (RESULTS 2026-09-24).

**Open, and more important:** "higher resolution" is not "sharper". Of the 24
shipped upgrades, 6 measure softer than the page crop on two focus statistics,
and by eye the page crop shows more detail in **at least 4**; 2 are ambiguous
(crisper crop with sharpening halos). The gates measure scale, coverage,
inliers and NCC — nothing measures focus. The 18 others are not adjudicated.
**Next experiment:** pre-register a focus criterion (e.g. asset-at-crop-size
gradient ratio) on a population that was not read here — another book, or the
owner's own by-eye verdicts collected before any number — then decide whether
the upgrade must beat the crop to ship. Until then an upgrade can be a
downgrade, and the owner is the check.
**REFUSED (unchanged):** lowering `min_coverage` below 0.90; `min_ncc` below
0.60. Checkerboards check alignment only — they do not say which side is
sharper (misread once, 2026-09-24).

---

## P8. Multilingual pages — a label ships, everything else is unmeasured

`Block.language` (Hunspell vote) has exactly one consumer, Stage 08's
de-hyphenation, graded on the render (38 broken words → 26, 0 newly broken).
**Deliberately not wired:** the EasyOCR disagreement gate and Stage 06's
threshold also key on a lexicon. **REFUSED:** a page-level `deu+ita` string
(loses umlauts while raising confidence — confident-word counts are not
comparable across language sets). **Wiring the EasyOCR gate to the block label is BLOCKED ON DATA** (counted
2026-09-24): on the Bulgarian fixtures, the only ones where that gate runs, 0 of
33 blocks get a label other than the page's, so the change could alter nothing.
It needs a Bulgarian page carrying an English/other-language block.

---

## P9. Reproducibility debts (cheap, and each one has bitten)

- **RNG.** `cv::theRNG()` is now seeded before GrabCut (multi-draw) and before
  the two `findHomography` calls; the *gates* on those homographies are still
  single-draw. Any new call into OpenCV's RANSAC, k-means, or GrabCut must seed
  or draw several times. Never threshold one draw.
- **Anchors outside the repo — CLOSED 2026-09-24.** Every `split_eval` row now
  grades from `testset/`. Pixel identity rests on this machine's JPEG decoder
  (OpenCV 5.0.0), as the zoomset and paleset rows already did.
- **Cross-arm comparisons.** `layout_order_eval` with and without `--no-stage05`
  are different quantities; the tau column especially. Never compare across.
- **The clipping metric divides by the label area**, so a 20 px label error
  reads as 3 % on the paleset rows. Any clip under ~2 % in an edge band is
  adjudicated by looking at the band, and the adjudication is written down.

---

## P10. Planned, not started

- **PDF import** (`plans/pdf-import.md`): **Slices 1 and 2 built 2026-09-24** —
  the console's **Import PDF** button (or `python -m pipeline.pdf_import`) makes a
  job (one page folder per PDF page, all or nothing, pages made by software
  refused unless ticked), shows each page's spread/single guess with a per-page
  toggle first, and — from the console — queues every page at once with no
  restart. A CLI import made while the console is open still waits for its next
  start. A two-page cut of a real ABBYY scan ran through the console to the end
  of Stage 06; no whole real book has been imported yet.
  **Slice 3 BUILT 2026-09-24** on the owner's call, exactly as measured: where an
  imported PDF's hidden text disagrees with Tesseract one word for one word, the
  word is flagged (`Word.layer_disagree`; 48 real mistakes to 16 correct words in
  the test, almost all formulas and symbols). It never supplies text and never
  clears a flag (23 % of agreed, flagged words are wrong). English only, a layer
  of ≥ 150 words, alignment coverage ≥ 0.42 — the measured population. Its 0.75
  describes pages as Stage 03 flattens them TODAY: change Stage 03 for imports
  and about 30 of the 71 judged spots move, so the precision must be re-judged.
  **Open defect: Stage 03 cuts the edges of flat scans with thin margins** —
  UVDoc enlarges an already-flat page and pushes line starts off it (60 words at
  an edge on 24 test pages, 56 of them on two pages of one paper; a lower bound).
  **A white border before flattening is REFUSED** at 15 % and 25 % (RESULTS
  2026-09-24): it removes the edge cuts but makes UVDoc bend flat pages (D3 page 1
  lost 24 % of its readable words); do not retry border widths or colours.
  **Skipping flattening for imported pages passes the same gate** (edges 60 → 0,
  the other 22 pages +0.7 %, worst −1.6 %; the 24 cut-off words on D6 all read
  whole again) and is NOT shipped: it waits on
  the owner, and what it costs on a crooked scan is unmeasured (no crooked page
  in the test). If shipped: key it on `layout_origin == "pdf_import"` (already
  written by the importer, read by nothing yet), and re-judge the text-layer
  marker's sites on the new pages.
  Every imported single page carries Stage 00's "result is PORTRAIT" warning,
  which is noise there.
- **Multi-view curvature** (`plans/multiview-curvature.md`): Phase 0 passed at
  N = 3, Phase 1 pre-registered, nothing in the pipeline reads it.
- ~~Caption↔figure grouping review in the editor~~ — **BUILT** (stale line
  corrected 2026-09-24). Pairing, re-pairing and unpairing a caption, and a
  marker on every caption that will print alone, shipped earlier; 2026-09-24
  added a "check this pair" marker on pairs guessed from position (`geometry`,
  `sole_figure`) with a one-click Confirm — 8 on the owner's book, besides its
  12 unpaired captions. Number-keyed pairs are not marked. What is NOT built:
  pairing a caption to a picture on the other page of the spread (the schema
  can hold it; neither editor nor renderer does it).

---

## How to add to this file

An entry has: the symptom in the deliverable, the modes if there are several,
what is REFUSED with the RESULTS pointer, what is POSTPONED and on whom, what is
BLOCKED ON DATA and which fixture, and the next experiment with its cost. When
an experiment runs, the entry is edited and a RESULTS row is appended — the
register is the one document here that is *rewritten* rather than appended.
