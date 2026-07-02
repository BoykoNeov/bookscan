"""Single shared schema for all inter-stage data structures.

Every stage reads and writes objects that conform to the types here. This is
the ONE contract the whole pipeline agrees on, so change it DELIBERATELY: in
its own commit, updating every stage that touches the changed fields
(see CLAUDE.md).

This is an intentionally lean first version — core geometry, words, blocks,
and the page container. It will be extended as stages 04–07 come online.
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


class Word(BaseModel):
    """One recognized word with geometry and OCR provenance (Stage 05)."""

    text: str
    bbox: BBox
    conf: float = Field(ge=0.0, le=100.0)  # Tesseract 0–100 (uncalibrated)
    engine: str = "tesseract"
    line_id: int | None = None
    block_id: int | None = None
    decision: WordDecision | None = None   # set by Stage 06


class Block(BaseModel):
    """A layout block with reading-order position (Stage 04)."""

    id: int
    type: BlockType
    bbox: BBox
    reading_order: int
    words: list[Word] = Field(default_factory=list)


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
