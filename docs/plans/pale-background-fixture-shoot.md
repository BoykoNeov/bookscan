# Shooting brief — the photographs the book detector needs

**Status:** open, 2026-08-28; re-pointed 2026-08-29, shot list UNCHANGED. This is
a **data** task, not a code task, and it is the only thing standing between the
project and an automatic fix for the pale-background defect — by either route
now open (see the update below). Owner agreed to shoot these; none have been shot
yet as of 2026-08-29 (the archive still ends at 2026-08-18).

---

## Why, in one paragraph

`pipeline/book_boundary.py` cannot find the book on a pale or cluttered surface.
On 2026-08-28 eight families of cue were measured as candidate fixes and **all
eight failed** (RESULTS 2026-08-28; `docs/data/a10_background_first_20260828.json`).
The best candidate — model the *surface* instead of the page — fixes
`paleset_02` outright, but needs a precondition saying when it is allowed to run,
and that precondition cannot be calibrated, because **the whole corpus contains
one usable positive example.** The 31 archived "pale-background" captures are 11
frames of one lap shot, 18 of one sofa shot and 2 more of the lap scene: **two
scenes, one session, one book, one surface each.** Nothing in the archive helps.

Meanwhile `tools/book_box_editor` lets you draw the box by hand and that splits
8 of 8, so scanning is **not blocked**. These photographs are what would let the
program stop asking.

**Update 2026-08-29 — the shoot has a second, now leading purpose.** A local
vision model (`qwen3.6:27b`, `tools/vlm_box_eval`, RESULTS 2026-08-29) supplies a
book box that splits **21/21** through the same `user_box` path, fixing both pale
rows. It needed **no precondition at all** — it was applied to every row,
including the 13 tightly framed flat scans, with zero gutter regressions. So the
"calibrate a precondition" framing above is no longer the only route to an
automatic fix, and may not be the shortest one.

That does **not** shrink this shoot; it re-points it. The `n = 2 scenes, not 31
examples` objection applies to the vision model **identically** — it has been
tried on one pale sofa and one lap, one session, one book, one surface each.
These photographs are now the evidence for *either* candidate:

* does the model's box generalise to surfaces, books and light it has not seen?
* does it ever cut **inward** far enough to lose content? That is the one real
  defect the run found (`de_02`, 1.89 % of the labelled book), and it is
  unexplained — see the note under the negatives below.
* and A10's precondition, if the model route stalls, still needs exactly the
  same pictures.

---

## What is actually missing: NEGATIVES

The instinct is to shoot more books on more sofas. That is only half of it, and
it is the easier half. The precondition has to answer *"is there a background at
all?"*, so it needs both:

* **positives** — a book lying on a surface, with room visible all round it;
* **negatives** — a spread that **fills the frame**, where the correct answer is
  "no background, do not crop". The corpus has 13 of these, but they are all
  flat-on-a-desk scans of three books. It has never seen a *tightly framed
  handheld* shot, and that is the case a background-first method inverts on.

Every cue that failed did so by putting the one positive inside the range of the
existing negatives. More of both is the only way to know whether a gap exists.

**Do not trim the negatives on the strength of this, 2026-08-29.** It would be
natural to guess that the vision model cuts inward *because* a spread fills the
frame, and to shoot tight framing to provoke it. Checked, and there is **no
visible relationship across the 8 labelled rows**: the two worst inward cuts sit
at opposite ends of the range (`zoomset_en_02`, book fills 35 % of the frame,
cuts in 8.4 %; `de_02`, fills 78 %, cuts in 8.9 %), while `de_01` at 68 % and
`paleset_01` at 58 % are fine. Eight rows and two failures is **absence of
evidence, not evidence of absence** — it does not license a claim either way. The
negatives keep their original rationale in full: a background-first method
inverts on tight framing, and A10 is still live.

---

## The shot list

Aim for **16–24 spreads**. More surfaces beats more pages: two spreads on each of
many surfaces is worth far more than twenty on one sofa.

