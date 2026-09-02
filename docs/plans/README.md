# Plans — index and state

One line per plan so a session can tell, without opening all ten, which are
live, which are parked, and which are finished. **Update the state here when a
plan changes state**; the plan itself keeps the reasoning. The live problems
these plans feed are ranked in `../OPEN_PROBLEMS.md`.

| plan | state (2026-09-02) | what it decides |
|---|---|---|
| `book-detector-pale-background.md` | **BLOCKED ON DATA.** Phases 0–1 done, A10 measured and refused, A9 (hand-drawn box) built and shipped, `vlm_box` shipped as a search window only. `split_eval` stays 19/21 on purpose. | How Stage 02 finds the book on a pale or cluttered surface. |
| `pale-background-fixture-shoot.md` + `pale-fixture-shoot-checklist.md` | **OPEN — needs the owner with a phone.** No frames shot yet. What it needs is *negatives* (tight handheld spreads), not more sofas. | The fixtures without which no pale-background precondition can be calibrated (n = 2 scenes today). |
| `panorama-and-next-steps.md` | **PARKED** (Phase 0 measured, Phase 2 no-verdict; Phase 1 not licensed until redesigned around per-region admission). §3 is the ranked defect list for the owner's book and is still current. | Whether close-ups can be painted onto the page, and what to build next. |
| `android-guided-capture.md` | **BUILT and verified on a phone** (M1–M5, 2026-08-28); M7 sweep capture built 2026-08-31, unverified on a phone. Auto-capture demoted to opt-in. | The capture app. |
| `partitioned-questing-pillow.md` | **DONE** (Gate 5 server; console shipped 2026-08-29). | The desktop FastAPI server. |
| `max-quality-fusion.md` | **SUPERSEDED by measurement.** Stage 01 stitching registers 6/317 close-ups with ORB (227/317 with SIFT) and painting them doubles text; the resolution is collected at Stage 07 instead (`figure_hires`). See `panorama-and-next-steps.md` for the live version of this idea. | The original multi-zoom fusion design. |
| `multiview-curvature.md` + `multiview-phase1-prereg.md` | **RESEARCH, not shipped.** Phase 0 passed at N=3; Phase 1 pre-registered; nothing in the pipeline reads it. | Correcting page curvature from several angles. |
| `pdf-import.md` | **PLAN ONLY**, not started. | Importing a PDF as if it were scanned pages. |

Two documents that are not plans but are read like one:

- `../OPEN_PROBLEMS.md` — the ranked register of what is still unsolved, with
  the next experiment for each and the preconditions that gate it.
- `../STATUS.md` — the chronological log of everything built, measured and
  refused (moved out of `CLAUDE.md` 2026-09-02).
