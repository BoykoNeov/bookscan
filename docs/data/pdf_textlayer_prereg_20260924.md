# Pre-registration — is a scanned PDF's own text layer worth using as a second opinion?

Written 2026-09-24, **before any disagreement was computed or looked at.**
Plan: `docs/plans/pdf-import.md`, Slice 3 ("run this before writing the merge").

## The question

A scanned PDF often carries a hidden text layer: somebody else's OCR of the same
page. Slice 3 would use it the way EasyOCR is used for Cyrillic: where the layer
and our Tesseract reading disagree, the word becomes a candidate for a flag. The
layer never supplies text or a confidence.

That is worth building only if the disagreements **find Tesseract mistakes that
Stage 06 does not already flag**, without burying them in flags on words
Tesseract read correctly. So the unit of value is a disagreement on a word Stage
06 **kept**:

* Tesseract wrong there = a **new catch** (the reader would otherwise get a wrong
  word with no marker);
* Tesseract right there = a **new false alarm** (a correct word gets a marker).

Disagreements on words Stage 06 already flagged add nothing and are only counted.

## Population (fixed now)

One document per text-layer producer, English only (no Bulgarian, German or
Italian scan with a text layer exists on this machine; that limit is part of the
result). Published papers, reports and manuals only; none of the owner's personal
documents. The PDFs are NOT committed (copyright); their SHA-256 are recorded by
the run.

