"""Read every block with one local model (pre-registration: ../panelread_prereg_20261021.md).

    python -X utf8 docs/data/panelread_20261021/read.py qwen3.6:27b
    python -X utf8 docs/data/panelread_20261021/read.py gemma4:31b --arms page

Writes readings_<model>.json next to this file: {stem: {arm: text}}. Resumable:
blocks already read are skipped. Only one of the two models fits the GPU, so they
run one after the other.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import time
from pathlib import Path

import requests
from PIL import Image

HERE = Path(__file__).parent
URL = "http://127.0.0.1:11434/api/generate"
MAX_SIDE = 1600
PROMPT = (
    'Transcribe all printed text in this image exactly as printed, in reading order: '
    'top to bottom, left to right. Keep each printed line on its own line. If the text '
    'is a table, write one table row per line with the cells separated by " | ". '
    'Ignore pictures, pictograms and symbols. Do not translate, correct, complete or '
    'explain anything, and do not add any word that is not printed. If a word is cut '
    'off at the edge of the image, write only the letters you can see. If the image '
    'contains no printed text, answer exactly: NO TEXT')
OPTIONS = {"temperature": 0, "seed": 0, "num_ctx": 16384, "num_predict": 4096}


def encode(path: Path) -> str:
    im = Image.open(path).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)   # never enlarges
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def ask(model: str, path: Path) -> dict:
    t = time.time()
    r = requests.post(URL, json={"model": model, "prompt": PROMPT, "images": [encode(path)],
                                 "stream": False, "think": False, "options": OPTIONS},
                      timeout=900)
    r.raise_for_status()
    j = r.json()
    return {"text": j["response"], "seconds": round(time.time() - t, 1),
            "prompt_eval_count": j.get("prompt_eval_count"), "eval_count": j.get("eval_count"),
            "done_reason": j.get("done_reason")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--arms", default="page,close")
    a = ap.parse_args()
    refs = json.loads((HERE / "references.json").read_text(encoding="utf-8"))
    man = {e["stem"]: e for e in json.loads((HERE / "crops_manifest.json").read_text(encoding="utf-8"))}
    out_path = HERE / f"readings_{a.model.replace(':', '_')}.json"
    out = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    for stem, ref in refs.items():
        if stem.startswith("_") or ref["stratum"] == "excluded":
            continue
        e = man[stem]
        for arm in a.arms.split(","):
            src = e["page_read"] if arm == "page" else e.get("close_crop")
            if not src or arm in out.get(stem, {}):
                continue
            got = ask(a.model, HERE / src)
            out.setdefault(stem, {})[arm] = got
            out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"{stem} {arm} {got['seconds']}s {got['done_reason']} "
                  f"{got['text'][:70]!r}", flush=True)


if __name__ == "__main__":
    main()
