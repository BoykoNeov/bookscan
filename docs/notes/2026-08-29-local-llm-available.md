# Local vision-language models are installed and measured (2026-08-29)

Two multimodal LLMs now run locally on this machine. They were set up in
`M:\claud_projects\localLLM` (separate project, its own README and tools), not
here, and **nothing in bookscan was changed** — no code, no config, no
`testset/`, and `tools/split_eval` was deliberately not run.

This note records what they are, what they measured on bookscan's own fixtures,
and — more importantly — the one risk the measurement does **not** cover.

## What is available

| Model | Ollama tag | Weights | What it is |
|---|---|---|---|
| Qwen 3.6 | `qwen3.6:27b` | 17 GB | dense 27B, text **and** image, 256K context |
| Gemma 4 | `gemma4:31b` | 20 GB | dense 30.7B, text **and** image, 256K context |

Both are natively multimodal, so one model does text and vision. They are served
by **Ollama on `http://localhost:11434`** — an HTTP service, not a Python
dependency, so nothing needs adding to `requirements.txt`. Only one fits in the
5090's 32 GB at a time; run them in sequence.

Measured on this GPU: `qwen3.6:27b` holds a **131,072-token context at 100% GPU**
(26.8 GB, ~158 tok/s), so context is not a constraint for whole-document work.

