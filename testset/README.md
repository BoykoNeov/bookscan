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
- **Block-order GT** (a second, distinct GT type) lives in
  `gt/<image_id>.blocks.json`: per-subpage block **segmentation + type +
  reading order**, anchored by first-words (no verbatim text, no bboxes). This
  is the ground truth for the Stage-04 reading-order / multi-column proof —
  WER is deliberately NOT used for it (WER on figure-sidebar spreads conflates
  layout scramble with recognition). Graded **per subpage** (Stage 02 splits
  the spread first) by matching each anchor to a detected block via text
  overlap. Block-order fixtures (all owner-validated 2026-07-03), each isolating
  a distinct layout failure mode:
  - `it_geo_04` — **reading-order**: genuine multi-column (2 prose cols + gutter
    caption col) + cross-gutter panorama. The first multi-column proof.
  - `it_geo_05` — **embedded caption**: a full-page watercolor map whose caption
    (C2) sits in the lower-left *inside* the figure bbox, so the detector
    swallows it (segmentation miss). Contrast C3 on the facing page (separate
    gutter column, detected fine).
  - `it_geo_06` — **grouping**: the first page with **≥2 figures sharing one
    column** (LEFT subpage: 4 figures + a 4-caption stack), so caption↔figure
    grouping is genuinely *discriminated*; the caption-stack order is
    **number-keyed** (C26 mispairs by geometry — correct pairing needs reading
    "Figura NN"). Exposes the detector's figure-merge + caption-mistyping gap.
  - `it_geo_07` — **reading order past N=1**: a multi-panel evolutionary schema
    where each stage is a diagram + two-column text (Tn-mid then Tn-right), so
    Kendall-tau catches **row-major vs column-major** slippage. + chronology
    table + 3-column inset.

  Graded by `tools/layout_order_eval.py` (the sequence-order + grouping metric).

## Composition

Each image is a **full two-page spread** (the pipeline's Stage 02 does the
gutter split; Gate 1 deliberately measures raw Tesseract on the captured
spread, before split/dewarp).

### Captured so far (first batch)

| ID prefix     | Content                                            | Count     | GT           |
|---------------|----------------------------------------------------|-----------|--------------|
| `en_coins_*`  | English (*Chopmarked Coins*): body + coin figs/caps + footnotes | 3 spreads | `01` |
| `bg_*`        | Bulgarian (Cyrillic) history: clean single-column  | 3 spreads | `01`, `02`   |
| `it_geo_*`    | Italian (Dolomites/Veneto geology): main col + figure sidebars | 7 spreads | `04`, `05`, `06`, `07` (block-order) |

Ground truth is present for **6 pages** (2 English + 4 Bulgarian, all with
footnotes) — clears the ≥5-page / ≥2-English / ≥1-Bulgarian / ≥1-footnote bar.
GT is **hand-transcribed from the photos** (noted in `manifest.csv`), not from
an ebook edition. `en_coins_03` is intentionally left without GT: Tesseract
interleaves its two facing pages (Hawai'i / Honduras) line-by-line, so a
sequence-based WER against reading-order GT would measure layout scramble, not
recognition. `bg_02` is the second Bulgarian datapoint (clean recognition,
mild justified-line-split scramble); `bg_01` is the pristine one.

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
