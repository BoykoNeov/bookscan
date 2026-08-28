"""Book-box editor — the operator draws the box the detector could not find.

**Why this exists, in one paragraph.** ``pipeline/book_boundary.py`` locates the
book so Stage 02 can look for the spine inside it rather than inside the room. On
a pale, cluttered or lap-held capture it cannot: the bright-paper mask merges the
book with its surroundings, and the 2026-08-28 investigation measured **eight**
families of cue that might have told the two apart — paper-mask statistics,
Mahalanobis scalars, ring homogeneity, blob compactness, connectivity, an ink
veto, brightness polarity, border texture — and none of them can (RESULTS
2026-08-28). That negative is what makes a human in the loop the right answer
rather than a cop-out: it is the option the plan ranks as having a **guaranteed
ceiling**, and Phase 1 already taught the detector to say "I did not find the
book" honestly, which is the moment to ask.

**It is worth the click, measured.** Feeding the eight hand-labelled book boxes in
as if an operator had drawn them splits **8 of 8** correctly — including both
``paleset`` frames that fail today (1699 against 1680 ±200, and 1749 against
1778 ±200).

**And it tolerates a real mouse.** A 4080 px frame shown ~1000 px wide is ~4 image
pixels per screen pixel, so the drag is nowhere near ruler-accurate. Shrinking each
labelled box to simulate that:

  * emit box = the drag exactly -> 1 % undersized already loses 1.95 % of the
    book, 5 % undersized loses 9.73 %;
  * emit box = the drag padded by ``search_pad`` -> **0.00 % clipping at every
    perturbation up to 5 %**, all eight gutters still correct, and text is only
    lost past a ~14 % undersized drag.

So ``book_boundary.user_box`` pads the drawn box outward and Stage 02 cuts the
padded one. Draw it roughly; do not fuss.

What this writes is ``<page_dir>/book_box.json`` — **user input, not a stage
artifact**, which is why it sits at the page-dir root and why Stage 02 checks its
provenance before trusting it (see ``stage02_split.UserBookBox``). Deleting the
file restores the detector exactly.

The "re-split" button runs **Stage 02 only**. That is the whole feedback loop this
tool needs — draw, re-split, look at the overlay — and it is self-contained and
fast. Stages 03-06 stay a separate, explicit run.

Usage:
    python -m tools.book_box_editor jobs/<job_id>/ [--port 8011] [--no-browser]
"""

from __future__ import annotations

import argparse
import json
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import cv2
import numpy as np

from pipeline import book_boundary as BB
from pipeline import stage02_split as S2

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = REPO_ROOT / "tools" / "assets" / "book_box_editor"
PREVIEW_W = 1400        # what the browser gets; the box is stored in FULL-res px
ANCHOR_REL = "01_fuse/anchor.png"


# --------------------------------------------------------------------------
# Pure logic (no HTTP) — this is what the tests exercise
# --------------------------------------------------------------------------


def list_pages(job_dir: Path) -> list[Path]:
    """Page folders holding a Stage 01 anchor, in name order."""
    return sorted(p for p in job_dir.iterdir()
                  if p.is_dir() and (p / ANCHOR_REL).exists())


