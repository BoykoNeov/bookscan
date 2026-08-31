"""Census: which LANGUAGE does each text block look like, per the dictionaries?

THE QUESTION. A real book carries several languages on one page — this corpus's
via-ferrata guide prints the German route description, then the English one, then
the Italian one, each in its own printed box. Stage 05 reads the whole page in one
language, so two of the three boxes are read with the wrong dictionary. Before any
per-block language machinery is built, this script answers the load-bearing
question on real artifacts: **does scoring a block's already-read words against the
four installed Hunspell dictionaries actually pick out the foreign panels, and
leave every other block on the page language?**

It is a MEASUREMENT TOOL, not a pipeline stage. It reads ``05_ocr/ocr.json`` (and,
in ``--reread`` mode, the ``03_dewarp`` pixels) and writes nothing back.

TWO PHASES, deliberately separate:

  * **score** (default, seconds) — per block, the hit rate of its existing words
    against each dictionary, the winning language, and the margin over the page
    language. No OCR runs. If this does not discriminate, the whole item is dead
    and nothing further need be built.
  * **--reread** (minutes, needs Tesseract) — for every block the score phase
    nominates, re-read that block's crop in the winning language and print the
    BEFORE/AFTER pair: word count, mean confidence, dictionary hits and hit rate.
    COUPLING, stated so it cannot rot silently: this arm calls
    ``block_reocr._reocr_block`` — a PRIVATE function of another module —
    deliberately, so the numbers are the ones a pipeline pass would really see
    rather than a second implementation of the same crop-and-read. If that
    signature changes, fix the call here: the refused experiment behind
    RESULTS 2026-08-31 stops being reproducible otherwise.

    This exists because the acceptance rule cannot be copied from
    ``block_reocr`` on faith: a garbled read FRAGMENTS, so it can return MORE
    tokens than a clean one, and a conjunctive "more words" clause would then
    refuse exactly the blocks this work is for. The rule is to be chosen from
    these numbers, not before them.

Usage::

    python -m tools.block_lang_census jobs/<job>/            # score only
    python -m tools.block_lang_census jobs/<job>/ --reread   # + candidate re-reads
    python -m tools.block_lang_census jobs/<job>/ --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.page_model import BBox, BlockType  # noqa: E402
from pipeline.second_opinion import load_lexicon, normalize_token  # noqa: E402

# Tesseract lang code -> lexicon base, mirroring config.yaml's
# engines.easyocr.lexicon map. Kept here rather than read from config because a
# census must be able to score languages the job was NOT run in.
LEXICONS = {
    "eng": "models/lexicons/en.dic",
    "deu": "models/lexicons/de.dic",
    "ita": "models/lexicons/it.dic",
    "bul": "models/lexicons/bg.dic",
}

# Blocks that are not prose. FIGURE words are labels printed inside artwork; a
# language vote over six map labels is noise.
SCORABLE = frozenset({BlockType.PARAGRAPH.value, BlockType.CAPTION.value,
                      BlockType.TITLE.value, BlockType.TABLE.value,
                      BlockType.HEADING.value, BlockType.LIST.value,
                      BlockType.FOOTNOTE.value, BlockType.OTHER.value})


def scorable_tokens(texts: list[str]) -> list[str]:
    """Normalized tokens worth voting with: at least two characters and at least
    one letter. A page number, a route height (``840``) or a stray ``|`` says
    nothing about language and would otherwise dilute every rate equally."""
    out = []
    for t in texts:
        n = normalize_token(t)
        if len(n) >= 2 and any(c.isalpha() for c in n):
            out.append(n)
    return out


@dataclass
class BlockScore:
    page: str
    subpage: str
    block_id: int
    block_type: str
    n_words: int
    n_tokens: int
    conf: float
    rates: dict[str, float]
    hits: dict[str, int]
    winner: str
    margin: float           # winner rate - page-language rate
    page_lang: str
    sample: str
    why: str = ""           # why this block was nominated: "vote" | "low" | ""
    # filled by --reread
    reread: dict | None = field(default=None)


def load_lexicons(langs: list[str]) -> dict[str, object]:
    """One dictionary per language, loaded ONCE. ``load_lexicon`` takes a list and
    returns the FIRST usable path, so it must be called per language — handing it
    all four returns English four times."""
    lex = {}
    for lc in langs:
        rel = LEXICONS.get(lc)
        if not rel:
            continue
        path = REPO_ROOT / rel
        obj = load_lexicon([path])
        if obj is None:
            print(f"  WARNING: no lexicon for {lc} at {path} — skipped",
                  file=sys.stderr)
            continue
        lex[lc] = obj
    return lex


def score_tokens(tokens: list[str], lex: dict[str, object]
                 ) -> tuple[dict[str, float], dict[str, int]]:
    hits = {lc: sum(1 for t in tokens if t in d) for lc, d in lex.items()}
    n = max(1, len(tokens))
    rates = {lc: h / n for lc, h in hits.items()}
    return rates, hits


def census(job: Path, langs: list[str], min_tokens: int
           ) -> tuple[list[BlockScore], dict[str, object]]:
    lex = load_lexicons(langs)
    rows: list[BlockScore] = []
    for page_dir in sorted(p for p in job.iterdir() if p.name.startswith("page_")):
        f = page_dir / "05_ocr" / "ocr.json"
        if not f.exists():
            continue
        doc = json.loads(f.read_text(encoding="utf-8"))
        for pg in doc.get("pages", []):
            page_lang = pg.get("language", "")
            for blk in pg.get("blocks", []):
                if blk.get("type") not in SCORABLE:
                    continue
                texts = [w["text"] for w in blk.get("words", [])]
                toks = scorable_tokens(texts)
                if len(toks) < min_tokens:
                    continue
                rates, hits = score_tokens(toks, lex)
                winner = max(rates, key=lambda k: rates[k])
                base = rates.get(page_lang.split("+")[0], 0.0)
                confs = [w["conf"] for w in blk.get("words", [])]
                rows.append(BlockScore(
                    page=page_dir.name, subpage=pg.get("name", ""),
                    block_id=int(blk["id"]), block_type=blk.get("type", ""),
                    n_words=len(texts), n_tokens=len(toks),
                    conf=round(float(np.mean(confs)) if confs else 0.0, 1),
                    rates={k: round(v, 3) for k, v in rates.items()},
                    hits=hits, winner=winner, margin=round(rates[winner] - base, 3),
                    page_lang=page_lang,
                    sample=" ".join(texts[:12])))
    return rows, lex


def print_report(rows: list[BlockScore], langs: list[str], min_margin: float,
                 top: int, low_conf: float = 0.0) -> list[BlockScore]:
    if not rows:
        print("no scorable blocks found")
        return []
    page_lang = rows[0].page_lang.split("+")[0]
    agree = [r for r in rows if r.winner == page_lang]
    print(f"\n{len(rows)} scorable text blocks; page language = {page_lang}")
    print(f"  winner == page language : {len(agree)} "
          f"({len(agree) / len(rows):.1%})")
    for lc in langs:
        n = sum(1 for r in rows if r.winner == lc)
        print(f"  winner == {lc:4s}          : {n}")

    cands = sorted((r for r in rows
                    if r.winner != page_lang and r.margin >= min_margin),
                   key=lambda r: -r.margin)
    print(f"\n{len(cands)} candidate blocks (winner != {page_lang}, "
          f"margin >= {min_margin}):")
    hdr = (f"{'page/sub':28s} {'id':>3s} {'type':9s} {'n':>4s} {'conf':>5s} "
           f"{'win':4s} {'marg':>5s}  " + " ".join(f"{lc:>5s}" for lc in langs))
    print(hdr)
    print("-" * len(hdr))
    for r in cands[:top]:
        sub = f"{r.page}/{r.subpage.replace('.png', '')}"
        print(f"[{r.why:4s}] ", end="")
        print(f"{sub:28s} {r.block_id:3d} {r.block_type:9s} {r.n_tokens:4d} "
              f"{r.conf:5.1f} {r.winner:4s} {r.margin:5.2f}  "
              + " ".join(f"{r.rates.get(lc, 0):5.2f}" for lc in langs))
        print(f"    {r.sample[:110]}")
    return cands


def reread_candidates(job: Path, cands: list[BlockScore], cfg: dict,
                      top: int, all_langs: bool = False) -> None:
    """Re-read each candidate's crop in its winning language and print the pair.

    Uses ``block_reocr._reocr_block`` — the SAME crop-and-read path the shipped
    starved-block pass uses — so the numbers here are the numbers a pipeline pass
    would see, not an approximation of them.
    """
    import cv2

    from pipeline import block_reocr as BR
    from tools.gate1_harness import find_tesseract, resolve_tessdata_dir

    binary = find_tesseract(cfg)
    if not binary:
        print("Tesseract not found — cannot re-read", file=sys.stderr)
        return
    tessdata = resolve_tessdata_dir(cfg)
    oem = int((cfg.get("tesseract", {}) or {}).get("oem", 1))
    lex = load_lexicons(sorted(LEXICONS))

    print(f"\n--- re-read of {min(len(cands), top)} candidates "
          f"(page language vs winner) ---")
    hdr = (f"{'page/sub':28s} {'id':>3s} {'lang':9s} {'words':>6s} {'conf':>6s} "
           f"{'hits':>5s} {'rate':>5s}")
    print(hdr)
    print("-" * len(hdr))
    for r in cands[:top]:
        page_dir = job / r.page
        img = cv2.imread(str(page_dir / "03_dewarp" / r.subpage), cv2.IMREAD_COLOR)
        if img is None:
            print(f"{r.page}/{r.subpage}: unreadable dewarp image", file=sys.stderr)
            continue
        doc = json.loads((page_dir / "05_ocr" / "ocr.json").read_text(encoding="utf-8"))
        pg = next((p for p in doc["pages"] if p["name"] == r.subpage), None)
        scale = float(pg.get("scale", 1.0)) if pg else 1.0
        blk = next((b for b in pg["blocks"] if int(b["id"]) == r.block_id), None)
        if blk is None:
            continue
        bb = blk["bbox"]
        box = BBox(x=bb["x"], y=bb["y"], w=bb["w"], h=bb["h"])
        sub = f"{r.page}/{r.subpage.replace('.png', '')}"

        # BEFORE: the words that actually shipped, scored the same way.
        toks = scorable_tokens([w["text"] for w in blk["words"]])
        _, hits = score_tokens(toks, lex)
        base_lang = r.page_lang.split("+")[0]
        print(f"{sub:28s} {r.block_id:3d} {base_lang + ' (page)':9s} "
              f"{len(blk['words']):6d} {r.conf:6.1f} "
              f"{hits.get(base_lang, 0):5d} "
              f"{hits.get(base_lang, 0) / max(1, len(toks)):5.2f}")

        out = {"page_words": len(blk["words"]), "page_conf": r.conf,
               "page_hits": hits.get(base_lang, 0), "page_tokens": len(toks),
               "why": r.why}
        seen = []
        for lang in ([base_lang, r.winner] if not all_langs
                     else [base_lang] + [l for l in sorted(lex) if l != base_lang]):
            if lang in seen:
                continue
            seen.append(lang)
            tw = BR._reocr_block(img, box, binary, tessdata, lang, oem, scale,
                                 BR.DEFAULTS)
            toks2 = scorable_tokens([w.text for w in tw])
            _, hits2 = score_tokens(toks2, lex)
            conf2 = float(np.mean([w.conf for w in tw])) if tw else 0.0
            print(f"{'':28s} {'':3s} {lang + ' (crop)':9s} {len(tw):6d} "
                  f"{conf2:6.1f} {hits2.get(lang, 0):5d} "
                  f"{hits2.get(lang, 0) / max(1, len(toks2)):5.2f}"
                  + ("   <- winner" if lang == r.winner else ""))
            out[f"crop_{lang}"] = {
                "words": len(tw), "conf": round(conf2, 1),
                "hits": hits2.get(lang, 0), "tokens": len(toks2),
                "text": " ".join(w.text for w in tw)[:400]}
        r.reread = out
        print()


def main(argv: list[str] | None = None) -> int:
    # Real book text is full of umlauts and accents; a Windows console defaults
    # to cp1252 and would abort the report mid-table on the first one.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("job", type=Path)
    ap.add_argument("--langs", default="eng,deu,ita,bul")
    ap.add_argument("--min-tokens", type=int, default=8,
                    help="skip blocks with fewer scorable tokens (a 3-word "
                         "caption cannot vote on a language)")
    ap.add_argument("--min-margin", type=float, default=0.10,
                    help="nominate a block only when the winner beats the page "
                         "language's rate by this much")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--low-conf", type=float, default=0.0,
                    help="also nominate blocks whose mean confidence is below "
                         "this, whatever the dictionary vote says (a garbled "
                         "block cannot vote on its own language)")
    ap.add_argument("--all-langs", action="store_true",
                    help="with --reread, re-read each candidate in EVERY "
                         "installed language, not just the voted winner")
    ap.add_argument("--reread", action="store_true",
                    help="also re-read each candidate crop in its winner "
                         "language (needs Tesseract)")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    langs = [s.strip() for s in args.langs.split(",") if s.strip()]
    rows, _ = census(args.job, langs, args.min_tokens)
    cands = print_report(rows, langs, args.min_margin, args.top, args.low_conf)

    if args.reread:
        from tools.gate1_harness import load_config
        reread_candidates(args.job, cands, load_config(REPO_ROOT / "config.yaml"),
                          args.top, args.all_langs)

    if args.json:
        args.json.write_text(json.dumps(
            {"job": str(args.job), "langs": langs,
             "min_tokens": args.min_tokens, "min_margin": args.min_margin,
             "blocks": [asdict(r) for r in rows]},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
