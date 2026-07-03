"""Unit tests for the Gate-4 textual caption parser (``pipeline.caption_parser``).

The positive/negative strings below are the ACTUAL routed OCR text dumped from
the pipeline on it_geo_06 / it_geo_05 / it_geo_07 (2026-07-03), not idealized GT
anchors — so these tests pin the parser against the real garbled sofa-shot text
it must survive. The mid-sentence "(fig. N)" negatives are the non-regression
guard (a body paragraph that merely mentions a figure must NOT be re-typed).
"""

from __future__ import annotations

from pipeline.caption_parser import (
    CaptionRef, parse_caption, is_caption, figure_number, pair_by_number,
    _lang_key,
)


# --------------------------------------------------------------------------
# Positive: real captions OCR'd off it_geo_06 (Italian), all typed 'paragraph'
# by the detector — the parser must recognize every one.
# --------------------------------------------------------------------------

IT_GEO_06_CAPTIONS = [
    ("Figura 28 Il Calcare del Fadalto (FAD), affiorante nella località di Cornolade", 28, None),
    ("Figura 26 CSR Fossili della Maiolica rinvenuti sul Monte Grappa. Essi sono due", 26, None),
    ("Figura 27 Il Calcare di Soccher, affiorante nella località Pieve di Castellavazzo", 27, None),
    ("In questa pagina: Figura 25 | La Maiolica, affiorante lungo il Lago del Corlo.", 25, "In questa pagina"),
    ("Sopra: Figura 29 Il tipico paesaggio modellato sulla Miaiolica, che caratterizza", 29, "Sopra"),
    ("A lato: Figura 30 La Maiolica è una roccia geliva che tipicamente si sgretola", 30, "A lato"),
]


def test_it_geo_06_all_captions_recognized():
    for text, num, prefix in IT_GEO_06_CAPTIONS:
        ref = parse_caption(text, "ita")
        assert ref is not None, f"missed caption: {text!r}"
        assert ref.number == num, f"{text!r}: got number {ref.number}, want {num}"
        assert ref.prefix == prefix, f"{text!r}: got prefix {ref.prefix!r}, want {prefix!r}"
        assert ref.keyword == "figura"


def test_caption_residual_strips_prefix_and_number():
    ref = parse_caption("In questa pagina: Figura 25 | La Maiolica, affiorante", "ita")
    assert ref is not None
    assert ref.caption_text.startswith("La Maiolica")   # prefix, keyword, number, "|" all stripped
    ref2 = parse_caption("Figura 28 Il Calcare del Fadalto", "ita")
    assert ref2.caption_text.startswith("Il Calcare")


# --------------------------------------------------------------------------
# Negative / non-regression: body prose that mentions a figure mid-sentence.
# These are the real paragraphs the detector correctly typed 'paragraph' — the
# parser must NOT promote them (start-anchoring guard).
# --------------------------------------------------------------------------

NON_CAPTIONS = [
    # it_geo_06 right P-block: mid-sentence "(fig. 28)".
    "La loro parte inferiore è eteropica con la Maiolica ma, essendosi deposte per un "
    "intervallo temporale superiore, entrambe finiscono per ricoprirla (fig. 28). La loro base",
    # it_geo_05 right P2: mid-sentence "(fig. 4)".
    "Durante il Cretaceo la Piattaforma Friulana fu interessata da un'attività tettonica "
    "piuttosto intensa (fig. 4), inquadrabile sempre nel processo di distensione crostale",
    # it_geo_07 T-blocks: start with a bare "N)" list marker, NO keyword.
    "1) Triassico sup. (Carnico sup. - Retico) Su una estesissima piana di marea si depone",
    "8) Kimmeridgiano - Cretaceo inferiore (Barremiano). Una temporanea crisi",
    # plain body prose
    "arriva al Santoniano, nel Cretaceo superiore (85 milioni di anni fa). La fine",
    "",
    "   ",
]


def test_non_captions_not_promoted():
    for text in NON_CAPTIONS:
        assert parse_caption(text, "ita") is None, f"false positive on: {text!r}"
        assert not is_caption(text, "ita")


def test_verb_figurano_not_matched():
    # "figurano" (a verb) must not match the "fig"/"figura" keyword even with a
    # trailing number, because the number must immediately follow the keyword.
    assert parse_caption("figurano tre esemplari nel riquadro", "ita") is None
    assert parse_caption("figurative 3 immagini", "ita") is None


