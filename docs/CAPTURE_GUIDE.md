# Gate 1 capture cheat-sheet

How to shoot the `testset/` photos and write ground truth so the OCR harness
measures **Tesseract, not your photography**. Follow this once; the set is
append-only and every future gate benchmarks against it.

Companion to [`GATE1_SPEC.md`](GATE1_SPEC.md). When done, run:

```bash
python -m tools.gate1_harness --testset testset/ --report docs/RESULTS.md
```

---

## 0. Which app

Your phone's **built-in Camera app, plain Photo mode**. Nothing special, no
extra install. Just:

- **iPhone:** default Camera, **Photo** mode. Turn **Live Photo off**; ideally
  set Formats → *Most Compatible* (JPEG) so ingest is trivial.
- **Android:** default Camera, **Photo** mode.
- **NOT a scanner app** and **NOT "Document/Scan" mode** (Adobe Scan, Microsoft
  Lens, CamScanner, Apple Notes / Google Drive scan). Those auto-crop,
  binarize, sharpen and force-flatten — exactly the preprocessing the pipeline
  is supposed to own. Feeding it a pre-"scanned" image contaminates the
  baseline. Plain photo only; the pipeline does the flattening later.

**These don't need to be studio shots.** Real handheld photos in ordinary
indoor light — a bit of page curl, a gentle angle, a soft shadow — are the
*design target*, not a problem to eliminate. The checklist below improves a
Gate-1 baseline at the margin; it is not a bar you must clear before shooting.
The first real testset (`en_coins_*`, `bg_*`, `it_geo_*`) was shot exactly this
way and reads fine.

## 1. How to shoot a page (the 60-second checklist)

**Light — helps, but don't chase perfection.**
- Bright, **even, diffuse** light. Best: near a window with indirect daylight,
  or two lamps at ~45° from the left and right.
- **Kill glare.** No single overhead point light on glossy/coated pages — it
  burns a hotspot that erases text. Tilt the book, not the phone, to move a
  reflection off the text.
- No shadow of your phone/hand across the page.

**Geometry.**
- Phone **directly overhead**, sensor plane **parallel** to the page (look for
  the "square" — avoid keystone/trapezoid perspective).
- Fill the frame with the page, leaving a small margin. One page (or one clean
  spread) per shot.
- Press the spread as flat as you can. Gutter curl is fine — later stages
  dewarp — but flatter = better Gate 1 baseline.

**Sharpness & resolution.**
- Use the **main (1×) lens at full resolution**. Do **not** digital-zoom —
  move the phone closer instead.
- **Tap to focus** on the text, wait for lock, then hold steady (brace elbows
  or use a 2-second timer to avoid shake).
- Before moving on, **pinch-zoom into the preview** and confirm individual
  letters are crisp. Aim for text roughly **≥25 px tall** in the final image
  (the harness auto-2×-upscales below 20 px, but native detail beats upscaling).

**Avoid:** motion blur, glare hotspots, finger/shadow over text, steep angles,
dim light (sensor noise), aggressive HDR/"scan" filters. Plain JPEG is fine;
RAW/DNG is a bonus, not required for Gate 1.

**Zoomsets** (`zoomset_*`): for one spread, take **1 full-spread anchor** frame
plus **4 quadrant close-ups** (top-left, top-right, bottom-left, bottom-right),
each close-up filling the frame with that quarter of the same spread. This
previews Gate 2's "do close-ups read better?" question.

---

## 2. Ground truth (`testset/gt/<image_id>.txt`)

Required for **≥5 pages**: **≥2 English, ≥1 Bulgarian, ≥1 with footnotes**.

- Plain **UTF-8** text file, named exactly `<image_id>.txt`.
- **Exact page text in reading order.** Multi-column → type the whole left
  column, then the whole right column. Footnotes → after the body text, in
  order.
- **One paragraph per line** (a paragraph = one long line, no manual wrapping).
- **Join hyphenated line-breaks:** a word split by line wrap (`encyclo-` /
  `pedia`) becomes one word (`encyclopedia`). Keep *real* hyphens
  (`well-being`).
- **Type what Tesseract will see:** if a page number or running header is
  printed on the page, include it (raw Tesseract reads it too — omitting it
  shows up as false errors). Be consistent.
- Source: hand-type, or copy from an ebook edition of the same book and fix any
  differences against the photo.

Fastest path: do ground truth for the 5 pages flagged in the template below,
capture the rest without GT (they still get word counts + confidence overlays).

---

## 3. Manifest — exact rows to fill

`testset/manifest.csv` columns: `image_id, file, language, gt_file, category, notes`
- `image_id` — stable id (also the GT filename stem).
- `file` — the image filename you drop into `testset/`.
- `language` — `english` / `bulgarian` / `italian` / `german` (or `eng/bul/ita/deu`).
- `gt_file` — path under `testset/` to the GT `.txt`, or blank if none.
- `category` — `clean` / `multicol` / `figures` / `old` / `zoomset` (drives the
  per-category table).
- `notes` — anything (book title, edition, lighting).

A ready-to-paste template is in
[`../testset/manifest_template.csv`](../testset/manifest_template.csv). Note the
template still lists the *aspirational* composition (German, `old`, `zoomset`,
etc.); the **first real batch is already ingested** — see the actual
[`../testset/manifest.csv`](../testset/manifest.csv). What we shot:

| ids | language | book | category | GT? |
|---|---|---|---|---|
| `en_coins_01..03` | English | *Chopmarked Coins* | figures + footnotes | `01` |
| `bg_01..03` | Bulgarian | history (Cyrillic) | clean single-col | `01`, `02` |
| `it_geo_01..03` | Italian | Dolomites geology | figures + sidebars | — |

Each image is a **full two-page spread** (not a single page), so 3 GT spreads =
**6 GT pages**: 2 English (`en_coins_01`) + 4 Bulgarian (`bg_01`, `bg_02`),
clearing the ≥5-page / ≥2-English / ≥1-Bulgarian / ≥1-footnote bar (all three
GT spreads carry footnotes). `en_coins_03` is deliberately GT-free — Tesseract
interleaves its two facing pages line-by-line, so sequence WER there would be
noise, not signal.

**Deferred (not yet captured):** German, `old`/worn typeface, `zoomset`
close-ups, and a true multi-column English page. Add these later as new ids —
the set is append-only.

**Reading-order caveat (Gate 2 preview).** Tesseract reads the Bulgarian
spreads in correct order (two clean single columns → left page then right).
But on the English coin pages and the Italian geology pages, the figure-caption
**sidebars** (Italian: one main text column with side blocks explaining each
figure) create false column boundaries, so raw Tesseract splices caption text
into the body flow and scrambles reading order. That inflates WER on those
spreads — it is a *layout* problem for Stage 02/04 to fix, not a recognition
failure. Judge raw OCR quality on `bg_*` and on the confidence-AUROC number.

---

## 4. Reading the result

`docs/RESULTS.md` gets a dated section per preprocessing variant, with the
per-language / per-category tables and a PASS / MIXED / FAIL verdict against the
gate's criteria. Also eyeball `testset/debug/<id>_*_conf.png` — word boxes
colored **green/yellow/red** by confidence — which is half the value of the
gate. A borderline verdict on hyphen-heavy English may be the labeling caveat
noted in the report, not real OCR failure.
