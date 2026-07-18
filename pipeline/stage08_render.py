"""Stage 08 — Render (editable ``document.json`` -> re-typeset HTML / PDF).

The counterpart to Stage 07: assemble builds the editable document, render turns
it — and ONLY it — into the finished, searchable, re-typeset output. Because
render is a **pure function of ``document.json`` + ``document_assets/``**, it is
safe to run any number of times: bake a PDF now, edit the document later, re-run
and the edits appear. It NEVER reads the per-page stage folders (self-containment
rule, ``docs/GATE4_SPEC.md``), so a document saved months ago still renders.

**Renders the CURRENT editable values, not provenance** — ``Word.text`` (not
``text_ocr``), ``Block.type`` / ``reading_order`` (not ``*_auto``) — so every
edit round-trips. In particular:

  * **``Block.text`` translation override supersedes the words.** This is the
    headline reason the requirement changed ("translate the text first"): when a
    block carries an edited/translated ``text``, it renders that plainly and the
    per-word OCR/flags are bypassed (words remain in the model as provenance).
  * **Uncertainty modes ride ``Word.flag_visible``** (the owner's per-word rule):
    a still-visible marker renders as a highlighted span (flag) or an inline
    image crop (patch); an *edited* word — even one that was flagged — renders as
    plain text, because editing it cleared the marker.
  * **Figures are cropped from the full-res page image** (``image_asset``) at the
    block bbox and placed in reading order; a FIGURE block renders the crop, not
    its (meaningless) OCR words. A CAPTION immediately following a figure is
    grouped into the same ``<figure>``.
  * **Running headers / page numbers are stripped by default** (per the CURRENT
    block type, so a user retype is honored); toggles in ``DocSettings``.
  * Output text is real text -> the HTML (and any PDF made from it) is searchable;
    ``DocSettings.fonts`` drive the embedded font stack (Latin + Cyrillic).

**HTML is the deliverable; the PDF engine is a thin consumer of it.** The HTML is
written print-ready (``@page``, page breaks) and fully self-contained (every image
inlined as a data URI — no external refs, no broken paths). The PDF backend is
**headless Chromium via Playwright** (owner decision): it renders the exact
``page.html`` this stage produces, so the PDF matches the browser preview 1:1
(``print_background`` keeps the flag highlight, ``prefer_css_page_size`` honors
``@page``). ``config.yaml reconstruct.pdf_backend`` selects it (``chromium`` |
``weasyprint`` | ``auto`` | ``none``); if the chosen engine is unavailable render
still writes ``page.html`` and says so in meta — the gate is never blocked.

**De-hyphenation on reflow** is a wired seam (repo pattern: ship the conservative
default arm, wire the hook — cf. the Stage-06 disagreement trigger): a line-end
hyphen is joined with the next line only if it starts lowercase AND the joined
token is in the per-language dictionary; with no dictionary loaded the default is
conservative — keep the hyphen. The gap is noted honestly in meta.

Contract:
  * **Reads** ``<job>/document.json`` + ``<job>/document_assets/`` ONLY.
  * **Writes** ``<job>/render/page.html`` (always), ``<job>/render/page.pdf``
    (when a PDF backend is available), and ``<job>/render/meta.json``.

Usage:
    python -m pipeline.stage08_render jobs/<job>/ [--debug]
"""

from __future__ import annotations

import argparse
import base64
import html
import time
from pathlib import Path

import cv2
import numpy as np

from pipeline.page_model import BBox, Block, BlockType, Document, DocPage, StageMeta, Word
from pipeline import stage04_layout as S4

