# Stage 00 orientation policy — options (2026-07-18)

Follows Finding 1 in `2026-07-18-real-capture-findings.md`. The German real
captures ingested sideways → DocLayout-YOLO `blocks=1` → cascade. This drafts
fix options for the owner to choose from. **Diagnosis is settled (orientation);
the fix is a policy decision — not yet adopted.**

## The precise failure (in the current code)

`tools/normalize.load_upright_bgr` does, in order:
1. `PIL.ImageOps.exif_transpose(im)` — applies the full EXIF orientation.
2. Tesseract OSD (`--psm 0`) — the intended source of truth for 0/90/180/270.
3. If OSD conf `< min_conf` (default **2.0**) or OSD is unavailable → **keep the
   `exif_transpose` result** and warn.

The docstring already states the design intent — *"EXIF is not trusted for
rotation, because it is wrong here"* — but step 1 still **applies** the EXIF
rotation, and step 3's fallback **keeps** it. So for a spurious `Orientation=6/8`
tag on already-upright landscape pixels:

- `exif_transpose` rotates the correct landscape into **sideways portrait**.
- OSD is supposed to rotate it back — and does on text-dense pages
  (Bulgarian OSD conf cleared the gate) — but on **figure-heavy pages OSD conf
  was 0.04–1.46 < 2.0**, so the fallback kept the sideways buffer.

The fallback is backwards: when the EXIF tag is a bad 90° call, the
`exif_transpose` buffer is the *worse* default and the **raw un-rotated buffer
was already upright**. The testset never caught this because OSD was always
confident enough there to override the bad default.

Note: `exif_transpose` is not pure noise — it is the only step that can undo the
**mirror/flip** orientations (EXIF 2/4/5/7). Phone cameras emit 1/3/6/8 (pure
rotations, no mirror); mirror tags come from front-cams/scanners. So a fix must
keep mirror handling while taking the *rotation* decision away from EXIF.

---

## Option A — Split EXIF: bake mirror, let OSD own rotation, fall back to RAW *(recommended)*

Decompose EXIF orientation into (optional horizontal mirror) ∘ (rotation). Apply
**only the mirror** component (`hflip` for EXIF ∈ {2,4,5,7}, identity for
{1,3,6,8}); **do not apply the EXIF rotation**. OSD then decides 0/90/180/270 on
the raw-orientation buffer. When OSD is low-confidence/unavailable, the fallback
is now the **raw buffer** (already upright for flat down-shots), not a
possibly-sideways one. Add a domain tiebreak: on low OSD conf, prefer the
orientation whose aspect ratio is **landscape** (a book spread must be landscape;
Stage 02 already assumes this).

- **Fixes all three observed cases:** Bulgarian stays landscape (OSD confirms 0°);
  both German pages stay upright-landscape via the raw fallback instead of going
  sideways.
- **Pros:** matches the stated design intent; smallest principled change; keeps
  mirror/flip handling; the low-conf fallback becomes "do nothing to rotation"
  (safe) instead of "apply a possibly-wrong 90°"; touches one shared helper.
- **Cons:** a capture whose EXIF 90° is *genuinely* correct AND whose OSD is
  low-confidence would stay unrotated. For flat spreads the sensor buffer is
  essentially always already-landscape, so this case is rare here — but it is a
  real behavior flip, so it needs the promoted fixtures to guard it.
- **Blast radius:** `tools/normalize.py` (shared by pipeline + Gate 1 harness) →
  re-run the Gate 1 harness to confirm no regression on the existing testset.

## Option B — Content/text-baseline orientation detector (medium-term robustness)

Add a geometric text-line detector as a stronger primary than OSD: projection-
profile variance / Hough on line structure tells landscape-vs-portrait even when
OSD's script detection starves for text; keep OSD (or a heuristic) only for the
180° flip.

- **Pros:** attacks the root weakness directly (OSD needs enough words; figure
  pages don't have them); works where OSD conf is low.
- **Cons:** more code + tests; resolves 90° (axis) but not 180° alone — still
  needs OSD/heuristic for upside-down; a page that is *all* figure (no text) is
  still unorientable by text. Best layered **on top of** Option A, not instead.

## Option C — Capture-side ground truth (long-term / product path)

The Gate 5 Android app knows it is doing a flat book down-shot; have it stamp a
reliable orientation (or a "trust raw pixels" flag) into the upload manifest, and
have Stage 00 honor an explicit orientation hint over EXIF/OSD when present.

- **Pros:** removes the guess entirely for the real phone→server path — the most
  robust long-term answer.
- **Cons:** does nothing for loose JPEGs / the testset / non-app captures; depends
  on Gate 5 app work; needs a manifest field + ingest support. Complements A/B,
  doesn't replace them.

## Option D — Narrow "trust-raw" heuristic (smallest, most targeted)

Only override EXIF when `EXIF ∈ {6,8}` AND the raw buffer is already landscape AND
OSD is low-conf → ignore the EXIF rotation. A minimal special-case of A's tiebreak.

- **Pros:** tiny change; encodes the "a spread is landscape" fact; fires only in
  the exact failure case.
- **Cons:** pure aspect-ratio heuristic; doesn't generalize (180°, single-page
  portrait); more of a patch than a policy. Prefer A, which subsumes it cleanly.

---

## These are not either/or — they are one layered resolver

A/B/C cover **different, non-overlapping failure modes**, so the end state keeps
all of them, not one. Each signal is blind where another sees:

- **OSD** (exists) needs enough *text* — starves on figure-heavy pages (the
  observed German failure).
- **B (text-baseline geometry)** needs *line structure* — robust where OSD
  starves, but blind on an all-figure page.
- **C (capture stamp)** needs the *Android app* — ground truth when present,
  absent for loose JPEGs / the testset.
- **EXIF** is unreliable but occasionally right — keep it as the *lowest* signal:
  mirror component always, rotation only as a last resort.

So the real design is a **confidence-gated priority cascade**, each layer winning
only when it is confident, with the landscape prior as final tiebreak:

```
resolve_orientation(signals...) -> (rotation, provenance, confidence)
  1. explicit capture hint (C)      <- device ground truth, if present
  2. text-baseline detector (B)     <- if strong axis confidence
  3. Tesseract OSD (existing)       <- if OSD conf >= gate
  4. EXIF: mirror always; rotation only if nothing above decided   (A)
  5. prior: prefer landscape (a book spread must be landscape)     (D folds in here)
```

**Caveat — this raises, not removes, the need for fixtures.** Stacking signals
only helps if each layer is confidence-gated; otherwise a wrong high-priority
signal silently overrides a right low-priority one. That is only verifiable
against fixtures with GT orientation. So the sequencing below is about *build
order under measurement*, not about shipping a single option.

## Build order

1. **Now:** build the resolver skeleton = Option A wired in as layers 4–5
   (mirror-only EXIF + raw fallback + landscape prior), with B and C as
   declared-but-empty layers the cascade simply skips. Guard by re-running the
   Gate 1 harness + at least one promoted real fixture.
2. **Before merging step 1:** promote 1–2 real captures to `testset/` with GT
   orientation — needed to guard A's fallback flip and to measure B later.
3. **Medium-term:** land Option B into layer 2, measured on those fixtures.
4. **Product:** land Option C into layer 1 when the Android app can stamp
   orientation (Gate 5).

B and C are absent layers the cascade skips until their inputs exist — pluggable
slots, not blockers. **Promote fixtures (step 2) before merging step 1**, so the
behavior change is measured, not assumed.