def page_state(page_dir: Path) -> dict:
    """Everything the browser needs about one page, and nothing it does not.

    Deliberately includes the detector's own ``reason`` and ``evidence``: the
    operator is being asked to do a job the detector could not, so they should see
    what it claimed — and since Phase 1 that text no longer overstates the case.
    """
    img = cv2.imread(str(page_dir / ANCHOR_REL),
                     cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if img is None:
        raise RuntimeError(f"unreadable anchor: {page_dir / ANCHOR_REL}")
    h, w = img.shape[:2]
    state: dict = {"page": page_dir.name, "frame_w": w, "frame_h": h,
                   "preview_w": min(PREVIEW_W, w)}

    user = S2.load_user_box(page_dir)
    state["user_box"] = list(user.box) if user else None
    state["user_box_stale"] = (
        S2.user_box_mismatch(user, w, h) if user else None)

    split = page_dir / "02_split" / "split.json"
    if split.exists():
        d = json.loads(split.read_text(encoding="utf-8"))
        c = d.get("book_crop") or {}
        state.update(
            gutter_x=d.get("gutter_x"), method=d.get("method"),
            crop_applied=d.get("book_crop_applied"),
            crop_source=d.get("book_crop_source", "detector"),
            reason=d.get("book_crop_reason", ""),
            evidence=d.get("book_crop_evidence", ""),
            detected_box=([c["x"], c["y"], c["x"] + c["w"], c["y"] + c["h"]]
                          if c else None),
            pages=[p["name"] for p in d.get("pages", [])])
    else:
        state.update(gutter_x=None, method=None, crop_applied=None,
                     crop_source=None, reason="", evidence="",
                     detected_box=None, pages=[])
    state["has_overlay"] = (page_dir / "debug" / "02_split.png").exists()
    return state


def save_user_box(page_dir: Path, box: list[int]) -> dict:
    """Write ``book_box.json`` with the provenance Stage 02 will check.

    Stamping the frame and its size here is what lets Stage 02 REFUSE the box
    later instead of silently applying coordinates that stopped meaning anything
    when Stage 01 re-ran. A box drawn on the wrong frame is a wrong crop with a
    human's confidence behind it.
    """
    img = cv2.imread(str(page_dir / ANCHOR_REL),
                     cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if img is None:
        raise RuntimeError(f"unreadable anchor: {page_dir / ANCHOR_REL}")
    h, w = img.shape[:2]
    x0, y0, x1, y1 = (int(v) for v in box)
    x0, x1 = sorted((max(0, min(w, x0)), max(0, min(w, x1))))
    y0, y1 = sorted((max(0, min(h, y0)), max(0, min(h, y1))))
    rec = S2.UserBookBox(
        box=[x0, y0, x1, y1], frame=ANCHOR_REL, frame_size=[w, h],
        drawn_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        note="drawn in tools/book_box_editor")
    # Reject here too, not only in Stage 02 — telling the operator now beats
    # letting them find out from a warning buried in meta.json.
    probe = BB.user_box(img, (x0, y0, x1, y1), BB.resolve_params({}))
    if not probe.applied:
        return {"ok": False, "error": probe.reason}
    (page_dir / S2.USER_BOX_FILE).write_text(
        rec.model_dump_json(indent=2), encoding="utf-8")
    return {"ok": True, "box": rec.box, "emit": list(probe.emit),
            "reason": probe.reason}


def clear_user_box(page_dir: Path) -> dict:
    """Delete the file. The detector then behaves exactly as if it never existed."""
    f = page_dir / S2.USER_BOX_FILE
    existed = f.exists()
    f.unlink(missing_ok=True)
    return {"ok": True, "removed": existed}


def resplit(page_dir: Path, cfg: dict) -> dict:
    """Re-run Stage 02 ONLY, so the operator sees the cut their box produced."""
    r = S2.run(page_dir, cfg)
    return {"ok": True, "gutter_x": r.gutter_x, "method": r.method,
            "crop_source": r.book_crop_source, "reason": r.book_crop_reason,
            "ratio": r.ratio, "pinch_depth": r.pinch_depth,
            "pinch_applicable": r.pinch_applicable,
            "pages": [p.name for p in r.pages]}


def preview_jpeg(path: Path, width: int = PREVIEW_W) -> bytes:
    """Scale an image down and JPEG it in memory — never written to the page dir.

    A 4080x3060 PNG is ~10 MB and the browser only needs to be drawn on, so this
    keeps the tool responsive without leaving files in a folder that belongs to
    the pipeline trace.
    """
    img = cv2.imread(str(path), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if img is None:
        raise FileNotFoundError(path)
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, max(1, int(h * width / w))),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        raise RuntimeError(f"could not encode {path}")
    return bytes(buf)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def make_handler(job_dir: Path, cfg: dict):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):     # quiet; the CLI prints what matters
            pass

        # -- helpers --
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _page(self, name: str) -> Path | None:
            """Resolve a page name, refusing anything that escapes the job dir."""
            p = (job_dir / name).resolve()
            if job_dir.resolve() not in p.parents and p != job_dir.resolve():
                return None
            return p if (p / ANCHOR_REL).exists() else None

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        # -- routes --
        def do_GET(self) -> None:
            u = urlparse(self.path)
            path, qs = unquote(u.path), parse_qs(u.query)
            if path == "/":
                html = (ASSET_DIR / "index.html").read_bytes()
                return self._send(200, html, "text/html; charset=utf-8")
            if path == "/api/pages":
                try:
                    return self._json([page_state(p) for p in list_pages(job_dir)])
                except Exception as exc:
                    return self._json({"error": str(exc)}, 500)
            if path in ("/frame", "/overlay"):
                page = self._page((qs.get("page") or [""])[0])
                if page is None:
                    return self._json({"error": "unknown page"}, 404)
                src = (page / ANCHOR_REL if path == "/frame"
                       else page / "debug" / "02_split.png")
                if not src.exists():
                    return self._json({"error": f"missing {src.name}"}, 404)
                try:
                    return self._send(200, preview_jpeg(src), "image/jpeg")
                except Exception as exc:
                    return self._json({"error": str(exc)}, 500)
            self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            u = urlparse(self.path)
            try:
                body = self._body()
            except Exception as exc:
                return self._json({"error": f"bad JSON: {exc}"}, 400)
            page = self._page(str(body.get("page", "")))
            if page is None:
                return self._json({"error": "unknown page"}, 404)
            try:
                if u.path == "/api/box":
                    return self._json(save_user_box(page, body["box"]))
                if u.path == "/api/clear":
                    return self._json(clear_user_box(page))
                if u.path == "/api/resplit":
                    return self._json(resplit(page, cfg))
            except Exception as exc:
                return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            self._json({"error": "not found"}, 404)

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Draw the book box Stage 02 could not find")
    ap.add_argument("job_dir", type=Path, help="jobs/<job_id>/")
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "config.yaml")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    job_dir = args.job_dir.resolve()
    if not job_dir.is_dir():
        ap.error(f"not a directory: {job_dir}")
    pages = list_pages(job_dir)
    if not pages:
        ap.error(f"no pages with {ANCHOR_REL} under {job_dir} — run Stage 01 first")

    cfg = S2.load_config(args.config)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(job_dir, cfg))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"book-box editor on {url}  ({len(pages)} page(s) in {job_dir.name})")
    print("  draw a rough box round the WHOLE book — it is padded outward before "
          "cutting, so a sloppy drag is safe")
    print("  Ctrl-C to stop")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
