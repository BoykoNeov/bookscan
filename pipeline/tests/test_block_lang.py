"""Per-block language labelling (pipeline/block_lang.py).

The guards these cover are not taste — each one is a false positive that was
measured on real artifacts and is named in the module docstring. The fake
lexicons here are plain sets, which is exactly what ``HunspellLexicon`` is a
drop-in for (``token in lexicon`` over normalized tokens).
"""
from __future__ import annotations

import pytest

from pipeline import block_lang as BL
from pipeline.page_model import BBox, Block, BlockType, Word

ENG = {"this", "ferrata", "strictly", "speaking", "two", "route", "ascend",
       "trail", "towards", "gap", "the", "and", "hm"}
DEU = {"und", "der", "schwierig", "klettersteig", "sehr", "route", "gut"}
ITA = {"via", "ferrata", "sentiero", "hm", "grotta", "cresta"}
LEX = {"eng": ENG, "deu": DEU, "ita": ITA}


def _block(words: list[str], btype: BlockType = BlockType.PARAGRAPH,
           bid: int = 1) -> Block:
    return Block(
        id=bid, type=btype, bbox=BBox(x=0, y=0, w=100, h=50), reading_order=0,
        words=[Word(text=t, bbox=BBox(x=i, y=0, w=5, h=5), conf=90.0,
                    engine="tesseract", line_id=0, block_id=bid)
               for i, t in enumerate(words)])


def test_labels_a_clearly_english_block_in_a_german_document():
    blk = _block(["This", "ferrata", "is", "strictly", "speaking", "two",
                  "ferratas.", "The", "two", "variants"])
    notes = BL.label_blocks([blk], "deu", LEX)
    assert blk.language == "eng"
    assert [n.block_id for n in notes] == [1]
    assert notes[0].doc_language == "deu"


def test_abstains_when_the_document_language_already_wins():
    blk = _block(["der", "Klettersteig", "ist", "sehr", "schwierig", "und",
                  "der", "Klettersteig", "und", "gut"])
    assert BL.label_blocks([blk], "deu", LEX) == []
    assert blk.language is None


def test_never_touches_the_words():
    """It is a label, not a re-read: word conservation must be untouched."""
    blk = _block(["This", "ferrata", "is", "strictly", "speaking", "two",
                  "ferratas.", "The", "two", "variants"])
    before = [(w.text, w.conf, w.bbox.x) for w in blk.words]
    BL.label_blocks([blk], "deu", LEX)
    assert [(w.text, w.conf, w.bbox.x) for w in blk.words] == before


def test_two_letter_tokens_do_not_vote():
    """THE guard. English Hunspell accepts a long tail of two-letter forms, so a
    block of pure noise scores high against English on that alone — which is how
    it_geo_05's junk block ("I nia pica ian na n PE aaa EEE") was nominated at
    min_len 2 and is not at 3."""
    junk = ["is", "at", "do", "av", "se", "vs", "fa", "cr", "la", "ir",
            "the", "and"]
    lex = {"eng": set(junk), "deu": {"und"}, "ita": {"via"}}
    assert BL.label_blocks([_block(junk)], "deu", lex, {"min_len": 2})
    blk = _block(junk)
    assert BL.label_blocks([blk], "deu", lex) == []
    assert blk.language is None


def test_a_repeated_token_cannot_decide():
    """Three blocks of route heights ("840 Hm 1450 Hm 1400 Hm ...") score Italian
    at 1.00 off one repeated token, ``hm``."""
    blk = _block(["840", "Hm", "1450", "Hm", "1400", "Hm", "550", "Hm",
                  "1300", "Hm", "100", "Hm"])
    assert BL.label_blocks([blk], "deu", LEX) == []


def test_the_winner_must_fit_its_own_dictionary():
    words = ["ferrata", "qqqq", "wwww", "eeee", "rrrr", "tttt", "yyyy",
             "uuuu", "iiii", "oooo"]
    assert BL.label_blocks([_block(words)], "deu", LEX) == []


def test_a_bilingual_line_abstains():
    """"Sehr gut versicherter Steig / Very good secured route" ties at margin
    0.00 in the corpus and must stay on the document language: it has no single
    language to be labelled with."""
    blk = _block(["sehr", "gut", "route", "und", "the", "and", "der",
                  "schwierig", "this", "two"])
    notes = BL.label_blocks([blk], "deu", LEX)
    assert notes == [] or notes[0].margin >= BL.DEFAULTS["min_margin"]
    assert blk.language is None


def test_figures_are_skipped():
    blk = _block(["This", "ferrata", "is", "strictly", "speaking", "two",
                  "ferratas.", "The", "two", "variants"],
                 btype=BlockType.FIGURE)
    assert BL.label_blocks([blk], "deu", LEX) == []
    assert blk.language is None


def test_disabled_and_single_lexicon_are_inert():
    """A fresh clone has no models/lexicons/, so the pass must do nothing rather
    than vote with one dictionary (which every block would then win or lose
    against for no reason)."""
    words = ["This", "ferrata", "is", "strictly", "speaking", "two",
             "ferratas.", "The", "two", "variants"]
    assert BL.label_blocks([_block(words)], "deu", LEX, {"enabled": False}) == []
    assert BL.label_blocks([_block(words)], "deu", {"eng": ENG}) == []
    assert BL.label_blocks([_block(words)], "deu", {}) == []


def test_params_come_from_config():
    p = BL.resolve_params({"block_lang": {"min_len": 4, "enabled": False}})
    assert p["min_len"] == 4 and p["enabled"] is False
    assert p["min_rate"] == BL.DEFAULTS["min_rate"]


@pytest.mark.parametrize("texts,expected", [
    (["Straße", "über", "1450"], ["straße", "über"]),
    (["a", "an", "the"], ["the"]),
    (["12", "3.5", "|"], []),
])
def test_vote_tokens_keeps_letters_and_drops_short_or_numeric(texts, expected):
    assert BL.vote_tokens(texts, 3) == expected
