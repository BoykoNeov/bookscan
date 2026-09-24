# Pre-registration: are the shipped figure upgrades actually sharper? (P7 follow-up)

Written 2026-09-24, before any sharpness number exists for the 24 upgrades.
Trigger: the one upgrade added today (`page_022__left` #5) was found SOFTER than
the page crop it replaced, by eye in the rendered page and by the numbers below;
`figure_hires` gates on scale, coverage, inliers and NCC, none of which measure
focus. A diagnostic census, not a gate: nothing ships from it.

Population: the 24 upgrades of the owner's book (`jobs/20260829-084115-de3c20d3`,
reproduced identically on the copy `W:\temp\claude\p7\job`).
Statistic, per figure: the upgraded asset resized DOWN (INTER_AREA) to the page
crop's size, then (a) variance of the Laplacian and (b) mean absolute Sobel
gradient, each divided by the same number on the page crop. A ratio < 1 on
BOTH means the upgrade carries less detail than the crop even at equal size.
Reported: the count with both ratios < 1, and each such figure looked at by eye
(asset vs crop at the crop's scale, one image each — sharpness, not alignment,
which the checkerboard already covers).
What it licenses: a finding for OPEN_PROBLEMS. A sharpness gate would be a new
parameter and needs its own pre-registration on a population not read here.
