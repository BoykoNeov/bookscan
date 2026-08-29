# bookscan — Book Scanning & Re-Typesetting Pipeline

## What this project is

A book-scanning system that produces **fully re-typeset searchable PDFs**: all
photographed text is REPLACED with real rendered text (clean reflowed layout),
while figures/illustrations are cropped from the page photos and placed back in
their correct reading-order positions. This is NOT the classic
invisible-OCR-layer-under-image approach — OCR output becomes the visible
document, so error handling is the load-bearing feature.

Three components:
1. **Android app** (`app-android/`) — guided capture: hover over a book spread,
   app auto-captures sharp frames (+ multi-zoom close-ups of large pages),
   uploads over local Wi-Fi. Built LAST, after the desktop pipeline is proven.
2. **Desktop server** (`server/`) — FastAPI on Windows + NVIDIA GPU: receives
   uploads, runs the pipeline, pushes status/previews back to the phone.
3. **Processing pipeline** (`pipeline/`) — staged, per-page, artifact-driven.

Target languages for OCR, in priority order: **English, Bulgarian (Cyrillic),
Italian, German**.

## Current status

<!-- UPDATE THIS SECTION AS WORK PROGRESSES -->
- [x] Gate 1: OCR quality harness (see `docs/GATE1_SPEC.md`) — DONE
- [x] Gate 2: fusion + split + dewarp improve OCR accuracy — DONE
- [x] Gate 3: layout + reading order correct on complex pages — DONE
- [x] Gate 4: end-to-end re-typeset PDF reads correctly — DONE
- [x] Gate 5: server + Android app — desktop FastAPI server DONE (see
      `docs/plans/partitioned-questing-pillow.md`); Android app M1–M5 BUILT and
      **VERIFIED ON A REAL PHONE 2026-08-28** (see
      `docs/plans/android-guided-capture.md` and RESULTS 2026-08-28): job
      list/resume, 7/7 stage progress, manual capture → upload → all seven
      stages, an 18-image page, upload retry over a dropped link, server killed
      mid-page and recovered, and the uncertainty mode chosen on the phone.
      **Auto-capture was demoted to an opt-in toggle** by that session — armed
      on a real spread it delivered one still, not the measured four — so
      manual capture is the flow.
      **Known open defect, not an app one:** neither real capture split into
      pages. `pipeline/book_boundary.py` returns the whole frame on a pale
      background, so the crop abstains and Stage 02's ink cue picks a white
      channel *inside* a page. Fix not attempted (13+ non-regression fixtures);
      planned in `docs/plans/book-detector-pale-background.md`. Its **Phase 0 is
      DONE 2026-08-28**: both failing frames are committed, labelled fixtures
      (`testset/paleset_01/02` + book-box and gutter GT), so **`tools/split_eval`
      now reads 19/21 and exits 1 on purpose** — the owner chose a red suite over
      hiding two known failures, so do NOT "fix" it by removing those rows.
      Scouting 2026-08-28 already closed the obvious fix: retuning the HSV
      thresholds cannot work (see the plan's section 5). **Phase 1 is DONE
      2026-08-28**: the artifacts no longer claim things they did not measure —
      the abstain reason stopped asserting "already tightly framed", the
      spine-pinch cue declares itself inapplicable where it cannot measure (and
      Layer 2 is skipped), and `corroborated` became `pinch_corroborated` plus a
      `corroborated_by` about the column that actually shipped. Zero accuracy
      change, verified by diffing the eval against HEAD. It also **closed B1's
      classifier by measurement** — six cheap ways to ask "was a book actually
      found?" all fail, because on a tight scan the book really does reach the
      frame border, so the only route is asking whether there is a background at
      all. **A10 (background-first) was then MEASURED 2026-08-28 and
      NOT shipped:** it fixes `paleset_02` outright (0.00% clipping, gutter 1752
      vs 1778) and wrecks `paleset_01` (clips 20.85% of the book, because that
      book runs off the left frame edge so the background model gets fitted to
      paper). Half the precondition is solved — how many frame sides the candidate
      blob touches — but "is there a background at all" has no cheap answer:
      eight families measured, all fail, structurally, because on a tight scan the
      method finds the printed area and a printed area is also large, rectangular,
      compact and darker-bordered. **n = 1:** the 31 archived pale captures are two
      scenes, not 31 examples, so more fixtures must be NEW photographs of NEW
      surfaces. Awaiting an owner call between shipping it off-by-default (the
      `per_page_source` precedent), gathering that data, or escalating to A9 (the
      phone supplies the box). **Owner's call 2026-08-28: build A9 AND go shoot
      more fixtures — and draw the box on the COMPUTER, not the phone.**
      `tools/book_box_editor` is BUILT and splits **8/8** with a drawn box,
      including both failing frames (`paleset_01` 2741 -> 1699, `paleset_02`
      none -> 1749). The shooting brief for the fixtures that would let the
      program stop asking is `docs/plans/pale-background-fixture-shoot.md` — and
      note what it needs is **negatives** (tightly framed handheld spreads), not
      more sofas. `split_eval` stays 19/21 until those exist and a precondition
      can be calibrated.
- **Local vision-language models are now installed on this machine
  (2026-08-29)** — `qwen3.6:27b` and `gemma4:31b`, served by Ollama on
  `localhost:11434`. Set up in `M:\claud_projects\localLLM`; **nothing in
  bookscan was changed and `split_eval` was not run.** Measured on bookscan's own
  fixtures: OCR post-correction cuts CER 6.72% -> 5.57% (English) and
  1.49% -> 1.16% (Bulgarian) **without altering a single number**, and qwen finds
  a book box on `paleset_01`/`paleset_02` (IoU 0.905/0.940) where the detector
  abstains. See `docs/notes/2026-08-29-local-llm-available.md`.
  **That note's open experiment has since been RUN — `tools/vlm_box_eval`,
  RESULTS 2026-08-29.** Routed through the same `user_box` path a hand-drawn box
  takes, qwen's box splits **21/21**: `paleset_01` 2741 -> 1697 and `paleset_02`
  none -> 1749, within 2 px of the hand-drawn box, **zero gutter regressions** —
  and the feared one-edge excess proved harmless (a +15 % edge still hit). The
  real findings are elsewhere. The detector **abstains on 17 of 21 rows**, so 15
  correct rows had never seen an applied crop before; they survived one, but
  "where the detector abstains" is therefore NOT a narrow trigger. And the crop
  **stopped being clip-free**: `de_02` loses 1.89 % of the labelled book (the one
  affected row in the shippable arm; `zoomset_en_02`'s 1.19 % never arises there,
  the detector crops it). Adjudicated as **no readable content lost** — cloth,
  the fanned page-edge block, a coloured tab sliver, checked by connected
  components and by eye. **That is a finding about the METRIC too:** until now
  nothing could produce a small non-zero clip (the detector abstains; a human
  draws generously), so `worst_clip == 0.0` has never had to tell "lost text"
  from "trimmed a tab". **The owner POSTPONED this decision 2026-08-29** and killed
  the easy half of it: grading **ink** is not a safe generalisation, because the
  outer edge of a photograph or illustration carries no glyphs, so an ink-only bar
  would pass a trimmed figure edge. "No text in the band" was never the same claim
  as "nothing of value in the band" — it holds for `de_02` (checked), not as a
  rule. Three live options, none chosen: an inward-only guard (no metric change),
  grade **content** (ink *or* imagery — undefined in the harness today), or keep
  `worst_clip == 0.0` and accept that a model box cannot pass it. **Mechanism and
  the number to build against:** outward excess is harmless (a **+15 %** edge
  still split), inward error is the whole failure mode, and the 8 % pad covers
  −3.64 % but not −8.36 %/−8.90 % — so it **stops covering between ~3.6 % and
  ~8.4 % inward**. Fix it with an inward-only guard or a union with the
  detector's own paper mask; do NOT retune `search_pad` (n = 1, recorded dead
  zone). All three passes returned byte-identical boxes, so the repeatability bar
  measured determinism, not robustness.
  **SHIPPED 2026-08-29 (`pipeline/vlm_box.py`) — as a search window and nothing
  else.** The owner's own scan of a book on a pale sofa mis-split on every page,
  making this the blocker for real work rather than an experiment. Stage 02 now
  asks the model where the book is **only** when the detector abstained AND no
  operator box exists, and uses the answer to aim the **spine search** while
  copying the emitted pixels from the detector untouched
  (`book_boundary.search_only`). Every frame it fires on is one the detector gave
  up on, so nothing is cropped at all and the path **cannot clip by
  construction**: `split_eval --vlm` reads **21/21 with 0.0 % clipping**, better
  than the cut-to-the-box arm. **It does NOT settle the postponed clipping
  decision** — whether a model box may ever *cut*, and what the bar should grade
  — and nothing here depends on the answer. A missing Ollama, an unreadable
  answer or an implausible box all fall back to the previous behaviour and say so
  in `split.json`. Still n = 2 scenes, so the fixture shoot stands. The plain
  `split_eval` guard is untouched and
  **stays red at 19/21** — this is a reason to build the fix, not to
  relabel the rows, and it does not replace the fixture shoot.

