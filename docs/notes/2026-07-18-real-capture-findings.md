# Real-capture pipeline findings — 2026-07-18

First run of the pipeline (stages 00→08) on **real multi-frame phone captures of
2-page book spreads**, as opposed to the flat single-page `testset/` fixtures.
Three 3-frame sets, dropped in `1/2/{1,2,3}/`:

| Set | Job | Language | Content |
|---|---|---|---|
| 1 | `realtest_de1` (+ `realtest_de1_fixed`) | German + English | Alpine via-ferrata guide *Latemartürme-Klettersteig* — banners, icon sidebar, parallel DE/EN columns, stacked photos |
| 2 | `realtest_de2` | German + English | Alpine guide *Rotwandklettersteig* — same layout + hand-drawn topo map |
| 3 | `realtest_bg` | Bulgarian | Plain 2-page prose spread (Taleb, *The Black Swan*), Cyrillic |

All jobs live under `jobs/` (gitignored). Command shape:
`python -m pipeline.run_all --input 1/2/<n> --job <job> --lang <deu+eng|bul> --mode flag`
then `stage07_assemble` + `stage08_render`.

## What worked (real-capture positives)

- **Cyrillic OCR is genuinely good.** `realtest_bg`: 607 words, e.g.
  *"нието – ако искате да докажете, че експерти не съществува…"* matches the page
  with only minor errors ("борсови подев ци" for "борсови посредници"). End-to-end
  to searchable PDF, 72 words flagged.
- **German/English prose OCR is good** once the page is correctly oriented
  (`realtest_de1_fixed`): *"Besonderheiten: Prachtferrata unweit des Karerpasses…"*,
  *"This gorgeous 1.4 km long ferrata crosses up and down…"*.
- **DocLayout-YOLO segments the ornate German page well** once oriented — clean
  multi-block detection of paragraphs, photos (figures), and titles. The layout
  *detector* is not the German failure; orientation is (see Finding 1).

## Finding 1 — Stage 00 orientation is fragile on figure-heavy flat captures (CRITICAL)

**Symptom.** Both German sets ingested as **portrait 3000×4000 rotated 90°**
(spine horizontal). On the sideways page DocLayout-YOLO collapsed to
`blocks=1` ("layout unusable"), cascading into OCR garbage. The Bulgarian set
ingested correctly as landscape 4000×3000.

**Root cause.** The phone JPEGs are stored as 4000×3000 landscape pixels that are
*already upright* (a viewer that ignores EXIF shows a readable spread), but they
carry a **spurious EXIF Orientation tag** (set 1 = 6, set 2 = 8, set 3 = 6 —
looks like a gyro-confused down-shot). Stage 00's `exif_transpose` honours that
tag and rotates the correct landscape into sideways portrait. Stage 00 then tries
to rescue orientation with Tesseract OSD, but OSD confidence was **0.04–1.46**
(below the 2.0 trust gate) on the figure-heavy German pages, so no rescue — while
the text-dense Bulgarian page cleared the gate and was rescued.

**Proof it is orientation, not layout.** Re-saving set 1's raw pixels with the
EXIF tag stripped (`realtest_de1_fixed`) flips DocLayout-YOLO from **`blocks=1`
→ `blocks=16`** with excellent segmentation. Single variable changed.

**This is a root-cause diagnosis, not an adopted fix.** "Strip EXIF universally"
would corrupt any capture whose EXIF is genuinely correct. The fix is an
orientation *policy* decision (options for the owner):
1. **OSD-first / EXIF-as-tiebreak** — trust content-based OSD over the gyro tag
   when they disagree; only fall back to EXIF when OSD is low-confidence.
2. **Text-baseline orientation detection** — cheap Hough/projection check for
   which axis the text lines run along; robust on figure pages where OSD is weak.
3. **"Flat-capture" heuristic** — treat near-zero device tilt (or a book-scan
   capture mode from the Android app) as "trust raw pixels, ignore EXIF".
   The Android capture app (Gate 5) can also stamp a reliable orientation.

## Finding 2 — Stage 02 gutter split never fires on real curved spreads (HIGH) — FIXED 2026-07-18

