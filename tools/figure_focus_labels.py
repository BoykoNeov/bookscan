"""Collect the owner's by-eye verdicts: is a picture upgrade sharper than the page crop?

Hand-off item 5 (``docs/plans/handoff-2026-11-12.md``), pre-registration
``docs/data/figure_focus_prereg_20261112.md``. ``pipeline/figure_hires.py`` swaps a
picture cut from the page for one cut from a close-up when the close-up is larger,
covers it and lines up; nothing checks that it is SHARPER. Before any focus number
is computed on a job, its owner says, for every upgraded picture, which of two
unlabeled tiles is sharper:

* the page crop (``document_assets/<page>.png`` cut at the block's box), enlarged
  to the upgrade's size with bicubic interpolation — what a reader would see if
  the upgrade were not there, at the same size;
* the upgrade itself (``Block.figure_asset``).

The two are shown side by side in a random order. Which side is which is held by
this server only and written to the answers file at save time, so the page the
owner looks at cannot give it away. Buttons: left sharper / right sharper /
cannot tell. A "1:1" view shows both at full size, scrolled together.

    python -m tools.figure_focus_labels jobs/<job>/ [--port 8013]
    then open http://127.0.0.1:8013/

Answers go to ``docs/data/figure_focus_labels_<job>_<date>.json``. Reads the job;
writes nothing into it. Tiles are made in memory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "docs" / "data"
SEED = 20261112   # fixed in the pre-registration; the order it makes is recorded


def upgraded_pictures(job_dir: Path) -> list[dict]:
    """Every live block whose upgrade Stage 08 would actually print, in document order."""
    doc = json.loads((job_dir / "document.json").read_text(encoding="utf-8"))
    out = []
    for p in doc["pages"]:
        for b in p["blocks"]:
            if not b.get("figure_asset") or b.get("deleted"):
                continue
            if b.get("figure_asset_box") != b.get("bbox"):
                continue   # Stage 08 falls back to the page crop: no upgrade shown
            out.append({"page_id": p["page_id"], "block_id": b["id"], "bbox": b["bbox"],
                        "asset": b["figure_asset"],
                        "scale": b.get("figure_asset_scale"),
                        "source": b.get("figure_asset_source")})
    return out


def tiles(job_dir: Path, item: dict) -> tuple[np.ndarray, np.ndarray]:
    """(page crop enlarged to the upgrade's size, upgrade)."""
    page = cv2.imread(str(job_dir / "document_assets" / f"{item['page_id']}.png"), cv2.IMREAD_COLOR)
    up = cv2.imread(str(job_dir / item["asset"]), cv2.IMREAD_COLOR)
    if page is None or up is None:
        raise FileNotFoundError(f"missing image for {item['page_id']} #{item['block_id']}")
    x, y, w, h = (item["bbox"][k] for k in ("x", "y", "w", "h"))
    crop = page[y:y + h, x:x + w]
    crop_big = cv2.resize(crop, (up.shape[1], up.shape[0]), interpolation=cv2.INTER_CUBIC)
    return crop_big, up


def blind_order(n: int, seed: int = SEED) -> list[str]:
    """For each item, which tile goes on the LEFT: 'crop' or 'upgrade'."""
    rng = random.Random(seed)
    return [rng.choice(("crop", "upgrade")) for _ in range(n)]


def decode(answer: str, left: str) -> str:
    """Owner's answer about a side -> verdict about the upgrade."""
    if answer == "cannot_tell":
        return "cannot_tell"
    sharper_side = left if answer == "left" else ("upgrade" if left == "crop" else "crop")
    return "upgrade_sharper" if sharper_side == "upgrade" else "crop_sharper"


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Which is sharper?</title>
<style>
body{font:15px system-ui,sans-serif;margin:16px;background:#f4f4f4;color:#222}
.pair{display:flex;gap:12px}.pair div{flex:1;background:#fff;border:1px solid #ccc;overflow:auto;max-height:78vh}
.fit img{width:100%;height:auto;display:block}.full img{display:block}
button{font-size:16px;padding:8px 18px;margin:8px 6px 0 0}#bar{margin:10px 0}
.done{color:#070}
</style></head><body>
<div id="bar"><b id="pos"></b> &nbsp; Which picture shows more real detail (ignore size and colour)?
&nbsp; <label><input type="checkbox" id="full"> 1:1 (full size, scrolls together)</label></div>
<div class="pair fit" id="pair"><div id="L"><img id="li"></div><div id="R"><img id="ri"></div></div>
<div><button onclick="ans('left')">Left is sharper</button><button onclick="ans('right')">Right is sharper</button>
<button onclick="ans('cannot_tell')">Cannot tell</button> &nbsp;
<button onclick="go(-1)">&larr; back</button><button onclick="go(1)">next &rarr;</button>
<span id="msg"></span></div>
<script>
let n=0,i=0,answers={};
const $=id=>document.getElementById(id);
async function init(){const r=await fetch('state');const s=await r.json();n=s.n;answers=s.answers;show();}
function show(){$('li').src='img/'+i+'/L';$('ri').src='img/'+i+'/R';
 $('pos').textContent='Picture '+(i+1)+' of '+n+(answers[i]?' — answered: '+answers[i]:'');}
function go(d){i=Math.max(0,Math.min(n-1,i+d));show();}
async function ans(a){answers[i]=a;const r=await fetch('answer',{method:'POST',body:JSON.stringify({i:i,answer:a})});
 const s=await r.json();$('msg').innerHTML=s.complete?'<span class="done">All answered and saved to '+s.path+'</span>':'saved ('+s.answered+' of '+n+')';
 if(i<n-1)go(1);else show();}
$('full').onchange=e=>{$('pair').className='pair '+(e.target.checked?'full':'fit');};
$('L').onscroll=()=>{$('R').scrollTop=$('L').scrollTop;$('R').scrollLeft=$('L').scrollLeft;};
$('R').onscroll=()=>{$('L').scrollTop=$('R').scrollTop;$('L').scrollLeft=$('R').scrollLeft;};
init();
</script></body></html>"""


def make_server(job_dir: Path, port: int, out_path: Path) -> ThreadingHTTPServer:
    items = upgraded_pictures(job_dir)
    if not items:
        raise SystemExit(f"{job_dir}: no upgraded pictures to judge")
    left = blind_order(len(items))
    answers: dict[int, str] = {}
    if out_path.exists():   # resume a half-done session
        prev = json.loads(out_path.read_text(encoding="utf-8"))
        answers = {k: it["answer"] for k, it in enumerate(prev["items"]) if it.get("answer")}

    def save() -> None:
        rec = {
            "tool": "tools/figure_focus_labels.py",
            "prereg": "docs/data/figure_focus_prereg_20261112.md",
            "job": job_dir.name, "seed": SEED,
            "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
            "complete": len(answers) == len(items),
            "items": [{**it, "left": left[k], "answer": answers.get(k),
                       "verdict": decode(answers[k], left[k]) if k in answers else None}
                      for k, it in enumerate(items)],
        }
        out_path.write_text(json.dumps(rec, indent=1), encoding="utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, body: bytes, ctype: str, code: int = 200) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                return self._send(PAGE.encode(), "text/html; charset=utf-8")
            if self.path == "/state":
                ans = {k: answers[k] for k in answers}
                return self._send(json.dumps({"n": len(items), "answers": ans}).encode(),
                                  "application/json")
            parts = self.path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "img" and parts[1].isdigit() and parts[2] in "LR":
                k = int(parts[1])
                if k >= len(items):
                    return self._send(b"no such picture", "text/plain", 404)
                crop_big, up = tiles(job_dir, items[k])
                want = left[k] if parts[2] == "L" else ("upgrade" if left[k] == "crop" else "crop")
                ok, png = cv2.imencode(".png", up if want == "upgrade" else crop_big)
                return self._send(png.tobytes(), "image/png")
            self._send(b"not found", "text/plain", 404)

        def do_POST(self) -> None:
            if self.path != "/answer":
                return self._send(b"not found", "text/plain", 404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            k, a = int(body["i"]), body["answer"]
            if not 0 <= k < len(items) or a not in ("left", "right", "cannot_tell"):
                return self._send(b"bad answer", "text/plain", 400)
            answers[k] = a
            save()
            self._send(json.dumps({"answered": len(answers), "complete": len(answers) == len(items),
                                   "path": str(out_path)}).encode(), "application/json")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("job_dir", type=Path)
    ap.add_argument("--port", type=int, default=8013)
    ap.add_argument("--out", type=Path, default=None,
                    help="answers file (default docs/data/figure_focus_labels_<job>_<date>.json)")
    a = ap.parse_args(argv)
    job = a.job_dir.resolve()
    out = a.out or OUT_DIR / f"figure_focus_labels_{job.name}_{dt.date.today():%Y%m%d}.json"
    srv = make_server(job, a.port, out)
    print(f"{len(upgraded_pictures(job))} pictures; open http://127.0.0.1:{a.port}/ ; answers -> {out}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
