"""Visual editor — the mutable edit surface over the editable ``document.json``.

This is the owner's chosen editing surface (``docs/GATE4_SPEC.md``, "Out of scope
for this gate (next step)"). It is **not** a pipeline stage: like Stage 07/08 it is
JOB-LEVEL and lives deliberately OUTSIDE the per-page immutable contract, and like
render it reads (and here also WRITES) **only** ``document.json`` + ``document_assets/``
— never the per-page stage folders — so a document saved months ago stays editable
after an upstream stage re-runs (self-containment rule).

A tiny stdlib ``http.server`` serves a single-page browser editor and a small JSON
API. No FastAPI dependency: that is Gate 5, and the reusable asset is the pure
edit-apply/validation logic here (``normalize_edits`` / ``save_document``), which a
future FastAPI server lifts unchanged — the HTTP layer is a thin swap.

**The load-bearing correctness rule — keep assemble's clobber-detection honest.**
``stage07_assemble._document_has_edits`` protects a user's work from a re-assemble
by checking exactly: ``settings.target_language`` set, any block ``structure_edited``,
any block ``order_confirmed`` (an accepted-auto-order review is real work too), any
block ``text`` override, or any word ``edited``. So when the editor saves, it MUST set
those same flags, or a later ``python -m pipeline.stage07_assemble`` (without
``--force``) would silently discard the edits. ``normalize_edits`` enforces this
server-side regardless of what the browser sent:

  * word ``text`` diverged from ``text_ocr``  -> ``edited = True``
    (this is also what clears the owner's per-word ``flag_visible`` marker and makes
    patch-mode render the correction instead of the stale crop);
  * block ``type``/``reading_order`` diverged from ``type_auto``/``order_auto``
    -> ``structure_edited = True``.
``order_confirmed`` (the review-mode "accept auto order" action) is sent by the browser
and saved as-is — it needs no divergence to infer. ``text_ocr``/``*_auto`` provenance is
NEVER touched.

**Preview is HTML-only.** Re-rendering the HTML (``stage08_render.render_html``) is
cheap; the Chromium/Playwright PDF path is slow/flaky, so it stays a separate
explicit export, not the live-preview loop.

Endpoints:
  GET  /                     the editor SPA (pipeline/assets/editor/index.html)
  GET  /api/document         current document.json
  PUT  /api/document         validate (pydantic) -> normalize_edits -> atomic save (+ .bak)
  GET  /assets/<relpath>     a file under document_assets/ (path-traversal guarded)
  POST /api/render           re-render render/page.html (HTML only) from disk
  GET  /render/page.html     the last HTML preview

Usage:
    python -m pipeline.editor jobs/<job>/ [--port 8000] [--no-browser]
"""

from __future__ import annotations

import argparse
import json
import os
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from pipeline.page_model import Block, Document, DocPage, Word
from pipeline import stage08_render as S8

REPO_ROOT = Path(__file__).resolve().parent.parent
EDITOR_DIR = REPO_ROOT / "pipeline" / "assets" / "editor"
ASSETS_DIRNAME = "document_assets"

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json; charset=utf-8",
}


# --------------------------------------------------------------------------
# Pure edit-apply / persistence logic (the seam Gate 5's FastAPI reuses)
# --------------------------------------------------------------------------


def load_document(job_dir: Path) -> Document:
    doc_json = job_dir / "document.json"
    if not doc_json.exists():
        raise FileNotFoundError(
            f"missing {doc_json} — run stage07_assemble on this job first.")
    return Document.model_validate_json(doc_json.read_text(encoding="utf-8"))


def normalize_edits(doc: Document) -> Document:
    """Enforce the edit invariants assemble's clobber-detection keys on, so saved
    edits survive a later re-assemble; never touch provenance (``text_ocr``/``*_auto``).

    Flags are only ever SET (additive) — a word/block already marked stays marked.
    """
    for page in doc.pages:
        for blk in page.blocks:
            if blk.type_auto is not None and blk.type != blk.type_auto:
                blk.structure_edited = True
            if blk.order_auto is not None and blk.reading_order != blk.order_auto:
                blk.structure_edited = True
            for w in blk.words:
                if w.text_ocr is not None and w.text != w.text_ocr:
                    w.edited = True
    return doc


def save_document(job_dir: Path, doc: Document) -> Path:
    """Atomically persist the (normalized) document to document.json, keeping the
    prior copy as document.json.bak. Temp file + ``os.replace`` so a crash mid-write
    can never leave a half-written working copy (edits are precious)."""
    normalize_edits(doc)
    doc_json = job_dir / "document.json"
    if doc_json.exists():
        bak = job_dir / "document.json.bak"
        bak.write_bytes(doc_json.read_bytes())
    tmp = job_dir / "document.json.tmp"
    tmp.write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, doc_json)  # atomic on Windows + POSIX
    return doc_json