**Fix (Stage 02 v0.2.0).** Added a second cue as a priority layer below the ink
valley (mirrors the Finding-1 orientation cascade): the **spine pinch**. An open
book photographed from above has its paper outline eaten in at the binding (top
edge dips, bottom edge rises), so the per-column vertical EXTENT of the bright
page region (Otsu page/background split) has a minimum right at the gutter. This
cue is content-independent — it survives figure-heavy pages where the ink valley
AND the binding shadow both fail — and, crucially, the very curvature that kills
the ink valley is what CREATES the pinch. Resolver = **ink-first, pinch-second**:
Layer 1 (ink) wins outright when confident, so all 13 flat testset spreads keep
byte-identical splits (non-regression by construction); Layer 2 (pinch, gate
depth ≥ 0.11) only runs when ink failed. Calibrated on the testset: flat spreads
pinch ≤ 0.09, the three curved spreads pinch 0.14–0.18 (clean gap). New
`testset/gt/gutter.json` + `tools/split_eval.py`: **15/15 spreads correct**
(13 ink, unchanged; de_01/de_02 now split via pinch at x≈1983/2047). Binding
shadow is kept as corroboration only (drifts onto a dark photo on de_01 → that
split is honestly flagged uncorroborated but lands correctly). Downstream proof:
re-running 02→05 on the Taleb spread de-scrambles reading order — all four
left-page (224) paragraphs now precede every right-page (225) paragraph; the
documented cross-gutter jump ("Друг начин" as block 2) is gone. Otsu dark-bg
assumption recorded in `meta.warnings`.

**Symptom (original).** All three real spreads emitted `single.png` — no confident
gutter (valley/page_ref = **0.80 / 0.85 / 0.91 / 0.93**, all above the 0.55
threshold). The two facing pages are then processed as one image.

**Consequence.** Reading order scrambles across the gutter. `realtest_bg` block
order pulls the **top-right** column in right after the **top-left** one
(block 1 = "нието…" left, block 2 = "[Др]уг начин…" right), i.e. it reads across
the spine instead of down the left page first.

**Why the testset never caught it.** Every Stage-02 warning already says the
testset is "one full-spread frame per page" and "single.png branch untested". The
real gutters are curved and shadowed, so the projection-profile valley is shallow
relative to the page and never clears the confident-gutter bar.

## Finding 3 — Block typing + reading order weak on the icon-sidebar/multi-column German page (MEDIUM)

Even with `realtest_de1_fixed` (correctly oriented, 22 blocks assembled):

- **Icon sidebar → junk words interleaved into the flow.** The star-rating /
  difficulty / duration / GPS pictogram panel OCRs into scattered noise blocks
  ("a ER", "Wa", "PM. 12).", "NN Juni – ARH Sept.") that land *early* in reading
  order. The panel is not recognised as a structured info-box to lift out or skip.
- **Within-column order inverted on the right page.** German column emitted
  Route → Zustieg → Anreise; the page order top-to-bottom is Anreise → Zustieg →
  Route. (DE and EN columns do *not* badly interleave — English clusters at the
  end, roughly correct.)
- A same-page ordering wrinkle also shows on the Bulgarian left page (the two
  "Експерти…" paragraphs are swapped) — an XY-Cut ordering issue independent of
  the gutter, so Finding 2 is not the whole reading-order story.

## Recommendation — promote these as regression fixtures (highest leverage)

These three captures break precisely the paths the current `testset/` **cannot
structurally reach** (spurious EXIF, curved 2-page gutter, multi-frame capture,
icon-sidebar layout, DE/EN parallel columns). Their single most useful role is as
**permanent regression fixtures for orientation (Finding 1) and gutter-split
(Finding 2)** — the two real-capture gaps every stage warning has been flagging.
Promotion needs ground-truth transcription/orientation/gutter labels
(append-only per `testset/README.md`); worth doing for at least one German + the
Bulgarian spread before touching the orientation/gutter code, so the fixes have a
measurable target.

Suggested next step order: (1) pick an orientation policy for Finding 1;
(2) promote 1–2 of these to `testset/` with GT; (3) fix gutter split against them.
