# Acceptance checks

## Geometry and rules

- Load world, binding, and manifests as UTF-8.
- For Guangling Inn, require `orthogonal-side-elevation`; reject a mixed or accidental top-down production set.
- Validate room ID equality, integer bounds, non-overlap, token capacity, unique route IDs, and exact graph equality.
- Validate one movement baseline and quiet left/right edge zones per side-view room.
- Validate two visual ports per route. Direct seams must touch, use opposite edges, align globally, and meet both room baselines; non-touching connections must be explicitly `svg` or `portal`.
- Resolve every non-interior port to logical canvas pixels. Require explicit `point: [x, y]` for interior ports, keep all motion-path points in bounds, and limit first/last endpoint deviation to 1px.
- Reject zero-length `svg`/`paired-door` motion paths. Permit a zero-length physical seam only when `visual.mode` is `seam-door` and a door asset/opening is declared.
- Require every production route to declare a supported `visual.mode` with a visible door, passage, steps, or stairs expression. Treat `segments` as hidden animation geometry, not as the default persistent connector.
- Confirm cross-floor movement uses declared portals and every portal has route segments on all affected floors.
- Confirm map metadata contains no story truth, clues, credentials, objects, or agent state.

## Asset-plan completeness

- Exactly one required `room-base` covers each room.
- Every route has a topology-appropriate compact fixture: same-floor door/threshold or cross-floor ladder/hatch endpoint.
- Fixture target bounds derive from port aperture/edge-safe geometry, never the full room rectangle. Reject same-floor stairs and room-scale portal art.
- Every asset has a unique relative source path, target, fit policy, anchor, z-order, and prompt-ledger entry.
- Derived target sizes match `rect × tile_size × render_scale`; no handwritten size disagrees with the derived value.

## Raster build

- Every normalized asset is exactly its derived target dimensions.
- Every floor composite is exactly `grid.width × render_scale` by `grid.height × render_scale`.
- Room bases fill their rectangles without transparent holes; overlays preserve real alpha and do not contain opaque fake backgrounds.
- Aspect ratio is preserved. Cover crops remain crop-safe; contain overlays use their declared anchor.
- No source is enlarged beyond `max_upscale`; no source or prior build is overwritten without explicit force/versioning.
- Build report lists every source, original size, output size, operation, scale, alpha result, and composite.
- Every local edit preserves its generated master and records input, revision output, bounds, parameters, reason, and checks. Final composites are never hand-painted.
- Ultra-wide strips are assembled only after every module is resized to the exact declared module dimensions; the report records repeat count, mirror policy, placement, and final pixel dimensions.
- A standardized door crossing a touching seam is applied to both room revisions in one operation, uses one shared baseline/aperture/frame, and changes no pixels beyond declared paired edge-safe bands.

## Visual QA

- Every room is a flat frontal side elevation with a horizontal baseline. Reject bird's-eye, isometric, three-quarter, receding-floor, vanishing-point, or camera-tilt artifacts.
- Edge-connectivity QA sheet covers every direct seam. Sills, baseline, aperture width, wall thickness, palette, and light spill match at 100% and UI scale.
- No gap, double post, clipped threshold, obstructing prop, or undeclared opening appears on room edges.
- Every connection fixture is legible at UI scale, unclipped, aligned to its declared edge anchor, and visually small relative to both connected room panels.
- Maximum token capacity still has readable walkable space.
- Raster art contains no text, labels, arrows, route lines, characters, clues, buttons, signatures, or watermark.

## Interaction and privacy

- Render every location and route with keyboard-focusable room targets.
- Keep compact architectural endpoints visible at rest and do not render complete connector lines in the player map. Focus/reachability highlights endpoints and rooms only; active movement uses its separate temporary motion path.
- Compute endpoint markers from route ports and do not synthesize a fixed per-room corner door.
- Highlight only destinations authorized by the action payload; selecting a room does not auto-submit.
- Animate same-floor, outdoor, and cross-floor movement in event order, with direct fallback and reduced-motion support.
- Player DOM, counts, tokens, and animation state derive only from the player's visible agents; observer/director visibility remains intentional.
- Check desktop, compact desktop, and narrow mobile viewports, then rerun engine, API, persistence, and browser smoke tests.
- Character feet remain anchored to the side-view baseline during idle, movement, room changes, and reduced-motion fallback.
- Public floor art loads successfully beneath the DOM/SVG layers. Portrait images are requested only for already-visible agents and retain a deterministic initials fallback when an asset is absent.
