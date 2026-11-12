# Pre-registration — does a focus number agree with the owner on which picture is sharper? (2026-11-12)

Written and committed before the statistic has been computed on any picture of
the population, and before any verdict has been collected. Hand-off item 5
(`docs/plans/handoff-2026-11-12.md`), open problem P7.

## Why

`pipeline/figure_hires.py` replaces a picture cut from the page with one cut
from a close-up when the close-up is larger, covers it and lines up. Nothing
checks that it is sharper. Of 24 upgrades on the owner's book, at least 4 look
worse than the page crop by eye (P7). Those 24 have been looked at and measured
and cannot be used to choose a rule.

## Population

Every upgrade Stage 08 would print in `jobs/20261021-104424-6d43b587` (the
sweep job): a live block with `figure_asset` set and `figure_asset_box ==
bbox`. Today that is **11 pictures** on 4 spreads. 11 is small: one
disagreement is 9 % of it. Whatever the next shoot brings is added later as a
separate, labelled-first population, never merged into this one after the fact.

Nobody has computed a focus number on these 11, and Claude has not looked at
their tiles.

## Ground truth (collected first, by the owner only)

`python -m tools.figure_focus_labels jobs/20261021-104424-6d43b587/` serves a
page showing, per picture, two unlabeled tiles side by side in an order drawn
from `random.Random(20261112)`: the page crop (`document_assets/<page>.png` cut
at the block's box) enlarged to the upgrade's size with bicubic interpolation,
and the upgrade. Buttons: left sharper / right sharper / cannot tell; a 1:1
view scrolls both together. Which side is which stays on the server and is
written to the answers file with each answer
(`docs/data/figure_focus_labels_<job>_<date>.json`). The owner answers; nobody
else. "Cannot tell" is a legitimate answer and is excluded from the agreement
count.

## Statistic (fixed now)

`tools/figure_focus_eval.py`, `focus_ratio(upgrade, crop)`:

- luminance (`cv2.COLOR_BGR2GRAY`), float32;
- the upgrade shrunk to the page crop's size with area interpolation
  (`INTER_AREA`); the crop untouched;
- Sobel, 3×3, x and y; gradient magnitude `sqrt(gx² + gy²)`; mean over the
  image;
- **ratio = mean gradient of the upgrade ÷ mean gradient of the crop.**

**Rule under test:** an upgrade ships only if `ratio ≥ 1.0`. The threshold is
1.0 by construction (sharper than what it replaces) and is **not tuned** on the
labelled pictures under any outcome.

`score` refuses to run until every one of the 11 verdicts is in.

## Gate

The rule PASSES only if both hold, on the pictures the owner could tell apart:

1. it agrees with the owner on **≥ 90 %** of them (ship ⇔ owner called the
   upgrade sharper); and
2. it **never ships one the owner called worse** (crop sharper).

PASS → propose to the owner a focus gate in `figure_hires` at 1.0 (built
off-by-default or on, the owner's call, and re-measured on the owner's book
only as a regression check, not as evidence). FAIL → written down as a refusal
with the disagreements listed; the owner stays the check. Fewer than 5 pictures
told apart → no verdict, wait for the next shoot.

## Control (instrument, not population)

`python -m tools.figure_focus_eval control jobs/20260829-084115-de3c20d3/`
(the owner's book, P7's 24 — already looked at, so usable only for this): for
every upgrade, a picture against itself must give **exactly 1.0**, and a copy
blurred on purpose (Gaussian σ = 2) must give **< 1.0** against the original.
The control is run and committed before the owner labels anything; it touches
no picture of the population.

## Not tested

Whether gradient energy rewards sharpening halos or JPEG noise (a crisp-looking
crop with halos was one of P7's ambiguous cases) — the owner's verdict is the
judge of that, which is why the gate is agreement with the owner and not a
property of the number. Colour, exposure and framing differences between the
two tiles are not controlled; the owner is asked to ignore them.
