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
- **Orientation GT** (a third GT type) lives in `gt/orientation.json`: one entry
  per `image_id` giving the spread's correct **upright** orientation, independent
  of its (often spurious) EXIF tag — `upright_aspect` (always `landscape` for a
  book spread), `raw_is_upright` (the stored buffer is already upright, so the
  resolver must apply net-0 rotation and ignore the EXIF), and the
  `exif_orientation` actually present. This is the ground truth for the Stage 00
  orientation resolver (`tools/normalize`). Every capture from this owner's phone
  carries a spurious `EXIF=6/8` on already-upright landscape pixels (14×6, 1×8),
  so `exif_transpose` alone rotates them sideways; the file both pins the two
  `de_*` orientation-break fixtures (figure-heavy → OSD can't rescue) and guards
  that the resolver keeps the existing OSD-rescued spreads upright. Checked by the
  `tools/normalize` orientation test.

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
| `de_*`        | German (via-ferrata guide): banners + icon sidebar + parallel DE/EN cols | 2 spreads | `01`, `02` (orientation) |

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

## Multi-view skew sets (`skewset_*`) — added 2026-08-18

A **different shape of fixture** from everything above, and the reason it needs its
own section: an entry is a **set of frames of ONE spread from different
viewpoints**, not a single capture. It exists for the multi-view curvature effort
(`docs/plans/multiview-curvature.md`), whose Phase 1 could not be validated because
five merge policies had been compared on the same three pages that carried the
ground truth.

Read together with:
- `docs/plans/multiview-phase1-prereg.md` — the **pre-registered** claims. Written
  and committed *before* any ground truth was keyed on these images, so that
  choosing a policy on them is not possible after the fact.
- the `docs/RESULTS.md` row of 2026-08-18 — how the sets were chosen out of 97
  captures, and the four corrections made on the way.
- `testset/skewset_manifest.json` — per-set anchor/candidate, orientation pin,
  hand-read page crop, and the GT-free headroom numbers that justified selection.

| id | language | book | curl | role |
|---|---|---|---|---|
| `skewset_en_01` | english | *Chopmarked Coins* p.12 | strong | **win case** — clearest headroom; a clean complementary-halves pair |
| `skewset_en_02` | english | *Chopmarked Coins* p.191 | strong | **guard case** — large but symmetric exchange; where an over-eager policy shows itself |
| `skewset_it_01` | italian | Italian via-ferrata atlas p.62 (a **new** book, not `it_geo_*`) | strong | **win case** — the Italian arm |
| `skewset_de_01` | german | German via-ferrata guide pp.40-41 (same book as `de_*`) | mild | **declared no-headroom control** — only ~7 tokens of gain; a flat result here is expected, not a failure |
| `skewset_orient_01` | italian | — | — | orientation fixture: OSD 180° accepted at conf 2.58. **Not usable as a multi-view pair** for a second reason: 134655 is a page-*turn* shot, so it photographs different content (0–1 word correspondences) |
| `skewset_orient_02` | italian | — | — | orientation fixture: text-free panorama, OSD conf 0.24; also the "don't wreck a photo page" guard |

**Anchor vs candidate is decided by measurement, not by capture order.** The anchor
is the frame reading the most dictionary-valid tokens — the face-on view production
would feed Stage 03, and the frame the band GT is keyed on. On `skewset_it_01` the
first frame in time is the *oblique* one, which is exactly why this is recorded per
set rather than inferred.

**Orientation is pinned per set**, because the shipped resolver disagrees with
itself across frames of one spread on the two `skewset_orient_*` sets: an OSD call
at conf 2.6–3.1 is trusted (`DEFAULT_MIN_OSD_CONF = 2.0`) and a 180° error is
invisible to the landscape prior, since a rotated spread is still landscape. Those
two sets are in `gt/orientation.json` as fixtures for that defect. **The resolver
was reported, not patched**, when these were added.

**Stated limits, so nobody quotes these further than they go:**
- **No ground truth is keyed yet.** No arm has been scored on these images. The
  headroom numbers in the manifest are a GT-free *dictionary proxy* — they rank
  sets, they do not score arms.
- **No Bulgarian.** The Cyrillic arm of the multi-view claim is unvalidated.
- **`skewset_de_01` has essentially no headroom** and is labelled a control, not a
  win case. The German book is a figure-heavy guide, so on the target page the
  candidate view gains only **7** valid gutter tokens (net −6), and its Gate B
  gutter-correspondence count sits exactly on the floor of 12. A German result off
  it will be noisy either way; the fix is a German book with continuous text, not
  more frames of this one.
- **Selection numbers were corrected once.** The sets were chosen on a band pooling
  both inner margins of the spread; the GT band is per-page, and re-measuring moved
  two of the four. See RESULTS 2026-08-18 "Correction 4" — trust
  `headroom_perpage` in the manifest, not `headroom_gutter`.
- Page crops are **hand-specified** (three automatic routes were measured and
  rejected on this batch), so reproducing the measurement means using the
  `page_crop` boxes in the manifest, not re-deriving them.
