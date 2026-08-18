"""Measure how much of a rendered document survives as *findable* text in its PDF.

A re-typeset PDF's whole point is that the text is real (CLAUDE.md: "Reconstruction
output is real text -> the PDF is inherently searchable"). The honest question is
therefore not "is there a text layer" but "does a reader searching for a word in
the document find it".

Population = the words Stage 08 was actually asked to emit AS TEXT: words in
blocks the document's settings did not strip (running headers / page numbers),
minus - in ``patch`` mode - the words deliberately replaced by an image crop.
Patch words are counted separately: they SHOULD be absent from the text layer,
so counting them as misses would punish the mode for working.

Two hit definitions per word:

* ``verbatim`` - the word appears as a contiguous substring of the extracted text
* ``loose``    - it appears with optional whitespace between its characters

The gap between them isolates spurious intra-word spacing, which is exactly what
a viewer's search box trips over. **That gap is extractor-dependent, not a
property of the PDF**, which is why this tool runs every extractor it can find:
Chromium writes one glyph per ``Tj`` with an explicit ``Td`` displacement (its
Type3 output has no run-level advances), so each extractor has to re-derive word
boundaries from glyph geometry and they disagree. Reporting one extractor's
number alone would invent a defect that no reader sees.

Usage::

    python -m tools.pdf_searchability jobs/<job>=<path/to.pdf> [more...]
    python -m tools.pdf_searchability jobs/<job>          # uses <job>/render/page.pdf
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# type -> the document setting that strips it
_STRIPPED_BY = {"header": "strip_running_headers", "page_number": "strip_page_numbers"}


# --------------------------------------------------------------------------
# extractors (each returns the whole document's text, or None if unavailable)
# --------------------------------------------------------------------------
def _text_pypdf(pdf: Path) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    return "".join((p.extract_text() or "") for p in PdfReader(str(pdf)).pages)


def _text_mupdf(pdf: Path) -> str | None:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None
    with fitz.open(str(pdf)) as doc:
        return "".join(page.get_text() for page in doc)


EXTRACTORS = {"pypdf": _text_pypdf, "mupdf": _text_mupdf}


# --------------------------------------------------------------------------
def expected_text_words(doc: dict) -> tuple[list[str], int, int]:
    """(words the render should emit as text, patch-replaced count, stripped count)."""
    st = doc.get("settings") or {}
    mode = st.get("uncertainty_mode")
    words: list[str] = []
    patched = stripped = 0
    for page in doc.get("pages", []):
        for blk in page.get("blocks", []):
            setting = _STRIPPED_BY.get(blk.get("type"))
            if setting and st.get(setting):
                stripped += len(blk.get("words", []))
                continue
            if blk.get("text"):        # block-level override supersedes its words
                continue
            for w in blk.get("words", []):
                if mode == "patch" and w.get("patch_asset"):
                    patched += 1
                    continue
                text = (w.get("text") or "").strip()
                if text:
                    words.append(text)
    return words, patched, stripped


def score(words: list[str], text: str) -> dict:
    flat = re.sub(r"[ \t]+", " ", text)
    verbatim, loose_only, missing = [], [], []
    for w in words:
        if w in flat:
            verbatim.append(w)
        elif re.search(r"\s*".join(map(re.escape, w)), flat):
            loose_only.append(w)
        else:
            missing.append(w)
    n = len(words) or 1
    return {
        "extracted_chars": len(text),
        "verbatim": len(verbatim),
        "verbatim_pct": round(100 * len(verbatim) / n, 1),
        "found_only_with_spaces_ignored": len(loose_only),
        "loose_pct": round(100 * (len(verbatim) + len(loose_only)) / n, 1),
        "not_found_at_all": len(missing),
        "examples_space_broken": sorted(set(loose_only))[:8],
        "examples_missing": sorted(set(missing))[:8],
    }


def measure(job_dir: Path, pdf: Path) -> dict:
    doc = json.loads((job_dir / "document.json").read_text(encoding="utf-8"))
    words, patched, stripped = expected_text_words(doc)
    out = {
        "job": job_dir.name,
        "pdf": str(pdf),
        "mode": (doc.get("settings") or {}).get("uncertainty_mode"),
        "pdf_bytes": pdf.stat().st_size,
        "words_rendered_as_text": len(words),
        "words_replaced_by_patch_image": patched,
        "words_in_stripped_blocks": stripped,
        "by_extractor": {},
    }
    for name, fn in EXTRACTORS.items():
        text = fn(pdf)
        out["by_extractor"][name] = score(words, text) if text is not None else "unavailable"
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 2
    results = []
    for spec in args:
        job, _, pdf = spec.partition("=")
        job_dir = Path(job)
        pdf_path = Path(pdf) if pdf else job_dir / "render" / "page.pdf"
        results.append(measure(job_dir, pdf_path))
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
