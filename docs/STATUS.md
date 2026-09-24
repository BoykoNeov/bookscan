# Status log — what was built, measured, refused, and why

This is the project's **chronological record**, moved out of `CLAUDE.md` on
2026-09-02 so that the orientation file stays readable while nothing that was
learned is lost. Every entry below is verbatim from the file it came from. The
rules for it:

- **Append, never rewrite.** A later measurement that overturns an earlier entry
  gets a new entry (or a dated "REVISED" clause inside the old one, as several
  entries already carry) — the wrong first reading stays visible, because the
  reasoning that led to it is part of the record.
- **Each entry is a summary.** The numbers, inputs and outputs behind it live in
  `docs/RESULTS.md` (dated rows) and `docs/data/` (machine-readable), and the
  design it came from lives in `docs/plans/`. Follow the pointers before
  re-attempting anything an entry says was refused.
- **The distilled version is elsewhere.** `CLAUDE.md` carries the one-line
  guardrails these entries earned; `docs/OPEN_PROBLEMS.md` carries the live
  problems, ranked, with the next experiment for each. Read those first, this
  file when you need the story behind a rule.

---

## Gates and shipped work, in the order they happened

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
- **A "figure" that is really a text panel is promoted to text — SHIPPED
      2026-08-29 as `pipeline/text_panel.py`** (Stage 05, between caption ejection
      and the starved-block re-read; that position is load-bearing because
      `block_reocr` skips FIGURE blocks, so a promoted panel is re-read for free).
      **The plan's premise for this item was WRONG and the eye-check is what found
      it.** Of the 18 blocks that render as photographs of text in the owner's
      book, only **4** are Stage 04 mis-typing a box; the other **14** are text all
      the way through Stage 05 and are turned into pictures at Stage 07 by our own
      `unreadable_panel`, **correctly** — their OCR is not usable text (the
      English-language panel reads `Englist Version Crane a Of w wa Z SH Zu SO Saar
      Aatter`, median conf 19.2 against a floor of 70.5). So the "12.2 % of the
      book's words" figure counted words that are **not recoverable text at all**,
      and this was never the cheapest item in `docs/plans/panorama-and-next-steps.md`.
      The 14 need the *reading* fixed first and the largest cause is **language** —
      that is the multilingual work, not typing. What ships is the 4: **3 of 36
      Stage 05 candidates promoted, 3/3 correct**, both route tables and the
      four-country grade table, **683 words at OCR confidence ~90**.
      Three guards, each earned by a measured failure. (a) **Two text questions
      must agree** — the context arm vetoed 2 of 23 and both were right (a photo
      banner; a photograph of an information board). (b) **The surface question as
      an EITHER-arm veto** — without it the pass promotes the sofa, including a
      534-word band of weave noise at conf 19.7 that both text arms confidently
      call TEXT; offering `SURFACE` as a third answer to the text prompt changes
      **not one answer of 55**. The asymmetry with `figure_surface` is deliberate:
      to FLAG a block surface both arms must agree (a false positive deletes real
      content), to PROMOTE one neither arm may even suspect it. (c) **The prompt
      WORDING is part of the measurement** — measured naming "a mountaineering
      guidebook", then generalised as it must be, and the generalisation flipped a
      photographed warning sign from PICTURE to TEXT; one clause fixed it and a
      second, apparently harmless clause then lost a real 87-word table. All 3-5
      identical draws, so the model is **deterministic** here and a flip between
      runs is a changed prompt, not sampling. **An edited prompt is an unmeasured
      prompt.** The two passes divide the work — `text_panel` asks *is this worth
      reading?*, `unreadable_panel` asks *can this be read?* — and that net is
      measured (the wrongly promoted sign was demoted straight back). **Honest
      limit: the net only catches junk-text false positives**; a photograph with
      READABLE burned-in text would pass both and be deleted, so the
      two-questions rule is the safety argument and must not be simplified.
      **Promotion deletes pixels** (Stage 08 renders a paragraph from its words) —
      it is recoverable via `type_promoted` in the editor, which is not the same as
      harmless. `min_words` 8 (sweeping to 3 adds 15 candidates, 0 promotions).
      **TURNED OFF the same day, and this is the part to read.** The classifier
      survives its own re-check — the shipped prompts over all 36 candidates
      return the same 3, all 3 really are panels of text, the sofa still refused
      — but classification was never the deliverable. **Read as rendered, the
      text is worse than the photograph it replaces.** All three are
      multi-column TABLES and Stage 08 emits a promoted block as one `<p>`, so
      the columns collapse: the seven-column route table loses every time from
      its route (`7 Std. 9 Std. 2½ Std. 6½ Std.` in a row, page numbers
      stranded) and the grade table interleaves four countries (`Österreich
      Deutschland I [| 1eatien ] Frankreich A KI F F A/B leicht facile facile`).
      Median confidence ~90, so neither this pass nor `unreadable_panel`'s 70.5
      floor can see it — the **fourth** time here a confidence number rose while
      the text got worse. Promotion deletes pixels, so that is a loss.
      `enabled: false` in `config.yaml`; code, guards and tests stay. **The real
      blocker is Stage 08 rendering a TABLE as a table** (these three blocks are
      the fixture), then per-block language. A single-column panel of running
      text would probably win today — this book has none, so that is a guess.
      n = 1 book, adjudicated by eye.
