# v002 side-elevation calibration

Status: `portal_calibration_blocked_alpha`

## Result

- Projection changed from overhead to a flat frontal room side elevation.
- Generated source is preserved under `source/generated/`.
- Deterministic cover normalization produced the exact 640×384 lobby target without free stretching.
- The lower horizontal strip provides a clear character baseline; furniture stays against the back wall.
- Left/right boundary areas are relatively quiet and can receive standardized connection overlays after port validation.

## v2 revision

- Raised the full-room brightness and opened shadow detail while preserving storm ambience.
- Removed all top and bottom black stage margins; the architecture and floor now fill the 5:3 canvas.
- Reduced realistic material modeling in favor of ink-like outlines, simplified color blocks, and limited cel shading.
- Preserved the frontal side-elevation camera, horizontal token baseline, main set dressing, and quiet side zones.
- Exact normalized output: `calibration-build-v2/normalized/room-lobby-base.png`, 640×384.

## Connection and staircase calibration

- `connection-door-standard-v1.png`: complete reusable frontal doorframe, open center, level threshold, and v2 line/color treatment passed. Planned target is 128×256.
- `portal-main-stairs-lower-side-v1.png`: complete side-profile flight ascending lower-left to upper-right; all treads, stringer, rail, posts, and landing lip passed. Planned target is 384×256.
- `portal-main-stairs-upper-side-v1-rejected.png`: rejected because it duplicated most of the lower flight.
- `portal-main-stairs-upper-side-v2.png`: corrected independent upper platform/arrival, railing, posts, endpoint, and open drop passed. Planned target is 384×256.

All selected connection/stair sources are opaque RGB with a baked checkerboard. A built-in background-extraction edit on the doorway also returned RGB. These assets have not been normalized or accepted as production overlays.

The next permitted step is either explicit user authorization for deterministic local Alpha extraction on the v002 doorway and staircase pair, or an explicit CLI/API transparency fallback. Other rooms remain ungenerated.
