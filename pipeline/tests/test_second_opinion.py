"""Unit tests for the EasyOCR second-opinion alignment (pure logic, no GPU).

The load-bearing filter is the DICTIONARY GATE (see RESULTS.md 2026-07-18): a raw
token-diff flagged 89/763 real Cyrillic words (precision ~0) because on Cyrillic
EasyOCR is the noisier reader (homoglyphs se->ce, its own misreads). The gate
flags a Tesseract word iff  norm(T) not in dict  AND  EasyOCR nominated a
norm(E) in dict — flag only a Tesseract NON-word that EasyOCR replaced with a
VALID word. This subsumes homoglyph-folding and join-tolerance in one filter.

Also covered: the inert-seam contract (dictionary=None flags nothing — the
mechanism stays dormant until the owner supplies a lexicon), the region-confidence
gate, replace-only (a pure delete = EasyOCR under-detection), and x-sort within a
line (Tesseract word-ORDER is not a text disagreement).
"""
from pipeline.second_opinion import Region, find_disagreements, normalize_token


def _boxes(*specs):
    """specs: (x, text) — fixed y/w/h on one line for readability."""
    boxes, texts = [], []
    for x, text in specs:
        boxes.append((x, 0, 40, 20))
        texts.append(text)
    return boxes, texts


def _line(text, conf, x0=0, y0=0, x1=1000, y1=30):
    return Region(x0, y0, x1, y1, text, conf)


# A tiny normalized lexicon standing in for the per-language dictionary.
DICT = {normalize_token(w) for w in
        ["Chopmarked", "Coins", "the", "cat", "касапница", "власти", "се", "и"]}


def test_normalize_strips_punctuation_and_folds_case():
    assert normalize_token("Chapmarked,") == "chapmarked"
    assert normalize_token("36.24).") == "3624"
    assert normalize_token("ВЛаСТИ") == normalize_token("власти")
    assert normalize_token("!!!") == ""


# ---- the inert-seam contract ------------------------------------------------


def test_no_dictionary_flags_nothing():
    """dictionary=None is the inert seam: even a blatant substitution is silent
    until a lexicon is supplied (repo pattern, mirrors stage08.join_hyphen)."""
    boxes, texts = _boxes((0, "Chapmarked"), (50, "Coins"))
    regions = [_line("Chopmarked Coins", 0.9)]
    assert find_disagreements(boxes, texts, regions, 0.30, None) == set()


# ---- the dictionary gate ----------------------------------------------------


def test_nonword_replaced_by_valid_word_is_flagged():
    """The motivating case: Tesseract's 'Chapmarked' is not a word, EasyOCR
    nominated 'Chopmarked' which IS — flag the Tesseract non-word."""
    boxes, texts = _boxes((0, "Chapmarked"), (50, "Coins"))
    regions = [_line("Chopmarked Coins", 0.9)]
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == {0}


def test_valid_tesseract_word_is_never_flagged():
    """Homoglyph immunity: Tesseract's 'се' is a valid word, so even though EasyOCR
    read the Latin lookalike 'ce', се is in the dict -> never flagged. This is the
    single filter that kills the 89-flag Cyrillic noise."""
    boxes, texts = _boxes((0, "се"))
    regions = [_line("ce", 0.9)]  # EasyOCR homoglyph
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == set()


def test_genuine_cyrillic_misread_is_flagged():
    """Real bg_01 survivor: Tesseract 'касалница' (non-word) vs EasyOCR
    'касапница' (real word, in dict) — a true Tesseract л/п misread."""
    boxes, texts = _boxes((0, "касалница"))
    regions = [_line("касапница", 0.9)]
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == {0}


def test_nonword_but_easyocr_offers_no_valid_word_is_not_flagged():
    """Both engines produced non-words (EasyOCR nominated nothing valid) — the
    documented blind spot: no evidence Tesseract is the wrong one, so no flag."""
    boxes, texts = _boxes((0, "касалница"))
    regions = [_line("касалннца", 0.9)]  # EasyOCR also garbled, not in dict
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == set()


def test_agreement_flags_nothing():
    boxes, texts = _boxes((0, "Chopmarked"), (50, "Coins"))
    regions = [_line("Chopmarked Coins", 0.9)]
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == set()


# ---- the region-confidence gate ---------------------------------------------


def test_low_confidence_region_cannot_nominate():
    """EasyOCR junk region ('L=' @0.09) is dropped before it can nominate a word,
    so it can't flag a Tesseract token even if the token is a non-word."""
    boxes, texts = _boxes((0, "Chapmarked"))
    regions = [_line("Chopmarked", 0.09)]
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == set()
    # ...above the floor the same disagreement WOULD flag:
    assert find_disagreements(boxes, texts, [_line("Chopmarked", 0.5)], 0.30, DICT) == {0}


# ---- replace-only + x-sort structural rules ---------------------------------


def test_pure_delete_does_not_flag():
    """EasyOCR missed a trailing token — under-detection, not a Tesseract error.
    (No replace opcode, so the dict gate never even runs on it.)"""
    boxes, texts = _boxes((0, "Chopmarked"), (50, "xyzzy"))
    regions = [_line("Chopmarked", 0.9)]
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == set()


def test_insert_has_no_word_to_flag():
    boxes, texts = _boxes((0, "Coins"))
    regions = [_line("Coins the", 0.9)]
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == set()


def test_word_reorder_is_not_a_disagreement():
    """Tesseract stores words out of reading order but the tokens agree once
    x-sorted — must NOT masquerade as a text change (all are valid words too)."""
    boxes = [(100, 0, 40, 20), (0, 0, 40, 20), (50, 0, 40, 20)]
    texts = ["the", "се", "и"]                   # stored scrambled
    regions = [_line("се и the", 0.9)]           # x-order: се(0) и(50) the(100)
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == set()


def test_word_outside_every_region_is_untouched():
    boxes, texts = _boxes((5000, "Chapmarked"))
    regions = [_line("Chopmarked", 0.9)]
    assert find_disagreements(boxes, texts, regions, 0.30, DICT) == set()


def test_word_assigned_to_single_best_region_on_overlap():
    """Two overlapping regions cover the same word; it's processed once, against
    the tighter-overlapping region — the tight one agrees, so no flag."""
    boxes, texts = _boxes((10, "cat"))
    wide = Region(0, 0, 1000, 100, "Chopmarked", 0.9)  # would flag, loose overlap
    tight = Region(0, 0, 60, 25, "cat", 0.9)           # agrees, tight overlap
    assert find_disagreements(boxes, texts, [wide, tight], 0.30, DICT) == set()