- **Each block is labelled with the language it is PRINTED in, and the re-read the
      plan asked for is REFUSED — both 2026-08-31 (`pipeline/block_lang.py`).**
      This was the last blocker `text_panel` named. **The plan's item was to
      re-read a foreign-language block with that language's OCR, and measuring it
      first killed that half.** Over all 36 blocks a dictionary vote nominates in
      the owner's book, read twice from the same crop: where a block reads WELL
      the language is a **wash** — word counts identical (101/101, 103/103, 87/87,
      56/56, 45/45, 42/42, 32/32), confidence within a point, and the text diff
      cuts both ways (`interestin` -> `interesting` against `Ferrata Roghel` ->
      `Ferrara Roghe!`), with one 99-word English paragraph **byte-identical**
      read as German. Where a block reads BADLY — the fourteen translation panels
      this work was aimed at — the other language returns **different garbage, not
      better** (`technacz! 68- Kcules (1-6` becomes `wana! 6 ficunes (A-€`). So
      **`docs/plans/panorama-and-next-steps.md` §2's premise is wrong: those
      panels are unreadable because of the PIXELS, not the dictionary**, and they
      are NOT fixed — do not re-attempt this from language.
      What ships is a **label and nothing else**: `Block.language`, written from a
      Hunspell vote over the words already read. No word is added, dropped,
      re-read or edited, so word conservation is untouched and an abstain is free.
      **The single consumer is Stage 08's de-hyphenation** — which joins a line-end
      hyphen only when the joined token is a real word, so without this an English
      paragraph in a German book keeps `rou- tes` and `at- tractive` broken in the
      PDF. Over the owner's book plus all fifteen fixtures, 1032 blocks: **21
      labelled, 16 joins gained, 0 lost**; thirteen of fifteen single-language
      fixtures label **nothing**. Graded on the **render** as well as the label —
      six spreads through Stage 05/06/assemble/render, rendered twice from one
      document: **38 broken words become 26, 0 newly broken**. Four guards, each
      earned by a measured false positive; **`min_len` 3 is the load-bearing one**
      (English Hunspell accepts a long tail of two-letter forms, so a block of pure
      noise scores 0.61 against English on `la ir at do av se vs fa is cr` alone —
      at 2 `it_geo_05`'s junk block is nominated, at 3 it is not and no real
      paragraph is lost anywhere). The block's lexicon is a **union** with the
      document's, also measured: alone it loses `de_02`'s `Rosen- garten`, a German
      massif named in an English paragraph, because a book printing one language
      inside another is full of the other's proper nouns. **Deliberately ONE
      consumer** — the EasyOCR disagreement gate and Stage 06's threshold also key
      on a lexicon and are NOT wired to this, because neither is measured. n = 2
      books, one supplying 17 of the 21 labels. See RESULTS 2026-08-31.
