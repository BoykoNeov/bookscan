"""P7 follow-up: the blocks unreadable_panel re-types to FIGURE never reach the
hires search (it runs after it). Search each of them now, exactly as Stage 07
searches a figure, and report which upgrade.

    python docs/data/hires_panels_probe_20260924.py <job_dir> <document.meta.json>
Writes docs/data/hires_panels_20260924.json and, per upgraded panel, a page-crop
vs upgraded checkerboard under W:/temp/claude/p7/checker/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import figure_hires as FH  # noqa: E402
from pipeline import stage07_assemble as S7  # noqa: E402
from pipeline.page_model import Block, BlockType  # noqa: E402

CHECK = Path("W:/temp/claude/p7/checker")


def checker(a: np.ndarray, b: np.ndarray, tile: int = 48) -> np.ndarray:
    b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    m = ((yy // tile + xx // tile) % 2 == 0)[..., None]
    return np.where(m, a, b)


def main(job: Path, meta: Path) -> int:
    cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    params = FH.resolve_params(cfg)
    doc = json.loads((job / "document.json").read_text(encoding="utf-8"))
    upgraded = {(u["page"], u["block"]) for u in
                json.loads(meta.read_text(encoding="utf-8"))["params"]["figure_hires_sources"]}
    CHECK.mkdir(parents=True, exist_ok=True)
    # a figure that the hires pass never saw: re-typed FIGURE by a Stage 07 pass
    # that runs after it (type_promoted and FIGURE), and not already upgraded
    todo: dict[str, list] = {}
    for p in doc["pages"]:
        for bd in p["blocks"]:
            if bd["type"] == "figure" and bd.get("type_promoted") \
                    and (p["page_id"], bd["id"]) not in upgraded and not bd.get("is_surface"):
                todo.setdefault(p["page_id"], []).append(Block.model_validate(bd))
    out = []
    for pid in sorted({k.split("__")[0] for k in todo}):
        pd = job / pid
        frames = S7._capture_frames(pd, params)
        for sub in ("left", "right", "single"):
            key = f"{pid}__{sub}"
            if key not in todo:
                continue
            img = cv2.imread(str(pd / "03_dewarp" / f"{sub}.png"), cv2.IMREAD_COLOR)
            for blk in todo[key]:
                b = blk.bbox
                crop = img[b.y:b.y2, b.x:b.x2]
                got = FH.compose(crop, FH.candidates(crop, frames, params), params)
                row = {"page": key, "block": blk.id, "bbox": b.model_dump(),
                       "words": len(blk.words), "upgraded": got is not None}
                if got is not None:
                    hi, used = got
                    row.update(scale=round(hi.shape[1] / max(1, crop.shape[1]), 3),
                               sources=[s.as_dict() for s in used])
                    up = cv2.resize(crop, (hi.shape[1], hi.shape[0]),
                                    interpolation=cv2.INTER_CUBIC)
                    cv2.imwrite(str(CHECK / f"{key}__{blk.id}_checker.png"), checker(up, hi))
                    cv2.imwrite(str(CHECK / f"{key}__{blk.id}_hires.png"), hi)
                    cv2.imwrite(str(CHECK / f"{key}__{blk.id}_crop_up.png"), up)
                out.append(row)
                print(row if not row["upgraded"] else {k: row[k] for k in ("page", "block", "words", "scale")})
        for f in frames:
            f.release()
    (REPO / "docs/data/hires_panels_20260924.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print(f"{sum(r['upgraded'] for r in out)} of {len(out)} upgrade")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2])))
