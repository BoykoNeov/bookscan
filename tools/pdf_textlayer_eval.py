"""Is a scanned PDF's own text layer worth using as a second opinion?

``docs/plans/pdf-import.md`` Slice 3 says to measure this before building it; the
protocol is pre-registered in ``docs/data/pdf_textlayer_prereg_20260924.md`` and
this tool implements exactly that document. Three steps, run in order:

    python -m tools.pdf_textlayer_eval prepare W:/temp/claude/pdf_textlayer/work
    python -m tools.pdf_textlayer_eval sites   W:/temp/claude/pdf_textlayer/work
        -> writes blind contact sheets (sheets/*.png) and labels_template.json;
           a judge fills labels.json by LOOKING at the sheets, never at key.json
    python -m tools.pdf_textlayer_eval score   W:/temp/claude/pdf_textlayer/work

``prepare`` cuts the chosen pages of each PDF into a sub-PDF, imports it with
``pipeline.pdf_import`` and runs the shipped ``run_all`` on every page.
``sites`` aligns the PDF's text layer against Stage 06's words BY SEQUENCE (Stage
03 moves the words, so the layer's boxes cannot be matched geometrically), finds
the 1<->1 disagreements, samples them, and draws each as a crop of ``03_dewarp``
with the two readings shown as A and B in a seeded random order. ``score`` joins
the labels to the key and applies the pre-registered gate.
"""

from __future__ import annotations

import difflib
import glob
import hashlib
import json
import random
import subprocess
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SEED = 20260924
CAP_PRIMARY = 60
CAP_AGREE = 20
MIN_LAYER_WORDS = 150
FRACTIONS = (0.3, 0.5, 0.7)
LINE_END_MARKS = ("\u00ad", "\u00ac")      # soft hyphen, ¬

_SRC = r"W:\Claude_projects\space-station\sources"
DOCS = [
    ("D1", r"M:\backup2\boiko\chernobyl_insag_7.pdf"),
    ("D2", _SRC + r"\Introduction to Mathematical Modeling of Crop Growth_ How -- *.pdf"),
    ("D3", _SRC + r"\olson1963.pdf"),
    ("D4", _SRC + r"\spacecraft thermal control handbook volume*.pdf"),
    ("D5", r"W:\temp\claude\bore_friction\ADA431357.pdf"),
    ("D6", _SRC + r"\biochemj01085-0088.pdf"),
    ("D7", _SRC + r"\connor1990.pdf"),
]
CONTROL = ("C", str(REPO / "jobs" / "figtext_en_coins_01" / "render" / "page.pdf"))
LABELS = ("A", "B", "neither", "both", "unclear")
AGREE_LABELS = ("right", "wrong", "unclear")


def _resolve(pattern: str) -> Path:
    hits = sorted(glob.glob(pattern))
    if len(hits) != 1:
        raise SystemExit(f"expected one file for {pattern!r}, found {hits}")
    return Path(hits[0])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def choose_pages(doc, *, control: bool = False) -> list[int]:
    """0-based pages, per the pre-registration."""
    from pipeline.pdf_import import SCAN_COVERAGE, image_coverage

    n = doc.page_count
    if control or n <= 3:
        return list(range(n))
    chosen: list[int] = []
    for f in FRACTIONS:
        start = round(f * (n - 1))
        for j in range(start, min(n, start + 11)):
            if j in chosen:
                continue
            pg = doc[j]
            if (len(pg.get_text("words")) >= MIN_LAYER_WORDS
                    and image_coverage(pg) >= SCAN_COVERAGE):
                chosen.append(j)
                break
    return chosen