- **Stage 08 renders a TABLE as a table — SHIPPED 2026-08-31 as
      `pipeline/table_grid.py` (Stage 05) + a `<table>` path in Stage 08.** This is
      the blocker yesterday's row named. **The interesting part is that the rows
      could NOT be worked out at render time, and that is a proof, not a tuning
      failure.** Tesseract's `line_id` groups a *cell*, not a row (on the owner's
      route table the names are lines 0-35, the times 43-75, the heights 92-124),
      the printed columns are staggered against each other by ~0.7 of the row
      pitch, and the stagger **aliases**: sliding the name column by a whole row
      pitch scores 7.4 px mean residual against 8.1 px for the truth, so the wrong
      answer fits better. Deskewing (-2.86 deg) collapses three of five columns to
      within 1 px and still does not fix it. **Do not re-attempt this from
      geometry.** What knows the rows is Tesseract re-reading the block crop as one
      uniform block (`psm 6`) — it has the ruled lines, its lines span the whole
      table (x 36-2344 of 2370 vs a page-pass line's 126-506 of 1185), and it reads
      two columns the page pass never read. But it is used as a **row oracle and
      nothing else**: its *text* is measurably worse than the page pass's (mean
      conf 70.6 vs 91.8; `2,2 4½ Std.` -> `, .`, `1250` -> `[250`, `102` -> `I Ly`),
      so rows come from the re-read and text from the page pass. The pass **never
      adds, drops or edits a word** — it writes only `Word.table_row` /
      `table_col` — so word conservation is untouched and an abstain is free.
      Acceptance is **structural** (the re-read's lines must span materially more
      of the block's width, 0.30 -> 0.97), which is exactly why this is a new
      module and not a rule in `block_reocr`, whose "more words AND no lower
      confidence" test would correctly refuse the right answer. **4 of the
      corpus's 7 Stage-04 TABLE blocks grid (12x2, 17x4, 7x2, 17x2).** The 3
      abstentions were opened and looked at and are **not all correct** — an
      earlier draft claimed they were on the strength of inspecting one, and that
      is corrected in the RESULTS row. One is right (an 8-word fragment); one is
      the right outcome for the wrong reason (a real 90x3 German/English/Italian
      glossary whose page-pass read is 24 junk words, so there is nothing to
      grid — an upstream defect); and **one is a genuine miss**: `it_geo_07` #5,
      the corpus's only non-owner-book table, is a real 3-column chart that is
      read well, refused because the page pass splits `INFERIORE` across the
      printed column rule and the fragments sit IN the 3 px gutter, so the
      x-projection sees one column. **Two candidate fixes were swept over the
      whole population and both change nothing on every block** (`col_gap_mult`
      1.0->0.35; excluding full-width header cells from the column vote) and
      neither was kept. The route that could work is taking the **columns** from
      the oracle read too — not attempted. Two guards earned
      by measurement: a same-slot collision counts only across *different printed
      rows* (otherwise the guard refused the fixture at 16% vs a 15% bar for being
      right), and words inside a cell order by visual line at a 0.9-height
      tolerance (0.6 splits one skewed line and sorts its right half first).
      `deu` does **not** fix the numeric cells (68.5 vs 70.6, adds `Hım`) — this is
      not a language problem. **Honest limit, pre-registered before any render was
      read: a correct grid is necessary and NOT sufficient.** `2,2`->`22`,
      `1,3`->`13`, `4½`->`4Y`, `170`->`I70` survive a perfect grid, so whether the
      two route tables now beat their photographs is still the owner's call.
      The **grade table refuses itself** on the structural rule, exactly as
      predicted, and tuning against it was forbidden in advance.
      `text_panel`'s promoted panels are now re-typed TABLE when they grid
      (guard: `type_promoted` AND PARAGRAPH, uniquely that pass's mark), so its
      remaining blocker is **per-block language alone**. See RESULTS 2026-08-31.
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
- **Panorama Phase 0 is MEASURED 2026-08-31 — the plan's own premise is REFUSED
      and a narrower reorder passes (`tools/panorama_phase0.py`).** Seven
      placements of all 317 close-ups, one matcher and one acceptance rule, gate
      and population pre-registered before any number existed
      (`docs/data/panorama_phase0_prereg_20260831.md`). **Flattening the close-up
      too — "flatten first, stitch second", the plan's stated reorder — is worse
      than leaving it raw on EVERY statistic and places 62 fewer close-ups
      (154 vs 216).** UVDoc flattens a borderless close-up fine, so this is not a
      capability gap. **Read the refusal precisely: what was measured is a
      SEPARATE UVDoc pass on the close-up, registered against Stage 03's separate
      pass on the page — two neural dewarps of differently-framed content, which
      cannot agree by construction.** That variant is refused and should not be
      re-attempted; flattening the source by resampling the PAGE's own
      displacement field is a different thing and was not tested. What
      survives is **flatten the TARGET only** — raw close-up onto the dewarped
      page, then `mesh_align` over the source's own footprint — which passes at
      **1.39 px / 1.27 px** on the pre-registered statistic and 1.67 px on an
      independent one (dense optical flow, added because grading a
      phase-correlation correction with phase correlation is circular at the
      correction's own grid, which on this book it nearly is). **Against a
      measured floor of 0.09 px**: the target's own pixels through the identical
      machinery, the control this repo owes itself since the sharpness gate that
      nothing could pass. **The old doubling was largely correction SCOPE, not the
      target** — estimating the field over the whole enlarged page (what the failed
      run did) scores 4.24 px, indistinguishable from no correction at all (4.13),
      against 1.55 px over the footprint on the same target. **The median passes
      and the TAIL does not, and the tail is what doubles text:** only 16 of 172
      placed close-ups have a worst-twentieth under 5 px and **72 (42 %) are at
      30 px or worse** — a word width. Over every close-up SHOT, not just the
      placed ones, that is **5 %** paintable at a 5 px rule and 18 % at 10 px —
      which reorders the plan, because a capture loop that frames tighter becomes
      the precondition rather than the follow-on (placement is flat across zoom,
      so tighter costs nothing). So Phase 1 is licensed **only** as a design
      that paints hard narrow seams and skips a source by its own local error,
      never as "paint every registered source". A sub-window re-fit reaches the
      same accuracy with no field at all (1.60 px) but 30–43 % of windows cannot
      answer — a fallback, not a drop-in. **Nothing here says the page reads
      better**: this is placement, further from the deliverable than a confidence
      number, and Phase 2 (one `page_013` render comparison, more confident words
      AND a text diff) is the next thing to do — before Phase 1 is built. The
      four sofa spreads are worse under every arm and are not covered. See
      RESULTS 2026-08-31.
      **Phase 2 is now MEASURED 2026-08-31 (`tools/panorama_phase2.py`) and
      returns NO VERDICT — which parks the whole panorama thread.** Of 40
      close-ups that register onto their flattened subpage, only **5 clear the
      pre-registered 10 px bar and 4 of those land on one topographic map**, so
      the statistic has almost no text under it. Reported as a no-verdict, not
      patched into a pass. **Phase 1 is NOT licensed and the route is NOT
      refused** — it was never given a fair text page. Four things it settled.
      (a) **The blocker is the TAIL inside a source, not which sources**: even
      well-placed subpages run a 1.2–1.5 px median against a 10–27 px
      worst-twentieth, so a whole-source rule discards sources that are typically
      fine. Phase 1 needs **per-REGION** admission — a redesign, not a retune.
      (b) The seam must be **word-aligned** (2 of 3 genuine word losses sit within
      3 word-heights of a paint boundary). (c) **Two explanations are dead, and the
      first draft of the row asserted one of them**: "the good close-ups are aimed
      at pictures" is refuted (35 of 37 footprints are figure-heavy, including
      every badly-placed one), and "tighter framing places better" reverses once
      the single spread carrying it is removed — so this does **not** confirm the
      capture loop as the precondition, in either direction. (d) **Per-source
      residuals are seed-dependent, Phase 0's included**: `cv::theRNG()` feeds
      RANSAC and FLANN, one source reads 9.76 / 10.25 / 14.34 px across draws, and
      **9 of 40 flip across the bar** — admission is now the worst of three seeded
      draws and no single-draw residual should ever be thresholded again. The
      control fires (painting the REJECTED sources loses 35 confident words while
      total words RISE 200 -> 242, the recorded doubling signature), so the null
      is real. One encouraging note that claims nothing: the single text subpage
      that did paint **ties on confident words (102 vs 102) and wins on the text
      diff**, rejoining two hyphen-broken words — the count was blind to it because
      the improvement was two words becoming one. n = 1 book, 3 spreads.
- **The phone can now sweep for close-ups — SHIPPED 2026-08-31 as
      `app-android/.../ui/SweepScreen.kt` + `capture/SweepGate.kt`, and it is the
      CAPTURE half only.** There was no panorama option in the app to test: the
      capture screen is a manual shutter plus a four-frame hover burst, the
      close-up screen is one tap per close-up. Now: pick a zoom, tap Start sweep,
      slide across the spread, and a still is taken every time the view has
      travelled far enough. **It stitches nothing and cannot** — Phase 1 is not
      licensed and Phase 2 gave no verdict — so the frames are **ordinary
      close-ups**: same `PendingSpread`, same single multipart POST, same Stage 01
      area classifier, same `downscaleCloseupInPlace` (an un-downscaled frame is
      above `fullspread_area_frac` and would compete to be the **anchor**). It is
      built because Phase 2's no-verdict was a **data famine** — 5 of 40 sources
      admitted, 4 onto one map — and close-ups over text cost one tap each, so
      nobody gathers them. It does **not** lean on "tighter framing is the
      precondition"; Phase 2 measured that and it does not survive its confound.
      **`HoverGate` is NOT reused and must not be loosened to do this**: it is
      fitted to fire *because the phone is still* (zero bursts across a 21 s
      moving recording), so `SweepGate` inverts the test — motion triggers,
      sharpness vetoes. **The one number settled by measurement is the idle
      floor**: summing raw per-frame motion fires **6** shots across the 23 s
      *steady* recording (duplicates of one patch out of a capped budget),
      summing only the excess over 3.1 fires none, and both arms stay in
      `tools/calibrate_sweep.py`. 200 is where a standing phone goes silent (150
      still fires a second shot) and fills the 24-frame budget in 20.5 s of real
      hand motion, a median 834 ms apart. **But the motion signal is a "the
      picture changed" proxy, not a distance — a RATE control, never an overlap
      guarantee**, and the logs it is anchored to are a hold and a re-frame, not a
      sweep; a time-only fallback ships beside it for that reason. The 24-frame
      cap is **per SPREAD, not per run**, and that is load-bearing: a spread is
      one POST (because `upload_page` names pages by arrival) and `start()`
      resets the gate's own count, so a per-run cap would bound nothing — three
      passes would be 72 frames in one request. A shot the camera was too busy
      to take is given back to the budget and counted on screen. Sweep frames are named
      `frame_NN_sweep` and the server **preserves that marker** into
      `ingest.json`'s `source`, so "a sweep helped" can be told from "more
      close-ups helped". **Nothing is verified on a phone** — auto-capture was
      measured at four stills per hover and delivered one on a real spread. See
      `docs/plans/android-guided-capture.md` M7.
- **Importing a PDF and re-typesetting it is PLANNED, not built** —
      `docs/plans/pdf-import.md`. Import fills `00_ingest/` and nothing
      downstream changes; the PDF's own text layer is a second opinion routed
      through `second_opinion.py`, never the text source.


---

## 2026-09-02 — The book detector was a random draw; the record moved out of CLAUDE.md

- **Found by running the guard from a clean clone.** `tools/split_eval` crashed
  on `de_01` (its anchor lives in gitignored `jobs/`), and while checking whether
  the committed JPEG could stand in, `find_book` returned four different boxes on
  the same frame within one process — from a full abstain to a crop that removes
  11.9 % of the labelled book, including the left page's icon sidebar. GrabCut's
  GMM init draws from OpenCV's unseeded global RNG. Swept all 21 rows under eight
  seeds (RESULTS 2026-09-02, `docs/data/grabcut_seed_sweep_20260902.json`):
  17 rows seed-invariant, two lap captures jitter 2–4 % harmlessly, raw `de_02`
  is a coin flip between "no crop" and content lost.
- **Shipped:** `find_book` takes three seeded GrabCut draws, emits their union,
  and abstains when they disagree on any edge by more than `emit_pad` — a
  derived threshold, not a tuned one. Raw `de_02` now abstains for a stated
  reason and splits 7 px from GT via the pinch cue. Every gradable row is
  byte-identical or better; worst clip 0.0 %. Cost: 3× one GrabCut per spread,
  written down. RANSAC in Stage 01 and `figure_hires` is seeded (fixes the
  draw, not the gate). The silent frame-decode skip in `figure_hires` now
  reports into `document.meta.json`. `split_eval` prints `UNAVAILABLE` for the
  two off-machine rows instead of crashing.
- **Not checked, must be on the owner's machine:** the real `de_02` anchor's
  `gc_jitter`; the sofa job's spreads 2 and 4 (were they "unstable" rather than
  "confidently wrong"?); anything downstream of Stage 02 (no Tesseract here).
- **Structure:** the 550-line status diary moved from `CLAUDE.md` into this
  file verbatim; `CLAUDE.md` now carries a short "where we stand", a guardrail
  list (one line per rule, with the RESULTS date), and the measurement
  discipline. New `docs/OPEN_PROBLEMS.md` ranks the live problems (P1–P10) with
  the next experiment and the precondition for each; new `docs/plans/README.md`
  indexes the plans with their state. README status updated from "Gate 1 in
  progress".

---

## 2026-09-24 — The sofa spreads are stably wrong, not unstable

- **Ran the two checks the 2026-09-02 entry left for the owner's machine**
  (RESULTS 2026-09-24, `docs/data/gc_jitter_sofa_20260924.json`). `split_eval`
  reads 19/21, worst clip 0.0 %, as predicted. The real `de_02` anchor is
  unstable (three seeded draws disagree by 12.9 %) and abstains for that reason.
  **The owner's sofa spreads 2 and 4 give the identical box on eight of eight
  seeds** — mode (c) is real, and the seeding change does nothing for the
  owner's defects. Measured in memory; the job's Stage 02 folders were not
  rewritten.
- **Correction to the 2026-08-29 entry** ("keeping the full frame height",
  "confidently wrong in one axis"): looked at, the box keeps sofa on three
  sides — it starts at the frame's left edge at full height, and its one inward
  edge stops at loose white sheets lying on the sofa, not at the book. Spread 3
  has the same GrabCut box and was saved only by the area gate firing on its
  union with the search box.
- **Correction to the 2026-08-29 entry** ("so the model was never asked"): true
  of spread 4, false of spread 2, where a second trigger (no spine found in the
  detected book) asked the model and used its box to aim the gutter search. The
  pixels cut were the detector's on both.
- **OPEN_PROBLEMS P1 experiment 4's cue is dead as written** (it fires on
  neither spread); a three-edge variant is unmeasured. Experiment 1 is closed.
  The fix available today for spreads 2 and 4 is a hand-drawn book box.