- **The operator can choose the OCR language, and the sofa stops rendering as a
      picture — both SHIPPED 2026-08-29**, prompted by the owner reading the
      rendered PDF of their own book and listing ~15 defects. **Ten of the
      fifteen have one cause: the book was photographed on a pale sofa.**
      `server/worker.py` now passes `--lang` (job-level, `job.json`, a
      `PATCH /api/jobs/{id}` and a picker in the console); a job with no recorded
      language passes NO flag, which is deliberately not the same as passing the
      config default. **The sofa defect is localised to the FIRST FOUR SPREADS**,
      and neither branch of the `vlm_box` path shipped earlier the same day can
      remove it: on spreads 1/3 the detector abstained and the model's box only
      *aims* the spine search so nothing is cut; on spreads 2/4 the detector did
      NOT abstain — it returned "cropped to detected book" with a box keeping the
      **full frame height**, so the model was never asked. The trigger is
      `abstained`; this book's failure mode is *confidently wrong in one axis*.
      `pipeline/figure_surface.py` removes the visible symptom without cutting a
      pixel: it asks a local vision model whether a figure is the surface the
      book is lying on, **twice** — about the crop alone, and about the whole page
      with the block outlined — and flags it only when both agree. **Each single
      question discards real book content** (the crop arm a printed photo of an
      information board, the page arm a tilted chapter banner), for the same
      reason: a via-ferrata guide is full of printed photographs of rock, and a
      picture of a rough surface looks like a rough surface. Their intersection
      flagged **16 of 163 and lost nothing**; **0 of 93** figures flagged across 26
      assembled testset jobs from other books. `Block.is_surface` is a FLAG, not a
      deletion — Stage 08 skips it and the editor can clear it. OFF by default,
      same contract as `vlm_box`. **It does NOT fix the crop** and must not be read
      as fixing the detector: spreads 1-4 still have wrong margins and their dewarp
      still ran on a frame containing fabric, and cutting to a model box is still
      the owner's postponed decision. **The garbage text is NOT a dictionary
      problem — measured and REFUSED:** the zero-dictionary-word blocks on those
      spreads are the guide's ROUTE TABLES (`840 Hm 1450 Hm`, `4 5td. 6% Std.`),
      the most valuable data in it; and **0 of 150** text blocks there sit outside
      the paper band, so the junk is *on* the paper — real content read badly
      because the dewarp ran on a frame containing fabric. That points back at the
      crop, not at a text filter.
