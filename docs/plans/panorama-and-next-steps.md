# Panorama capture, multilingual pages, and what to build next

Written 2026-08-29, after the owner read the rendered PDF of their own
via-ferrata guide and listed ~15 defects, proposed continuous panorama-style
capture, and pointed out that a real book can carry several languages on one page.

This document is three things: a plan for the panorama idea, a plan for
multilingual pages, and a ranked list of everything else — ranked by **measured**
cost to the book, not by how interesting it is.

---

## 0. The finding that should shape all of it

Three separate times now, a change has raised a confidence number while making
the text worse:

| what | the number that went up | what actually happened |
|---|---|---|
| outer-gutter CLAHE (2026-07-17) | mean confidence | recall +0.000 — refused |
| the close-up word union (today) | 1.403x "union" | 36 % of matches were the matcher failing |
| multi-language OCR (today) | +7.2 % confident words | `Berücksichtigung` -> `Beriicksichtigung` |

**Rule going forward: no accuracy claim without a text diff.** A confident-word
count compares two readings of the same alphabet. The moment the alphabet, the
lexicon or the language set changes, the count stops being comparable, because
confidence is partly "does this fit a dictionary I was given" — and a wrong word
that fits a dictionary outscores a right word that does not.

---

## 1. Panorama capture

### What the owner proposed

The phone's own panorama mode is useless for books because it wants you to rotate
the phone. But the *principle* is right: keep shooting continuously while moving
over the spread, stitch as you go, repeat until the whole page has been seen
sharply, and only then start recognising page components.

### Why the naive version is already dead

Stitching before flattening has been measured and it fails, twice:

- Stage 01 warps a close-up **down** into the anchor to blend it, which throws
  the extra pixels away before anything is written (0.77x the anchor's confident
  words over the same region).
- Enlarging the canvas so close-ups land at their own size fixes that, and the
  text comes out **doubled**: leftover displacement of a *well-registered*
  close-up is a median 6.5 px and up to 59 px, and it is **not smooth** —
  neighbouring tiles disagree by up to 45 px. Tried at three mesh resolutions.

The cause is not a bad matcher. A homography assumes the page is flat; a
photographed page is a cylinder seen off-axis, and no single homography can
express that. **A continuous panorama that stitches before dewarp walks straight
back into this.** So the premise of the plan is a reorder: **flatten first, stitch
second.**

There is already a working example of the reorder in the repo.
`pipeline/figure_hires.py` stitches pictures successfully, and it does exactly
this: it bends each source onto the *flattened* page with a smooth displacement
field (`mesh_align`) before painting it, because one homography could not express
what the dewarp did to the paper. Without that step the composite tore the word
"Arzalpenturm" in half at a seam.

### Phase 0 — the cheap experiment that decides everything (about a day)

**Question:** does `mesh_align` remove the doubling on text, the way it removed
the tearing on pictures?

**Method:** take the 227 close-ups that SIFT registers globally (shipped ORB
registers 6; `feature_engine: sift` already exists in config), bend each one onto
the flattened page with the existing `mesh_align`, and re-measure the same
leftover-displacement statistic that killed the enlarged canvas.

**Gate, pre-registered:** median residual under 2 px **and** neighbouring-tile
disagreement under 5 px. Current values without `mesh_align` are 6.5 px and 45 px.

**If it fails, the panorama route is closed** on the same evidence that closed the
enlarged canvas, and nothing further gets built. This is the whole point of doing
it first: it costs a day and it uses only code that already ships.

### Phase 1 — sharpness-aware patchwork (a few days, only if Phase 0 passes)

The owner has explicitly licensed visible patchwork *provided the patches are
sharper*. So: paint a source only where it is genuinely sharper than what is
already there, keep the existing pixels elsewhere, and use a **hard narrow seam**
rather than a wide feather. (The wide feather is what made the under-covered
figure composite visibly worse than the plain crop — two disagreeing sources
smeared across the blend.)

The ordering logic already exists and is measured: sharpest source first, each one
painting only pixels no better source has claimed. Painting by coverage instead
hands every overlap to the source with the least resolution to offer.

### Phase 2 — does it actually read better (half a day)

Re-run OCR on the composite page and compare with the plain flattened page.
**Gate: more confident words AND a text diff showing no degradation** — per
section 0, the word count alone is not allowed to decide this.

### Phase 3 — the capture loop (the large build, Android)

Only if 0–2 pass. The phone keeps a live coverage-and-sharpness map of the spread
and keeps shooting until every part of it has been seen at target sharpness,
instead of the operator guessing when they are done. This is the owner's
"repeatable until a maximum sharp picture is achieved".

Two things known in advance about this phase:

- The current close-ups are framed **on the page**, median 1.30x linear. That is
  why reading them separately gains almost nothing (section 3.5). A capture loop
  should be aiming for much tighter frames — the resolution has to exist before
  any amount of software can spend it.