- **Correction, same day:** the white sheets do **not** set the box's right
  edge on spreads 2 and 4 — it sits in open sofa 150–350 px past the book, and
  the sheets are 650–870 px further out (RESULTS 2026-09-24, correction clause).
  Nor is it established that they caused spread 3's escape: its own search box
  is the whole frame. On spreads 2 and 4 the detector's paper mask runs to the
  left, top and bottom frame edges — it reads the sofa as paper there.
- **`split_eval` no longer needs `jobs/`.** The committed `de_01.jpg`/`de_02.jpg`
  decode pixel-identical to the gitignored anchors the two rows used to read
  (EXIF orientation ignored — their tags are spurious), so the
  `ANCHOR_OVERRIDE` special case is gone and both rows name their JPEG. Checked
  from a clean worktree with no `jobs/`: 21 of 21 graded, 19/21, 0.0 %
  (RESULTS 2026-09-24). Closes OPEN_PROBLEMS P1 experiment 2 and the P9
  "anchors outside the repo" debt.

### 2026-09-24 — pictures split in two: counted, and the continuity test refused

- **Handoff written for the phone session:** `docs/plans/sweep-to-panorama-handoff.md`
  (install, shoot one dense-text spread in sweep mode, fit the sweep gate,
  pre-register and run panorama Phase 2 on it). Stitching fixes resolution,
  not the wrong crop.