STAGE = "stage08_render"
VERSION = "0.2.0"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Bundled, tracked fonts embedded as @font-face data URIs (self-containment
# rule: the HTML must render Noto on any machine, with or without it installed —
# otherwise Chromium/WeasyPrint silently fall back to a system serif like Times
# New Roman and Cyrillic can tofu). NotoSerif.ttf is a VARIABLE font (wght
# 100–900) so a single file yields Regular through Bold with no faux-bolding.
# Its family name MUST match the CSS ``font-family`` stack strings exactly.
FONTS_DIR = REPO_ROOT / "pipeline" / "assets" / "fonts"

# (file, family, font-weight, font-style). Add Noto Sans here when bundled — the
# loader emits a face for whatever files are PRESENT, independent of a document's
# ``settings.fonts`` (which defaults to []), so embedding never silently drops.
_FONT_FACES: list[tuple[str, str, str, str]] = [
    ("NotoSerif.ttf", "Noto Serif", "100 900", "normal"),
]

# Block types dropped by default (running headers / page numbers), gated by the
# document's toggles. Keyed on the CURRENT type so a user retype is honored.
_STRIP = {
    BlockType.HEADER: "strip_running_headers",
    BlockType.PAGE_NUMBER: "strip_page_numbers",
}


# --------------------------------------------------------------------------
# De-hyphenation seam (pure, unit-tested)
# --------------------------------------------------------------------------


def join_hyphen(left: str, right: str, dictionary: set[str] | None) -> str | None:
    """Return the de-hyphenated join of a line-end ``left`` with the next line's
    ``right``, or None to keep them separate (hyphen retained).

    Rule (CLAUDE.md): join only if ``left`` ends with a hyphen AND ``right`` starts
    lowercase AND the joined token is in the per-language dictionary. With no
    dictionary the default is conservative — never join (a wired seam, not a TODO):
    returns None, so the hyphen is kept until a dictionary is supplied.
    """
    ls = left.rstrip()
    if not ls.endswith("-") or not right[:1].islower():
        return None
    if dictionary is None:
        return None                       # conservative default: keep the hyphen
    candidate = ls[:-1] + right
    return candidate if candidate.lower() in dictionary else None


def merge_hyphens(words: list[Word], dictionary: set[str] | None) -> list[Word]:
    """Fold line-end hyphenated plain words into the following word per
    ``join_hyphen``. Flagged/edited words at the boundary are left untouched
    (their marker must survive). Default (no dictionary) is a no-op."""
    out: list[Word] = []
    i = 0
    while i < len(words):
        w = words[i]
        if (i + 1 < len(words) and not w.flag_visible and not words[i + 1].flag_visible
                and w.line_id is not None and words[i + 1].line_id is not None
                and words[i + 1].line_id != w.line_id):
            joined = join_hyphen(w.text, words[i + 1].text, dictionary)
            if joined is not None:
                nxt = words[i + 1]
                out.append(w.model_copy(update={
                    "text": joined,
                    "text_ocr": (w.text_ocr or "") + (nxt.text_ocr or ""),
                }))
                i += 2
                continue
        out.append(w)
        i += 1
    return out


# --------------------------------------------------------------------------
# Inlining assets as data URIs (keeps the HTML self-contained + path-bug-proof)
# --------------------------------------------------------------------------


def _data_uri_from_bytes(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _data_uri_from_file(path: Path) -> str | None:
    try:
        return _data_uri_from_bytes(path.read_bytes())
    except OSError:
        return None


def _crop_data_uri(page_bgr: np.ndarray, box: BBox) -> str | None:
    h, w = page_bgr.shape[:2]
    x0, y0 = max(0, box.x), max(0, box.y)
    x1, y1 = min(w, box.x2), min(h, box.y2)
    if x1 <= x0 or y1 <= y0:
        return None
    ok, buf = cv2.imencode(".png", page_bgr[y0:y1, x0:x1])
    return _data_uri_from_bytes(buf.tobytes()) if ok else None


# --------------------------------------------------------------------------
# Word / block -> HTML
# --------------------------------------------------------------------------


def _word_html(w: Word, mode: str, job_dir: Path) -> str:
    """One word as an inline fragment, honoring its still-visible uncertainty
    marker. An edited word (marker cleared) renders as plain escaped text."""
    txt = html.escape(w.text)
    if not w.flag_visible:
        return txt
    if mode == "patch" and w.patch_asset:
        uri = _data_uri_from_file(job_dir / w.patch_asset)
        if uri:
            return f'<img class="patch" alt="{txt}" title="{txt}" src="{uri}">'
    return f'<span class="flag" title="uncertain (conf {w.conf:.0f})">{txt}</span>'


def _block_body_html(blk: Block, mode: str, job_dir: Path,
                     dictionary: set[str] | None) -> str:
    """Inline HTML for a text block: the translated override if present, else the
    words rendered with de-hyphenation + per-word markers."""
    if blk.text is not None:                       # translation / block-level edit
        return html.escape(blk.text)
    words = [w for w in merge_hyphens(blk.words, dictionary) if w.text.strip()]
    return " ".join(_word_html(w, mode, job_dir) for w in words)


_TAG = {
    BlockType.TITLE: ("h1", "title"),
    BlockType.HEADING: ("h2", "heading"),
    BlockType.PARAGRAPH: ("p", "paragraph"),
    BlockType.LIST: ("p", "list"),
    BlockType.TABLE: ("p", "table"),
    BlockType.FOOTNOTE: ("p", "footnote"),
    BlockType.CAPTION: ("figcaption", "caption"),
    BlockType.HEADER: ("p", "header"),
    BlockType.PAGE_NUMBER: ("p", "page-number"),
    BlockType.OTHER: ("p", "other"),
}


def _figure_html(blk: Block, page_bgr: np.ndarray | None,
                 caption: Block | None, mode: str, job_dir: Path,
                 dictionary: set[str] | None) -> str:
    """A FIGURE block: crop from the full-res page image at its bbox (NOT its OCR
    words), optionally with the following CAPTION grouped in the same <figure>."""
    inner = ""
    uri = _crop_data_uri(page_bgr, blk.bbox) if page_bgr is not None else None
    if uri:
        inner += f'<img class="figure" src="{uri}" alt="figure">'
    else:
        inner += '<div class="figure-missing">[figure]</div>'
    if caption is not None:
        inner += f'<figcaption class="caption">{_block_body_html(caption, mode, job_dir, dictionary)}</figcaption>'
    return f'<figure class="figure-block">{inner}</figure>'


def _page_html(page: DocPage, doc: Document, job_dir: Path,
               dictionary: set[str] | None) -> str:
    """One physical page: blocks in reading order, stripped/figured/typed."""
    mode = doc.settings.uncertainty_mode
    page_bgr = cv2.imread(str(job_dir / page.image_asset), cv2.IMREAD_COLOR)

    blocks = sorted(page.blocks, key=lambda b: b.reading_order)
    parts: list[str] = [f'<section class="page" data-page="{html.escape(page.page_id)}">']
    i = 0
    while i < len(blocks):
        blk = blocks[i]
        strip_key = _STRIP.get(blk.type)
        if strip_key and getattr(doc.settings, strip_key):
            i += 1
            continue
        if blk.type is BlockType.FIGURE:
            cap = None
            if i + 1 < len(blocks) and blocks[i + 1].type is BlockType.CAPTION:
                cap = blocks[i + 1]
                i += 1                              # consume the grouped caption
            parts.append(_figure_html(blk, page_bgr, cap, mode, job_dir, dictionary))
            i += 1
            continue
        tag, cls = _TAG.get(blk.type, ("p", "other"))
        body = _block_body_html(blk, mode, job_dir, dictionary)
        if body.strip():
            parts.append(f'<{tag} class="{cls}">{body}</{tag}>')
        i += 1
    parts.append("</section>")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Document -> full HTML page (print-ready, self-contained)
# --------------------------------------------------------------------------


def _font_face_css(fonts_dir: Path = FONTS_DIR) -> str:
    """`@font-face` rules embedding each bundled TTF as a base64 data URI.

    Driven by files PRESENT on disk (not a document's ``settings.fonts``), so an
    empty-fonts document still gets Noto embedded. A variable font declares its
    full weight range (``font-weight: 100 900``) so Chromium synthesizes every
    weight from one file. Missing dir/file -> no faces (graceful degrade to the
    named-stack system fallback, same as before this fix); noted in meta."""
    faces: list[str] = []
    for fname, family, weight, style in _FONT_FACES:
        p = fonts_dir / fname
        if not p.exists():
            continue
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        faces.append(
            f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
            f'font-style: {style}; font-display: swap; '
            f'src: url(data:font/ttf;base64,{b64}) format("truetype"); }}'
        )
    return "\n".join(faces) + ("\n" if faces else "")


def _css(fonts: list[str]) -> str:
    stack = ", ".join(f'"{f}"' for f in fonts) or '"Noto Serif", serif'
    stack += ", serif"
    return _font_face_css() + f"""
@page {{ size: A4; margin: 22mm 20mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: {stack}; font-size: 11.5pt; line-height: 1.45;
       color: #111; max-width: 46rem; margin: 0 auto; padding: 1.5rem; }}
h1.title {{ font-size: 1.7em; margin: 1.2em 0 .5em; }}
h2.heading {{ font-size: 1.3em; margin: 1em 0 .4em; }}
p {{ margin: 0 0 .7em; text-align: justify; }}
p.footnote {{ font-size: .85em; color: #444; }}
p.list {{ margin-left: 1.2em; }}
.section-sep {{ border: 0; border-top: 1px dashed #ccc; margin: 1.4em 0; }}
.flag {{ background: #fff2a8; border-bottom: 1px solid #e0c000; padding: 0 1px;
         border-radius: 2px; }}
img.patch {{ height: 1.15em; vertical-align: text-bottom; margin: 0 1px;
             border: 1px solid #d9534f; }}
figure.figure-block {{ margin: 1em 0; text-align: center; page-break-inside: avoid; }}
img.figure {{ max-width: 100%; height: auto; }}
figcaption.caption {{ font-size: .9em; color: #333; margin-top: .3em; }}
.figure-missing {{ color: #999; font-style: italic; }}
section.page + section.page {{ margin-top: 1.4em; }}
@media print {{ section.page {{ break-before: page; }}
                section.page:first-child {{ break-before: auto; }} }}
"""


def render_html(doc: Document, job_dir: Path,
                dictionary: set[str] | None = None) -> str:
    title = html.escape(doc.document_id)
    body = []
    for pi, page in enumerate(doc.pages):
        if pi:
            body.append('<hr class="section-sep">')
        body.append(_page_html(page, doc, job_dir, dictionary))
    lang = doc.settings.target_language or doc.settings.source_language
    return (
        f'<!doctype html>\n<html lang="{html.escape(lang)}">\n<head>\n'
        f'<meta charset="utf-8">\n<title>{title}</title>\n'
        f"<style>{_css(doc.settings.fonts)}</style>\n</head>\n<body>\n"
        + "\n".join(body)
        + "\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------
# PDF backend (owner decision: headless Chromium via Playwright)
# --------------------------------------------------------------------------
#
# The PDF is a thin consumer of the print-ready, fully self-contained page.html.
# Chromium is primary because it renders the EXACT HTML the preview already
# produces, so the PDF matches the browser 1:1 (one rendering target, not two).
# WeasyPrint stays as a secondary fallback (its own CSS engine may diverge).
# Whatever is chosen, if it is unavailable we fall through and still emit HTML,
# so the gate is never blocked.


def _pdf_via_chromium(html_path: Path, out_pdf: Path) -> tuple[bool, str]:
    """Render ``render/page.html`` to PDF with Playwright headless Chromium.

    Loads the LOCAL file (``file://``) rather than pushing the HTML string over
    CDP: the HTML inlines full-res dewarped images as data URIs and can be many
    MB, so a local load is faster and less flaky. ``file://`` resolves ``data:``
    images fine, so the self-contained HTML needs no asset server.

    Two flags are load-bearing:
      * ``print_background=True`` — Chromium prints backgrounds OFF by default,
        which would silently drop the ``.flag`` uncertainty highlight (CLAUDE.md's
        load-bearing feature) from the PDF.
      * ``prefer_css_page_size=True`` — honor the HTML's ``@page { size: A4; ... }``
        instead of Chromium's default Letter/margins.

    NOTE (Gate 5): the sync Playwright API raises if called inside a running
    asyncio loop. Fine for this CLI (no loop); the future FastAPI server must
    drive PDF export off the request loop (async API or a subprocess), not call
    this directly.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return False, "playwright not importable"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(html_path.as_uri(), wait_until="load")
                page.pdf(path=str(out_pdf), print_background=True,
                         prefer_css_page_size=True)
            finally:
                browser.close()
    except Exception as e:  # pragma: no cover - depends on a launched browser
        return False, f"Chromium present but failed ({e!r})"
    try:                                    # version is cosmetic; never fail on it
        from importlib.metadata import version
        ver = version("playwright")
    except Exception:
        ver = "?"
    return True, f"PDF written via headless Chromium (Playwright {ver})"


def _pdf_via_weasyprint(html_str: str, out_pdf: Path) -> tuple[bool, str]:
    """Secondary fallback: HTML string -> PDF with WeasyPrint if importable."""
    try:
        import weasyprint  # type: ignore
    except Exception:
        return False, "weasyprint not importable"
    try:
        weasyprint.HTML(string=html_str).write_pdf(str(out_pdf))
        return True, f"PDF written via WeasyPrint {weasyprint.__version__}"
    except Exception as e:  # pragma: no cover - depends on system libs
        return False, f"WeasyPrint present but failed ({e!r})"


def try_render_pdf(html_str: str, out_pdf: Path, backend: str = "chromium",
                   html_path: Path | None = None) -> tuple[bool, str]:
    """Dispatch HTML->PDF by the configured ``backend``. Returns (wrote_pdf, note).

    ``backend``: ``chromium`` (default), ``weasyprint``, ``auto`` (chromium then
    weasyprint), or ``none`` (skip). Chromium needs the on-disk ``html_path``
    (it loads the local file); WeasyPrint consumes the HTML string. A chosen
    engine that is unavailable falls through to the next candidate, and if none
    succeed we return False with a clear note — render still wrote page.html.
    """
    backend = (backend or "chromium").lower()
    if backend == "none":
        return False, "pdf_backend=none — emitted HTML only (PDF skipped by config)."

    attempts: list[tuple[bool, str]] = []
    order = {"chromium": ["chromium"], "weasyprint": ["weasyprint"],
             "auto": ["chromium", "weasyprint"]}.get(backend, ["chromium"])
    for name in order:
        if name == "chromium" and html_path is not None:
            ok, note = _pdf_via_chromium(html_path, out_pdf)
        elif name == "weasyprint":
            ok, note = _pdf_via_weasyprint(html_str, out_pdf)
        else:
            ok, note = False, f"{name}: html_path unavailable"
        if ok:
            return True, note
        attempts.append((ok, f"{name}: {note}"))

    tried = "; ".join(n for _, n in attempts)
    hint = ("install it with `pip install playwright && playwright install "
            "chromium`" if "chromium" in order else "")
    return False, (f"pdf_backend={backend} unavailable — emitted HTML only "
                   f"[{tried}]. {hint}".rstrip())


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def run(job_dir: Path, cfg: dict, debug: bool = False) -> Path:
    t0 = time.perf_counter()
    job_dir = job_dir.resolve()
    doc_json = job_dir / "document.json"
    if not doc_json.exists():
        raise FileNotFoundError(
            f"missing {doc_json} — Stage 08 renders the editable document. Run "
            f"stage07_assemble on this job first.")
    doc = Document.model_validate_json(doc_json.read_text(encoding="utf-8"))

    out_dir = job_dir / "render"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_str = render_html(doc, job_dir, dictionary=None)  # de-hyphen dict seam
    html_path = out_dir / "page.html"
    html_path.write_text(html_str, encoding="utf-8")

    backend = str((cfg.get("reconstruct") or {}).get("pdf_backend", "chromium"))
    wrote_pdf, pdf_note = try_render_pdf(
        html_str, out_dir / "page.pdf", backend=backend, html_path=html_path)

    n_blocks = sum(len(p.blocks) for p in doc.pages)
    n_words = sum(bool(w.text.strip()) for p in doc.pages for b in p.blocks for w in b.words)
    n_flag = sum(w.flag_visible for p in doc.pages for b in p.blocks for w in b.words)
    n_trans = sum(1 for p in doc.pages for b in p.blocks if b.text is not None)
    n_fig = sum(1 for p in doc.pages for b in p.blocks if b.type is BlockType.FIGURE)
    order_mode = doc.settings.order_mode
    n_order_unreviewed = sum(
        b.order_review_visible(order_mode) for p in doc.pages for b in p.blocks)

    embedded = [fam for fname, fam, *_ in _FONT_FACES if (FONTS_DIR / fname).exists()]
    if embedded:
        font_note = ("Fonts embedded as @font-face data URIs (self-contained): "
                     + ", ".join(embedded) + " — covers Latin + Cyrillic; renders "
                     "identically without the font installed on the host.")
    else:
        font_note = (f"No bundled TTFs found in {FONTS_DIR} — HTML names the font "
                     "stack but embeds nothing; the renderer falls back to a system "
                     "serif (Cyrillic may tofu). Bundle NotoSerif.ttf to fix.")

    total_ms = (time.perf_counter() - t0) * 1000.0
    meta = StageMeta(
        stage=STAGE, version=VERSION,
        params={
            "pages": len(doc.pages), "blocks": n_blocks, "words": n_words,
            "flag_visible": n_flag, "translated_blocks": n_trans, "figures": n_fig,
            "mode": doc.settings.uncertainty_mode,
            "order_mode": order_mode,
            "order_unreviewed": n_order_unreviewed,
            "source_language": doc.settings.source_language,
            "target_language": doc.settings.target_language,
            "pdf_backend": backend,
            "wrote_pdf": wrote_pdf,
            "embedded_fonts": embedded,
            "reads": ["document.json", "document_assets/"],
        },
        timings_ms={"total": round(total_ms, 1)},
        warnings=[
            pdf_note,
            font_note,
            "De-hyphenation is a wired seam: no per-language dictionary is loaded, "
            "so line-end hyphens are conservatively KEPT (join needs next-line "
            "lowercase AND joined token in dictionary). Supply a dictionary to "
            "activate joins.",
            "Render is a pure function of document.json + document_assets/ (reads "
            "no per-stage folders); re-run any time after edits. Images inlined as "
            "data URIs -> the HTML is self-contained and portable.",
        ] + ([
            f"order_mode=review and {n_order_unreviewed} block(s) still have an "
            "unreviewed reading order (not renumbered, not confirmed) — the output "
            "used Stage 04's automatic order for them. Open the editor to confirm/"
            "correct before treating this render as final. Editor-only signal; not "
            "shown in the print output.",
        ] if order_mode == "review" and n_order_unreviewed else []),
    )
    (out_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return html_path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Stage 08 — render the editable document.json to HTML (+PDF)")
    ap.add_argument("job_dir", type=Path, help="job folder, e.g. jobs/<job>/")
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)

    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = S4.load_config(args.config)
    html_path = run(args.job_dir, cfg, debug=args.debug)
    meta = (args.job_dir / "render" / "meta.json")
    print(f"{args.job_dir}: wrote {html_path}")
    if meta.exists():
        import json
        p = json.loads(meta.read_text(encoding="utf-8"))["params"]
        print(f"  pages={p['pages']} words={p['words']} figures={p['figures']} "
              f"flagged={p['flag_visible']} translated_blocks={p['translated_blocks']} "
              f"mode={p['mode']} pdf={p['wrote_pdf']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