- Auto-capture was already demoted to an opt-in toggle because on a real spread
  it delivered one still where four were measured. A capture loop is auto-capture
  with a goal; it must be built against that failure, not around it.

**Honest summary of the panorama idea: the physics is right, one measurement
stands between it and a real build, and that measurement is cheap.**

---

## 2. Multilingual pages

### The finding

Tesseract accepts `deu+ita`, and the job language field already validates that
shape, so putting combinations in the console picker is a two-line change.
**Measured today, and it must not be offered as a page-level setting.** Adding a
language whose alphabet lacks umlauts makes the umlaut-free reading plausible, so
it gets chosen *and scored higher*: `Überholende` -> `Uberholende`,
`Berücksichtigung` -> `Beriicksichtigung`. `Via` — an Italian word — got worse
when Italian was added. Full numbers in `docs/RESULTS.md`.

### The right shape: language per block, not per page

This book's foreign-language content is **physically separated into panels** —
the German route description, then the English one, then the Italian one, each in
its own box. That is the normal case for a multilingual book: languages are
laid out in blocks, not shuffled word by word.

So the unit is the block, and the machinery already exists:

- **`block_reocr.py` already re-reads a single block** when the page pass starved
  it, and already has the right acceptance rule: keep the re-read only if it wins
  on more words **and** on its own confidence, never on a cutoff.
- **Four Hunspell dictionaries are already installed** (`tools/setup_lexicons.py`,
  English, Bulgarian, Italian, German) and already reachable at runtime.

**Design:** read the page once in the job's primary language. For each text block,
score its words against each installed dictionary. Where the primary language is
clearly not the best fit, re-read that block alone in the winning language and
keep it only if it wins on **both** word count and dictionary hits — never on
confidence, per section 0. Everything else is unchanged, and a job with one
language behaves exactly as it does today.

The local model is a second route to the same question ("what language is this
block in?" is a one-second question for a person, which is the shape of question
it is measurably good at). The dictionary route is free and needs no model, so it
goes first; the model is the fallback for a block with too few words to score.

### The connection worth noticing

The 28 blocks currently rendered as **pictures of text** (section 3.1) are largely
these same translation panels. Fixing that defect and supporting multilingual
pages are substantially the same work item — do 3.1 first, because a block that is
not text at all cannot be given a language.

---

## 3. Everything else, ranked by what it costs the book

### 3.1 Text panels rendered as pictures — 12.2 % of the book's words. Do this first.

59 picture blocks carry 8 or more words; the model calls 28 of them text; those 28
hold **1607 words out of the book's 13155**. These are the route data sidebars, the
hut information boxes, and the English and Italian translation panels — the owner's
items #15 and #19. Rendered as photographs they are not searchable, not
correctable, not translatable, and not spell-checkable.

**THE PREMISE ABOVE IS WRONG, measured 2026-08-29 while building it.** It assumed
Stage 04 mis-types these boxes as pictures. Only **4** of them are that. The other
fourteen are text blocks all the way through Stage 05 and are turned into pictures
at Stage 07 by *our own* `unreadable_panel`, correctly: their OCR is not text a
reader could use — the English Version panel reads "Englist Version Crane a Of w wa
Z SH Zu SO Saar Aatter", at median confidence 19.2 against a floor of 70.5. So the
1607-word figure counted words that are **not recoverable text at all**, and this
was never "the cheapest fix in this list".

Splitting the item honestly:

* **the 4 mis-typed boxes** — the two big route tables and the four-country grade
  table, ~683 words at OCR confidence ~90 — are fixed, and shipped, by
  `pipeline/text_panel.py` (below);
* **the 14 unreadable ones** need the text to become readable before typing means
  anything, and the largest single cause is **language**: the English panel and the
  trilingual glossary are being read as `deu`. That is §2 of this document, not this
  item. Re-typing them without fixing the reading would render noise, which is
  exactly the trade `unreadable_panel` was built to refuse.

The original design sketch, kept because the shipped module follows it: it is the
mirror of the sofa question, which is shipped and measured at 16 flagged out of 163
with nothing lost. Same module shape, same two-questions-must-agree rule, new
prompt pair: "is this a picture, or is it text in a box?" — asked about
the crop alone and about the outlined block on the whole page. A block both
questions call text gets promoted and re-read by `block_reocr`.

**CORRECTED 2026-08-29, before building it.** The sentence that stood here said
the risk was low because a wrongly promoted picture is "a garbage text block the
operator can see and revert — not a deletion". That is wrong, and a plan that
understates a failure mode is how a safety rule gets "simplified" later. Stage 08
renders a PARAGRAPH from its words, so a picture wrongly promoted is **gone from
the PDF**. This is the same risk class as `figure_surface`, not a lesser one, and
the two-questions-must-agree rule is the safety argument rather than politeness.