- **P3 census** (`tools/figure_continuity_census.py`, RESULTS 2026-09-24):
  pre-registration and eye labels committed before any score. 52 vertically
  stacked pairs, **21 real splits** (the old 45 does not reproduce; its method
  was never committed), none carrying a hi-res asset. The
  continuity statistic catches 18/20 but wrongly merges 4 (text panels over
  thumbnails, wide photos over narrow blocks) → **FAIL, refused**. Next is a
  two-question local-model check graded against the committed labels.
- Same-day correction (RESULTS): three of the four wrong merges have a real
  boundary 6–9 px outside the checked band (loose detector boxes); no
  threshold rescues the rule.

### 2026-09-24 — pictures split in two: the local model asked twice, refused too

- **Pre-registered before any graded pair was asked** (commit c779758): two
  frozen prompts, 13 distinct pictures committed so the map's 7 pairs cannot
  carry recall, both questions on every pair, two draws. A first second question
  (margin bars) was dropped on out-of-population probes and says so.
- **FAIL** (RESULTS 2026-09-24): 10 of 13 pictures restored, 37/37 controls
  whole, 0 unreadable, 0 flips. But **10 of 34 separate pairs merged**, 4 of
  them off the sofa: a hut photo glued to its information panel ("a caption"),
  and pairs with a 21–24 px sliver where "ONE" describes the big block. The
  seam question alone is nearly blind (17 of 34 wrong).