- **Three owner proposals measured 2026-08-29, two refused; and two defects found
      behind the German render.** (a) **Reading each close-up separately and merging
      the words is a WASH** — line-aligned over 34 close-ups, a max-confidence merge
      gains 122 words (+2.0 %) and loses 133, and **every gain is the same string at
      higher confidence** (`und@50 -> und@95`), not a word recovered. Bounded, not
      closed: these close-ups are framed on the PAGE at a median 1.30x, so it says
      the union does not pay *at this framing*. (b) **A page-level multi-language
      OCR string (`deu+ita`) is REFUSED** — it raises high-confidence words 7.2 %
      while LOSING umlauts (`Berücksichtigung -> Beriicksichtigung`), because a
      language whose alphabet lacks them makes the umlaut-free reading fit a
      lexicon and therefore score higher. **Third time a change raised a confidence
      number while making the text worse**; the rule is now **no accuracy claim
      without a text diff**, and confident-word counts are NOT comparable across
      language sets. Multilingual support belongs at the **block**, not the page.
      (c) **Panorama is planned, not built** —
      `docs/plans/panorama-and-next-steps.md`, whose premise is a REORDER
      (flatten first, stitch second) because the doubled text was a homography
      failing on a curved page, and whose Phase 0 is one day of reusing
      `mesh_align`. That plan also ranks the remaining defects by measured cost;
      the top item is that **12.2 % of the book's words (1607, in 28 blocks) are
      rendered as photographs of text** — the route sidebars and the
      English/Italian panels. Two defects fixed on the way: **Stage 08's
      de-hyphenation rule was never handed a dictionary** (correct, unit-tested,
      inert — 138 broken words in the owner's book, 63 now rejoin), and
      **`normalize_token` was deleting the accented letters of three of the four
      target languages** (`è -> ""`), with a measured **0 of 5604** delta on
      Bulgarian, the only language whose gate actually runs.
- **The operator console SHIPPED 2026-08-29** (`server/assets/console/index.html`
      + `server/routes_pages.py`, launched by `bookscan.bat`). One browser page
      for the whole job: the job list, a thumbnail grid, a per-page view with all
      seven stage overlays, and a text view drawing every word box on the
      flattened page coloured by Stage 06's verdict, with the uncertain words
      listed and clickable. The page views are **read-only over the immutable
      trace** — the only writing button is "re-run this page", which enqueues on
      the existing worker (`run_all` has no single-stage flag, so "re-run from
      stage N" would be a promise the pipeline cannot keep). Assemble asks before
      discarding edits rather than forcing. Previews are downscaled on the fly
      (~80 ms; a debug overlay is a 5-15 MB PNG) and never cached to disk.
      One deliberate call: a stage pip is green when the stage **ran**, not
      "green unless it warned" — stages put provenance notes in `meta.json`'s
      `warnings` ("v0.2: UVDoc"), so warning-colouring painted all 25 pages amber
      and meant nothing. The notes are still shown verbatim, called notes.
- **Close-up stitching is measured as NOT WORKING on real captures, and this is
      a replication, not a new bug (2026-08-29).** Over the owner's own 25-spread
      book, **6 of 317 close-ups registered** onto their anchor. 283 were
      rejected for too few inliers (clustered at 3-7 against a threshold of 8),
      28 registered but were refused by the do-no-harm gate for being *softer*
      than the anchor, 11 for a degenerate homography or photometric
      disagreement. `stage01_fuse.py`'s own docstring already diagnosed this at
      n = 11 ("a capture-guidance and/or dewarp-before-stitch problem, not a
      matcher problem") and `min_inliers` was already corrected once, 25 -> 8.
      **Do NOT lower `min_inliers` again** — 5 inliers is noise, not a weak
      homography, and the recorded measurement says loosening it adds a false
      positive. The actionable half is the operator's: the extra taps per spread
      currently buy nothing, and the 28 "located but softer" close-ups are a
      capture problem (too close, motion blur, focus hunting), not a code one.
      **REVISED 2026-08-29 on both halves.** The "softer" reading was wrong: a
      control run put the ANCHOR'S OWN PIXELS through the identical warp and they
      score 0.506 against a bar of 1.0, so nothing can pass that gate — the number
      measures the warp's resampling, not the photograph. The close-ups actually
      beat that control on 25 of 34. The *decision* stands, for a better reason:
      warping a close-up DOWN into the anchor destroys the resolution before
      anything is written (0.77x the anchor's high-confidence words over the same
      region), so blending stays off and `min_sharpness_ratio` stays at 1.0.
      The resolution is real (median 1.30x linear) and is now collected where it
      survives — see the figure pass below.
- **Enlarging the page so close-ups land at their own size was MEASURED and NOT
      shipped (2026-08-29).** The owner's proposal — stop shrinking a close-up
      into the anchor, enlarge the anchor instead — is right about the physics,
      and two of its three premises hold. **Stage 01's matcher is the reason
      registration fails:** the identical question asked with SIFT registers
      **227 of 317** close-ups where shipped ORB(4000) registers **6**
      (`feature_engine: sift` already exists; the fixtures only showed 6/11 vs
      5/11, this book shows the real gap). **The per-block alternative is dead:**
      an individual TEXT block matches the WRONG paragraph (agreement 0.04-0.36
      against a correct 0.6+), because a paragraph is not locally unique and a
      photograph is — so a bigger canvas is the only way to spend those
      registrations. **But the canvas fails its own control.** On `page_013`,
      same language on every arm: baseline 324 high-confidence words, enlarged
      1.58x with NO close-ups pasted **336**, enlarged 1.58x **with** them
      **270**. The enlargement is harmless; the close-ups cost 66 confident
      words, and the pixels show why — the text comes out **doubled**. The
      leftover displacement of a well-registered close-up is a median **6.5 px**
      and up to **59 px**, and it is **not smooth** (neighbouring tiles disagree
      by up to 45 px), because a homography assumes a plane and a page is a
      cylinder seen off-axis. Tried at three mesh resolutions, identical every
      time. This is exactly the mechanism `stage01_fuse`'s docstring already
      named — *outside the model rather than badly matched* — and the route that
      could work is registering **after Stage 03 flattens both images**, which is
      a different and larger piece of work. See RESULTS 2026-08-29.
      **The bigger lever found on the way is free and unbuilt:** this German book
      is read as **`eng`**, because `server/worker.py` passes `--mode` to
      `run_all` and never `--lang`, so `languages.default` decides for every job
      the console or the phone submits. Same page in `deu`: 335 high-confidence
      words vs 324 and +2.8 mean confidence. **The operator cannot choose a
      language today.**
- **Pictures are re-cut at the close-ups' own scale (`pipeline/figure_hires.py`),
      SHIPPED 2026-08-29.** The owner's requirement is pictures at the highest
      available detail. Stage 01 cannot deliver that (see above), so Stage 07
      takes each FIGURE, finds every capture holding a piece of it, and rebuilds
      it at those captures' scale — stitching, in the picture's own frame instead
      of the anchor's. Matching works here precisely because it failed there: a
      spread is repetitive text, a figure is locally unique, and on `page_023` six
      frames register against the figure that Stage 01 never located.
      **24 of 163 figures upgraded** on the owner's book, median **1.43x** linear,
      best **3.65x**, ~8 s per spread inside assemble. Refusing is
      the normal outcome and costs nothing — the page crop stays. Three things
      the measurement decided, do not undo them casually: `min_ncc` is **0.60**
      not 0.50 (wrong sources measured 0.51-0.52, right ones 0.63+); sources are
      chosen **greedily** (a source that adds no new pixels can only add its own
      alignment error — painting all ten on `page_023` was the bug); and each fit
      is **ECC-refined**, because the crop is dewarped and the source is not.
      **REWORKED 2026-08-29 for maximum detail, on the owner's via-ferrata topo
      map** (RESULTS 2026-08-29). The canvas now comes from the **sharpest**
      source, not the widest — eighteen frames match that map, one holds a fifth
      of it at 3.16x, and the old rule delivered the whole picture at 1.86x.
      Sources are laid down **sharpest-first, each painting only pixels no better
      source has claimed** (ordering by coverage handed every overlap to the
      source with least resolution to offer). And each source is **bent onto the
      flattened page** by a smooth displacement field before it lands
      (`mesh_align`), because one homography cannot express what Stage 03 did to
      the paper — without it the sharpest-first composite tore the word
      "Arzalpenturm" in half at a seam. 24 upgraded (was 22), 0 lost, topo map
      1.86x -> 3.16x. **One open thread:** an offline sweep upgrades 25 and the
      shipped run 24; `page_022__left` block 5 upgrades reproducibly in isolation
      (1.29x, coverage 1.00, agreement 0.827) but was refused in the batch. Most
      likely a frame decode returning None under memory pressure — the module
      holds every frame of a spread decoded — which `candidates` skips SILENTLY.
      Fix the silent skip before chasing the rest. **`min_coverage` stays 0.90 and lowering it is REFUSED by
      measurement:** at union 0.607 the composite is visibly worse than the page
      crop (two disagreeing sources smeared across a wide feather, 39 % still an
      upsample) and it scored 0.889 on the result gate while damaged — an
      under-covered figure needs another PHOTOGRAPH, not another threshold.
      Verify by CHECKERBOARD, never side-by-side: a sharper picture reveals text
      the blurry crop hides, which reads as a framing change and misled this
      session twice. `--no-figure-hires` / `figure_hires.enabled: false` turns it
      off. See RESULTS 2026-08-29.
- **Importing a PDF and re-typesetting it is PLANNED, not built** —
      `docs/plans/pdf-import.md`. Import fills `00_ingest/` and nothing
      downstream changes; the PDF's own text layer is a second opinion routed
      through `second_opinion.py`, never the text source.

## Architecture: the stage contract (IMPORTANT)

The pipeline is a chain of stages. **Every stage obeys the same contract:**

1. Each stage is an independently runnable CLI:
   `python -m pipeline.stage04_layout jobs/<job_id>/<page>/`
2. A stage reads ONLY the artifacts of the previous stage from the page
   directory, and writes its own artifacts into its own numbered subfolder.
3. Every stage writes THREE things:
   - its output image(s) and/or JSON,
   - a `meta.json` (stage version, params used, timings, warnings),
   - a **debug overlay image** in `debug/` (e.g. detected boxes drawn on the
     page) so failures are visible to a human at a glance.
4. Stages NEVER modify earlier artifacts. Re-running a stage overwrites only
   its own folder. Any page can be re-run from any stage.
5. All inter-stage data structures conform to `pipeline/page_model.py`
   (the single shared schema). Change the schema ONLY deliberately, in its own
   commit, updating all stages that touch the changed fields.

**Editable-document exception (Stages 07–08).** Items 1–4 describe the per-page,
immutable pipeline trace (00–06). The editable document (`Document` in
`page_model.py`) is deliberately different: it is **job-level** and **mutable** —
the user's editable working copy (translate / fix OCR / reorder before, or after,
baking a PDF). Stage 07 `assemble` builds it from the whole job; Stage 08
`render` is a **pure, re-runnable** function of it. Both read ONLY `document.json`
+ `document_assets/` — never the per-page folders — so a saved document survives
upstream re-runs (self-containment). Assemble won't clobber an edited document
without `--force`. See `docs/GATE4_SPEC.md`.

**Operator-book-box exception (Stage 02).** Item 2 says a stage reads only the
previous stage's artifacts. `<page_dir>/book_box.json` is not an artifact of any
stage: it is **user input**, the same kind of thing as `config.yaml` or
`--mode patch`, and it lives at the page-dir ROOT rather than in a numbered
folder so it can never be mistaken for one. No stage writes it —
`tools/book_box_editor` does, from a human's mouse. It exists because the book
detector provably cannot find the book on a pale or cluttered surface (eight cue
families measured and closed, RESULTS 2026-08-28), and a hand-drawn box splits
8/8 including both frames that fail today. Because it carries a human's
confidence it is checked, not trusted blindly: Stage 02 **refuses** a box whose
recorded frame or frame size does not match the current anchor (a box drawn
before Stage 01 re-ran is a confidently wrong crop), the box is **padded outward**
before anything is cut (measured: cutting to the drag exactly loses 1.95–9.73 %
of the book on a 1–5 % undersized drag, padding loses 0.00 %), and a missing or
corrupt file means the detector runs exactly as before.

**Higher-resolution figure exception (Stage 07).** Item 2 again. Stage 07 reads
`03_dewarp` and `06_uncertain`; `pipeline/figure_hires.py` makes `00_ingest` a
third per-page folder it reads — still upstream, still never written. It has to be
that one: the extra pixels a picture needs exist ONLY in the frames as shot, and
`01_fuse/anchor.png` is where Stage 01 already threw them away (it warps a
close-up DOWN into the anchor, so reading the anchor would be reading the loss).
The upgrade is an ADDITION, never a replacement: `Block.figure_asset` is optional,
None means "crop the page image" and is the normal case, and Stage 08 falls back
to the page crop whenever `figure_asset_box` does not equal the block's live bbox
— the document is mutable, and a high-resolution picture of a figure's OLD
outline is a wrong picture, which is worse than a soft one.

**Per-page frame-source exception (Stage 02, opt-in and OFF by default).** Item 2
says a stage reads only the previous stage's artifacts. Per-page frame selection
(`pipeline/page_source.py`, config `per_page_source.mode: ocr`) lets `left.png`
and `right.png` be cut from **different** full-spread photographs, so it needs
the gutter (Stage 02) *and* the candidate pixels (Stage 00) at once. With the
mode on — and only then — Stage 02 reads those frames back out of `00_ingest/`,
named by `01_fuse/fuse.json`'s `fullspread_frames`. The rule's purpose is
preserved: `00_ingest` is upstream, is never written, and the speculative
dewarp+OCR probe that decides is entirely in memory and writes no artifacts.
Consequence for the schema: `SubPage.box` is in the coordinates of the frame
named by the new `SubPage.source` — with the mode off that is always
`01_fuse/anchor.png` and the old "ORIGINAL spread coordinates" wording holds
verbatim. Default is off for a **measured** reason, not caution (RESULTS
2026-08-26); do not turn it on without reading that row.

### Job folder layout

```
jobs/<job_id>/<page_NNN>/            <- per-page, immutable pipeline trace
  00_ingest/    raw uploads normalized to RGB PNG + capture metadata
  01_fuse/      anchor image after multi-zoom stitch (or best single frame)
  02_split/     left.png, right.png (gutter split) — or single.png
  03_dewarp/    dewarped page image(s), full resolution
  04_layout/    layout.json (blocks: type, bbox, reading_order) + overlay
  05_ocr/       ocr.json (words: text, bbox, confidence, engine) + overlay
  06_uncertain/ resolved.json (per-word decision: keep/flag/patch) + patches/
  debug/        one overlay PNG per stage (04_layout.png, 05_ocr.png, ...)

jobs/<job_id>/                       <- JOB-LEVEL, editable (Stages 07–08)
  document.json         editable re-typeset doc (all pages, MUTABLE working copy)
  document_assets/      self-contained images: dewarp pages + flag/patch crops
  document.meta.json    Stage 07 assemble meta
  render/               page.html (always) + page.pdf (when a PDF engine exists)
```

### Pipeline stages

| Stage | Module | Does | Primary tools |
|---|---|---|---|
| 00 | `stage00_ingest` | RAW/JPEG → normalized RGB, EXIF, per-page folder | Pillow, rawpy |
| 01 | `stage01_fuse` | multi-zoom stitch onto anchor frame; pick sharpest frame | OpenCV (features + homography, ECC refine) |
| 02 | `stage02_split` | book-boundary crop (`book_boundary.py`) → gutter detection → left/right pages; optional per-page frame source (`page_source.py`, off by default) | OpenCV (projection profile, GrabCut) |
| 03 | `stage03_dewarp` | flatten page curvature | UVDoc (default), DocTr++ (partial crops) |
| 04 | `stage04_layout` | block detection + reading order | DocLayout-YOLO + XY-Cut++ |
| 05 | `stage05_ocr` | word-level text + bbox + confidence; caption ejection (`caption_eject.py`) + starved-block re-read (`block_reocr.py`) + figure-edge text absorption (`figure_text.py`) | **Tesseract 5 TSV (backbone)**; EasyOCR second opinion for Cyrillic |
| 06 | `stage06_uncertainty` | per-word decision using user mode a/b/c | own code |
| 07 | `stage07_assemble` | job-level: build editable `document.json` + self-contained `document_assets/`; higher-resolution figure assets (`figure_hires.py`) | own code; OpenCV (SIFT + RANSAC + ECC) |
| 08 | `stage08_render` | `document.json` → re-typeset HTML (always) → PDF (re-runnable) | own code; WeasyPrint/headless-Chromium (PDF, TBD), Noto fonts |

### Non-negotiable design decisions (do not "optimize" these away)

- **Tesseract 5 is the confidence/bounding-box backbone.** VLMs and Surya may
  be added as second opinions for hard passages, but they must NEVER be the
  sole text source or the confidence source (no reliable word boxes, no
  calibrated confidence, hallucination risk).
- **Confidence thresholds are adaptive per document**, never a single global
  hard-coded cutoff. Cross-engine disagreement is a second trigger for
  "uncertain", independent of raw confidence.
- **Uncertainty modes (user-selectable, all three must exist):**
  - `flag` — low-confidence words rendered in a highlighted span in the output;
  - `best_guess` — emit text plainly;
  - `patch` — crop the word's image box from the full-res dewarped page
    (03_dewarp output, NOT a downscaled copy) and inline it as a tiny `<img>`.
  - Markers are **per-word**: a marker clears only when *that* word is edited or
    deleted (Stage 08 renders on `Word.flag_visible`), never wholesale.
- **Reading-order mode (user-selectable, parallel to the uncertainty modes).**
  `DocSettings.order_mode`: `auto` (trust Stage 04's proposed order) or `review`
  (the editor surfaces every block's reading order for the user to confirm/correct
  before reconstruction). Unlike the uncertainty modes it changes **zero pipeline
  computation** — it is editor-review state over an already-assembled document.
  A block's "needs review" marker clears **per-block** and keyed on the *order
  field specifically* (`Block.order_review_visible`): the user renumbers
  (`reading_order` ≠ `order_auto`) OR explicitly accepts (`order_confirmed`); a
  type-only edit must NOT clear it. This is the *linear-order review* half only —
  caption↔figure **grouping** (ranked above exact order by the owner) is a
  separate, still-open concern.
- **Editable document before finalize (Stages 07–08).** The pipeline must save an
  editable-by-the-program `document.json` BEFORE finalizing to PDF, so the text
  can be corrected/translated first — or a PDF baked now and edited later.
  Render is a pure, re-runnable function of that document; edits round-trip.
  Editable text is a word-level layer with provenance (`text` = current,
  `text_ocr` = original OCR, kept forever); a block-level `text` override carries
  a translation and supersedes the words.
- **Figures are cropped from the full-resolution dewarped image** and placed
  with their captions as a single block in reading order.
- **De-hyphenation rule on reflow:** join a line-end hyphen with the next line
  only if the next line starts lowercase AND the joined token is in the
  per-language dictionary; otherwise keep the hyphen.
- **Running headers / page numbers are stripped by default** (user toggle to
  keep them).
- Reconstruction output is real text → the PDF is inherently searchable.
  Embed Noto fonts covering Latin + Cyrillic.

## Repo layout

```
bookscan/
  CLAUDE.md              <- this file
  docs/GATE1_SPEC.md     <- current work spec
  docs/data/             <- machine-readable inputs+outputs behind a RESULTS row
                            (committed so a result is auditable without temp/)
  pipeline/              <- stages + page_model.py + run_all.py
  server/                <- FastAPI upload/status/preview server (BUILT)
  app-android/           <- Kotlin app, 3 Gradle modules (BUILT, unverified on
                            a real device): app/ UI+VM, capture/ frame scoring
                            + hover gate, network/ API client + retry
  testset/               <- fixed benchmark images + ground truth (NEVER edit
                            images; append-only). See testset/README.md
  jobs/                  <- runtime output, gitignored
  tools/                 <- harness scripts (accuracy eval, debug viewers)
  config.yaml            <- paths, languages, thresholds, model choices
```

## Conventions for working in this repo

- Python 3.11+, type hints everywhere, `pydantic` models in `page_model.py`.
- One stage per Claude Code session where possible. Always validate against
  `testset/` before declaring a stage done; commit per working stage.
- Every stage gets a `--debug` flag that also dumps intermediate arrays/crops.
- Windows host: prefer `pathlib`, no shell-isms in subprocess calls; Tesseract
  binary path comes from `config.yaml`.
- When debugging a bad page, inspect `jobs/<id>/<page>/debug/` overlays FIRST
  before reading code.
- **`tools/layout_order_eval` grades the SHIPPED block set (Stage 04 + Stage 05).**
  It runs the three later block-creating passes itself — orphan-word rescue,
  `caption_eject`, `block_reocr` — so a "miss" is a real absence from the
  document, not a stage boundary. (Closed 2026-08-26; before that the eval
  stopped after Stage 04 and understated segmentation recall by 3 of 112.)
  `--no-stage05` reproduces pre-2026-08-26 rows and does NOT grade the
  deliverable. **Never compare a row from one arm against a row from the other**:
  the tau column especially is a different quantity, because an orphan block
  re-ranks the whole set through XY-Cut before anything ships.
- GPU: assume a single consumer NVIDIA card; load models lazily per stage,
  release VRAM when a stage CLI exits.
- Accuracy numbers reported by `tools/` scripts go into `docs/RESULTS.md`
  (append a dated row; never overwrite history).
- **The Android app is installed over Wi-Fi debugging. That is the method this
  project uses** — not a USB cable, and not sideloading the APK through a
  browser. Build with `./gradlew assembleDebug` in `app-android/`, then push it
  to the phone with `adb install -r` over a wireless connection (recipe in
  **Commands** below). Do not offer the browser-download route as the default;
  it needs the operator to tap through an "install unknown apps" prompt and
  leaves a port open on the LAN, and adb reports success or failure of the
  install itself, which a browser download does not.
  **The one part Claude cannot do alone:** on Android 11+ a first pairing needs a
  six-digit code and a *random* pairing port that only exist while the phone's
  "Pair device with pairing code" dialog is open, and only the operator can read
  them off the screen. So ASK for the code and `IP:port` and wait — do not fall
  back to another install method because the phone is not yet visible. Once
  paired, the phone is remembered and later installs need only `adb connect`.

## Commands

**The console is the interface. Start here, not with a Python command.**
Double-click `bookscan.bat` (or `python -m uvicorn server.app:app --host 0.0.0.0
--port 8000`) and everything the operator does lives at `http://127.0.0.1:8000/`:
the job list, a per-page view of every stage overlay, the block and per-word
certainty inspector, re-run a page, assemble, render, and the text editor. The
CLIs below still exist and are still the contract — the console calls exactly
them, through `server/worker.py`'s subprocess — but they are for development and
measurement, not for processing a book.

```
# run one stage on one page
python -m pipeline.stage05_ocr jobs/demo/page_001/

# run full pipeline on a folder of captures
python -m pipeline.run_all --input testset/spread_03/ --job demo --mode flag

# draw the book box by hand when the detector could not find the book
# (writes <page>/book_box.json; "Save & re-split" re-runs Stage 02 only)
python -m tools.book_box_editor jobs/<job>/ [--port 8011]

# open the visual editor on an assembled job (edit OCR/type/order/translation,
# then Preview / re-render). Reads+writes ONLY document.json + document_assets/.
python -m pipeline.editor jobs/<job>/ [--port 8000]

# the console (the operator interface for everything above)
bookscan.bat            # or: python -m uvicorn server.app:app --host 0.0.0.0 --port 8000

# Gate 1 harness
python -m tools.gate1_harness --testset testset/ --report docs/RESULTS.md

# build + install the Android app over Wi-Fi (THE install method here)
cd app-android && ./gradlew assembleDebug
#   phone: Settings > Developer options > Wireless debugging > ON
#   first time only: tap "Pair device with pairing code", read off the 6-digit
#   code and the IP:PORT it shows (that port is random and dies with the dialog)
adb pair <ip>:<pairing_port> <code>      # first time on this machine only
adb connect <ip>:<connect_port>          # the port on the Wireless debugging screen
adb install -r app-android/app/build/outputs/apk/debug/app-debug.apk
#   adb lives at M:\claud_projects\android-sdk\platform-tools\adb.exe
#   `adb mdns services` lists the phone when wireless debugging is on; an empty
#   list means it is OFF, not that the network is broken
```
