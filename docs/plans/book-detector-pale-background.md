# Fixing the book detector on a pale background

**Status:** planned, not started. Written 2026-08-28 at the end of the
on-device session that found the defect; the scouting numbers below were
measured that day, the fix was deliberately not attempted.

**Owner-visible symptom:** two real phone captures of a book on a pale sofa did
not split into pages. One was cut in the wrong place, one was not cut at all.
This is the only thing between the verified Android app and a usable scan
(RESULTS 2026-08-28, `docs/data/device_session_20260828.json`).

---

## 1. What actually breaks, in order

Five links; the fix could go in at any of them, which is why this is a plan and
not a patch.

1. **`paper_mask` merges the book with the room.** The rule is absolute HSV:
   `S < 0.25 and V > 0.55`. On the sofa capture the page is *dim* (V 0.534) and
   the sofa is *pale and grey* (V 0.524, S 0.256) — about 0.01 of separation on
   the brightness axis. 39.9 % of the whole frame passes the rule; only 56 % of
   the actual page does. The `close_k` morphology then welds the surviving page
   fragments to the surviving sofa fragments into one component.
2. **The percentile trim cannot save it.** `search_box` trims the 2nd/98th
   percentile to kill *thin bright leaks* (a cable, a chair edge) — leaks with
   almost no pixel mass. A sofa is not a leak; it is half the frame, and
   percentiles keep it.
3. **GrabCut inherits the contamination.** Seeded from that component, it grows
   over everything, so the emit box reaches 92 % (page_001) and 100 %
   (page_002) of the frame.
4. **The abstain gate then misreports the failure.** `abstain_area_frac` 0.83
   fires and the recorded reason is *"book fills 92 % of the frame — already
   tightly framed, not cropping"*. That sentence is a **framing verdict
   produced by a detection that never happened**, and it is wrong: both frames
   have a wide margin of room all round. It misled this session's operator into
   telling the owner to stand further back, which the owner correctly rejected.
5. **Stage 02 then searches the whole frame, and the cascade misfires.**
   * `page_001`: the ink-whitespace layer found a valley *inside* a page at
     x=2741 with ratio 0.525 — just under the 0.55 gate — and Layer 1 wins
     outright, so it shipped. Meanwhile the spine-pinch cue (x=1668) and the
     binding-shadow cue (x=1730) **agreed with each other** inside the 122 px
     tolerance, ~1000 px away, and were ignored.
   * `page_002`: ink ratio 0.701 (no valley) and pinch depth 0.012 — the pinch
     cue assumes a **dark** background, so Otsu inverts on a pale sofa and the
     cue returns a meaningless number rather than declaring itself
     inapplicable. No gutter, so `single.png`.

### The near-miss table (page_001)

| cue | value | gate | verdict | was it right? |
|---|---|---|---|---|
| ink valley | ratio **0.525** | < 0.55 | passed by 0.025 | **wrong** (x=2741, inside a page) |
| spine pinch | depth **0.106** | >= 0.11 | failed by 0.004 | **right** (x=1668) |
| binding shadow | x=1730 | corroboration only | agrees with pinch | right |

Both gates were within ~5 % of flipping, in opposite directions. This is the
single strongest argument for a consensus rule, and the reason the cascade work
in section 5 is on the list at all.

---

## 2. Baseline and constraints (measured 2026-08-28; re-run before trusting)

`python -m tools.split_eval` gives **19/19 spreads correct, worst clipping
0.0 %**. That harness already grades both things the fix must not break, and
exits non-zero on either. It is the acceptance gate; nothing here ships without
it.

The crop is only *applied* on 4 of the 19 (the `zoomset_*` lap captures);
`de_01`/`de_02` abstain at 85 %/89 %, the 13 flat spreads at 97-100 %.

**Headroom, so next session does not re-derive it:**

| knob | current | must keep passing | must start failing | headroom |
|---|---|---|---|---|
| `valley_ratio` | 0.55 | en_coins_02 and zoomset_de_01 at **0.47** | page_001 at **0.525** | 0.055, midpoint ~0.50 |
| `pinch_min_depth` | 0.11 | de_01 **0.15**, de_02 **0.18** | page_002 **0.012** | wide, but page_001's **0.106** sits just under |
| `abstain_area_frac` | 0.83 | de_02 at 0.89 must abstain | — | cropping de_02 was measured to move its gutter from 7 px to 96 px off |

**Trap on `valley_ratio`:** en_coins_02 is the floor, and its pinch depth is
only **0.05**. If a tightened ink gate ever drops it through to Layer 2, Layer 2
cannot catch it and it becomes a single-page regression. zoomset_de_01 has a
net (pinch 0.22); en_coins_02 does not.