- Observed after scoring: the model's and the pixel rule's wrong merges are
  disjoint, so requiring both would be clean on these labels. That choice was
  made after seeing the errors → a hypothesis for a second book, not a result.
- P3 now ranks the operator's lever first: a "merge with the figure below"
  action in the editor, which does not exist yet.

### 2026-09-24 — pictures split in two: the operator's merge button

- **Built** in the editor page (so both `pipeline/editor.py` and the console
  have it): "Merge with the picture below" on a selected picture, and a picker
  for any other picture on the page. The split rules hold in reverse — the
  selected block keeps its id, nothing is allocated, the removed pieces'
  captions are re-pointed, `structure_edited` is set by hand, nobody else is
  renumbered (a gap is left; renumbering would clear order-review markers).
- **Pull-in:** a picture the joined box overlaps joins in the same click and is
  named on the button; the joined box is outlined on the page before the click.
  Surface-flagged blocks never join and cannot be merged. A caption on another
  page pointing at a piece that would vanish blocks the merge (undo only covers
  the current page). Warnings before the click: two captions on one picture,
  different printed figure numbers, text that newly lands inside or across the
  picture, a close-up asset that stops being used, a caption held only by
  adjacency that would come loose.
- **Checked** (RESULTS 2026-09-24): `tools/figure_merge_check.py` drives the
  real page over a copy of the owner's job — 13/13 labelled pictures rejoined
  exactly, 15 clicks, 0 pieces taken in by mistake, 143 → 123 rendered
  pictures. One wart: a junk OCR block inside the page-23 map is painted out as
  a pale patch; needs a "delete block" action.
- Tests: 7 new in `pipeline/tests/test_editor.py` (3 Python-layer: the merged
  shape survives normalize + PUT, reads as edited, renders as one picture with
  the re-pointed caption from the page crop rather than the stale close-up;
  4 browser: merge below, pull-in, refusals, picker + undo).

### 2026-09-24 — sofa crop: the "three frame edges" cue

- Pre-registered, eye-labelled 38 phone frames before computing, then ran it
  (RESULTS 2026-09-24, "three frame edges"). All gates pass; fires on spreads
  2 and 4 only; 0 false fires — but no frame that could false-fire ever
  reaches the cue (tight scans abstain earlier), and the positives are one
  scene. Shipped as `book_crop.three_edge_abstain`, **off**.
- Not a fix: with it on, the sofa spreads get no crop instead of a wrong one.
- Found: spread 21 (dark chair) is a wrong crop touching two edges (a cushion
  kept on the left) — mode (c) is not only a pale-surface failure; costs no
  content.
- Asked the local model for spread 4's box for the first time: right, and tight.

### 2026-09-24 — sofa crop: "model box ∪ paper mask" refused offline

- P1 experiment 3's option 1, pre-registered and computed from recorded boxes.
  On every target frame (both pale rows, sofa spreads 1–4) the guarded box is
  ≥ 83 % of the frame or the same three-sided sofa crop; it also leaves
  `de_02`'s 1.89 % clip untouched. Refused, no code. The model box cutting now
  waits on the owner's clipping-bar decision and the fixture shoot.

### 2026-09-24 — figure upgrades closed; table columns refused; sofa checkbox

- P7: assembled the owner's book twice on a copy — identical to each other and
  to 2026-08-29 (24, no decode failures). The missing 25th is an icon panel
  `unreadable_panel` turns into a picture after the hires pass ran. A fix that
  searched converted panels was built, then REVERTED: rendered, its one upgrade
  is softer than the page crop (the checkerboard had been misread). A census of
  the 24 shipped upgrades: 6 measure softer; by eye at least 4 are. Nothing
  measures focus; P7 reopened on that.
- P6: columns from the psm-6 re-read, pre-registered — refused (the target
  still reads as one column; a two-line block grids 2 × 6). Code removed.
- Editor: "not part of the book — do not print" checkbox in the block
  inspector (clears or sets `is_surface`, marks the block hand-edited, undoable).
  Browser test `test_e2e_clear_the_surface_flag`.

### 2026-09-24 — editor: "Delete block" (reversible)

- `Block.deleted` (schema, set only by the editor): a hide, not a removal; the
  block keeps its words and place and "Restore" puts it back. Stage 08 (v0.4.0)
  drops deleted blocks before caption binding, the adjacency fallback and the
  figure text mask, so a deleted block neither prints, binds as a caption, nor
  paints a patch into a picture. `normalize_edits` marks it hand-edited
  server-side. Editor: Delete/Restore in the inspector with what the delete will
  do, dotted outline, struck-through row; every pairing/merge/split/review helper
  skips deleted blocks the way the renderer does; a caption whose picture was
  deleted is marked ("figure gone").
