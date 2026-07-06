# GATE 4 SPEC — Editable Document + Re-typeset Output (Stages 07–08)

## Why this gate changed shape

The original plan was a single Stage 07 `reconstruct` that went page model →
HTML → PDF in one shot. The owner changed the requirement:

> "I want to be able to save the text (and the rest of the file) in an
> editable-by-the-program format, **before** finalizing it to PDF (for example
> to translate the text first), or bake the first PDF automatically and later
> return for edits."

So the PDF is no longer a dead end. There is now a **durable, editable document
artifact** in the middle, and PDF generation becomes a **pure, re-runnable
step** on top of it. Both of these workflows must work:

- **edit-then-PDF** — assemble the document, edit it (fix OCR, change reading
  order / block type, translate), *then* render the PDF.
- **auto-PDF-then-edit-later** — render a PDF immediately from the freshly
  assembled document, come back weeks later, edit the same document, re-render.

## The split: assemble → render

| Stage | Module | Reads | Writes |
|---|---|---|---|
| 07 | `stage07_assemble` | ALL `page_*/06_uncertain/` of a job (+ `03_dewarp` images, `06_uncertain/patches`) | `jobs/<job>/document.json` + `jobs/<job>/document_assets/` |
| 08 | `stage08_render` | `document.json` + `document_assets/` **only** | `jobs/<job>/render/page.html` (always) + `page.pdf` (when a PDF backend is available) |

Stage 07 is the **first job-level stage** — it aggregates every page folder of a
job into one document. Stage 08 is a **pure function** of the document: given the
same `document.json`, it always produces the same output, and it is safe to run
any number of times as the document is edited.

## `document.json` — the editable format

### It is deliberately OUTSIDE the per-page stage contract

Every stage so far is **per-page and immutable**: a stage writes only its own
numbered subfolder, and stages never modify earlier artifacts (CLAUDE.md). The
document is different **on purpose**:

- **Job-level**, not per-page — one file for the whole book/spread set.
- **Mutable** — it is the user's working copy. The user (or, later, the visual
  editor) edits it in place. Re-assembling from the pipeline would overwrite
  edits, so **assemble refuses to clobber an edited document** unless
  `--force` is given (edits are precious; the immutable per-stage trace is
  always still there to re-assemble from).

The immutable per-page pipeline trace (`00_ingest` … `06_uncertain`) is the
*source of record*; `document.json` is the *editable derivative*. They coexist.

### Self-containment is a hard rule

**Stage 08 render, and the future editor, read ONLY `document.json` +
`document_assets/` — never the per-page stage folders.** Rationale: re-running
an upstream stage (e.g. Stage 06 clears `06_uncertain/patches/` on every run)
must not break a document saved months ago. Therefore assemble **copies** into
`document_assets/`:

- the **dewarped page images** (`03_dewarp/*.png`) — needed so the editor can
  show each word in its original visual context, and so `patch` crops can be
  re-cut if an edit demands it;
- the **flag/patch crops** referenced by Stage 06's patch manifest.

All asset references in `document.json` are **relative paths** into
`document_assets/`, so the whole `jobs/<job>/` document + assets pair is
portable.

### Editable model (see `page_model.py` for the authoritative types)

Reading unit is the **physical page** (subpage: `left`/`right`/`single`),
flattened in reading order across all spreads. Each page keeps its blocks; each
block keeps its words.

**Block** — structure is user-overridable, not just the automatic path:
- `type` (BlockType) and `reading_order` are **editable**; the auto-detected
  originals are preserved (`type_auto`, `order_auto`) and `structure_edited`
  flags a human override, so the editor can show "you changed this" and the auto
  value is never lost.
- Optional `text` — a **block-level edited/translated** rendering that
  *supersedes* the per-word text when present (the translation path: a
  free-flowing translated sentence does not map 1:1 to source word boxes). The
  original `words` are always retained as provenance and visual-context anchors.

**Word** — text is editable, OCR original is provenance:
- `text` — current, editable text (what renders).
- `text_ocr` — the original Tesseract read, kept forever as provenance so an
  edit/translation never destroys the source.
- `edited` — set true when `text` diverges from `text_ocr` or the word is
  otherwise touched.
- `bbox`, `conf`, `engine`, `decision` — unchanged from Stage 05/06; `bbox` is
  in 1× dewarp coords = the coordinate space of the page image asset, so the
  editor can highlight the word on the page image with no transform.
- `patch_asset` — relative path to this word's patch crop (patch mode), if any.

### The per-word flag-visibility rule (owner's decision)

> "A single or small change should not hide/delete the markers. Only when the
> marked words themselves are edited/deleted should the flag disappear."

Uncertainty markers (flag highlight / patch image) are **per-word**, and a
marker is shown until *that specific word* is edited or deleted — never cleared
wholesale by editing something else in the block. Implemented as:

