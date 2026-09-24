"""Read-only probe: run find_book (shipped params) on the real de_02 anchor and
the sofa job's spreads 1-4, and list 8 seeded GrabCut draws per frame.
Writes nothing into the repo or the job."""
import json, sys, time
from pathlib import Path
import cv2
REPO = Path(r"M:\claud_projects\bookscan")
sys.path.insert(0, str(REPO))
import yaml
from pipeline import book_boundary as BB

cfg = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8")) or {}
params = BB.resolve_params(cfg)
frames = {"de_02(real)": REPO / "jobs/orient_fix_de2/page_001/01_fuse/anchor.png"}
job = REPO / "jobs/20260829-084115-de3c20d3"
for i in range(1, 5):
    frames[f"sofa_{i}"] = job / f"page_{i:03d}/01_fuse/anchor.png"


def spread(bs):
    if len(bs) < 2:
        return 0.0
    u = bs[0]
    for b in bs[1:]:
        u = BB._union(u, b)
    uw, uh = max(1, u[2] - u[0]), max(1, u[3] - u[1])
    return max((max(b[i] for b in bs) - min(b[i] for b in bs))
               / (uw if i % 2 == 0 else uh) for i in range(4))


out = {}
for name, p in frames.items():
    img = cv2.imread(str(p))
    h, w = img.shape[:2]
    t = time.perf_counter()
    bb = BB.find_book(img, params)
    ms = (time.perf_counter() - t) * 1000
    draws8 = [BB.grabcut_box(img, params, rng_seed=s) for s in range(8)]
    ok = [d for d in draws8 if d is not None]
    rec = {"frame": [w, h], "applied": bb.applied, "reason": bb.reason,
           "emit": list(bb.emit), "gc_jitter_3": bb.diag.get("gc_jitter"),
           "gc_draws_3": bb.diag.get("gc_draws"),
           "draws_8": [list(d) if d else None for d in draws8],
           "jitter_8": round(spread(ok), 4), "ms": round(ms)}
    out[name] = rec
    print(f"\n== {name}  frame {w}x{h}  applied={bb.applied}  "
          f"jitter(3)={rec['gc_jitter_3']}  jitter(8)={rec['jitter_8']}")
    print(f"   reason: {bb.reason}")
    print(f"   emit:   {list(bb.emit)}")
    for s, d in enumerate(draws8):
        print(f"   seed {s}: {list(d) if d else None}")
(Path(__file__).parent / "gc_jitter_sofa_20260924.json").write_text(json.dumps(out, indent=1))