- Side effect, pinned by a test: a caption with no pairing that followed a
  deleted block now sits next to the picture before it and is grouped with it.
- Checked on a copy of the owner's job (`tools/delete_block_check.py`, RESULTS
  2026-09-24): the P3 wart on `page_023__right` is gone — #15's text no longer
  prints and the map shows "15A" where the patch was.

### 2026-09-24 — editor: guessed caption pairs are marked for checking

- The P10 line "grouping review not built" was stale: pairing/unpairing and the
  "will print alone" marker already existed. Added the missing half the
  `PairSource` docstring anticipated: a caption paired by `geometry` or
  `sole_figure` is marked "pair: guessed — check" (page outline, list dot, a
  per-page bar) with **Confirm pair**, which stamps `pair_source = user` on the
  same picture. Number pairs are left alone; no bulk confirm. No schema change.
  On a copy of the owner's job: 8 guessed pairs marked, 12 unpaired captions
  marked (unchanged). Whether the 8 are right is the owner's look.

### 2026-09-24 — PDF import, Slice 1

- `pipeline/pdf_import.py`: a PDF becomes a job, one `page_NNN/raw/frame_00.png`
  per PDF page, rendered (never extracted) at a recorded dpi (300). Wider than
  tall → spread, else single, written to `page_NNN/page_layout.json` with its
  provenance and overridable with `--layout`. A page whose images cover < 90 %
  of it (union, so tiled scans count and an invisible OCR layer does not
  matter) is not a scan and refuses the import, naming the pages; encrypted
  and unreadable files refuse too. All or nothing: rendered in a staging folder
  under `W:\temp\claude`, copied in with frames under `raw.importing/` (the
  console's startup scan ignores them), renamed to `raw/` only when every page
  is in, `job.json` last. `--dry-run` prints each page's verdict and the size.
- Stage 02 v0.6.0: reads `page_layout.json` (a new documented exception, like
  the book box). `single` → whole frame as `single.png`, no spine search, no
  book detection, operator box still wins, per-page source skipped with a
  warning. No file (every phone page) → unchanged; `split_eval` 19/21, 0.0 %.
- Checked end to end (`tools/pdf_import_check.py`, RESULTS 2026-09-24): the
  imported spread reads word-for-word like the direct photograph; a declared
  single page reaches the render as `page_002__single`.
- Not built: the console button (Slice 2), the text layer as a second opinion
  (Slice 3). Known wart: Stage 00 warns "result is PORTRAIT" on every imported
  single page.

### 2026-09-24 — PDF import, follow-ups from review

- **Rotated pages were refused (bug, fixed).** Image boxes come back in the
  page's unrotated space; a scan stored with `/Rotate 90` measured 71 % image
  coverage and would have refused the whole import. Boxes are now turned into
  the displayed page first: 100 % at 90/180/270, and the spread/single call
  follows the displayed shape. Test `test_a_rotated_scan_is_a_scan_...`.
- **The console does not see an import while it is running.** Its queue is in
  memory and filled from disk only at startup (`server/reconcile.py`). The CLI
  message and the docs now say so; `server/tests/test_pdf_import_reconcile.py`
  pins that the startup scan finds every imported page and none mid-publish.
- Job ids now follow the server's rule (no dots); the staging folder comes from
  `paths.import_staging` in config.yaml (OS temp dir if that drive is absent).
- Deleted blocks: `Block.order_review_visible` now skips them like the editor
  does, and Stage 08's meta counts (blocks, words, flags, figures, unreviewed)
  count only what renders.

### 2026-09-24 — PDF import, Slice 2: the console's Import PDF button

- **What the operator does:** jobs list → *Import PDF* → choose the file (and a
  resolution, 300 dpi by default) → *Check*. The console lists every page: its
  pixel size, wide or tall, how much of it is picture, and the spread/single
  guess with a per-page selector (plus "set every page to"). Pages made by
  software are named in red and need an explicit "import anyway" tick. Mode and
  OCR language are chosen on the same screen. *Import* renders the pages with
  a progress bar; when the last page is in, the job appears and every page is
  queued on the worker at once — **no restart**.
- `server/routes_import.py`: upload + survey (`POST /api/imports`, creates no
  job), start (`POST /api/imports/{token}/start`), progress (`GET`), discard
  (`DELETE`). It calls `pdf_import.import_pdf` unchanged, so every refusal and
  the all-or-nothing publish are the importer's. One import renders at a time
  (409 otherwise). A shutdown mid-render stops after the current page and
  publishes nothing. Uploads live beside the importer's staging folder, never
  inside it (`import_pdf` wipes `<staging>/<job_id>`), and keep the PDF's own
  (sanitised) name, which `import.json` records.
- `pdf_import`: `page_layouts` (per-page override, provenance `operator`) and an
  `on_page` progress callback; with neither, the output is byte-identical
  (tested). Also fixed: on Windows a PDF that MuPDF failed to open stayed locked
  while the error was alive, so a refused upload could not be deleted (measured
  WinError 32); the refusal is now raised unchained, outside the handler.
- **Not added, on purpose:** a runtime "rescan for new pages". The phone upload
  writes `raw/` a moment before it enqueues, so a rescan landing in that gap
  would run the page twice. A CLI import still waits for the console's next
  start, and the CLI says so.
- Verified in a real browser (Playwright, a throwaway jobs folder) on a two-page
  cut of a real ABBYY-produced scan: check → per-page change → reload keeps the
  checked PDF → import → job page with pages running/queued → both pages done
  through Stage 06 in ~20 s each. Suite 809 passed.

### 2026-09-24 — PDF import, Slice 3 measured: the PDF's hidden text as a second opinion

- Pre-registered first (`docs/data/pdf_textlayer_prereg_20260924.md`, committed
  before any disagreement existed; one addendum before labelling, because the
  control's only disagreements fell on already-flagged words). Tool
  `tools/pdf_textlayer_eval.py` (prepare / sites / score); data in
  `docs/data/pdf_textlayer_20260924/`.
- 7 English documents from 7 text-layer producers, 20 pages, the shipped
  pipeline; the layer aligned by word sequence (Stage 03 moves the words, so
  its boxes are useless); 71 disagreements judged blind.
- **Gate passes for the raw trigger** (48 catches, 16 false alarms, 0.75, four
  documents at ≥ 0.50); the dictionary-gated version is refused (5 catches). The
  control was clean (0 of 4 disagreements invented by the method).
- **But the catches are notation**: both engines wrong at 35 of 48 (subscripts,
  Greek, code zeros), one chemistry paper gives 20; on plain words the layer is
  wrong more often than Tesseract (ABBYY read "the" as "die" six times in one
  report). Without that paper the gate's per-document clause fails.
- **Agreement is not evidence**: 23 % of flagged words the layer agrees with are
  still wrong. The layer must never clear a flag and never supply text.
- **Found on the way:** Stage 03 (UVDoc) enlarges an already-flat scan and cuts
  line starts on a thin-margin page (2 of 20 pages; 40 and 16 words). Open.
- Not built: whether to ship the raw trigger for imported PDFs is the owner's
  call; the measurement says it would add ~3 flags a page, three in four right,
  almost all in formulas.
- **Correction, same day:** "without that paper the gate's per-document clause
  fails" was wrong as worded — the clause passes at exactly 4 of 5, so losing
  ANY passing document fails it; the chemistry paper is special only in carrying
  20 of the 48 catches. The edge count is a lower bound, and at the top/bottom it
  finds 3 more pages with one word at the edge. The blinding leaked slightly (the
  red box is always Tesseract's). RESULTS carries the correction clause.

### 2026-09-24 — Text-layer marker built; white border refused; skip-flattening measured

- **Owner's decisions:** build the raw text-layer trigger; fix edge cutting with
  a white border.
- **Marker built** (`pipeline/pdf_text_layer.py`, `Word.layer_disagree`, schema in
  its own commit): the importer saves each page's hidden words as
  `pdf_text_layer.json` (page-root input, documented in CLAUDE.md) and marks every
  page `origin: pdf_import`; Stage 05 aligns and marks, Stage 06 ORs it in. The
  eval tool now imports the same code; a replay reproduces all 71 labelled sites
  and every page's counts, and a Stage 05+06 re-run on a copy marks exactly those
  words. Abstains outside the measured population (English, ≥ 150 layer words,
  coverage ≥ 0.42).
- **White border refused** at both pre-registered widths (15 %, 25 %): edge cuts
  60 → 0, but UVDoc then bends flat pages; other pages lose 3–5 % of agreeing
  words, one page 24 %. The Stage 03 code was reverted, never committed.
- **Skip flattening for imported pages** (the prereg's named next arm, addendum
  before numbers) passes every clause; not shipped — the owner's call, and the
  cost on a crooked scan is unmeasured.
- The marker's measured precision belongs to today's Stage 03 output: on the
  changed pages about 30 of 71 judged spots disappear and ~20 new ones appear.
- **Correction, same day:** the "other pages" figure was over 18 pages, not the
  registered 22; recomputed (15 % −2.60 %, 25 % −4.88 %, skip +0.73 %), no
  verdict changes. A direct count shows skipping flattening restores all 24
  cut-off words on D6 (the agreement count had understated it).

### 2026-09-24 — Imported pages not flattened (shipped); text-layer marker switched off

- **Owner: "ship it".** Stage 03 v0.3.0 writes an imported page unchanged (keyed on
  `layout_origin`, the importer's marker); UVDoc is not loaded for it. The shipped
  code reproduces the measured skip arm exactly on all 24 test pages.
- **Marker re-judged on those pages** (addendum 2, written before labels; 21 new
  sites judged blind by a fresh helper): 35 catches / 23 false alarms, 3 of 5
  documents at ≥ 0.50 → fails. D3 lost four catches because Tesseract now reads
  them right. **Switched off in config.yaml** by the rule fixed in advance; code
  kept; owner's call to turn it back on.
