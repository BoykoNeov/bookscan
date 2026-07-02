# testset — fixed OCR benchmark

Manually captured phone photos of book pages + ground truth. **All future
gates benchmark against this same set**, so it is the project's regression
anchor.

## Rules (IMPORTANT)

- **Append-only.** Never edit, re-shoot, or overwrite an existing image in
  place. If a capture is bad, add a NEW `image_id` — never mutate an old one.
- Source images are tracked in git. `debug/` overlays are regenerable and
  gitignored.
- Ground truth lives in `gt/<image_id>.txt`: exact page text in reading order,
  one paragraph per line, hyphenated line-breaks joined. Hand-typed or copied
  from an ebook edition of the same book.

## Composition

Each image is a **full two-page spread** (the pipeline's Stage 02 does the
gutter split; Gate 1 deliberately measures raw Tesseract on the captured
spread, before split/dewarp).

### Captured so far (first batch)

| ID prefix     | Content                                            | Count     | GT           |
|---------------|----------------------------------------------------|-----------|--------------|
| `en_coins_*`  | English (*Chopmarked Coins*): body + coin figs/caps + footnotes | 3 spreads | `01`, `03` |
| `bg_*`        | Bulgarian (Cyrillic) history: clean single-column  | 3 spreads | `01`         |
| `it_geo_*`    | Italian (Dolomites geology): main col + figure sidebars | 3 spreads | —       |

Ground truth is present for **6 pages** (4 English + 2 Bulgarian, all with
footnotes) — clears the ≥5-page / ≥2-English / ≥1-Bulgarian / ≥1-footnote bar.
GT is **hand-transcribed from the photos** (noted in `manifest.csv`), not from
an ebook edition.

### Still targeted (append later as new ids)

| ID prefix     | Content                                                   | Count    |
|---------------|-----------------------------------------------------------|----------|
| `de_*`        | German pages                                               | 2 spreads |
| `en_multicol_*` | a genuine multi-column English page                     | 2 spreads |
| `old_*`       | older book / worn typeface                                 | 2 spreads |
| `zoomset_*`   | 1 full-spread anchor + 4 quadrant close-ups (same spread)  | 3–4 sets |

**Reading-order note:** Bulgarian spreads OCR in correct order (two clean
single columns). English/Italian spreads have figure-caption sidebars that make
raw Tesseract scramble reading order — a Stage 02/04 layout problem, not a
recognition one; it inflates WER on those spreads.

## Layout

```
testset/
  manifest.csv          # image_id, file, language, gt_file, category, notes
  <image files>         # the captures (append-only)
  gt/<image_id>.txt     # ground-truth text (reading order, hyphens joined)
  debug/                # harness-generated overlays (gitignored)
```

## manifest.csv columns

`image_id, file, language, gt_file (optional), category, notes`