```
edited        := word.edited OR (word.text_ocr is not None AND word.text != word.text_ocr)
flag_visible  := word.decision in {FLAG, PATCH} AND not edited
```

The implicit `text != text_ocr` term makes the **interim hand-edit path safe**:
until the visual editor exists the only way to edit is hand-editing
`document.json`, and a user who changes `text` but forgets `edited: true` still
clears the marker — and in patch mode Stage 08 then renders their corrected text
instead of the stale original crop. On a fresh assemble `text_ocr == text`, so it
is a no-op until text actually changes.

Consequences that fall out for free:
- Fixing one OCR word clears only *its* marker; other flagged words in the same
  block stay flagged.
- A whole-block **translation** = editing/deleting every source word, so all of
  that block's markers clear naturally — while `words`/`text_ocr` remain as
  provenance. One rule covers both OCR-correction and translation.

## Stage 08 render

- **HTML is always produced** and is itself a first-class artifact: a
  self-contained, searchable, browser-viewable rendering (assets inlined or
  referenced from `document_assets/`). It doubles as a human-readable preview.
- **PDF** is produced by **headless Chromium via Playwright** (owner decision,
  2026-07-06). Chromium renders the *exact* `page.html` this stage writes, so the
  PDF matches the browser preview 1:1 — one rendering target, not two. Two flags
  are load-bearing: `print_background=True` (else the `.flag` yellow highlight —
  the load-bearing uncertainty marker — silently drops from the PDF) and
  `prefer_css_page_size=True` (honor `@page { size: A4 }`). Render loads the local
  file via `file://` rather than pushing the multi-MB data-URI HTML over CDP.
  `config.yaml reconstruct.pdf_backend` selects the engine (`chromium` |
  `weasyprint` (secondary fallback) | `auto` | `none`); an unavailable engine
  falls through and render still writes `page.html`, so the gate is never blocked.
  **Verified** on real jobs: `dw_en_coins_01` (English, 60 flags) → valid `%PDF`,
  7.2 MB, 39.6k yellow highlight pixels present (proves `print_background`);
  `bg_01` (Bulgarian) → valid `%PDF`, 3.2k searchable Cyrillic chars.
  **Sync-API caveat (Gate 5):** `sync_playwright()` raises inside a running
  asyncio loop; the future FastAPI server must export PDFs off the request loop
  (async API or subprocess), not call `try_render_pdf` directly.
- **Font embedding is an owed follow-up.** Chromium *does* embed + subset the
  fonts it uses (the PDFs above are portable and searchable), but with only a
  named `"Noto Serif"` stack and no Noto installed on the host it fell back to
  **Times New Roman**. CLAUDE.md's non-negotiable is Noto embedded for Latin +
  Cyrillic — that needs `@font-face` with bundled Noto TTFs in `_css`, tracked
  separately from wiring the engine.
- Render honors doc-wide settings carried in `document.json` (uncertainty mode
  already resolved at Stage 06, header/page-number stripping, fonts, target
  language) so editing a setting and re-rendering just works.
- De-hyphenation on reflow and running-header / page-number stripping (CLAUDE.md
  non-negotiables) live here.

## Out of scope for this gate (next step)

The **visual editor** (page image + block/word overlays; edit reading order,
block type, and OCR text in visual context; translate; preview) is the owner's
chosen surface for editing, but sequenced *after* format + render (owner's
call: "format + render, then editor"). `document.json` is designed now to drive
it: per-word boxes in page-image space, retained provenance, and structure
overrides are all present so the editor is a view/controller over an existing
model, not a schema change.

## Decisions log (this gate)

- Split single reconstruct into **07 assemble** (editable document) + **08
  render** (re-runnable PDF/HTML). — owner
- Editable format is `document.json`, job-level, mutable, **outside** the
  per-page immutable contract; assemble won't clobber edits without `--force`.
- **Self-contained**: render/editor read only the document + `document_assets/`;
  assemble copies dewarp images + crops in.
- Editable text is a **word-level layer with provenance** (`text`/`text_ocr`),
  plus an optional block-level translated `text` override.
- Structure (reading order, block type) is **user-overridable** with the auto
  value preserved.
- **Per-word** flag-visibility: a marker clears only when its own word is
  edited/deleted. — owner
- Edit surface is a **visual editor** (see word in context; edit
  order/type/OCR), built **after** format + render. — owner
- PDF backend = **headless Chromium via Playwright** (owner, 2026-07-06);
  data-driven via `reconstruct.pdf_backend`, WeasyPrint kept as fallback,
  HTML always still emitted. Verified on real jobs.
- **Owed:** Noto `@font-face` embedding (Chromium currently falls back to Times
  New Roman); visual editor.