The helper scripts use a Python **3.11** venv at `M:\claud_projects\localLLM\.venv`
(the machine's default Python is 3.14, which most ML wheels do not support yet).
That is deliberately separate from bookscan's own environment.

## OCR post-correction: measured on real Stage 05 output

Not synthetic damage — this reads bookscan's own artifacts
(`jobs/dw_en_coins_01`, `jobs/pscan_bg_01`), reconstructs page text in reading
order, and scores against the hand-transcribed truth in `testset/gt/`.

| Document | Tesseract CER | after `qwen3.6:27b` | after `gemma4:31b` |
|---|---|---|---|
| `en_coins_01` (English) | 6.72% | **5.57%** (13 s) | 5.63% (42 s) |
| `bg_01` (Bulgarian) | 1.49% | **1.16%** (12 s) | **1.07%** (32 s) |

About a fifth of the character error removed, ~13 s per spread with qwen (which
is ~3x faster than gemma for the same result). Reasoning mode (`--think`) bought
0.13 points for 5x the wall-clock and is not worth it.

**No number was corrupted, which is the result that matters for a re-typeset
document.** The check flagged catalogue codes and years as missing from the
model's output — `KM# 36.2a`, `1808-21`, page numbers `174`/`175` — and every one
was traced back to text Tesseract never produced. `1808-21` occurs twice in the
truth and once in the OCR. The model invented nothing and altered no digit. It
did repair real damage: `® Year(s) Issued: 1808-21 i 21 . Hit Reference(s):`
became `Year(s) Issued: 1808-21 Catalog Reference(s):`.

**The ceiling, and it is the relevant one for Gate 1.** Post-correction cannot
recover text the OCR never emitted, and that is where the whole remaining error
sits — dropped and unreadable regions, not misread characters. A bigger text
model will not move this. Giving the model the page crop alongside the text
might, and both models can take an image, so that experiment is now cheap.

## Book boundary: promising, and the risk is NOT the one the numbers show

Both models were asked for the book's box on `paleset_01` and `paleset_02` — the
two frames where `book_boundary.py` abstains and returns the whole frame.

| Frame | Model | IoU | labelled book outside the box |
|---|---|---|---|
| `paleset_01` | `qwen3.6:27b` | 0.905 | 5.34% |
| `paleset_02` | `qwen3.6:27b` | 0.940 | 4.50% |
| `paleset_01` | `gemma4:31b` | 0.850 | 11.88% |
| `paleset_02` | `gemma4:31b` | 0.706 | 19.53% |

Both models find a book where the detector cannot. **qwen is clearly the better
of the two** and is the one worth pursuing.

**No new padding is needed.** At a 5% outward pad both qwen boxes clip 0.00%, so
`book_boundary`'s existing `search_pad = 0.08` already covers them. Do not
introduce a different pad value — 0.08 was swept against the eight labelled boxes
and has a recorded dead zone (`zoomset_de_01` passes at 0.00, fails at 0.03,
passes at 0.06+), and one pad concept with one value is the right shape.

### The risk these numbers do not measure

RESULTS 2026-08-28 measured that **asymmetric** box error is what breaks the
split, because the spine is searched in the middle 30–70% of the box: extra width
on one edge slides the book sideways inside it until the spine leaves the band.
The measured table was 8/8 at 5% one-edge excess, **7/8 at 10%**, 5/8 at 20%.

qwen's `paleset_01` box is asymmetric in exactly that direction. Per edge, as a
fraction of the labelled book:

| Frame | left | right | top | bottom |
|---|---|---|---|---|
| `paleset_01` | −0.13% | **+4.85%** | −1.57% | −3.64% |
| `paleset_02` | +0.21% | +1.42% | −2.38% | −2.12% |

(positive = box sits outside the book, safe; negative = box cuts into it)

`paleset_01` carries a **~5-point one-edge excess on the right** — sitting exactly
on the boundary of the 8/8 row. `paleset_02` is nearly symmetric and looks safe.
Padding outward does not help: a symmetric pad preserves the asymmetry.

So an IoU of 0.905 with 0.00% clipping after padding **can still lose the
split**. That is not visible in any number in the table above.

### Therefore: IoU is not the metric, and this is the experiment

`testset/gt/book_box.json` says it plainly — "do not fit a book detector to these
boxes; the load-bearing metric stays `testset/gt/gutter.json`". Everything
measured above is clipping against the diagnostic label. It says the approach is
**worth trying**. It does not say it works.

The real test is the one this note deliberately did not run: emit a VLM box into
`<page_dir>/book_box.json` — the same user-input file `tools/book_box_editor`
writes, which `book_boundary.user_box` already validates, refuses when
degenerate or frame-mismatched, and pads by `search_pad` — then run Stage 02 and
read gutter correctness out of `tools/split_eval`. If a model-supplied box splits
the two pale frames without disturbing the 19 that pass today, that is evidence.
Nothing short of it is.

Note the shape this suggests: a VLM is not a new detector, it is **a third source
for a box the pipeline already knows how to consume and distrust**, alongside
`detector` and `operator` in `split.json`'s `book_crop_source`. All the existing
safety rules apply to it unchanged.

Two things this note is explicitly **not**:

- It is **not** a reason to touch the 19/21 red run. `split_eval` is red on
  purpose; those two rows stay graded until the detector actually improves, and
  a passing VLM experiment would be a *fix*, not a re-labelling.
- It is **not** a replacement for the fixture shoot. This is n = 2 scenes, the
  same two, which is precisely the "two scenes, not 31 examples" problem
  `docs/plans/pale-background-fixture-shoot.md` was written about. What the
  program still needs is **new photographs of new surfaces**, and especially the
  negatives (tightly framed handheld spreads) that brief asks for.

Also untested and load-bearing: whether a VLM box holds on the six spreads the
detector already handles. It could not be scored from `testset/` alone —
`book_box.json` records no `anchor` for `de_01`/`de_02` (read off gitignored
`jobs/orient_fix_de*`) and the `zoomset_*` anchors are not under `testset/`. The
probe skips any row whose anchor it cannot confirm rather than score a box
against a label read on a differently framed image. Point it at the right images
and those six become testable.

## Practical details for whoever picks this up

- **Coordinate conventions differ between the two models, and mixing them up
  looks exactly like model failure.** `qwen3.6` answers
  `{"bbox_2d": [x1, y1, x2, y2]}`; `gemma4` answers
  `{"box_2d": [y1, x1, y2, x2]}`. Both normalise to 0–1000 and both wrap the
  answer in a ```json fence. Read one with the other's order and IoU falls from
  0.94 to 0.75.
- Images were downscaled to a 1120 px long edge before sending. Full 4080 px
  frames are not needed for a page-level box.
- **Ollama defaults `num_ctx` to 4096** whatever the model advertises, and
  truncates silently. Always set it explicitly.
- Tools, with their measured results, are in `M:\claud_projects\localLLM\README.md`:
  `book_box_probe.py` (box + overlay + scoring against `book_box.json`),
  `ocr_eval_real.py` (CER and number-drift against real Stage 05 output),
  `textfix.py` (the working correction/rewrite CLI), `vram_probe.py`.
