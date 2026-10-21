# Pre-registration: the vision model's book box may CUT, behind a second question (P1)

Written 2026-10-21, before any check answer exists and before any number below
is computed.

## Why now

The owner answered the decision postponed on 2026-08-29: **a model's box may
cut** (owner, 2026-10-21: "yes, it can"). That answers whether. It does not
answer what the clipping bar grades, and it does not lift the guardrail that
anything which discards content needs **two questions that agree**. Cutting the
frame to the model's box discards pixels, and its measured failure is an
inward cut past the pad: `de_02`, left edge −8.90 % of the book, 1.89 % of the
labelled book lost (RESULTS 2026-08-29). The model is deterministic at
temperature 0, so asking the box question twice is one question. The guard
offered in OPEN_PROBLEMS (union with the paper mask) was refused on 2026-09-24.

So the cut ships only behind a **different second question**, aimed at that
failure, which a person answers in a second by looking.

## The rule, fixed now

Fires only where the shipped fallback fires today: the detector abstained, no
operator box, `vlm_box` returned a plausible box. Then:

1. **Candidate cut** = the model's box through the operator path's padding,
   exactly as arm C of 2026-08-29 (`book_boundary.user_box` arithmetic: emit =
   box padded `emit_pad` ∪ box padded `search_pad`; search = box padded
   `search_pad`). No new pad, no new value.
2. **Moved edges** = the edges of that cut that lie inside the frame. An edge
   that reaches the frame edge cuts nothing and is not asked about: if the book
   runs off the photograph there, the photographer cut it, not us.
3. **Second question**, on the candidate crop alone (long side 1120 px, JPEG
   q90, `num_ctx` 8192, temperature 0, `think: false`, same model
   `qwen3.6:27b`), verbatim:

   > This image was cropped from a photograph of an open book. Look at each of
   > the four edges of this image. For each edge, say whether the book is cut
   > off by that edge: true if any part of the book - its paper, printed text,
   > pictures, page edges or tabs - continues beyond that edge of the image,
   > false if the whole book stops before that edge. Answer with JSON only,
   > exactly: {"left": true or false, "right": true or false, "top": true or
   > false, "bottom": true or false}. No other text.

4. **Cut** iff the answer parses (first JSON object carrying all four keys as
   booleans) and **every moved edge is false**. Otherwise the page is handled
   exactly as today (the model aims the search, nothing is cut), and the reason
   is recorded.

The prompt is a measured parameter: once the first answer exists it is frozen.
Any edit is a new, unmeasured prompt and needs a new pre-registration.

## Populations

- **T** — the 21 `split_eval` rows (`testset/gt/gutter.json`), model boxes from
  `docs/data/vlm_box_split_20260829.json` (cached, not re-asked; identical by
  determinism). 8 rows have `book_box.json` labels.
- **O** — the owner's spreads 1 and 3 (`jobs/20260829-084115-de3c20d3`), the
  two on which the detector abstains; boxes from their `split.json`.
- **O′ (reported, not a ship gate)** — spreads 2 and 4, reachable only with
  `book_crop.three_edge_abstain` on. That cue's own blocker (no tight frame
  filling three sides has ever reached it) is unchanged by this run, so its
  default stays off whatever O′ shows.

## Gates (all must pass to turn the cut on in `config.yaml`)

**G1 — split, T.** With the rule on: **21/21 gutters** and **worst clip of a
labelled book 0.0 %**. A labelled row that clips > 0.0 % after the check said
"not cut off" is a FAIL of the check, recorded as such; no label, row or bar is
changed. (Expected informative row: `de_02`, the check should refuse its left
edge.)

**G2 — it does something.** The check accepts the cut on at least one of
`paleset_01`, `paleset_02`, owner spread 1, owner spread 3. If it accepts none,
the result is "no effect": the code may ship off, nothing is turned on.

**G3 — text on every T row that is cut.** Arms: *uncut* (today: model-aimed
search, whole-frame emit) vs *cut*. Both through Stage 02 `cut_pages` and Stage
03 (`dewarp_halves`, config method), OCR via `tools.dewarp_ab.ocr_text`
(config oem/psm, the probe upscale), page language from `testset/manifest.csv`.
- rows with a GT transcript (`bg_01`, `bg_02`, `en_coins_01`): **FAIL if word
  accuracy (`ocr_metrics.word_accuracy`) drops by more than 1.0 percentage
  point**; CER reported.
- every cut row: words at conf ≥ 80 reported; **FAIL if it drops by more than
  60** (the reframing churn floor recorded 2026-08-19 — borrowed, a floor, not
  a matched estimate); the token diff is written out and read either way.

**G4 — the owner's book, O.** Spreads 1 and 3 re-run through Stages 02–06 on a
copy (`W:\temp\claude`), cut on vs the job as it stands. Looked at, by eye, and
written down: (a) is any book content outside the cut on the anchor overlay —
**any yes is a FAIL**; (b) does the dewarped page still carry a band of sofa;
(c) words, words at conf ≥ 80, and blocks `unreadable_panel` turns into
pictures (P2's count), before and after; (d) a text diff of each page, the route
tables read by eye against the photograph. (b)–(d) are reported, not
thresholded: two spreads cannot carry a threshold.

## Also reported

- For each of the 8 labelled rows and each moved edge: the check's answer
  against the truth (does the labelled book extend past that edge of the cut).
  A table, not a gate; n is tiny and says so.
- Every refusal by name, with the answer.

## What a pass licenses, and what it does not

A pass turns on `vlm_box.cut` in `config.yaml` (module default stays off, like
`vlm_box` itself). It does not touch `split_eval`'s red rows (they are graded
as they ship, and the harness gains a flag for the cut, nothing else), does not
retune `search_pad`/`emit_pad`, does not turn on `three_edge_abstain`, and does
not replace the fixture shoot: T has two pale scenes and O is one sofa.