**Cost:** `find_book` is 258-1375 ms on a 12 Mpx frame. Anything evaluated
per-candidate multiplies that.

---

## 3. Phase 0 — bank the fixture (blocking; do this first)

The two failing frames exist **only** in gitignored `jobs/`:

```
jobs/20260828-092505-15c41a76/page_001/01_fuse/anchor.png   4080x3060, wrong split at 2741
jobs/20260828-092505-15c41a76/page_002/01_fuse/anchor.png   4080x3060, no split at all
```

565 MB + 178 MB of job folder, one `git clean` from gone. Every experiment
below is measured against these two frames; without them this plan is
unexecutable.

1. Copy both anchors into `testset/` under a new id (suggested `paleset_01` /
   `paleset_02`), append-only, and commit the **anchor itself** so the row is
   reproducible from the repo alone. Do **not** copy `split_eval.py`'s
   `ANCHOR_OVERRIDE` wart, which reaches into gitignored `jobs/` for
   `de_01`/`de_02`.
2. Hand-label `testset/gt/book_box.json` — this doubles the labelled corpus from
   6 to 8 and adds the *first* pale-background lighting setup — and
   `testset/gt/gutter.json`.
3. Append the ids to `testset/README.md` with what makes them special.

**Decide the red-suite mechanism at the same time.** `split_eval` exits
non-zero unless everything passes, so adding two known-failing spreads turns
the suite red on day one. Either mark them expected-fail carrying the reason,
or give them a separate arm (repo precedent: `layout_order_eval --no-stage05`).
Pick one in the first ten minutes or the phase stalls on it.

---

## 4. Phase 1 — make the failure honest (no accuracy change)

Cheapest work on the list, provably non-regressive, and it is the part that
actually burned the owner.

* **B1. Separate "no detection" from "already tight."** Before the 83 % gate,
  test positive evidence that a book was actually found — whether the mask
  reaches the frame border and corners, or whether there is any colour contrast
  between inside and outside the box. If the box is the frame because the mask
  ran away, say *that*, in `meta.warnings`, `split.json` and the overlay.
  Accuracy is unchanged by construction, so the 19/19 is safe.
* **C2. Let the pinch cue declare itself inapplicable.** Check that Otsu
  actually separated a bright page from a dark background (bimodality, and
  which side the page falls on). On a pale background return "not applicable"
  instead of 0.012, so a reader can tell "no pinch" from "cue meaningless".
* **B3. Make `corroborated` self-describing** in `split.json`. It is currently
  serialized unqualified and is scoped to the pinch cue only; on page_001 it
  read `true` while the shipped answer was ~1000 px away from both corroborating
  cues. Already noted as owed in RESULTS 2026-08-28.

---

## 5. Phase 2 — cheap cues, in the order the evidence supports

**Recommended order after the 2026-08-28 probes: A10 first** (it already solves
both failing frames and reuses existing GrabCut code), then A11's ranking idea
if A10's precondition proves hard to state, then A1'/A4 as fallbacks.

### Already closed by measurement this session — do not re-attempt

* **Retuning `val_min` (brightness).** Swept 0.55 down to 0.35 on both failing
  captures: the emit box does not move at all (page_001 stays 0.918, page_002
  stays 1.0). The brightness axis carries no signal here. An *adaptive*
  brightness threshold is equally dead — page and sofa are 0.01 apart, so no
  per-image cutoff on V separates them either.
* **Retuning `sat_max` (saturation) globally.** Saturation *is* the
  discriminating axis: dropping `sat_max` to 0.12 flips both captures from
  abstain to a real crop (0.70 and 0.63 of frame). But measured against the
  suite it is a catastrophe — **`sat_max` 0.18 gives 17/19 and 42.1 % clipping;
  `sat_max` 0.12 gives 12/19 and 100 % clipping** (zoomset_en_01 loses its
  entire labelled book). One global saturation constant cannot serve both
  corpora.

That negative is the most useful thing this scouting produced: **the fix cannot
be a threshold retune.** It has to be per-image adaptivity, a different cue, or
escalation.

### A10. Background-first: model the surface, not the page (owner's proposal, 2026-08-28)

**The idea.** Every method above asks *"what does a page look like?"* — bright,
colourless, covered in text. Each of those assumptions dies on a real book: a
full-page photograph is neither bright nor colourless, a coloured border is not
paper-white, and a plate-only page has no text. Turn the question around and ask
*"what does the surface look like?"* The sofa or desk is **relatively
homogeneous and touches the frame border**, so it can be modelled without
knowing anything about books at all — the book is then simply the large thing
that is *not* the surface, and it is roughly rectangular.

This is assumption-light in exactly the place the current detector is
assumption-heavy, and it is **the recommended first experiment of Phase 2.**