def render_preview(job_dir: Path) -> Path:
    """Re-render render/page.html (HTML only) from the on-disk document. The slow
    Chromium PDF path is intentionally NOT run here — preview stays cheap."""
    doc = load_document(job_dir)
    out_dir = job_dir / "render"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_str = S8.render_html(doc, job_dir, dictionary=None)
    html_path = out_dir / "page.html"
    html_path.write_text(html_str, encoding="utf-8")
    return html_path


def _safe_child(root: Path, relpath: str) -> Path | None:
    """Resolve ``relpath`` under ``root``, or None if it escapes (traversal guard)."""
    root = root.resolve()
    try:
        target = (root / relpath).resolve()
    except OSError:
        return None
    if root == target or root in target.parents:
        return target
    return None


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    job_dir: Path = Path(".")  # set by serve()

    server_version = "bookscan-editor/0.1"

    # ---- helpers ----
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _serve_file(self, path: Path) -> None:
        if not path.is_file():
            self._json(404, {"error": f"not found: {path.name}"})
            return
        ctype = _MIME.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    # ---- routing ----
    def do_GET(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if route in ("/", "/index.html"):
            self._serve_file(EDITOR_DIR / "index.html")
        elif route == "/api/document":
            try:
                doc = load_document(self.job_dir)
            except FileNotFoundError as e:
                self._json(404, {"error": str(e)})
                return
            self._send(200, doc.model_dump_json().encode("utf-8"),
                       "application/json; charset=utf-8")
        elif route == "/api/meta":
            self._json(200, {"job_dir": str(self.job_dir),
                             "job": self.job_dir.name})
        elif route.startswith("/document_assets/"):
            # Asset refs in document.json (image_asset / patch_asset) already carry
            # the "document_assets/" prefix, so the browser requests "/"+ref. Serve
            # from the job dir, guarded to the document_assets subtree only.
            target = _safe_child(self.job_dir / ASSETS_DIRNAME,
                                 route[len("/document_assets/"):])
            if target is None:
                self._json(403, {"error": "forbidden"})
            else:
                self._serve_file(target)
        elif route == "/render/page.html":
            self._serve_file(self.job_dir / "render" / "page.html")
        elif route.startswith("/static/"):
            target = _safe_child(EDITOR_DIR, route[len("/static/"):])
            self._serve_file(target) if target else self._json(403, {"error": "forbidden"})
        else:
            self._json(404, {"error": f"no route {route}"})

    def do_PUT(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if route != "/api/document":
            self._json(404, {"error": f"no route {route}"})
            return
        raw = self._read_body()
        try:
            doc = Document.model_validate_json(raw)  # reject a malformed working copy
        except Exception as e:  # pydantic ValidationError or JSON error
            self._json(400, {"error": "invalid document", "detail": str(e)[:2000]})
            return
        save_document(self.job_dir, doc)  # normalizes edit flags + atomic write + .bak
        has_edits = _document_has_edits(doc)
        self._json(200, {"ok": True, "has_edits": has_edits})

    def do_POST(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if route == "/api/render":
            try:
                render_preview(self.job_dir)
            except Exception as e:  # keep the editor alive; report the failure
                self._json(500, {"ok": False, "error": str(e)[:2000]})
                return
            self._json(200, {"ok": True, "href": "/render/page.html"})
        else:
            self._json(404, {"error": f"no route {route}"})

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        pass


def _document_has_edits(doc: Document) -> bool:
    """Mirror of stage07_assemble._document_has_edits (kept local to avoid importing
    the whole assemble stage just for one predicate) — reported to the UI so the user
    sees when their edits are now protected against a re-assemble."""
    if doc.settings.target_language:
        return True
    for pg in doc.pages:
        for blk in pg.blocks:
            if blk.structure_edited or blk.order_confirmed or blk.text is not None:
                return True
            if any(w.edited for w in blk.words):
                return True
    return False


# --------------------------------------------------------------------------
# Server entry
# --------------------------------------------------------------------------


def serve(job_dir: Path, port: int = 8000, open_browser: bool = True) -> None:
    job_dir = job_dir.resolve()
    load_document(job_dir)  # fail fast with a clear message if there's no document
    handler = type("_Bound", (_Handler,), {"job_dir": job_dir})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"bookscan editor — {job_dir.name}")
    print(f"  editing {job_dir / 'document.json'}")
    print(f"  serving {url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Visual editor for the editable document.json (Gate 4).")
    ap.add_argument("job_dir", type=Path, help="job folder, e.g. jobs/<job>/")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true",
                    help="do not auto-open a browser (e.g. for tests)")
    args = ap.parse_args(argv)

    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    serve(args.job_dir, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