BUILT 2026-08-29 as `pipeline/text_panel.py`, and the build found a third thing
the design above did not have: without a **surface veto**, 3 of 21 promotions are
out-of-focus upholstery, which the model calls TEXT in both arms with complete
confidence. See RESULTS 2026-08-29.

### 3.2 The four sofa spreads still have the wrong crop — blocked on the owner

`figure_surface` removed the visible symptom; it did not fix the cause. Spreads 1–4
still have wrong margins, their dewarp still ran on a frame containing fabric, and
the meaningless letters the owner flagged trace back to exactly that (measured: the
junk is *on* the paper, and it is the route tables, so no text filter may touch it).

The fix requires cutting to a model-supplied box, which is the owner's **postponed**
decision: may a model's box ever cut, and what should the clipping bar grade? The
mechanism is known and recorded — outward excess is harmless (a +15 % edge still
split correctly), inward error is the entire failure mode, and the existing 8 % pad
covers −3.6 % but not −8.4 %. An inward-only guard, or a union with the detector's
own paper mask, is the shape of the fix. **Do not retune `search_pad`.**

There is also a second, narrower hole worth fixing regardless: the model is only
asked where the book is when the detector **abstains**. On spreads 2 and 4 the
detector did not abstain — it returned a confident box that kept the full frame
height. "The detector gave up" is not the same trigger as "the detector is wrong",
and this book's failure mode is the second one.

### 3.3 Pictures split in two — 45 pairs (the owner's white lines, #12/#14/#18/#20)

35 stacked figure pairs have nothing between them: one picture cut in half by the
layout detector. 10 more are split by a caption printed *on* the photograph
(item #16). A whiteness-of-the-gap rule was built and **rejected by inspection**:
it correctly merges 20 but also glues orange text sidebars onto photographs on 5,
which is visible by eye.

What it needs is a **continuity test** — do the two halves' pixels actually continue
across the gap? — not a whiteness test. The correlation machinery for that already
exists in `figure_hires` (`min_ncc`, measured at 0.60 because wrong sources scored
0.51–0.52 and right ones 0.63+). Medium effort, well-defined, and it removes a
whole family of the owner's complaints at once.

### 3.4 The silent frame-decode skip — one line, do it while passing

`figure_hires.candidates()` skips a frame that fails to decode **without saying so**.
This is the most likely explanation for an offline sweep upgrading 25 figures and
the shipped run upgrading 24, with one block reproducibly upgrading in isolation and
being refused in the batch. Fix the silence before chasing the symptom.

### 3.5 Reading the close-ups separately — measured, a wash, closed at this framing

The owner's proposal, measured properly: a max-confidence merge over line-aligned
readings gains **122 words (+2.0 %)** and loses 133 the other way, and every gain is
the same string at higher confidence (`und@50 -> und@95`), not a word recovered.
Not worth a pipeline stage.

**Bounded, not closed forever:** these close-ups are framed on the page at a median
1.30x. The measurement says the union does not pay *at this framing*. A close-up
framed on a text block is untested — and that is the same operator-side lever the
figure work found (the 103 figures that were not upgraded mostly had no candidate
at all, because the close-ups were framed on the page rather than on the pictures).

### 3.6 The item not yet investigated

"That stitching is on the right track, but the text below the picture is cut"
(#11). The high-resolution figure asset is cut for the block's bounding box; if the
caption sits inside the figure block, the asset can crop it. Small, and it is the
one flagged defect with no diagnosis yet.

---

## 4. Suggested order

1. **3.1 text-panels-as-pictures** — biggest measured loss, cheapest fix, and it
   unblocks the multilingual work.
2. **Section 2 per-block language** — extends shipped machinery, no new models.
3. **Panorama Phase 0** — one day, decides a large build either way.
4. **3.3 picture continuity** — removes a whole family of visible defects.
5. **3.2 the crop** — as soon as the owner settles the clipping question.

3.4 costs a line and can ride along with any of them.

---

## 5. Three observations worth carrying

**The local model earns its place on questions a person answers in one second by
looking**, and nowhere else. Every win so far is that shape: where is the book,
is this the sofa, what language is this. Every time it has been asked to be a
source of truth instead of a judgement, it has been either unnecessary or unsafe.
The two-questions-must-agree rule is what makes it safe to act on, and it should
stay attached to anything that discards content.

**A flag is not a deletion, and at one book of evidence that distinction is
load-bearing.** Everything the model decides should be reversible by the operator
until there are many books behind it.

**The cheapest lever keeps turning out to be the operator's.** Three independent
measurements ended at "the photograph was framed wrong", not "the code is wrong":
the close-ups that carry no extra resolution, the figures with no candidate source,
and the book photographed on a pale sofa. Capture guidance may be worth more than
the next algorithm — which is, in the end, exactly what the panorama idea is.
