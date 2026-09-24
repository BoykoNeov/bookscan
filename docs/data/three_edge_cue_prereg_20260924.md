# Pre-registration: the "box touches three frame edges" cue (P1, mode c)

Written 2026-09-24, **before the cue has been computed on any frame**. Probe:
`docs/data/three_edge_cue_probe_20260924.py`. Nothing in `pipeline/` changes
unless the gates below all pass, and even then only behind an off-by-default
flag (see "What a pass licenses").

## The question

`OPEN_PROBLEMS.md` P1 mode (c): on the owner's sofa spreads 2 and 4 the
detector emits a crop that is stable over 8 seeds and wrong on three sides —
it starts at the frame's left edge and spans the full height, so sofa is kept
left, top and bottom (RESULTS 2026-09-24). The proposed cue: **refuse (abstain)
when the emitted crop touches three or more frame edges.** Experiment 4 of P1
says: before building it, count how many correct rows have that shape — if any
do, it is dead — and check `paleset_01`, whose book runs off the frame edge.

What was known before writing this, and is therefore not a finding: spreads 2
and 4 emit (0, 0, 2971, 3060) and (0, 0, 2863, 3060) on 4080×3060 frames — the
cue fires on both by construction. Spread 3's GrabCut box has the same shape
but the frame abstains at the area gate. No other frame's emitted box has been
looked at for this shape.

## Definitions

- **Touches an edge:** the emitted box's coordinate equals the frame boundary
  exactly after clamping — `x0 == 0`, `y0 == 0`, `x1 == w`, `y1 == h`. No
  tolerance. (Emit boxes are padded outward and clamped, so a book within
  roughly the pad of an edge lands exactly on it; that is recorded, see below.)
- **The cue fires** on a frame iff `find_book` (shipped params from
  `config.yaml`'s `book_crop` over the defaults, the three seeded draws)
  returns `applied=True` AND the emitted box touches ≥ 3 edges.
- **Diagnostic only, gates nothing:** the unpadded GrabCut union's distance to
  each edge, and the paper-mask search box's touched edges. The search box is
  NOT a second gate — it runs to the frame edges on tight scans too.

## Gates (all must pass)

**G1 — the shipped guard, with the cue on.** `tools/split_eval`'s 21 rows run
through `find_book` + the cue (a firing frame is treated exactly as an abstain:
full-frame search and emit). Pass iff the same 19 rows pass and worst clip stays
0.0 %. Reported alongside: **how many of the 21 rows crop at all** today — a row
that abstains is not a test of the cue, and the count says how many rows
actually exercise it.

**G2 — the labelled books, independent of today's detector.** Every label in
`testset/gt/book_box.json` (8 rows) is padded by `emit_pad` (0.06 of its own
width/height, as `_pad_box` does) and clamped to its frame. Pass iff **none**
touches ≥ 3 edges. A label that does would mean the cue forbids the correct
crop on that frame forever — `paleset_01` (label starts at x = 0) is the named
trap. Diagnostic: the same with the search pad (0.08).

**G3 — phone negatives, labelled by eye before computing.** Population: every
`jobs/2026*/page_*/01_fuse/anchor.png` on this machine (38 frames, 8 jobs). For
each frame, **from a thumbnail with no box drawn**, record which frame edges the
book's content (the two visible pages, same convention as `book_box.json`)
reaches or comes within ~6 % of. Labels committed to
`docs/data/three_edge_cue_labels_20260924.json` before the probe runs; not
revised afterwards (a wrong label gets a dated note). Each edge is `yes`,
`near` (within ~6 %) or `no`; **`near` counts as reaching** — the conservative
direction, since it can only turn a fire into a false one.
- A **fire** on a frame whose book reaches ≥ 3 of the box's touched edges is a
  **false fire** (the crop was honest). Pass iff **0 false fires**.
- A fire where at least one touched edge is one the book does NOT reach is a
  **true fire** (the crop keeps surface on that side).
- Reported per **scene**, not per frame: the owner's 25 spreads are one book on
  one sofa, n = 1; each other job is grouped by the session it came from.

**Required positives:** spreads 2 and 4 of `jobs/20260829-084115-de3c20d3`
fire. (Known in advance; if they do not, the probe is wrong, not the cue.)

## What a pass licenses — and what it does not

- **It is not a fix.** On spreads 2 and 4 the cue turns a three-sided sofa crop
  into no crop at all: sofa on four sides. The rendered PDF does not improve
  from the cue alone.
- What it buys: an honest refusal in place of "cropped to detected book"; the
  frame lands on the abstain path, where the local model's search window
  (`vlm_box`) and a hand-drawn `book_box.json` already act, and where a future
  model-box cut (P1 experiment 3, the inward-only guard) would act.
- All positives are one scene. A pass licenses **an off-by-default option**
  (`book_crop.three_edge_abstain: false`), not a default change.
- A failure of G1, G2 or G3 kills the cue as written. It is reported as a
  refusal, and the threshold is not adjusted (e.g. "four edges", a tolerance)
  on the same frames.

## Diagnostic, grades nothing

If spread 4 abstains under the cue, ask `vlm_box` once for its box (it has
never been asked; RESULTS 2026-09-24 item 5) and record the answer, drawn on
the preview, beside spread 2's.
