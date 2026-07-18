"""Reproducibly build ``models/lexicons/`` — the per-language Hunspell dictionaries
the Stage 05 cross-engine disagreement gate (and the Stage 08 de-hyphenation rule)
need.

``models/`` is gitignored, so the seam ships INERT (see ``pipeline/second_opinion``
``.py``); this script activates it locally, mirroring ``tools/setup_tessdata``. For
each configured language it downloads a Hunspell ``.dic``/``.aff`` pair from the
LibreOffice dictionaries repo (pinned commit) and, for Bulgarian, builds a GeoNames
gazetteer OVERLAY (``bg.geo.txt``) covering the measured proper-noun blind spot
(toponyms are absent from a general dictionary — RESULTS.md 2026-07-18).

NOTHING is expanded to a flat wordlist here: the gate validates surface forms
morphologically through spylls at runtime (``HunspellLexicon.__contains__``), so
``помашки`` validates without being listed. German compounds are likewise handled
by lookup (they are generative and could not be enumerated anyway).

    python -m tools.setup_lexicons                    # all configured languages
    python -m tools.setup_lexicons --force            # re-download even if present
    python -m tools.setup_lexicons --only bul         # just one (tesseract lang code)
    python -m tools.setup_lexicons --geo-countries BG,GR,TR  # widen the bg overlay

Sources / licenses: LibreOffice/dictionaries (SHA-pinned; per-dict GPL/LGPL/MPL —
bg_BG is GPL/LGPL) and GeoNames (CC-BY 4.0). Both allow redistribution; the built
files stay gitignored regardless (models/ in .gitignore). The LibreOffice dicts are
reproducible (pinned commit); the GeoNames dumps are a rolling, unversioned file,
so the overlay may drift between rebuilds (see GEONAMES_URL).
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Pinned LibreOffice dictionaries commit (verified live 2026-07-18).
LO_SHA = "da8a7e73fd26a134ad7c6438fa7c310730906b3a"
LO_RAW = f"https://raw.githubusercontent.com/LibreOffice/dictionaries/{LO_SHA}"
# tesseract lang code -> (repo subdir, source basename) of the .dic/.aff pair.
LO_SOURCES = {
    "eng": ("en", "en_US"),
    "bul": ("bg_BG", "bg_BG"),
    "ita": ("it_IT", "it_IT"),
    "deu": ("de", "de_DE_frami"),
}
# GeoNames per-country dump (CC-BY): tab-separated; col[1]=name, col[3]=altnames.
# CAVEAT: unlike the SHA-pinned LibreOffice dicts, these dumps are a ROLLING,
# unversioned file — GeoNames does not tag releases, so a rebuild months later
# yields a (slightly) different overlay. The overlay is therefore NOT bit-for-bit
# reproducible the way the .dic/.aff pairs are. Accepted: a gazetteer drifts.
GEONAMES_URL = "https://download.geonames.org/export/dump/{cc}.zip"
# Default overlay scope. BG covers modern-Bulgaria toponyms. NOTE (measured,
# RESULTS.md 2026-07-18): historical Aegean-Thrace exonyms this corpus is dense
# with are only PARTIALLY in GeoNames — Дедеагач is a Cyrillic altname under GR,
# but Гюмурджина/Дуганхисар are absent from GeoNames entirely. Add neighbours
# with e.g. --geo-countries BG,GR,TR (buys 1 of 3; the rest GeoNames lacks).
GEONAMES_COUNTRIES = ("BG",)

# A known valid word per language — post-download sanity that spylls loads the
# pair AND morphology works (i.e. not base-form-only). deu uses an inflected
# plural on purpose.
SANITY = {"eng": "cats", "bul": "помашки", "ita": "case", "deu": "Häuser"}


def load_cfg() -> dict:
    with open(REPO_ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _download(url: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"  download {dst.name} <- {url}")
    urllib.request.urlretrieve(url, dst)
    print(f"    ok ({dst.stat().st_size / 1e6:.2f} MB)")


def _has_cyrillic(s: str) -> bool:
    return any("Ѐ" <= ch <= "ӿ" for ch in s)


def build_geonames_overlay(dst: Path, countries: tuple[str, ...], force: bool) -> None:
    """Download the GeoNames dump(s) and write a Cyrillic-only word-token overlay.

    Multi-word names ("Стара Загора") are split into individual word tokens
    (``стара``, ``загора``) because the gate matches single OCR word tokens.
    Non-Cyrillic alternatenames (ASCII / transliterations / other scripts) are
    dropped — the gate normalizes Cyrillic, so Latin forms would only pollute the
    set. Tokens are stored raw (one per line); ``_load_overlay`` normalizes them."""
    if dst.exists() and not force:
        print(f"  keep {dst.name} ({dst.stat().st_size / 1e3:.0f} KB)")
        return
    print(f"  GeoNames overlay <- {list(countries)} (rolling dump, NOT version-pinned)")
    tokens: set[str] = set()
    for cc in countries:
        with urllib.request.urlopen(GEONAMES_URL.format(cc=cc)) as r:
            blob = r.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as z, z.open(f"{cc}.txt") as f:
            for raw in io.TextIOWrapper(f, encoding="utf-8"):
                cols = raw.split("\t")
                if len(cols) < 4:
                    continue
                for name in [cols[1], *cols[3].split(",")]:
                    for word in name.split():
                        if _has_cyrillic(word):
                            tokens.add(word)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(sorted(tokens)), encoding="utf-8")
    print(f"    ok ({len(tokens)} Cyrillic place-name tokens from "
          f"{','.join(countries)} -> {dst.name})")


def sanity_check(code: str, base: Path) -> bool:
    """Load the pair through spylls and confirm a known word validates."""
    try:
        from spylls.hunspell import Dictionary
    except ModuleNotFoundError:
        print("  WARNING: spylls not installed — skipping load check "
              "(pip install spylls).", file=sys.stderr)
        return True
    word = SANITY.get(code, "")
    dic = Dictionary.from_files(str(base))
    ok = bool(dic.lookup(word) or dic.lookup(word.capitalize())) if word else True
    print(f"  sanity: lookup({word!r}) = {ok}")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build models/lexicons/ (Hunspell dicts + GeoNames overlay)")
    ap.add_argument("--force", action="store_true",
                    help="re-download even if the files are already present")
    ap.add_argument("--only", help="limit to one tesseract lang code (e.g. bul)")
    ap.add_argument("--geo-countries", default=",".join(GEONAMES_COUNTRIES),
                    help="comma-separated GeoNames country codes for the bg "
                         "overlay (default BG; e.g. BG,GR,TR for Aegean exonyms)")
    args = ap.parse_args(argv)
    geo_countries = tuple(c.strip().upper() for c in args.geo_countries.split(",") if c.strip())

    cfg = load_cfg()
    lex_cfg = (((cfg.get("engines", {}) or {}).get("easyocr", {}) or {})
               .get("lexicon", {}) or {})
    if not lex_cfg:
        print("no engines.easyocr.lexicon mapping in config.yaml", file=sys.stderr)
        return 1

    codes = [args.only] if args.only else list(lex_cfg)
    rc = 0
    for code in codes:
        if code not in lex_cfg:
            print(f"skip {code}: no config path", file=sys.stderr)
            rc = 1
            continue
        if code not in LO_SOURCES:
            print(f"skip {code}: no LibreOffice source mapped", file=sys.stderr)
            rc = 1
            continue
        target = REPO_ROOT / lex_cfg[code]      # e.g. models/lexicons/bg.dic
        base = target.with_suffix("")           # models/lexicons/bg
        subdir, src = LO_SOURCES[code]
        print(f"[{code}] -> {base.name}.{{dic,aff}}")
        for ext in ("dic", "aff"):
            out = base.with_suffix("." + ext)
            if out.exists() and not args.force:
                print(f"  keep {out.name} ({out.stat().st_size / 1e6:.2f} MB)")
                continue
            _download(f"{LO_RAW}/{subdir}/{src}.{ext}", out)
        if code == "bul":
            build_geonames_overlay(base.with_suffix(".geo.txt"), geo_countries, args.force)
        if not sanity_check(code, base):
            print(f"  WARNING: sanity lookup failed for {code} — check the pair.",
                  file=sys.stderr)
            rc = 1

    print("lexicons ready." if rc == 0 else "lexicons built with warnings.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
