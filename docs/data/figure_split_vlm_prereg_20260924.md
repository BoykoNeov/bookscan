# Pre-registration: is this one picture or two? — the local model, asked twice (P3)

Written 2026-09-24, **before any graded pair or control has been shown to the
model**. Tool: `tools/figure_split_vlm.py`. Nothing in `pipeline/` changes; this
decides whether a merge pass is worth building, after the pixel-continuity rule
was refused the same day (RESULTS 2026-09-24).

## Population and labels — unchanged from the census

- The census's pairs, found by the census's code
  (`tools/figure_continuity_census.population`): **52 owner pairs** in
  `jobs/20260829-084115-de3c20d3` (all classes: empty, between, surface,
  sofa_spread) plus **3 pairs** in `jobs/figtext_it_geo_06` (the named trap of
  separate stacked figures).
- Labels: `docs/data/figure_continuity_labels_20260924.json`, committed before
  the census scored anything and made with no model in the loop. **21 `one`**
  (all owner), **34 separate** (`two` / `sidebar` / `surface`, owner and
  it_geo_06).
- **Distinct pictures:** `docs/data/figure_split_vlm_groups_20260924.json`,
  committed with this file. The 21 `one` pairs are pieces of **13 pictures**;
  the map on `page_025__left` alone is 7 pairs. Grouping is by shared blocks,
  checked by eye on the census sheets.
- **Positive control:** the census's 37 singletons labelled `single` (each one
  a whole picture by eye), each asked as a pair — its top half and bottom half,
  cut at the **fixed midpoint** (no random draw), gap 0.

## The judge

`qwen3.6:27b` through Ollama, exactly `pipeline/figure_surface.py`'s call and
settings (`_ask`: temperature 0, `think: false`, `num_ctx` 4096, JPEG q90). Any
other model is a new pre-registration, not a second arm of this one.

**Question 1, the crop** — the page image cut to the rectangle around both
blocks, unmarked, shown at max side 768. Pixels inside that rectangle that
belong to neither block (text beside a narrower block) are **left in**.

> This image is a region cut from a page of a printed book.
> Does it show ONE single continuous picture (one photograph, one map or one
> drawing, possibly with a caption printed on it), or TWO OR MORE separate items
> placed one above the other (for example two different photographs, or a
> picture and a separate box or panel of text)?
> Answer with one word only: ONE or TWO.

**Question 2, the seam** — a window of the page around both blocks (padded
horizontally by max(40 px, 10 % of its width), vertically by max(150 px, 50 % of
its height), clipped to the page), placed between two white margins (each
max(48 px, 6 % of the window width)); in each margin a red arrow points inward
at the **seam row**, the middle of the gap between the upper block's bottom and
the lower block's top. Nothing is drawn on page pixels. Max side 1120.

> This is part of a page of a printed book. The two red arrows in the white
> margins point at one horizontal line across the page. Look along that line.
> Does one single picture (a photograph, map or drawing) CONTINUE across that
> line, with the same picture above and below it? Or is that line a BOUNDARY,
> where one item ends and a different item begins (a separate photograph, a box
> of text, a coloured panel, or blank paper)?
> Answer with one word only: CONTINUES or BOUNDARY.

The two ask different things: question 1 counts items, question 2 asks about the
cut line. Their errors should be less correlated than two wordings of "how many".

**Parsing.** An answer reads as the word only if exactly one of the two words
appears in it; anything else is unreadable (`?`).

**Draws.** Each question is asked **twice** on every pair and control, and
**both questions are asked on every pair** (no short-circuit), so each arm can be
reported alone. At temperature 0 the model has been deterministic (RESULTS
2026-08-29), so the second draw checks determinism only; it is not independent
evidence. A draw-to-draw flip means no merge.

**Merge** = both draws of question 1 say ONE **and** both draws of question 2
say CONTINUES.

## How the prompts were arrived at (out-of-population only)

Before this file was written the prompts were tried only on jobs outside the
graded population: `floor_en_coins_01` (two single figures of two coins each)
and `floor_it_geo_07` (four single diagrams, as halves, and four pairs of
separate stacked diagrams). No owner pair, it_geo_06 pair or control was asked.

- A first question 2 — a red bar and a blue bar in a left margin beside each
  block's rows, "SAME picture or DIFFERENT items?" — was **dropped**: on
  `floor_it_geo_07` it called 2 of 4 single diagrams DIFFERENT and 1 of 4
  separate pairs SAME. The model does not reliably tie a margin bar to a band of
  the page.
- The seam question on the same eight: 4/4 singles CONTINUES, 3/4 separate
  pairs BOUNDARY. The fourth (`page_001__left` 10-15, two separate diagrams of
  one series, blank paper at the arrows) came back **CONTINUES** — a known
  failure of question 2 alone, recorded here before the run. Question 1 said
  TWO on all four separate pairs and ONE on all four singles.
- Question 1 was not edited at any point. The prompts are frozen as printed
  above; editing one word after this commit is a new pre-registration.

## Gate (fixed now)

- **Wrong merge** = a merge on any of the 34 separate pairs, in any class.
- **PASS (a merge pass is worth building):** zero wrong merges, **and** at least
  **7 of the 13 pictures restored**. A picture is restored when its merged pairs
  connect all of its blocks into one group (the map needs a spanning set of its
  7 pairs, not all 7).
- **FAIL:** any wrong merge, or fewer than 7 pictures restored.
- **NO VERDICT:** more than 10 % of first-draw answers (pairs and controls, both
  questions) unreadable; or fewer than 50 % of the 37 controls merged by both
  questions (the questions cannot recognise a whole picture, so the pairs'
  answers mean nothing); or Ollama unavailable.

**Also reported, not gated:**
- the three-row table, from the first draw: question 1 alone, question 2 alone,
  both agree, each with pairs caught and separate pairs wrongly called one;
- pairs merged (of 21), pictures with any pair merged, merged pairs outside
  the map;
- the controls per question;
- every draw-to-draw flip.

The one `one` pair in the `between` class (`page_023__right#14-16`, an `other`
block in the gap) counts toward its picture. Merging it in a real build would
also have to absorb that block; that is a build question, not this one.

**The width-ratio precondition noticed after the census** is not used anywhere
here.

## What a result licenses

- **PASS** → build an off-by-default merge pass (the `figure_surface`
  contract: missing service or disagreement changes nothing; the merge is
  re-grouping only and reversible in the editor), with its own tests, and
  **still** report that zero wrong merges on 34 separate pairs is compatible with
  a true wrong-merge rate up to about 9 % (rule of three), and that the 34 are
  not independent (7 are from two sidebar columns, `page_023__left` and
  `page_025__left`).
- **FAIL** → P3 records the refusal with the arm table; the prompts are **not**
  re-tuned on these pairs. A new prompt is a new pre-registration and needs
  pairs it was not read off.

Outputs: `docs/data/figure_split_vlm_20260924.json` (every pair and control,
raw answers, parsed answers, merge, the summary); the images each question saw
under `W:\temp\claude\figure_split_vlm\`.
