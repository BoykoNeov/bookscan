"""P7: replay Stage 07's hires loop for ONE spread (page_022), in batch order.

Same shared frame index, same block order, same _upgrade_figure call, over both
subpages - the batch conditions the isolation probe did not have. Reports which
figures upgrade, and block 5 of the left page in particular.

    python docs/data/hires_batch_replay_20260924.py <job_dir> [--skip-before]
--skip-before: start at left #5 (no figure searched before it) - the control.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import cv2
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import figure_hires as FH  # noqa: E402
from pipeline import stage07_assemble as S7  # noqa: E402
from pipeline.page_model import Block, BlockType  # noqa: E402


def main(job: Path, skip_before: bool) -> int:
    cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    params = FH.resolve_params(cfg)
    doc = json.loads((job / "document.json").read_text(encoding="utf-8"))
    pd = job / "page_022"
    frames = S7._capture_frames(pd, params)
    started = not skip_before
    res = []
    with tempfile.TemporaryDirectory() as td:
        for stem in ("left", "right"):
            page = next(p for p in doc["pages"] if p["page_id"] == f"page_022__{stem}")
            img = cv2.imread(str(pd / "03_dewarp" / f"{stem}.png"), cv2.IMREAD_COLOR)
            for bd in page["blocks"]:
                blk = Block.model_validate(bd)
                if blk.type is not BlockType.FIGURE:
                    continue
                if not started:
                    if stem == "left" and blk.id == 5:
                        started = True
                    else:
                        continue
                up = S7._upgrade_figure(blk.model_copy(deep=True), img, frames,
                                        params, Path(td), f"p22__{stem}")
                res.append({"page": stem, "block": blk.id,
                            "upgraded": up is not None,
                            "scale": up and up["scale"]})
                print(res[-1])
    print("decode_failed:", [f.name for f in frames if f.decode_failed])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1]), "--skip-before" in sys.argv))
