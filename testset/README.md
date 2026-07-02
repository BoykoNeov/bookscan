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

## Required composition (Gate 1)

| ID prefix       | Content                                                  | Count      |
|-----------------|----------------------------------------------------------|------------|
| `en_clean_*`    | modern English book, clean single/double column          | 5 spreads  |
| `bg_*`          | Bulgarian (Cyrillic) pages                                | 3 spreads  |
| `it_*`          | Italian pages                                            | 2 spreads  |
| `de_*`          | German pages                                             | 2 spreads  |
| `en_multicol_*` | multi-column or footnote-heavy English page              | 2 spreads  |
| `en_figures_*`  | pages with images + captions                             | 2 spreads  |
| `old_*`         | older book / worn typeface                               | 2 spreads  |
| `zoomset_*`     | 1 full-spread anchor + 4 quadrant close-ups (same spread)| 3–4 sets   |

Ground truth required for **≥5 pages** (≥2 English, ≥1 Bulgarian, ≥1 with
footnotes).

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
