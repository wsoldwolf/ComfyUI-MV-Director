# EMD 00008 Action grounding and camera-plan review

Date: 2026-09-20

## Scope

Analyzed `C:\Software\ComfyUI\output\mv_director\context_loop_emd_00008.md` together with its compiled plan `context_loop_plan_00007.txt` and compared it with EMD 00007. The review focuses on lyric-grounded objects and effects, Action diversity, facial performance, Arc/face transitions, fixed-fixture leakage, and finite Camera output.

## Findings

- The document is structurally complete: 16 Scenes, 52 Shots, 4 CUT Scene entries and 12 CONTINUE entries.
- Fixed-fixture leakage improved: Action references to stone lanterns fell from 16 in EMD 00007 to zero in EMD 00008.
- Action diversity regressed: unique Action texts fell from 47 to 37 and exact repeated instances rose from 6 to 15.
- 35 of 52 Actions use `胸の前`, 26 use `胸郭を傾ける`, and 12 use `左右非対称`. The model replaced the former lantern/walking default with a hand-up/down plus chest-tilt template.
- The lyric cue `苔へと還る` and the two `狐火` Scenes produced no Action target or autonomous phenomenon. The Cue Card contract was therefore not observable in final Action text.
- Six face approaches exist, including Arc-to-face and face-to-Arc structures, but Action facial acting remains weak: opening the eyes dominates while closure, blinking, half-open gaze, lowered gaze, narrowed focus, eyebrow acting, and mouth expression are mostly absent.
- Fifteen Arc Shots are present and all are at least 2.9 seconds, so short Arc misuse is resolved. However, 11 of the 15 share essentially the same full-body low-front-three-quarter to medium side geometry.
- The EMD Subject correctly states a black wooden geta platform with red hanao. Malformed footwear English observed in the compiled plan is a separate Compiler translation concern rather than an EMD identity error.

## Root cause

The deterministic generic-hand check only matched a terminal sentence such as `手を上げる。`. It did not match a composite output such as `右手を胸の前で急いで上げ、その動きに合わせて頭部を右へ向け、胸郭を傾ける。`. The Action audit also had no finite reason for omitting a validated lyric target or for assigning a torso/hand-only Action to a face-performance role. After the bounded repair budget, the lowest-violation LLM text was retained AS IS, allowing the template family to reach the final EMD.

Finite Camera validation removed target leakage successfully, but exact finite plans were not compared after serialization against recent history. Local fallback ordinals also repeatedly selected the same Arc geometry across batches.

## Implemented revision: Planner v45

- Expanded generic hand raise/lower detection to include composite clauses that append head, shoulder, chest, or silhouette motion.
- Added Scene-level validated target preservation. A concrete valid Cue Card target must appear in at least one role-appropriate Action in that Scene, not in every Shot. Missing targets cause `missing_grounded_cue_target` retry without Python rewriting.
- Added face-role validation. `face_and_upper_body_accent` requires an eyelid, gaze, eyebrow, mouth, or facial-expression change; torso/hand-only candidates cause `face_performance_missing` retry.
- Added finite audit reasons `MISSING_GROUNDED_CUE` and `FACE_PERFORMANCE_MISSING`.
- Added INFO diagnostics for Cue Card valid/invalid counts, grounded targets, and per-slot Action quality retry reasons.
- Treats the complete finite Camera seven-field tuple as a plan identity. Exact reuse in the current batch or recent 12 Camera history is a quality violation.
- Diversified finite fallback Arc-in, Arc-out, ordinary long Arc, face Zoom, and non-Arc geometries using Scene/Shot identity, while preserving the required slot contract and avoiding recent serialized plans when possible.

## AS IS boundary

Python still does not rewrite accepted Action text. It validates finite facts already supplied by the LLM contract, selects the affected slot, and asks the LLM to regenerate it. On bounded repair exhaustion, the best LLM candidate remains AS IS with diagnostics. Camera remains the existing finite-selection exception: Python serializes enumerated LLM selections and uses a target-free structural fallback only after an invalid bounded retry.

## Verification

- Added direct regression coverage for the EMD 00008 composite hand template.
- Added Scene-level moss target omission and successful non-contact target realization tests.
- Added face-performance-role omission and valid gaze/eyebrow performance tests.
- Added exact finite Camera plan repetition and varied Arc fallback tests.
- Planner-focused suite: 73 tests passed.
- Full suite under the live ComfyUI virtual environment: 335 tests passed with no skips.