# Map binding and asset-manifest schema

Keep simulation rules in `world.json`. Put replaceable geometry and public art-build metadata in a sibling `map_binding.json`.

## Side-elevation geometry

Guangling Inn uses `orthogonal-side-elevation`. The grid positions rectangular room panels; it does not imply a top-down floor plane.

```json
{
  "schema_version": 1,
  "projection": "orthogonal-side-elevation",
  "grid": {"columns": 12, "rows": 8, "tile_size": 64, "width": 768, "height": 512},
  "floors": [{"id": 1, "name": "一层"}],
  "rooms": {
    "lobby": {
      "floor": 1,
      "rect": {"x": 4, "y": 4, "w": 5, "h": 3},
      "theme": "lobby",
      "token_grid": {"columns": 5, "rows": 2},
      "movement_baseline": 0.86,
      "edge_safe": {"left": 0.12, "right": 0.12}
    }
  },
  "routes": [{
    "id": "stairs--lobby",
    "from": "stairs",
    "to": "lobby",
    "kind": "door",
    "visual_join": "seam",
    "ports": {
      "from": {"room": "stairs", "edge": "right", "offset": 0.86, "aperture": 0.18},
      "to": {"room": "lobby", "edge": "left", "offset": 0.86, "aperture": 0.18}
    },
    "segments": [{"floor": 1, "points": [[192, 320], [252, 320]]}],
    "visual": {
      "mode": "paired-door",
      "label": "门",
      "endpoint_asset": "/static/assets/maps/guangling_inn/v002/connection-door-standard.png",
      "show_overview_path": true
    }
  }]
}
```

Coordinates remain one-based integer cells. `movement_baseline`, port `offset`, port `aperture`, and `edge_safe` values are normalized ratios from 0 to 1:

- for a left/right port, `offset` is measured downward along the room edge and normally equals `movement_baseline`;
- for a top/bottom port, `offset` is measured rightward;
- `aperture` is the opening span relative to the corresponding room dimension;
- `edge_safe.left/right` reserves quiet strips for deterministic connection art and local seam repair.

Port coordinates use the logical canvas pixel space declared by `grid.width`, `grid.height`, and `grid.tile_size`. Left/right/top/bottom port points are derived from the room rectangle and normalized offset. An `interior` port must additionally declare an explicit `point: [x, y]` in that pixel space; `offset` alone is not a coordinate.

`visual_join` values:

- `seam`: room rectangles physically touch; ports use opposite edges and resolve to one global coordinate;
- `svg`: panels do not touch; SVG draws the public connective path between declared ports;
- `portal`: stairs, ladder, hatch, cellar descent, exterior transition, or cross-floor connection with required endpoint artwork.

Every route must contain `segments`, but they are animation sampling paths rather than always-visible connectivity lines. The first point must match the `from` port, the last point must match the `to` port, and every point must remain within the logical canvas. A cross-floor route has a segment for every endpoint floor. Non-seam movement paths must have non-zero length; a physical seam may use a zero-length path only with `visual.mode: "seam-door"` and a declared door asset/opening.

`visual.mode` controls the persistent compact boundary affordance independently of the motion path:

- `seam-door`: one doorway spanning a real touching seam; no persistent connector line;
- `paired-door`: a matched small doorway at each same-floor port; no persistent connector line;
- `covered-passage`: two compact corridor-mouth entrances without a spanning line;
- `cellar-steps`: a compact hatch/threshold endpoint, not room-size stone steps;
- `stairs`: compact cross-floor ladder/hatch endpoint fixtures, not a room-scale stair flight.

`label` is human-readable assistive text. `endpoint_asset` is a public static URL when the visual mode uses one shared endpoint asset. New player-facing bindings do not expose full connector lines; `show_overview_path` is legacy metadata only. Missing `visual` remains a supported runtime compatibility case for old worlds, but new side-elevation production bindings must declare it and pass `validate_side_edges.py`.

`orthogonal-top-down` remains valid only for explicit legacy compatibility. Do not mix top-down room art with side-elevation room art inside one binding.

## Production asset manifest

Put this object under `map_binding.asset_manifest` when artwork is planned:

```json
{
  "schema_version": 1,
  "render_scale": 2,
  "source_root": "art/v002/source/selected",
  "prompt_ledger": "art/v002/prompt-ledger.json",
  "normalized_root": "normalized",
  "composite_root": "composite",
  "max_upscale": 1.25,
  "connection_kit": "art/v002/source/connection-kit",
  "assets": [{
    "id": "room-lobby-base",
    "kind": "room-base",
    "room_id": "lobby",
    "source": "room-lobby-base.png",
    "prompt_id": "room-lobby-base",
    "fit": "cover",
    "anchor": "center",
    "z": 10,
    "required": true
  }]
}
```

Target geometry is either `room_id` or explicit `floor` plus `rect`, never both. Output size is always derived:

```text
target_width  = rect.w × grid.tile_size × render_scale
target_height = rect.h × grid.tile_size × render_scale
target_x      = (rect.x - 1) × grid.tile_size × render_scale
target_y      = (rect.y - 1) × grid.tile_size × render_scale
floor_size    = grid.width × render_scale by grid.height × render_scale
```

### Fit and edit policies

- `cover`: aspect-preserving LANCZOS resize plus centered crop for opaque room bases.
- `contain`: optional alpha trim plus aspect-preserving LANCZOS resize on an exact transparent canvas for overlays.
- Never free-stretch. Regenerate if crop or contain destroys required geometry.
- `max_upscale` limits linear enlargement.
- Generated masters, locally edited revisions, and final normalized assets live in separate directories. An edit recipe must identify the selected revision.

## Invariants

- Room keys exactly equal world location IDs; rectangles are positive integer cells, in bounds, and non-overlapping per floor.
- Token slots cover world capacity.
- Unordered route endpoints exactly equal unique world connections.
- For side elevation, every room declares a valid movement baseline and edge-safe strips.
- For side elevation, every route declares ports whose `room` values equal its endpoints.
- Left/right door ports align with their room baseline; direct seams touch, use opposite edges, and resolve to one global coordinate.
- Interior ports have explicit in-bounds pixel points. Animation-path endpoints differ from their declared ports by at most 1px, all path points are in bounds, and non-seam paths are non-zero.
- Every production route declares one supported `visual.mode` and at least one visible architectural endpoint expression. Motion paths are hidden by default and are not the sole connectivity affordance.
- Every room has exactly one required room-base asset.
- Every portal route has required artwork on every endpoint floor.
- Asset IDs and paths are unique, relative, and contained by declared roots.
- Every prompt ID resolves in the versioned prompt ledger.
- Raster/public metadata contains no characters, clues, secrets, or generated truth.
- Missing `asset_manifest` remains valid for legacy rendering; production delivery must pass `--require-assets`.
