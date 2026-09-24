# Pre-registration: "union the model box with the paper mask" (P1 experiment 3)

Written 2026-09-24 before the guard was computed on any frame. Offline: the
model boxes are the recorded ones (`vlm_box_split_20260829.json` for the 21
testset rows; `split.json` of the owner's spreads 1 and 3; today's asks for 2
and 4, RESULTS 2026-09-24 "three frame edges"). The paper mask is deterministic
(`book_boundary.paper_mask`, shipped params); no GrabCut, no model call.

**Guard, as written in OPEN_PROBLEMS option 1:** cut box = union of the model
box padded by `search_pad` (what `user_box` does) and the bounding box of the
detector's raw paper-mask component.

**Graded:** clip of each of the 8 `book_box.json` labels (bar 0.0 %); on the
target frames (`paleset_01`, `paleset_02`, owner's sofa spreads 1–4) the
fraction of the frame kept and the edges touched.

**Kill line:** if on every target frame the guarded box is >= 83 % of the frame
(the area gate would refuse it) or touches >= 3 frame edges, the guard is a
no-op where the model box is needed: refused, no code. It passes only if it
removes surface on at least one target frame AND clips 0.0 % on all 8 labels.
