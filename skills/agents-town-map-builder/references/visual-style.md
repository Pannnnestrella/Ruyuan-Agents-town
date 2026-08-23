# 2D side-elevation visual style

## Projection lock

Guangling Inn uses `orthogonal-side-elevation`. Each room is a flat frontal stage or dollhouse cutaway:

- camera perpendicular to the back wall at character eye level;
- back wall is a frontal rectangle with parallel vertical posts and horizontal beams;
- walkable floor is a narrow horizontal strip at the bottom, not a floor plane receding into depth;
- characters move on declared horizontal screen-space baselines;
- no bird's-eye, top-down, isometric, three-quarter, vanishing-point, diagonal-wall, or perspective-grid composition.

The repository legacy maps may be used only for their crisp outlined 2D game-asset finish, modular density, material vocabulary, and readable silhouettes. They are not projection references because their camera is overhead. When the user mentions 如鸢/代号鸢, translate that into broad traits—refined historical-romance atmosphere, elegant ink-informed linework, softly painted cel shading, restrained ornament, and warm narrative lighting—without copying an existing room, asset, logo, character, or signature composition.

## Layer ownership

1. **Raster room bases:** frontal walls, beams, windows, approved architectural openings, furniture, weather, shadows, and atmosphere.
2. **Raster connection fixtures:** compact doors/thresholds for same-floor routes and compact ladders/hatches for cross-floor routes, anchored between or at the edges of room panels.
3. **DOM rooms:** names, descriptions, public/restricted badges, focus state, and click targets.
4. **SVG topology:** port highlights, reachable states, direction cues, and active movement paths; no player-facing full-map connector lines.
5. **DOM tokens:** only agents visible in the current view.

Never bake labels, arrows, route lines, door icons, characters, badges, clues, or interaction states into raster art. A door opening may appear only when its room-edge port is declared in `map_binding.json`; SVG/DOM remains authoritative for whether it is reachable.

## Shared ImageGen prompt block

```text
Use case: stylized-concept
Asset type: modular 2D side-elevation room background for an interactive game map
Style/medium: refined original Chinese historical-romance game environment; clean ink-informed outlines; simplified shapes and flat color blocks; limited two- or three-step cel shading; subtle paper/gouache texture; unmistakably 2D, not photorealistic and not 3D-rendered
View: exact flat side elevation / frontal dollhouse cutaway; camera perpendicular to the back wall at character eye level; one level horizontal character baseline
Architecture: frontal wall rectangle; parallel vertical posts; parallel horizontal beams; narrow floor strip only; no floor plane receding into depth
Lighting/mood: medium-bright and clearly readable even in storm ambience; raised midtones and open shadows with controlled warm lantern accents; no crushed blacks, glossy modeling, or volumetric 3D light
Palette: charcoal-brown timber, muted blue-gray, dusty cinnabar, aged parchment beige, sparse warm gold
Composition: full-bleed illustration filling the declared target aspect edge-to-edge; no black bars or unused stage margins; reserve declared edge-safe zones; keep the movement baseline and maximum-capacity token area clear
Constraints: no text, labels, letters, arrows, route lines, UI, characters, clues, signatures, logos, or watermark
Avoid: bird's-eye, top-down, isometric, three-quarter view, visible floor-plan tops, diagonal receding floor, perspective grid, vanishing point, camera tilt, depth corridor, photorealistic texture, deep 3D volume, smooth gradient-heavy rendering, crushed shadows, black bars, letterboxing, empty stage margins, false door, clipped threshold, giant props, hard vignette
```

## Room prompt suffix

State the room ID, narrative function, exact logical rectangle, target pixel aspect, movement-baseline ratio, left/right edge-safe widths, declared visual ports, essential materials, and at most three important set-dressing elements. Keep furniture against the back wall and leave the lower character band readable. Do not ask ImageGen to decide where rooms connect.

For calibration, generate one representative 5:3 lobby without baked doors. The local assembly pass adds or reveals standardized edge openings only after the port data passes validation.

## Edge-port art rules

- Use a shared connection kit for doorframe, open threshold, curtained opening, exterior gate, and corridor mouth.
- Choose fixture type from topology before prompting: same floor means door/doorway/threshold/corridor mouth; different floors mean compact ladder/hatch/stair marker. ImageGen must not decide this semantic.
- Side ports are anchored to `left` or `right`; their sill aligns with the room's `movement_baseline`.
- A fixture occupies only the declared aperture and edge-safe strip. It must not exceed 25% of either connected room's width or 35% of its height, and must never replace the room background.
- Vertically stacked or cross-floor transitions use explicit compact `upper`, `lower`, or `interior` endpoint fixtures, never an invented same-floor door.
- Keep a quiet strip at every side edge. No table, shelf, post, lantern, shadow blob, or loose object may cross a declared port aperture.
- Direct room seams use the same opening width, threshold height, wall thickness, palette, and light spill on both assets.
- Raster openings show architecture only. SVG adds availability, direction, hover/focus, and active movement state.

## Connection-fixture prompts

- **Same-floor door:** transparent front-facing mini fixture; one narrow open doorframe plus a short flat threshold, centered on the shared boundary. No wall, room interior, corridor, staircase, ladder, arrow, or floor-spanning structure.
- **Same-floor non-touching pair:** generate one small matched doorway asset and reuse it at both endpoint ports. Do not generate a bridge or line across the distance between panels.
- **Cross-floor ladder/hatch:** transparent compact fixture; a short straight ladder or hatch with only enough rungs/steps to read clearly at UI scale, anchored to the panel edge. It is an endpoint symbol, not a full architectural flight.
- **Cellar access:** compact hatch or short descending threshold at the declared port; no room-size stone staircase.

Shared fixture prompt constraint: `small boundary connector between two room panels; exact flat front/side elevation; object fills only its tight transparent canvas; target display footprint is the declared aperture; no room background; no full staircase; no long line.` Repeat invariants on every edit: change only the named defect; preserve scale, compact footprint, palette, transparency, and baseline anchor.

## Character tokens

Characters are not part of room art. Reuse canonical portraits/standees from the repository. Render each as a transparent DOM token with a bottom-center anchor on the room baseline. If a room needs more visible occupants than fit shoulder-to-shoulder, use deterministic screen-space slots or controlled overlap; do not fake depth by turning the room into a top-down plane.

## Review rubric

Reject a candidate that fails any of these checks:

- frontal side-elevation projection;
- target aspect and crop safety;
- full-bleed framing with readable midtones and no black/empty margins;
- clearly 2D line-and-color rendering rather than realistic modeled volume;
- clear baseline and capacity band;
- quiet declared edge zones;
- style/palette/material continuity;
- no forbidden UI, text, people, or fake connections;
- real alpha and complete geometry for portals.