# ---------------------------------------------------------------- prepare
def prepare(work: Path) -> None:
    import fitz

    from pipeline.pdf_import import import_pdf

    work.mkdir(parents=True, exist_ok=True)
    jobs = work / "jobs"
    manifest = {"seed": SEED, "docs": []}
    for doc_id, pattern in DOCS + [CONTROL]:
        path = _resolve(pattern)
        src = fitz.open(path)
        pages = choose_pages(src, control=doc_id == "C")
        md = src.metadata or {}
        sub = fitz.open()
        for j in pages:
            sub.insert_pdf(src, from_page=j, to_page=j)
        sub_path = work / doc_id / "sub.pdf"
        sub_path.parent.mkdir(parents=True, exist_ok=True)
        sub.save(sub_path)
        sub.close()
        manifest["docs"].append({
            "id": doc_id, "file": str(path), "sha256": _sha256(path),
            "page_count": src.page_count, "pages_1based": [j + 1 for j in pages],
            "producer": md.get("producer", ""), "creator": md.get("creator", "")})
        src.close()
        if not (jobs / doc_id).exists():
            import_pdf(sub_path, jobs, dpi=300, layout="detect", mode="flag", lang="eng",
                       job_id=doc_id, allow_vector=doc_id == "C",
                       staging_root=work / "staging")
        print(f"{doc_id}: {path.name[:60]} pages {[j + 1 for j in pages]}", flush=True)
    (work / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    for page_dir in sorted(jobs.glob("*/page_*")):
        if (page_dir / "06_uncertain" / "resolved.json").exists():
            continue
        r = subprocess.run([sys.executable, "-m", "pipeline.run_all", str(page_dir),
                            "--mode", "flag", "--lang", "eng"], cwd=REPO,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        (page_dir / "eval_run.log").write_text(
            f"exit {r.returncode}\n{r.stdout}\n{r.stderr}", encoding="utf-8")
        print(f"  {page_dir.parent.name}/{page_dir.name}: exit {r.returncode}", flush=True)


# ---------------------------------------------------------------- tokens
def prep_tokens(items: list[tuple[str, object]]) -> list[dict]:
    """(raw text, ref) -> comparison tokens, identically for both engines.

    NFKC; a trailing soft hyphen or ``¬`` is a line-end ``-`` and one elsewhere is
    dropped; ``x-`` + lowercase next token joins; then ``normalize_token``; empty
    tokens are dropped. A joined token keeps the refs of every word in it."""
    from pipeline.second_opinion import normalize_token

    clean = []
    for raw, ref in items:
        t = unicodedata.normalize("NFKC", raw or "")
        for m in LINE_END_MARKS:
            if t.endswith(m):
                t = t[:-1] + "-"
            t = t.replace(m, "")
        clean.append((t, [ref]))
    joined: list[tuple[str, list]] = []
    i = 0
    while i < len(clean):
        t, refs = clean[i]
        while (t.endswith("-") and len(t) > 1 and i + 1 < len(clean)
               and clean[i + 1][0][:1].islower()):
            i += 1
            t, refs = t[:-1] + clean[i][0], refs + clean[i][1]
        joined.append((t, refs))
        i += 1
    out = []
    for t, refs in joined:
        n = normalize_token(t)
        if n:
            out.append({"norm": n, "raw": t, "refs": refs})
    return out


def tesseract_words(page_dir: Path) -> list[dict]:
    res = json.loads((page_dir / "06_uncertain" / "resolved.json").read_text(encoding="utf-8"))
    words = []
    for sp in res["pages"]:
        blocks = sorted(sp["blocks"], key=lambda b: (b.get("reading_order") is None,
                                                     b.get("reading_order") or 0))
        for b in blocks:
            for wi, w in enumerate(b.get("words") or []):
                words.append({"sub": sp["name"], "block": b["id"], "i": wi,
                              "text": w["text"], "bbox": w["bbox"],
                              "decision": w.get("decision") or "keep"})
    return words


def align(t_toks: list[dict], l_toks: list[dict]):
    sm = difflib.SequenceMatcher(a=[t["norm"] for t in t_toks],
                                 b=[x["norm"] for x in l_toks], autojunk=False)
    return sm.get_opcodes()


# ---------------------------------------------------------------- sites
def sites(work: Path) -> None:
    import fitz

    from pipeline.second_opinion import load_lexicon

    lex = load_lexicon([REPO / "models" / "lexicons" / "en.dic"])
    if lex is None:
        raise SystemExit("no English lexicon at models/lexicons/en.* — arm (b) would be inert")
    manifest = json.loads((work / "manifest.json").read_text(encoding="utf-8"))
    per_doc, primary, agree = {}, [], []
    for d in manifest["docs"]:
        src = fitz.open(d["file"])
        stats = {"pages": 0, "t_tokens": 0, "l_tokens": 0, "equal_t": 0, "coverage": [],
                 "sites": 0, "sites_kept": 0, "sites_flagged": 0, "armb_kept": 0,
                 "other_replace": 0, "flagged_agree": 0}
        kept_sites, agree_pool = [], []
        for k, pno in enumerate(d["pages_1based"]):
            page_dir = work / "jobs" / d["id"] / f"page_{k + 1:03d}"
            if not (page_dir / "06_uncertain" / "resolved.json").exists():
                raise SystemExit(f"{page_dir} has no Stage 06 output; run prepare")
            words = tesseract_words(page_dir)
            t_toks = prep_tokens([(w["text"], idx) for idx, w in enumerate(words)])
            l_toks = prep_tokens([(w[4], None) for w in src[pno - 1].get_text("words")])
            ops = align(t_toks, l_toks)
            eq = sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag == "equal")
            stats["pages"] += 1
            stats["t_tokens"] += len(t_toks)
            stats["l_tokens"] += len(l_toks)
            stats["equal_t"] += eq
            cov = eq / len(t_toks) if t_toks else 0.0
            stats["coverage"].append(round(cov, 3))
            for tag, i1, i2, j1, j2 in ops:
                if tag == "equal":
                    for t in t_toks[i1:i2]:
                        if any(words[r]["decision"] != "keep" for r in t["refs"]):
                            stats["flagged_agree"] += 1
                            agree_pool.append(_site(d["id"], pno, page_dir, words, t, None,
                                                    lex, cov))
                    continue
                if tag != "replace":
                    continue
                if i2 - i1 != 1 or j2 - j1 != 1:
                    stats["other_replace"] += 1
                    continue
                s = _site(d["id"], pno, page_dir, words, t_toks[i1], l_toks[j1], lex, cov)
                stats["sites"] += 1
                if s["kept"]:
                    stats["sites_kept"] += 1
                    stats["armb_kept"] += s["arm_b"]
                    kept_sites.append(s)
                else:
                    stats["sites_flagged"] += 1
                    if d["id"] == "C":
                        # The control's check is over EVERY disagreement it has
                        # (prereg, "Control"), kept or flagged; see the addendum.
                        kept_sites.append(s)
        src.close()
        rng = random.Random(f"{SEED}-{d['id']}")
        if len(kept_sites) <= CAP_PRIMARY:
            sample = list(kept_sites)
        else:
            sample = rng.sample(kept_sites, CAP_PRIMARY)
        for s in sample:
            s["in_uniform_sample"] = True
        extra = [s for s in kept_sites if s["arm_b"] and not s.get("in_uniform_sample")]
        for s in extra:
            s["in_uniform_sample"] = False
        primary += sample + extra
        rng2 = random.Random(f"{SEED}-{d['id']}-agree")
        agree += (list(agree_pool) if len(agree_pool) <= CAP_AGREE
                  else rng2.sample(agree_pool, CAP_AGREE))
        per_doc[d["id"]] = stats
        print(f"{d['id']}: {stats['pages']} pages, {stats['t_tokens']} tesseract tokens, "
              f"coverage {stats['coverage']}, {stats['sites']} sites "
              f"({stats['sites_kept']} on kept words), sampled {len(sample)}+{len(extra)}",
              flush=True)

    order = random.Random(SEED)
    order.shuffle(primary)
    for n, s in enumerate(primary, 1):
        s["id"] = f"S{n:03d}"
        s["a_is_tesseract"] = random.Random(f"{SEED}-{s['id']}").random() < 0.5
    order.shuffle(agree)
    for n, s in enumerate(agree, 1):
        s["id"] = f"G{n:03d}"
    key = {"per_doc": per_doc, "primary": primary, "agree": agree}
    (work / "key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False),
                                   encoding="utf-8")
    (work / "labels_template.json").write_text(json.dumps(
        {"primary": {s["id"]: "" for s in primary}, "agree": {s["id"]: "" for s in agree}},
        indent=1), encoding="utf-8")
    _sheets(work, primary, agree)


def _site(doc_id, pno, page_dir, words, t, l, lex, cov) -> dict:
    ws = [words[r] for r in t["refs"]]
    x0 = min(w["bbox"]["x"] for w in ws)
    y0 = min(w["bbox"]["y"] for w in ws)
    x1 = max(w["bbox"]["x"] + w["bbox"]["w"] for w in ws)
    y1 = max(w["bbox"]["y"] + w["bbox"]["h"] for w in ws)
    s = {"doc": doc_id, "pdf_page": pno, "page_dir": str(page_dir), "sub": ws[0]["sub"],
         "box": [x0, y0, x1 - x0, y1 - y0], "t_raw": t["raw"], "t_norm": t["norm"],
         "kept": all(w["decision"] == "keep" for w in ws),
         "decisions": [w["decision"] for w in ws], "page_coverage": round(cov, 3)}
    if l is not None:
        s.update(l_raw=l["raw"], l_norm=l["norm"],
                 arm_b=bool(t["norm"] not in lex and l["norm"] in lex and len(l["norm"]) >= 2))
    return s


def _font(size: int):
    from PIL import ImageFont
    for f in (r"C:\Windows\Fonts\arial.ttf", str(REPO / "pipeline/assets/fonts/NotoSerif.ttf")):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _crop(site: dict, tile_w: int, crop_h: int):
    from PIL import Image, ImageDraw
    name = site["sub"] if site["sub"].endswith(".png") else f"{site['sub']}.png"
    img = Image.open(Path(site["page_dir"]) / "03_dewarp" / name).convert("RGB")
    x, y, w, h = site["box"]
    line_h = max(20, min(h, 80))
    pad_y = int(line_h * 1.2)
    cx = x + w / 2
    half = max(w / 2 + line_h * 3, 350)
    box = (int(max(0, cx - half)), int(max(0, y - pad_y)),
           int(min(img.width, cx + half)), int(min(img.height, y + h + pad_y)))
    c = img.crop(box)
    ImageDraw.Draw(c).rectangle((x - box[0] - 3, y - box[1] - 3, x + w - box[0] + 3,
                                 y + h - box[1] + 3), outline=(220, 30, 30), width=3)
    scale = min(tile_w / c.width, crop_h / c.height, 1.5)
    return c.resize((max(1, int(c.width * scale)), max(1, int(c.height * scale))))


def _sheets(work: Path, primary: list[dict], agree: list[dict]) -> None:
    from PIL import Image, ImageDraw

    out = work / "sheets"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    tile_w, crop_h, text_h, cols, rows = 760, 190, 40, 2, 6
    font = _font(24)

    def draw(items, prefix, caption):
        per = cols * rows
        for n in range(0, len(items), per):
            sheet = Image.new("RGB", (cols * (tile_w + 20) + 20, rows * (crop_h + text_h + 24) + 20),
                              "white")
            dr = ImageDraw.Draw(sheet)
            for k, s in enumerate(items[n:n + per]):
                cx = 20 + (k % cols) * (tile_w + 20)
                cy = 20 + (k // cols) * (crop_h + text_h + 24)
                sheet.paste(_crop(s, tile_w, crop_h), (cx, cy))
                dr.text((cx, cy + crop_h + 6), caption(s), fill="black", font=font)
            sheet.save(out / f"{prefix}_{n // per + 1:02d}.png")

    def cap_primary(s):
        a, b = ((s["t_raw"], s["l_raw"]) if s["a_is_tesseract"] else (s["l_raw"], s["t_raw"]))
        return f"{s['id']}   A: {a}     B: {b}"

    draw(primary, "primary", cap_primary)
    draw(agree, "agree", lambda s: f"{s['id']}   reading: {s['t_raw']}")
    print(f"{len(primary)} primary sites, {len(agree)} agreement sites -> {out}")


# ---------------------------------------------------------------- score
def _decide(site: dict, label: str) -> str | None:
    """'catch' (Tesseract wrong), 'false_alarm' (Tesseract right), None (unclear)."""
    if label not in LABELS:
        raise SystemExit(f"{site['id']}: label {label!r} not in {LABELS}")
    if label == "unclear":
        return None
    if label in ("neither",):
        return "catch"
    if label == "both":
        return "false_alarm"
    t_side = "A" if site["a_is_tesseract"] else "B"
    return "false_alarm" if label == t_side else "catch"


def score(work: Path) -> dict:
    key = json.loads((work / "key.json").read_text(encoding="utf-8"))
    labels = json.loads((work / "labels.json").read_text(encoding="utf-8"))
    docs = [d for d in key["per_doc"]]
    out = {"per_doc": {}, "arms": {}, "agree": {}, "control": {}}
    rows = {}
    for s in key["primary"]:
        lab = labels["primary"].get(s["id"], "")
        if not lab:
            raise SystemExit(f"{s['id']} has no label")
        s["label"] = lab
        s["outcome"] = _decide(s, lab)
        rows.setdefault(s["doc"], []).append(s)

    def tally(sites_):
        c = sum(s["outcome"] == "catch" for s in sites_)
        f = sum(s["outcome"] == "false_alarm" for s in sites_)
        u = sum(s["outcome"] is None for s in sites_)
        return {"catches": c, "false_alarms": f, "unclear": u,
                "precision": round(c / (c + f), 3) if c + f else None,
                "neither": sum(s["label"] == "neither" for s in sites_),
                "layer_right": sum(s["outcome"] == "catch" and s["label"] != "neither"
                                   for s in sites_)}

    for d in docs:
        doc_sites = rows.get(d, [])
        a = [s for s in doc_sites if s["in_uniform_sample"]]
        b = [s for s in doc_sites if s["arm_b"]]
        out["per_doc"][d] = {**key["per_doc"][d], "arm_a": tally(a), "arm_b": tally(b)}

    real = [d for d in docs if d != "C"]
    ctrl = out["per_doc"].get("C", {}).get("arm_a", {})
    dec = (ctrl.get("catches", 0) + ctrl.get("false_alarms", 0))
    ctrl_fa_share = ctrl.get("false_alarms", 0) / dec if dec else None
    valid = ctrl_fa_share is not None and ctrl_fa_share <= 0.20
    out["control"] = {"false_alarm_share": None if ctrl_fa_share is None else round(ctrl_fa_share, 3),
                      "valid": valid}
    for arm in ("arm_a", "arm_b"):
        pooled = {"catches": 0, "false_alarms": 0, "unclear": 0}
        for d in real:
            for k in pooled:
                pooled[k] += out["per_doc"][d][arm][k]
        cf = pooled["catches"] + pooled["false_alarms"]
        prec = pooled["catches"] / cf if cf else 0.0
        eligible = [d for d in real if out["per_doc"][d][arm]["catches"]
                    + out["per_doc"][d][arm]["false_alarms"] >= 5]
        good = [d for d in eligible if (out["per_doc"][d][arm]["precision"] or 0) >= 0.5]
        gates = {"precision>=0.50": prec >= 0.5, "catches>=20": pooled["catches"] >= 20,
                 ">=4 docs at 0.50": len(good) >= 4}
        verdict = ("NO VERDICT (control invalid)" if not valid
                   else "BUILD" if all(gates.values()) else "REFUSE")
        out["arms"][arm] = {**pooled, "precision": round(prec, 3), "eligible_docs": eligible,
                            "docs_at_0_50": good, "gates": gates, "verdict": verdict}

    for s in key["agree"]:
        lab = labels["agree"].get(s["id"], "")
        if lab not in AGREE_LABELS:
            raise SystemExit(f"{s['id']}: agreement label {lab!r} not in {AGREE_LABELS}")
        s["label"] = lab
    for d in docs:
        g = [s for s in key["agree"] if s["doc"] == d]
        out["agree"][d] = {k: sum(s["label"] == k for s in g) for k in AGREE_LABELS}
    (work / "result.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (work / "key_labelled.json").write_text(json.dumps(key, indent=1, ensure_ascii=False),
                                            encoding="utf-8")
    print(json.dumps(out, indent=1))
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] not in ("prepare", "sites", "score"):
        print(__doc__)
        return 2
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(REPO))
    {"prepare": prepare, "sites": sites, "score": score}[args[0]](Path(args[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
