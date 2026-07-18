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

## Recommendation (layered)

1. **Now:** Option A — principled minimal fix in `tools/normalize.py`, guarded by
   re-running the Gate 1 harness + at least one promoted real fixture.
2. **Next:** promote 1–2 real captures to `testset/` with GT orientation (needed
   to guard A's behavior flip and to measure B).
3. **Medium-term:** Option B text-baseline detector, measured on those fixtures.
4. **Product:** Option C orientation stamp when the Android app lands (Gate 5).

Sequencing matters: **promote fixtures (step 2) before merging A**, so the
behavior change is measured, not assumed.
