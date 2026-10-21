# Pre-registration — a local model reads the text the book loses, and does a second opinion flag its mistakes?

Written 2026-10-21, committed before any model reads any block. Owner's go-ahead the
same day: "aim close-ups at the tables and panels, and read those with the local
model plus that disagreement flag".

## Why

Since 2026-10-21 a model may write the text, on one condition: something must flag
its mistakes first (it misreads fluently and gives no confidence). The first
candidate the owner named is "mark every word where the model and Tesseract
disagree". The places the book loses text are its **tables** and the
**panels** that Stage 05 reads as noise and `unreadable_panel` turns into
pictures. Tesseract is weakest exactly there, so a Tesseract-based flag may fire
on every word and carry no information. This test measures both halves: how well
the model reads these blocks, and which second opinion actually separates its
right words from its wrong ones.

## Population (fixed before reading)

Every block of the owner's document (job `20260829-084115-de3c20d3`) that is a
TABLE or a FIGURE promoted from text (`type_promoted`): 28 blocks. Typed by eye
into strata (`panelread_20261021/references.json`):

| stratum | n | scored how |
|---|---|---|
| table | 6 | in order (route tables ×5, the three-language glossary) |
| panel | 14 | in order (English-version boxes, icon sidebars, hut boxes, walking times, one glossary column) |
| map | 2 | labels as an unordered bag (a map has no reading order) |
| notext | 4 | the right answer is no text (three are sofa, one a photograph) |
| excluded | 2 | not scored; reasons in the file (a box that cuts words in half; a dense map nobody can type reliably) |

**Close-up census** (`coverage_census_v2.py`, control: the whole-spread photo
covers 28/28): 0 of 6 tables and 17 of 22 promoted blocks have a close-up holding
≥ 90 % of the block at ≥ 1.15×. Every frame of this job predates the 2026-10-21
phone change, so these close-ups were shrunk to half their area on the phone.
Of the 17, 3 are sofa (no-text) and 14 are text blocks with a usable close-up:
5 cut automatically (local homography that passed a coarse likeness check),
9 cut by hand on a frame-coordinate grid (`hand_boxes.json`) because the
automatic placement failed its check. All cuts were looked at before reading.

## Inputs (fixed)

- `crops/<stem>__pagepad.jpg` — the shipped flattened page, block box + 4 % per
  side. Every scored block.
- `crops/<stem>__close.jpg` — the close-up cut. 14 text blocks.
- Tesseract: the block's shipped words (`Word.text_ocr` in document order), as
  the document holds them today.

## Readers (fixed)

- **Q** = `qwen3.6:27b`, **G** = `gemma4:31b`, through Ollama
  `/api/generate`, `think: false`, `temperature 0`, `seed 0`, `num_ctx 16384`,
  `num_predict 4096`. Image downscaled (never enlarged) so its long side is at
  most 1600 px, JPEG q90.
- Prompt, verbatim, the same for every block and both models:

```
Transcribe all printed text in this image exactly as printed, in reading order: top to bottom, left to right. Keep each printed line on its own line. If the text is a table, write one table row per line with the cells separated by " | ". Ignore pictures, pictograms and symbols. Do not translate, correct, complete or explain anything, and do not add any word that is not printed. If a word is cut off at the edge of the image, write only the letters you can see. If the image contains no printed text, answer exactly: NO TEXT
```

Arms: **T** (Tesseract), **Q-page**, **Q-close**, **G-page**. The primary model
reading is Q-page (it exists for every block); Q-close is the close-up arm.

## Scoring (fixed; `panelread_20261021/score.py`)

Normalisation, both sides: Unicode NFC; ’ ‘ ´ \` → '; “ ” „ → "; ½ ¼ ¾ →
" 1/2" " 1/4" " 3/4" (so "4½" and "4 1/2" agree); "|" removed; a line-end
hyphen joined when the next letter is lowercase (`(\w)-\s+([a-zäöüß])` →
`\1\2`, on both sides); whitespace collapsed. Case-sensitive. "NO TEXT" alone
counts as empty output. Tokens = whitespace split.

1. **Alignment.** Model tokens are aligned to reference tokens with
   `difflib.SequenceMatcher(autojunk=False)`. A model token is **right** if it
   lies in an equal block, otherwise **wrong**. Model tokens before the first
   equal block or after the last are **spill** (text from the 4 % margin) and are
   dropped. A reference token marked `[?x]` is uncertain: anything aligned to it
   (equal or replaced) is dropped from every count.
2. **Word error rate** per block and pooled per stratum: (substituted + deleted
   + inserted) / scored reference tokens, inserts excluding spill. Character
   error rate is reported beside it (Levenshtein on the normalised strings,
   uncertain tokens removed from the reference only).
3. **Numbers**, reported separately: a token containing a digit is a number.
   *Number recall* = reference numbers matched equal / reference numbers.
   *Wrong numbers* = model number tokens that are wrong (substituted or
   inserted, spill excluded). A changed number is the worst error this book can
   carry (a walking time, a height, a phone number).
4. **Map**: bag-of-tokens precision and recall (multiset).
5. **No-text**: number of tokens produced (invented text).

## The flag (fixed)

For a model reading M and a second opinion S on the same block, a token of M is
**flagged** if, aligning M to S by the same procedure, it is not in an equal
block. Second opinions:

- **S1 Tesseract** (the owner's named candidate),
- **S2 the other model on the same pixels** (G-page for Q-page),
- **S3 the same model on the other photograph** (Q-close for Q-page and back;
  14 blocks only).

Graded per stratum on the tokens of M that are scored (not spill, not uncertain):

- **catch rate** = flagged wrong / wrong,
- **number catch rate** = flagged wrong numbers / wrong numbers,
- **false-alarm rate** = flagged right / right.

**Bar (chosen now, the owner may move it, I may not):** a second opinion meets
the owner's condition on a stratum when catch rate ≥ 0.90, number catch rate =
1.00 (every wrong number flagged), and false-alarm rate ≤ 0.25. A flag that marks
nearly everything passes catch and fails false alarm, which is the outcome this
test exists to detect.

## The reader comparison (reported, no ship decision)

Pooled WER and wrong-number count per stratum for T, Q-page, G-page, Q-close.
**Close-ups help the model** if, on the 14 blocks that have both, Q-close's
pooled WER is at least 25 % lower (relative) than Q-page's **and** Q-close is
better on more blocks than it is worse. Otherwise: not shown on these
(shrunk) close-ups.

## Adjudication after scoring (fixed now)

The reference was typed by Claude, not the owner. After scoring, every place
where any reader disagrees with the reference **on a number token** is
re-checked against the sharpest pixels at full zoom. A reference slip is
corrected only when the print is unambiguous, every correction is listed in the
RESULTS row with before/after scores, and the owner is offered the full list
(numbers first).

## What this does NOT license

- Shipping model text in a PDF. That needs the flag bar met, then a separate,
  pre-registered build, and the render judged by the owner by eye ("grade the
  render, not the label").
- Anything about close-ups at full size: these were shrunk on the phone.
- Anything beyond one book, 22 scored text blocks, one prompt, two models.
