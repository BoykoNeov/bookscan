"""Is each de_0N Stage 01 anchor (gitignored jobs/orient_fix_deN) pixel-identical
to the committed testset/de_0N.jpg, read the way tools/split_eval reads it
(EXIF orientation ignored)? Writes de_anchor_identity_20260924.json beside itself.
Needs the owner's jobs/ folder; that is the point — it is run once, so that
split_eval never needs jobs/ again."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
FLAGS = cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
out = {"opencv": cv2.__version__, "read_flags": "IMREAD_COLOR|IMREAD_IGNORE_ORIENTATION",
       "rows": {}}
for n in ("1", "2"):
    jpg = REPO / f"testset/de_0{n}.jpg"
    png = REPO / f"jobs/orient_fix_de{n}/page_001/01_fuse/anchor.png"
    a, j = cv2.imread(str(png), FLAGS), cv2.imread(str(jpg), FLAGS)
    same_shape = a.shape == j.shape
    d = np.abs(a.astype(np.int16) - j.astype(np.int16)) if same_shape else None
    out["rows"][f"de_0{n}"] = {
        "jpg": jpg.relative_to(REPO).as_posix(),
        "png": png.relative_to(REPO).as_posix(),
        "jpg_file_sha256": hashlib.sha256(jpg.read_bytes()).hexdigest(),
        "png_file_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
        "jpg_decoded_sha256": hashlib.sha256(j.tobytes()).hexdigest(),
        "png_decoded_sha256": hashlib.sha256(a.tobytes()).hexdigest(),
        "shape_hwc": list(a.shape),
        "max_abs_diff": int(d.max()) if same_shape else None,
        "differing_pixels": int((d.max(axis=2) > 0).sum()) if same_shape else None,
        "jpg_exif_orientation": Image.open(jpg).getexif().get(274),
    }
    print(f"de_0{n}", out["rows"][f"de_0{n}"])
(Path(__file__).parent / "de_anchor_identity_20260924.json").write_text(
    json.dumps(out, indent=1), encoding="utf-8")