# --------------------------------------------------------------------------
# it_geo_07: keyword clean but NUMBER OCR-garbled (GT "Figura 31" read "Figura 3").
# Typing must still succeed; the (wrong) number is what OCR gave — documents the
# fragility that gates the pairing claim.
# --------------------------------------------------------------------------

def test_it_geo_07_caption_typed_despite_number_garble():
    text = ("In queste pagine: Figura 3 Schema evolutivo del Bacino di Belluno in rapporto "
            "alle piattaforme trentina e friulana.")
    ref = parse_caption(text, "ita")
    assert ref is not None
    assert ref.prefix == "In queste pagine"
    assert ref.number == 3          # OCR truncated 31 -> 3; typing unaffected


# --------------------------------------------------------------------------
# Multilingual keyword table (target languages; NOT validated on a fixture).
# --------------------------------------------------------------------------

def test_multilingual_keywords():
    assert parse_caption("Figure 4 A cross section of the coin", "eng").number == 4
    assert parse_caption("Fig. 12 detail", "eng").number == 12
    assert parse_caption("Abbildung 7 Querschnitt", "deu").number == 7
    assert parse_caption("Abb. 7 Detail", "deu").number == 7
    assert parse_caption("Фигура 9 напречен разрез", "bul").number == 9
    assert parse_caption("Фиг. 9 детайл", "bul").number == 9


def test_lang_normalization():
    for tok in ("it", "ita", "Italian", "ita+eng", "unknown"):
        assert _lang_key(tok) == "ita"
    assert _lang_key("eng") == "eng"
    assert _lang_key("de") == "deu"
    assert _lang_key("bg") == "bul"


def test_english_does_not_match_italian_only_keyword():
    # "figura" is not an English keyword; under lang=eng it should not match.
    assert parse_caption("figura 5 something", "eng") is None
    # but "fig"/"figure" are shared enough that English still catches its own.
    assert parse_caption("Figure 5 something", "eng") is not None


# --------------------------------------------------------------------------
# figure_number: conservative recovery of a figure's own corner label.
# --------------------------------------------------------------------------

def test_figure_number_conservative():
    assert figure_number("26") == 26
    assert figure_number("  25 ") == 25
    assert figure_number("Fig. 27") == 27
    assert figure_number("") is None            # empty (the it_geo_06 reality)
    assert figure_number("   ") is None
    # body words leaking into a figure box must NOT fabricate a number
    assert figure_number("La Maiolica affiorante 26 lungo il lago") is None
    assert figure_number("affiorante nella località") is None


# --------------------------------------------------------------------------
# pair_by_number: the number-keyed trap + the it_geo_06 blind-figure reality.
# --------------------------------------------------------------------------

def test_pair_by_number_defeats_geometric_trap():
    # C26 belongs to F26 (top-right) though it is 2nd in the LEFT stack. If figure
    # numbers ARE known, number-pairing pairs C26->F26 regardless of geometry.
    captions = {"C25": 25, "C26": 26, "C27": 27, "C28": 28}
    figures = {"F25": 25, "F26": 26, "F27": 27, "F28": 28}
    pairs = pair_by_number(captions, figures)
    assert pairs == {"C25": "F25", "C26": "F26", "C27": "F27", "C28": "F28"}


def test_pair_by_number_no_figure_numbers_yields_nothing():
    # The REAL it_geo_06 case: figure corner labels don't OCR -> all numbers None
    # -> pairing yields {} (honest: no textual figure signal, nothing guessed).
    captions = {"C25": 25, "C26": 26, "C27": 27, "C28": 28}
    figures = {"Fmerged": None, "F26": None}
    assert pair_by_number(captions, figures) == {}


def test_pair_by_number_ambiguous_shared_number_pairs_nothing():
    # A merged/duplicated figure box carrying the same number twice is ambiguous.
    assert pair_by_number({"C5": 5}, {"Fa": 5, "Fb": 5}) == {}


def test_captionref_is_frozen():
    ref = parse_caption("Figura 1 x", "ita")
    assert isinstance(ref, CaptionRef)
    try:
        ref.number = 2  # type: ignore[misc]
        assert False, "CaptionRef should be frozen"
    except Exception:
        pass
