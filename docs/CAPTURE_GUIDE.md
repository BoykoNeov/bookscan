# Gate 1 capture cheat-sheet

How to shoot the `testset/` photos and write ground truth so the OCR harness
measures **Tesseract, not your photography**. Follow this once; the set is
append-only and every future gate benchmarks against it.

Companion to [`GATE1_SPEC.md`](GATE1_SPEC.md). When done, run:

```bash
python -m tools.gate1_harness --testset testset/ --report docs/RESULTS.md
```

---

## 1. How to shoot a page (the 60-second checklist)

**Light — the #1 factor.**
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

A ready-to-paste, pre-populated version is in
[`../testset/manifest_template.csv`](../testset/manifest_template.csv): shoot &
rename your photos to the listed `file` names (or edit the names), fill GT for
the 5 flagged rows, then copy it over `testset/manifest.csv`.

The template covers the spec's composition:

| category | ids | GT? |
|---|---|---|
| clean English | `en_clean_01..05` | `01`, `02` |
| Bulgarian | `bg_01..03` | `01` |
| Italian | `it_01..02` | — |
| German | `de_01..02` | `01` |
| multi-column / footnotes | `en_multicol_01..02` | `01` (the footnote page) |
| figures + captions | `en_figures_01..02` | — |
| old / worn typeface | `old_01..02` | — |
| zoomset (anchor + 4 quads) | `zoomset_01_{anchor,q1..q4}` ×3–4 sets | — |

That's 5 GT pages: 3 English (`en_clean_01`, `en_clean_02`, `en_multicol_01`),
1 Bulgarian (`bg_01`), 1 German (`de_01`) — with the footnote requirement met by
`en_multicol_01`.

---

## 4. Reading the result

`docs/RESULTS.md` gets a dated section per preprocessing variant, with the
per-language / per-category tables and a PASS / MIXED / FAIL verdict against the
gate's criteria. Also eyeball `testset/debug/<id>_*_conf.png` — word boxes
colored **green/yellow/red** by confidence — which is half the value of the
gate. A borderline verdict on hyphen-heavy English may be the labeling caveat
noted in the report, not real OCR failure.
