"""Single shared schema for all inter-stage data structures.

Every stage reads and writes objects that conform to the types here. This is
the ONE contract the whole pipeline agrees on, so change it DELIBERATELY: in
its own commit, updating every stage that touches the changed fields
(see CLAUDE.md).

This is an intentionally lean first version — core geometry, words, blocks,
and the page container. It will be extended as stages 04–07 come online.

Stage 07 (assemble) adds the **editable document layer** at the bottom of this
file: ``Document`` / ``DocPage`` / ``DocSettings`` are the job-level, MUTABLE,
user-editable derivative of the immutable per-page pipeline trace (see
``docs/GATE4_SPEC.md``). The per-word/per-block edit + provenance fields
(``Word.text_ocr``/``edited``, ``Block.type_auto``/``order_auto``/``text``) are
additive and optional, so Stage 04/05/06 output still validates unchanged.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class BBox(BaseModel):
    """Axis-aligned box in pixel coordinates of the image it was measured on.

    Top-left origin. ``x, y`` is the top-left corner; width/height are extents.
    """

    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h


class BlockType(str, Enum):
    """Layout block categories (Stage 04)."""

    TITLE = "title"
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST = "list"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    HEADER = "header"          # running header — stripped by default
    PAGE_NUMBER = "page_number"  # stripped by default
    OTHER = "other"


class UncertaintyMode(str, Enum):
    """User-selectable handling of low-confidence words (Stage 06).

    All three must exist end-to-end (see CLAUDE.md non-negotiables).
    """

    FLAG = "flag"              # render in a highlighted span
    BEST_GUESS = "best_guess"  # emit text plainly
    PATCH = "patch"            # inline a crop of the word from full-res dewarp


class WordDecision(str, Enum):
    """Per-word outcome of the uncertainty stage."""

    KEEP = "keep"      # confident enough — emit plainly
    FLAG = "flag"      # uncertain — highlight
    PATCH = "patch"    # uncertain — inline image crop


class OrderMode(str, Enum):
    """User-selectable handling of Stage 04's proposed reading order.

    Parallel to ``UncertaintyMode`` (which governs low-confidence *words*), this
    governs low-confidence *ordering*: reading order is fallible on hard real
    pages (multi-column + figure sidebars + cross-gutter panoramas), so the owner
    wants a first-class toggle between trusting the automatic order and reviewing
    it in the editor before reconstruction (owner design intent, 2026-07-03).

    Unlike ``UncertaintyMode``, this changes ZERO pipeline computation — it is
    purely editor-review state layered over an already-assembled document. It only
    ever affects whether the editor asks the user to confirm/correct block order.
    """

    AUTO = "auto"      # trust Stage 04's reading order as-is
    REVIEW = "review"  # surface each block's order for user confirm/correct/edit


class Word(BaseModel):
    """One recognized word with geometry and OCR provenance (Stage 05).

    Stages 04/05/06 only ever set ``text`` (the OCR read). The editable layer
    (Stage 07 assemble + the future editor) uses ``text`` as the CURRENT,
    editable text and keeps ``text_ocr`` as the immutable original, so an edit
    or translation never destroys the source (see ``docs/GATE4_SPEC.md``).
    """

    text: str
    bbox: BBox
    conf: float = Field(ge=0.0, le=100.0)  # Tesseract 0–100 (uncalibrated)
    engine: str = "tesseract"
    line_id: int | None = None
    block_id: int | None = None
    decision: WordDecision | None = None   # set by Stage 06

    # --- editable layer (Stage 07 assemble onward; None/False until then) ---
    text_ocr: str | None = None    # original Tesseract read, kept as provenance
    edited: bool = False           # True once `text` diverges from `text_ocr`
    patch_asset: str | None = None  # rel path into document_assets/ for a patch crop

    @property
    def flag_visible(self) -> bool:
        """Owner's per-word rule: an uncertainty marker (flag/patch) is shown
        until THAT word is edited or deleted — never cleared wholesale by editing
        something else in the block. A deleted word is simply gone.

        ``edited`` is treated as set EITHER explicitly OR implicitly when ``text``
        diverges from ``text_ocr``. The implicit path makes the interim hand-edit
        workflow safe: until the visual editor exists, a user editing
        ``document.json`` who changes ``text`` but forgets ``edited: true`` still
        clears the marker — and, crucially, in patch mode Stage 08 then renders
        their corrected text instead of the STALE original crop. On a fresh
        assemble ``text_ocr == text`` so this is a no-op; it only fires once text
        actually changes."""
        edited = self.edited or (self.text_ocr is not None and self.text != self.text_ocr)
        return self.decision in (WordDecision.FLAG, WordDecision.PATCH) and not edited


class Block(BaseModel):
    """A layout block with reading-order position (Stage 04).

    ``type`` and ``reading_order`` are the CURRENT (possibly user-overridden)
    values; ``type_auto``/``order_auto`` preserve the pipeline's automatic guess
    so an override is reversible and the editor can show what changed. Optional
    ``text`` is a block-level edited/translated rendering that SUPERSEDES the
    per-word text when present (the translation path); ``words`` are always kept
    as provenance + visual-context anchors (see ``docs/GATE4_SPEC.md``).
    """

    id: int
    type: BlockType
    bbox: BBox
    reading_order: int
    words: list[Word] = Field(default_factory=list)

    # --- editable layer (Stage 07 assemble onward; None/False until then) ---
    type_auto: BlockType | None = None   # automatic type before any override
    order_auto: int | None = None        # automatic reading_order before any override
    structure_edited: bool = False       # True if type/reading_order was overridden
    order_confirmed: bool = False        # user explicitly accepted the auto reading order
    text: str | None = None              # block-level translated/edited text override

    def order_review_visible(self, order_mode: str) -> bool:
        """Reading-order analogue of ``Word.flag_visible``: in REVIEW mode a block's
        proposed order stays 'needs review' until the user clears it, and — like
        ``flag_visible`` keys on the *specific* word field (``text`` vs ``text_ocr``)
        rather than any block edit — this keys on the *order field specifically*, NOT
        the shared ``structure_edited`` bit.

        ``structure_edited`` conflates type edits and order edits (both set it), so a
        type-only edit (paragraph -> heading, position untouched) must NOT count as
        having reviewed the order. Two independent clearing paths, neither touching
        type: the user RENUMBERS (``reading_order`` diverges from ``order_auto``) or
        explicitly ACCEPTS the auto order (``order_confirmed``). ``order_confirmed`` is
        a distinct bit precisely because accepting leaves ``reading_order`` equal to
        ``order_auto``, so acceptance can't be derived from the numbers.

        In AUTO mode nothing ever needs review. If ``order_auto`` is None (a document
        assembled before this field existed), we can't prove a renumber, so the block
        conservatively still shows as needing review until explicitly confirmed."""
        if order_mode != OrderMode.REVIEW.value:
            return False
        if self.order_confirmed:
            return False
        if self.order_auto is not None and self.reading_order != self.order_auto:
            return False
        return True


class Page(BaseModel):
    """The re-typeset model of a single page — the pipeline's central object."""

    page_id: str
    language: str = "eng"
    width: int
    height: int
    blocks: list[Block] = Field(default_factory=list)


