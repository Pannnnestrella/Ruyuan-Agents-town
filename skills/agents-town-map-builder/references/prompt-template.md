# Complete side-elevation map-generation prompt

```text
Use $agents-town-map-builder to design and prepare a production-ready interactive map package for the supplied Agents Town world.

Operate in two phases. Phase A may read files and write design, binding, manifests, prompts, local-edit recipes, and validation results, but must not generate images. Present the production plan and stop for approval. Phase B begins only after explicit image-generation approval.

Read world.json, the current frontend map consumer, and the repository legacy maps first. Preserve all location IDs and connections unless I explicitly authorize gameplay changes. Legacy images are finish/material references only; do not reuse their overhead camera.

Projection is orthogonal-side-elevation: every room is a flat frontal stage/dollhouse cutaway viewed perpendicular to the back wall at character eye level. The back wall is rectangular, the floor is only a narrow horizontal strip, and characters move on a declared horizontal baseline. Reject bird's-eye, top-down, isometric, three-quarter, receding-floor, perspective-grid, vanishing-point, or camera-tilt results.

Translate 如鸢/代号鸢 inspiration into broad original traits: refined Chinese historical-romance atmosphere, elegant ink-informed outlines, softly painted cel shading, restrained ornament, and warm narrative lighting. Do not copy an existing room, asset, logo, character, or signature composition.

Phase A deliverables:
1. graph audit and side-elevation spatial rationale;
2. per-room x/y/w/h, logical/rendered size, movement baseline, capacity slots, and quiet edge zones;
3. rule-edge table with from/to visual ports, join type (seam/svg/portal), aperture, and SVG route;
4. complete map_binding.json using projection orthogonal-side-elevation;
5. complete asset manifest covering every room and topology-appropriate compact boundary fixture: same-floor door/threshold, cross-floor ladder/hatch, and every portal endpoint;
6. shared style prompt, per-asset prompts, negative constraints, exact aspect, baseline, edge-safe instructions, reference roles, and prompt ledger;
7. explicit local-edit workflow that preserves generated masters, writes revision files and edit recipes, restricts edits to deterministic crop/resize/alpha/edge cleanup/connection-kit/color-match operations, and forbids painting final composites;
8. DOM/SVG renderer, side-view character baseline movement, responsive behavior, fallback, and privacy notes;
9. validate_map.py, validate_side_edges.py, and asset-plan results plus manual acceptance checklist;
10. a clear approval gate before ImageGen.

After approval, use built-in ImageGen by default. Calibrate with one side-view style anchor, one 5:3 room, one compact same-floor door/threshold sample, and only when required one compact cross-floor ladder/hatch pair. A fixture must fit only its declared edge aperture; same-floor routes must never produce stairs or room-scale architecture. Show this set and stop for style approval before generating the remainder.

Never trust generated dimensions. Run prepare_map_assets.py to derive every target from grid geometry, preserve aspect, resize with LANCZOS, cover-crop opaque bases, contain transparent overlays, and assemble exact composites. Then run validate_side_edges.py with the normalized root to create edge-connectivity-qa.png. Inspect every seam for equal baseline and sill, matching opening width and wall thickness, palette/light continuity, no gap/double post/clipping/obstruction, and no undeclared opening. Repair the smallest source revision, rebuild, and revalidate.

Do not bake room names, labels, arrows, route lines, characters, clues, UI states, or watermarks into raster art. Player views must not reveal remote agents through counts, DOM nodes, floor badges, animation remnants, or asset metadata.
```