| id | file | layer producer (from the PDF's metadata) |
|---|---|---|
| D1 | `M:\backup2\boiko\chernobyl_insag_7.pdf` (IAEA INSAG-7) | ABBYY FineReader |
| D2 | `W:\Claude_projects\space-station\sources\Introduction to Mathematical Modeling of Crop Growth_ How -- Christopher Boon Sung Teh -- ….pdf` | Internet Archive PDF 1.4.18 |
| D3 | `W:\Claude_projects\space-station\sources\olson1963.pdf` (Ecology, 1963) | Adobe Acrobat 10.1 Paper Capture |
| D4 | `W:\Claude_projects\space-station\sources\spacecraft thermal control handbook volume Ⅰ_fundamental -- ….pdf` | CVISION PdfCompressor 3.1 |
| D5 | `W:\temp\claude\bore_friction\ADA431357.pdf` (DTIC report) | not recorded (iText-modified) |
| D6 | `W:\Claude_projects\space-station\sources\biochemj01085-0088.pdf` (Biochem. J.) | Apex PDFWriter |
| D7 | `W:\Claude_projects\space-station\sources\connor1990.pdf` | Acrobat 3.0 Capture Plug-in |

**n = 7 documents.** Pages within a document are not independent evidence.

**Pages.** A document of 3 pages or fewer: all pages. Otherwise three pages, at
0-based index `round(f * (n - 1))` for f = 0.3, 0.5, 0.7; a chosen page whose
text layer has fewer than 150 words, or that is not a scan (images cover < 90 %),
is replaced by the next page after it that qualifies (at most 10 steps; a page
already chosen is skipped). The run records the chosen pages.

**Control (the plan's round trip).** One of this pipeline's own rendered PDFs,
`jobs/figtext_en_coins_01/render/page.pdf` (English, flag mode). Its text layer
IS the document's text, so it is right by construction: every disagreement there
is either a Tesseract mistake or an artefact of extraction/alignment. All its
pages are used; it is imported with `allow_vector` (it is not a scan).

## Procedure (fixed now)

1. Cut the chosen pages into a sub-PDF (PyMuPDF `insert_pdf`), import it with
   `pipeline/pdf_import.py` at 300 dpi, `layout=detect`, and run `run_all` on each
   page with `--mode flag --lang eng` — the shipped pipeline, unchanged.
2. **Layer tokens:** `page.get_text("words")` on the ORIGINAL PDF page, in the
   order the PDF stores them. **Tesseract tokens:** every word of
   `06_uncertain/resolved.json`, sub-pages in order, blocks by `reading_order`,
   words in stored order.
3. **Normalisation, identical on both sides:** Unicode NFKC (ligatures); a soft
   hyphen (U+00AD) or `¬` at the END of a token counts as a line-end `-` (that is
   how producers such as ABBYY mark one), and elsewhere is removed; a token
   ending in `-` followed by a token starting with a lowercase letter is joined
   into one (line-end hyphenation); then
   `pipeline.second_opinion.normalize_token`; tokens that normalise to empty are
   dropped. A joined Tesseract token stands for all its words.
4. **Alignment by sequence, not geometry** (Stage 03 moves the words, so the
   layer's boxes do not match ours): `difflib.SequenceMatcher(a=tesseract,
   b=layer, autojunk=False)` over the whole page. A **disagreement site** is a
   `replace` opcode with exactly one token on each side — the same 1↔1 rule
   `second_opinion.find_disagreements` uses. Other replace shapes are counted and
   reported, never scored. Per page, the share of Tesseract tokens inside `equal`
   opcodes is reported as **alignment coverage**; pages below 0.5 stay in, and a
   sensitivity row without them is reported.
5. **Two arms.**
   * **(a) raw:** every disagreement site.
   * **(b) dictionary-gated** (EasyOCR's rule): the Tesseract token is not in the
     English lexicon (`models/lexicons/en` via `second_opinion.load_lexicon`), the
     layer token is, and the layer token has at least 2 characters.
6. **Stage 06 state of a site:** *kept* when every Tesseract word in it has
   `decision == "keep"`; otherwise *flagged*.

## Adjudication (fixed now)

* **Primary sample:** disagreement sites on kept words. All of them when a
  document has 60 or fewer; otherwise a uniform random 60 (seed 20260924), plus
  every arm-(b) site the sample missed (used for arm (b) only; arm (a) is
  estimated from the uniform sample alone).
* **Secondary sample (reported, never gating):** flagged words where Tesseract and
  the layer AGREE, up to 20 per document (same seed) — the separate question
  "could agreement clear a flag". Never pooled with the primary count.
* **Blind:** each site is shown as a crop of `03_dewarp` (the image Tesseract
  read) around the word, with the two readings labelled A and B in a per-site
  random order (seed 20260924). The judge (Claude, by looking) picks: **A**,
  **B**, **neither**, **both** (they differ only in something that does not
  matter to a reader), or **can't tell**. Unblinding happens after all labels
  are written.
* Tesseract wrong = the layer's side, or neither. Tesseract right = Tesseract's
  side, or both. Can't tell is excluded from both and reported.

## The gate (fixed now), per arm

Build the layer as a disagreement trigger (that arm) only if **all three** hold:

1. pooled precision `catches / (catches + false alarms)` ≥ **0.50**;
2. pooled catches ≥ **20** (about one per page — below that it is not worth a
   code path);
3. precision ≥ 0.50 in **at least 4** of the documents that have ≥ 5 decidable
   adjudicated sites.

**Validity check first — the control.** If more than **20 %** of the control's
decidable sites are "Tesseract right" (where the layer is right by
construction, so the disagreement was invented by extraction or alignment), the
method cannot tell a foreign engine's opinion from its own noise, and the real
documents get **NO VERDICT** instead of pass/fail.

## What will be reported regardless

Per document: pages, Tesseract tokens, alignment coverage, sites (all / on kept
words / on flagged words), arm-(b) sites, catches, false alarms, neither, can't
tell; the secondary agreement sample; the control. A failure is reported as a
refusal in `docs/RESULTS.md`, like any other.

## Stated limits, now

English only; seven producers, one document each; the judge is a model looking at
crops, not a person; the population is scholarly and technical print, not books
photographed on a sofa, so imported-PDF numbers are not pooled with `testset/`.

## Addendum, 2026-09-24 — written after the site COUNTS, before any label

`sites` reported the control's 4 disagreements all on words Stage 06 had
flagged, so the primary rule (kept words only) gave the control nothing to judge
and its validity check could not run. The control paragraph above says every
disagreement in the control is examined; so all control disagreements, kept or
flagged, go into the blind set, and the 20 % rule is applied to them. Nothing
else changes. Also fixed before labelling: the crop step looked for
`<name>.png.png` (Stage 06 page names already end in `.png`).