class StageMeta(BaseModel):
    """Contents of every stage's ``meta.json`` (stage contract, item 3)."""

    stage: str
    version: str
    params: dict = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Editable document layer (Stage 07 assemble)
# --------------------------------------------------------------------------
#
# This is the ONE part of the schema that lives OUTSIDE the per-page immutable
# stage contract, on purpose (see docs/GATE4_SPEC.md): it is job-level, mutable,
# and the user's working copy. Stage 08 render and the future visual editor read
# ONLY a Document + its document_assets/ — never the per-page stage folders — so
# a document saved months ago keeps rendering after an upstream stage re-runs.

DOCUMENT_SCHEMA_VERSION = "1.0"


class DocSettings(BaseModel):
    """Doc-wide render/edit settings, carried in the document so editing a
    setting and re-rendering just works (no re-run of the pipeline)."""

    source_language: str = "eng"
    target_language: str | None = None    # set when the document is translated
    uncertainty_mode: str = "flag"        # flag | best_guess | patch (resolved at Stage 06)
    order_mode: str = "auto"              # auto | review — editor reading-order review (no pipeline effect)
    strip_running_headers: bool = True
    strip_page_numbers: bool = True
    fonts: list[str] = Field(default_factory=list)  # embedded at render (Latin+Cyrillic)


class DocPage(BaseModel):
    """One PHYSICAL page (a subpage: left/right/single) in reading order.

    A capture spread yields up to two of these; the document flattens all
    spreads of a job into a single ordered ``Document.pages`` list.
    """

    page_id: str            # unique, e.g. "page_001__left"
    source_spread: str      # the page_* folder it came from, e.g. "page_001"
    subpage: str            # left | right | single
    width: int              # of the dewarped page image (= word bbox coord space)
    height: int
    image_asset: str        # rel path into document_assets/ to the dewarped page image
    blocks: list[Block] = Field(default_factory=list)


class Document(BaseModel):
    """The editable, job-level re-typeset document — the artifact the owner asked
    to save before finalizing to PDF (translate first / auto-PDF-then-edit-later).

    Serialized to ``jobs/<job>/document.json`` beside a ``document_assets/`` dir
    holding every image it references by relative path (fully self-contained).
    """

    schema_version: str = DOCUMENT_SCHEMA_VERSION
    document_id: str
    job_id: str
    settings: DocSettings = Field(default_factory=DocSettings)
    pages: list[DocPage] = Field(default_factory=list)