**Positives — book on a surface, room visible all round (8–12 spreads)**

1. The pale sofa again (it is the known-hard case) — 2 spreads.
2. A wooden desk or table — 2 spreads.
3. A **white or near-white** surface: a painted table, a sheet of paper, a
   worktop. This is the nastiest case for a paper-brightness rule and we have
   never shot it — 2 spreads.
4. A patterned or textured surface: tablecloth, rug, carpet, bedspread — 2.
5. A dark surface, as a control that the easy case still works — 1–2.
6. Held on a lap, cluttered background, as in `paleset_01` — 1–2.

**Negatives — the spread fills the frame (6–8 spreads)**

7. Handheld, framed tight so the pages run off **all four** edges — 3–4.
8. Handheld, framed tight so the book runs off **one or two** edges only — 2.
9. Flat on a desk, framed tight, phone directly overhead — 2.

**Vary these across the set, don't hold them constant**

* **Books**: at least 3 different ones. Different paper colour, page size and
  binding. A book with coloured page borders is especially useful.
* **Light**: daylight, room light at night, and one with a visible shadow or
  glare across the page.
* **Content**: at least two spreads that are mostly **picture**, and one that is
  nearly blank. Text-based cues quietly assume a page full of prose.

---

## How to shoot them

* Use the app's **manual capture** (auto-capture is an opt-in toggle and delivers
  one frame, not four — RESULTS 2026-08-28).
* **One frame per spread is enough.** Multi-zoom is a different question; do not
  mix it in.
* Hold the phone roughly parallel to the book, as you would normally. Do **not**
  compose carefully for the detector — the point is to capture what real use
  looks like, including the framing that breaks it.
* Keep the whole spread in frame for the positives. For the negatives,
  deliberately do not.
* Note, per spread, in any form: which surface, which book, which light, and
  whether it is meant as a positive or a negative. A line of text per shot is
  plenty; it saves an hour of guessing later.

---

## What happens to them afterwards

1. `tools/archive_photos.py` copies them into `M:\claud_projects\bookscan_captures`
   with the manifest, so they cannot be lost with a `git clean`.
2. The usable ones are appended to `testset/` (append-only — never edit an
   existing image), with hand-read `gt/book_box.json` and `gt/gutter.json`
   entries. **Label before attempting any fix**, as `paleset_01/02` were, so the
   labels stay independent of whatever detector is being tried.

   **Anti-contamination rule, added 2026-08-29 — read this before labelling.**
   When twenty photographs land, there is now a shortcut that did not exist when
   this brief was written: a vision model will happily emit a box for each one in
   seconds, and so will `find_book`. **Seeding either ground-truth file from a
   model, from the detector, or from any code in this repo destroys the entire
   value of the shoot** — the labels would then agree with the method by
   construction, and every subsequent measurement would be circular. This is the
   same prohibition `testset/gt/book_box.json` already states in its own header
   ("do not fit a book detector to these boxes"), extended by name to the model.
   Label the way `paleset_01/02` were labelled: read off the full-resolution
   image with a ruler overlay, by eye, deciding for yourself where the book ends.
   Accepting or nudging a proposed box is not independent labelling.

   Note for whoever does it: `tools/book_box_editor` is the obvious instrument
   (drawing a box is exactly what a book-box label is) but as written it draws
   the **detector's** box on screen as a dashed reference while you drag. It does
   not pre-fill your drag — but it does anchor your eye, and it writes Stage 02
   *input*, not ground truth. Using it for labelling needs a blind mode that
   shows nothing computed. That work is not done.
3. `tools/split_eval` grows accordingly, and will get redder before it gets
   greener — that is the point of banking failures rather than hiding them.
4. Only then is the precondition worth attempting again, against enough negatives
   for a gap to be real rather than a coincidence of one picture.

**Until then, draw the box by hand:**

```
python -m tools.book_box_editor jobs/<job_id>/
```