**It is also nearly free to build.** `grabcut_box` already declares the frame
border to be background (`GC_BGD`); what it gets wrong is the *foreground* seed,
which comes from the broken paper mask. Replacing that seed with "everything far
from the border's colour model" is a change to code that already exists.

**Probed on 2026-08-28** (throwaway prototype: Lab colour, a Gaussian model
fitted to a 2 % border strip, Mahalanobis distance, Otsu, largest blob):

| frame | detector today | background-first | |
|---|---|---|---|
| real page_001 | 0.918 of frame (abstains) | **0.561** | would crop |
| real page_002 | 1.000 of frame (abstains) | **0.438** | would crop, and the box is visually tight and correct |

So it **solves the case that motivated this plan**, on the first try, with no
tuning. But run across the existing fixtures it produces nonsense:

| fixture | box area | |
|---|---|---|
| en_coins_01 / zoomset_en_01 / de_02 / zoomset_de_02 | 0.054 - 0.094 | absurd; already caught by the `min_area_frac` 0.10 guard |
| it_geo_01 | 0.387 | **would crop wrongly — not caught** |
| de_01 | 0.683 | **would crop wrongly — not caught** |
| bg_01 | 0.705 | **would crop wrongly — not caught** |

**Why, and this is the load-bearing insight:** on a tightly-framed spread *the
frame border IS the page*. The background model gets fitted to paper, and the
largest "unlike the border" blob becomes a figure **inside** the book. The method
does not degrade gracefully; it inverts.

**So the deliverable is not the detector, it is the precondition.** Before
trusting a background-first box, test *whether there is a background at all*:

* is the border strip homogeneous (low variance within it)?
* is the frame interior actually different from it (a real distance gap, not
  Otsu splitting noise)?
* does the resulting blob avoid touching the frame edge?

If the answer is no, abstain — which is already the correct, byte-identical
behaviour for all 13 flat fixtures. Note this pairs perfectly with Phase 1's B1:
"there is no background, so I cannot locate the book" is exactly the honest
reason string that item is about.

**Can we detect borders directly?** Measured on the pale-sofa frame, gradient
magnitude at 900 px width: grayscale median 24.1 / p99 242.3, saturation 14.8 /
159.5, and the Lab colour-opponent channels are nearly flat (a: 1.4 / 8.0,
b: 3.2 / 17.3). There *is* a usable step in luminance and saturation, so a
contour method is not hopeless here — but the edge is not dramatically stronger
than the page's own internal texture, so bare Canny plus "largest quadrilateral"
would be fragile. The literature's answer to precisely this is below.

**Known limit to record:** a background-first box encloses the *whole physical
book*, including the fanned block of closed pages beside the spread.
`testset/gt/book_box.json` deliberately excludes that block. Harmless for the
search box, wrong for the emit box, so the two-box split still matters.

### A11. Contour hypotheses ranked by contrast (from the literature)

The published state of the art for this exact problem — locating a document in a
phone photo against an unhelpful background — does not pick one boundary. It
**generates many candidate borders and then ranks them by a contrast criterion**:
how different the region *just inside* a candidate edge is from the region *just
outside* it. Tropin et al., *Approach for Document Detection by Contours and
Contrasts* (arXiv:2008.02615), report ~40 % fewer alternative-ordering errors and
~10 % fewer detection errors than contour-only methods, and name occlusion,
complex backgrounds and blur as what contour-only approaches fail on. The same
group's *Advanced Hough-based method for on-device document localization*
combines edge and colour features under a projective model and is built to run
on a phone. Benchmarks in this literature are MIDV-500 and SmartDoc.

Two things transfer directly:

1. **Rank, do not threshold.** Our failure is a thresholding failure — one global
   constant asked to serve two corpora. A scoring function over candidate
   rectangles ("strong edge support along the border, homogeneous outside,
   inhomogeneous inside") is a global fit that tolerates a weak or broken edge,
   and it subsumes A10 as one candidate generator among several.
2. **The rectangle prior is strong evidence and we are not using it at all.**
   Today's mask is per-pixel and shape-blind. A book is a quadrilateral; scoring
   candidate quadrilaterals uses that fact.

This is more work than A10 and should follow it, but it is the direction that
ends the whack-a-mole. Older work in the same vein — page-frame detection for
border-noise removal, and scanning inward from the image border for the first
statistically different pixels — supports the same "start from the outside"
instinct.

### A1'. Per-image adaptive saturation (most promising cheap lever)

The sweep shows the *right* threshold exists for each image — it simply is not
constant (~0.12 for the sofa frames, ~0.25 for the fixtures). So derive it per
image instead of fixing it: Otsu, or a valley-seek, on the S channel, perhaps
restricted to reasonably bright pixels. Keeps the whole two-box architecture.
Risk: on a tightly-framed spread the S histogram is nearly unimodal, so it must
degrade gracefully to today's behaviour rather than inventing a split.

### A4. Locate the book by *ink*, not by paper

The pages are the part of the frame with text on them; a sofa has none. Run the
existing adaptive threshold, aggregate ink density on a coarse grid, and take
the largest connected region of text-bearing cells as the book. Reuses
machinery Stage 02 already has, and aims at the actual discriminator.
Weaknesses to guard: a figure-only region has no ink, and patterned fabric can
look inky — so filter for *text-like* ink (stroke width, component size), not
any ink.

### A3/A6. Texture and detail energy

A page is smooth at large scale and busy at text scale; upholstery is smooth at
both. A multi-scale local-variance or gradient-energy map would separate them
without referencing colour at all. Slightly more work than A4, aimed at the
same physical fact.

### A2. Illumination normalization first, then today's rule

Divide by a heavily blurred copy, or CLAHE the V channel, so "bright" becomes
relative to the neighbourhood. **Explicitly not foreclosed** by the negative
CLAHE spike in the project memory: that measured *OCR recall on the gutter
band*, a different question, and its own leftover lead was named as "global
illumination normalization". Ranked below A1' because the V axis carries so
little signal here.

### C1/C3. Cascade work — deliberately last

Do this **after** the crop works, because a correct crop may make it moot.

* **C1. Consensus override.** When pinch and shadow agree with each other and
  the ink answer is far away *and* the ink call is marginal, do not let ink win
  outright. Must be a narrow tie-break, not a reordering — Layer 1 winning
  outright is exactly what guarantees the 13 flat non-regressions.
* **C3. Band-edge guard.** A minimum pinned near the edge of the `[0.30, 0.70]`
  search band is usually the band clipping the profile, not a real valley.
  Measured on the shipped path: the bad call sits **0.070** of the band from the
  edge, and the closest *ink-deciding* fixture is zoomset_en_02 at **0.225** — a
  clean gap, candidate gate ~0.15. **Scope it to the cue that decides:** de_01's
  ink argmin is at 0.061, closer to the edge than the bad call, but de_01
  resolves by pinch, so a guard on the deciding cue leaves it untouched. A guard
  applied to the ink argmin regardless of who decides would break de_01.
* Also check whether `[0.30, 0.70]` of an *uncropped* frame can even contain the
  true gutter when 40 % of that frame is room.

---

## 6. Phase 3 — escalation, if no cheap cue separates

| option | what it is | cost | ceiling |
|---|---|---|---|
| **A9. The phone supplies the box** | user drags a rectangle, or the app sends a rough crop | low: UI work, no new CV | **guaranteed** |
| **A8. Multi-hypothesis + arbitration** | generate boxes from several cues, pick by downstream evidence | high — multiplies 258-1375 ms per candidate | unknown |
| **A7. Learned segmentation** | pretrained salient-object / document segmentation | GPU; lazy-load + VRAM release per the repo rule | high, unmeasured |
| **A5. Edge/quad detection** | Hough/LSD line segments, fit the page quadrilateral | medium | poor here — low page/sofa contrast is the whole problem |

**A9 is first-class, not a footnote.** It is the only option with a guaranteed
ceiling, it fits the manual-capture flow the owner chose this session, and it
pairs naturally with Phase 1: once the detector can say *"I did not find the
book"* honestly, the app can ask instead of guessing.

**A8 carries a base-rate warning.** Two neighbouring results are already closed:
anchor choice by cheap criteria ("do not re-attempt") and per-page frame
selection (measured null; best cheap criterion 11/15 against chance 6.8).
Choosing a *box* by downstream evidence is not the same question, but in this
repo cheap criteria have been coin flips. Weigh that, do not rediscover it.

---

## 7. Acceptance criteria

1. `python -m tools.split_eval` stays at **19/19** on the existing spreads.
2. **Worst clipping stays 0.0 %** — losing page content is the one failure this
   stage treats as real.
3. Both new pale-background fixtures split within tolerance, **or** the detector
   abstains for a correctly-stated reason (Phase 1 is what makes that outcome
   honest, and therefore acceptable).
4. `find_book` cost stays inside a stated budget; if a phase multiplies it, the
   multiplier is written down.
5. A dated row in `docs/RESULTS.md` with machine-readable inputs and outputs
   under `docs/data/`, per the house rule.

**Stated refuse-outcome:** if no cheap cue separates page from background on
this corpus, that is a **measured negative to record and escalate to A9/A7** —
not a number to force. This repo has shipped negatives before (per-page frame
selection, the CLAHE spike, loosening the caption proximity rule), and doing so
again is a valid end state for Phase 2.
