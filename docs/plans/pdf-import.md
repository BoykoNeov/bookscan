# Importing a PDF and re-typesetting it through the pipeline

**Status: PLAN ONLY, not started.** Written 2026-08-29 at the owner's request
("i want to be able to import pdf's and reedit them through the pipeline as
scanned pages ... it is not neccessary do to that now, but write it as a plan").

## The goal, stated precisely

Take an existing PDF — a scan someone else made, a download, a photographed book
already bound into a file — and put it through this pipeline so that the output
is what this project always produces: **a re-typeset document whose visible text
is real rendered text**, with figures cropped from the page images and placed
back in reading order. The PDF's own text layer, if it has one, is not the
deliverable and is not trusted as the answer.

That last sentence is the whole design constraint. A PDF that already has text
invites a shortcut — read the text layer, reflow it, done — and that shortcut
produces a *different product* from the one this repo exists to build. The text
layer of a scanned PDF is somebody else's OCR, with somebody else's error rate,
no word-level confidence this pipeline can calibrate, and often no reliable word
boxes. Stage 06's entire job is deciding which words to doubt, and it cannot do
that job on confidences it did not measure.

## Where it plugs in

The pipeline is a chain of per-page stages over **images**. A PDF page is an
image (or can be made into one). So import is not a new pipeline — it is a new
way to fill `00_ingest/`, exactly as the phone upload does.

```
a PDF  ->  [ importer ]  ->  jobs/<job>/page_NNN/raw/*.png  ->  the existing chain
```

Everything downstream is untouched. That is the point, and any design that needs
to change Stage 03 or later has gone wrong.

### The one genuinely new decision: what is a "page"?

The pipeline's unit is a **spread** — one photograph containing two facing pages,
which Stage 02 splits at the spine. A PDF's unit is a **page**, and it may be:

* one book page per PDF page (the common case for a produced scan), or
* one spread per PDF page (common for a photographed book), or
* a cover, a plate, a fold-out.

This is a real fork and it must be **detected, then shown, then overridable** —
never guessed silently. Proposal:

* measure each PDF page's aspect ratio and cluster them;
* a page markedly wider than tall, in a document where most pages are, is a
  spread → hand it to Stage 02 as usual and let the spine detector work;
* a portrait page → mark it single-page so Stage 02 emits `single.png` and never
  looks for a spine (the mechanism exists; Stage 02 already emits `single.png`);
* show the verdict per page in the console before running, with a toggle.

**Do not** invent a new detector for this. The existing spine detector's own
confidence is the right signal, and where it abstains the operator sees it in
the console, which is what the console is for.

## Slices

### Slice 1 — `pipeline/pdf_import.py`, images only

A CLI and a function: `import_pdf(pdf_path, job_dir, dpi=300) -> list[Path]`.

* Render each PDF page to PNG at a stated DPI and write it as
  `page_NNN/raw/frame_00.png`, then let `run_all` take over. One PDF page → one
  page folder, in file order (the same arrival-order rule the upload path uses).
* **Render, do not extract embedded images.** A scanned PDF often stores one JPEG
  per page and extracting it is tempting because it is lossless. But it is not
  reliably the whole page: pages carry multiple images, masks, and rotations
  applied by the page's transform, and an extracted image is in image space, not
  page space. Rendering is correct by construction. Extraction is an
  optimisation to measure later, never the first implementation.
* DPI is a recorded parameter, not a constant. 300 is the starting number
  because Stage 05's Tesseract backbone wants roughly that for body text; the
  right value is whatever a measured run says, and the meta.json must record
  which was used so two runs are comparable.
* Library: **PyMuPDF (`fitz`)** — it renders, it is one wheel with no external
  binary, and it also exposes the text layer and the page rotation, which
  Slice 3 needs. `pdf2image` is rejected: it shells out to Poppler, which is
  another Windows binary to install and version.

Done when: a 10-page PDF becomes 10 page folders that `run_all` processes with
no other change, and the console shows them.

### Slice 2 — import from the console

A file picker on the job screen: choose a PDF, choose "each PDF page is a
spread / a single page / detect", press Import. It uploads, the importer runs,
pages get enqueued on the existing worker one at a time.

Done when: the owner never types a command to import a PDF.

### Slice 3 — use the PDF's own text as a SECOND OPINION, never as the answer

This is the slice with the actual value, and the one most likely to be built
wrongly, so it is last and it is fenced.

The project's non-negotiable rule (CLAUDE.md): *Tesseract 5 is the
confidence/bounding-box backbone; other engines may be second opinions for hard
passages but must never be the sole text source or the confidence source.* A
PDF's embedded text layer is exactly such a second opinion — a foreign OCR
engine's output, of unknown provenance, with boxes of unknown quality.

So it enters at the place the project already built for foreign opinions:
`pipeline/second_opinion.py`'s **disagreement trigger**. Where the embedded text
and Tesseract agree, confidence in that word rises. Where they disagree, the word
becomes a candidate for flagging — the same treatment EasyOCR already gets for
Cyrillic. It never overwrites `text_ocr`, never supplies a confidence, and never
decides a word on its own.

**How to know whether it is worth building:** it is gradeable, cheaply, on data
this repo already has. `tools/pdf_searchability.py` exists; the pipeline can
render one of its own finished PDFs back to images, re-import it, and compare
the recovered text against the document it came from — a round trip with known
ground truth. Run that before writing the merge, not after.

### Not in scope, deliberately

* **Vector/born-digital PDFs** (a LaTeX paper, an ebook export). Re-typesetting
  one is a solved problem with different tools and no photograph in it; this
  pipeline's whole apparatus — dewarp, spine detection, figure cropping from
  page photos — is dead weight there. Detect and say so, do not process.
* **Reading the PDF's own layout tree** for blocks. Stage 04's detector is the
  block source. A PDF's structure is usually absent and, when present, describes
  the producer's OCR, not the page.
* **Preserving the original PDF's fonts or layout.** The product is a re-typeset
  document. That is the project.

## Risks worth writing down now

* **A PDF is not evidence about capture quality.** Every measurement this repo
  has about dewarp, fusion and spine detection was made on its own photographs.
  An imported PDF has been through someone else's processing already — possibly
  already deskewed, already cropped, already sharpened. Numbers from imported
  pages must not be pooled with numbers from `testset/` without saying so.
* **Page count times DPI is a lot of pixels.** A 400-page PDF at 300 DPI is
  ~400 × 25 MB of PNG before any stage runs. The importer should stream page by
  page and the console should say what it is about to create before it creates
  it.
* **The 1:1 page mapping is load-bearing for resume.** The upload path names
  pages by arrival order and the worker resumes by folder; an importer that
  renumbers or skips on failure breaks both. Fail the import, do not skip a page.
