---
name: agents-town-map-builder
description: Design, generate, locally refine, assemble, and validate modular 2D side-elevation maps for Agents Town world packages, with an explicit legacy top-down compatibility mode. Use for map_binding geometry, room/portal artwork, edge connectivity, DOM/SVG movement UI, or a production-ready map asset pipeline; do not use for image-only scenes or unapproved gameplay-topology changes.
---

# Agents Town Map Builder

Turn an existing world graph into a rule-faithful interactive map and, when approved, a reproducible raster asset build. For Guangling Inn, default to flat 2D room side elevations: a frontal back wall and a single horizontal movement baseline, never a bird's-eye or isometric floor plan. Treat graph design, art generation, local source editing, edge connectivity, and deterministic assembly as separate stages.

## Choose the mode

- **Design mode:** audit the graph, design geometry, write `map_binding.json`, an asset manifest, prompts, and an approval preview. Do not generate images.
- **Production mode:** only after the user approves the asset plan or explicitly asks to draw, generate, review, normalize, and assemble artwork.
- **Repair mode:** inspect existing sources or composites, make the smallest targeted edit, then rerun normalization and validation. Never silently redesign the map during an art repair.

## Required workflow

1. Read the world file, current map consumer, and [map schema](references/map-schema.md). Audit IDs, capacities, floors, and unique undirected connections. Preserve IDs and topology unless the user explicitly authorizes a rule change.
2. Build integer geometry for the chosen projection. Use `orthogonal-side-elevation` for this project unless the user explicitly requests legacy compatibility. In side elevation, define each room's horizontal `movement_baseline`, quiet edge zones, and deterministic token slots. Place hubs, exits, chokepoints, and cross-floor portals first. Spatial proximity is not a rule edge. Treat connections as small boundary fixtures between room panels, not as room-scale scenery.
3. Write `map_binding.json` and its `asset_manifest`. Every route must declare its two visual edge ports. A direct seam must use opposite room edges, touch geometrically, and resolve to the same global port coordinate. Same-floor routes use a compact door, doorway, threshold, or corridor-mouth fixture; never stairs. Cross-floor routes may use a compact ladder, hatch, or stair marker anchored to the panel edge. The manifest must cover every room base and every required boundary fixture. Record target rectangles, fit policies, z-order, source paths, and a versioned build directory.
4. Run `scripts/validate_map.py <world.json> <map_binding.json> --require-assets`, `scripts/validate_side_edges.py <map_binding.json>`, and `scripts/report_asset_plan.py <map_binding.json>`. Fix graph, geometry, capacity, port, baseline, manifest, portal-art, and target-size errors before proposing image generation. Run the side-edge validator only for `orthogonal-side-elevation` bindings.
5. For any artwork request, read [image production](references/image-production.md) and [visual style](references/visual-style.md). Create a style anchor, one representative room, one compact same-floor door fixture, and only when the graph requires it one compact cross-floor ladder/hatch sample before producing the full set. Use built-in ImageGen by default; one call per distinct asset or variant.
6. Show the user the asset matrix, exact target sizes, style direction, stair treatment, prompts, and expected file paths. **Stop here until the user approves production** when they asked to review first.
7. After approval, generate candidates into a versioned `source/` directory. Inspect every candidate. Select rather than average variants; iterate with one targeted change while repeating projection, edge-safe, geometry, transparency, and no-text invariants.
8. If a selected candidate needs deterministic local correction, preserve the generated master and write a new revision plus an edit-recipe record. Permitted corrections include exact crop/resize, alpha extraction after explicit authorization, edge cleanup, edge-zone extension, and bounded color matching. Use `scripts/extract_alpha.py` for authorized checker removal and `scripts/apply_seam_door.py` to revise both halves of one declared touching doorway atomically. Never repaint gameplay topology or overwrite the selected master. Follow the local-edit gate in [image production](references/image-production.md).
9. For ultra-wide panels, first resize an approved repeatable module to an exact aspect-preserving module size, then assemble with `scripts/assemble_repeat_strip.py`; do not stretch one generated scene. Run `scripts/prepare_map_assets.py <map_binding.json> --output <versioned-build-dir>`. It must resize with LANCZOS, preserve aspect ratio, use cover-crop for opaque room bases, use transparent contain plus declared anchoring for overlays, and assemble exact-size floor composites. Never hand-stretch an asset.
10. Run `scripts/validate_side_edges.py <map_binding.json> --normalized-root <build/normalized> --qa-output <build/edge-connectivity-qa.png>`. Inspect the generated seam pairs at 100% and UI scale. Repair the smallest source revision responsible for a mismatched baseline, clipped threshold, edge color jump, visible gap, or false opening; rebuild after every edit.
11. Apply [acceptance checks](references/acceptance.md). Do not deliver missing sources, dimension mismatches, excessive upscaling, uncovered rooms, missing portal art, invalid alpha, unmatched visual ports, or composites with the wrong pixel dimensions.

## Non-negotiable rendering boundaries

- Raster room art may contain architecture, materials, furniture, weather, and shadows. It must not contain room-scale stairs merely to visualize a route. Approved connection fixtures are separate, compact assets anchored at declared ports.
- DOM owns room names, descriptions, badges, focus/click targets, and visible-agent tokens.
- SVG owns rule routes, door/portal affordances, reachable highlights, and active movement paths.
- In side-elevation production bindings, derive persistent compact architectural endpoints from `ports` and keep motion paths hidden at rest. Do not render full connector lines in the player map. Focus/reachability highlights endpoints and rooms; active movement uses its separate temporary motion path.
- Do not bake text, arrows, route lines, characters, clues, or interaction states into map art.
- Player-facing tokens, counts, DOM attributes, and animation remnants must derive only from that player's visible-agent collection.

## Output contract

Design mode delivers geometry tables, route/edge-port mapping, `map_binding.json`, complete asset matrix, per-asset prompts, prompt ledger skeleton, exact dimensions, and validator results. Production mode additionally delivers generated masters, locally edited revisions and recipes, normalized assets, exact-size floor composites, edge-connectivity QA sheet, build report, final prompts, visual QA notes, and remaining manual checks.

For a copy-ready request, use [prompt template](references/prompt-template.md).
