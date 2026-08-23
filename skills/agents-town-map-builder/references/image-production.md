# Side-elevation image production and local-edit pipeline

Use this reference only after geometry exists and artwork is requested. The reliable sequence is: freeze graph and ports, declare a manifest, calibrate projection, preserve generated masters, make authorized local revisions, normalize mechanically, assemble, and inspect every connected edge.

## Phase A — plan and approval gate

1. Freeze `world.json` topology and `map_binding.json` geometry.
2. For Guangling Inn, set `projection` to `orthogonal-side-elevation`. Declare every room's movement baseline and edge-safe zones before prompting.
3. Give every rule route two named visual ports. Classify it before prompting: same-floor routes use compact door/threshold fixtures; cross-floor routes use compact ladder/hatch/stair endpoint fixtures. A seam must join touching opposite edges at one global coordinate. Non-touching same-floor panels receive matched endpoint doors, never a generated long bridge.
4. Choose `render_scale`; scale 2 turns a 768×512 logical layer into a 1536×1024 composite.
5. Create one manifest row per room base and compact connection fixture. Fixture targets derive from port aperture/edge-safe geometry, not from the full room rectangle. Record exact target, fit, anchor, alpha, z-order, source, and prompt ID.
6. Create a prompt ledger with shared side-view constraints, asset prompt, declared ports, reference role, candidates, selected master, local edit recipe, revision reason, and approval state.
7. Run the geometry and port validators before generation:

```text
python scripts/validate_map.py world.json map_binding.json --require-assets
python scripts/validate_side_edges.py map_binding.json
python scripts/report_asset_plan.py map_binding.json
```

Present prompts, exact dimensions, movement baselines, port table, staircase pair, generation count, and expected paths. If the user asked to review first, stop before ImageGen.

## Phase B — side-view calibration

Generate in this order:

1. one frontal 2D material/style anchor;
2. one representative 5:3 room with no baked connection openings;
3. one standardized compact same-floor door/threshold sample;
4. only if required by graph topology, one compact cross-floor ladder/hatch endpoint pair.

Inspect each at target aspect and UI scale. Reject bird's-eye, isometric, three-quarter, receding-floor, vanishing-point, photorealistic, or 3D-modeled results. For fixtures, also reject any candidate that resembles room scenery, occupies more than its declared edge aperture, or turns a same-floor route into stairs. Confirm medium-bright readable values, clean 2D outlines and flat color blocks, limited cel shading, palette, and real alpha for overlays. Do not generate the remaining rooms until the user accepts the calibration set.

## Phase C — full generation

- Use built-in ImageGen by default, one call per distinct asset or variant.
- Save selected assets into a versioned `source/generated/` directory; do not leave project assets only in a tool cache.
- Use repository legacy maps only as finish/material references, never as camera references.
- Feed only the accepted style anchor or directly related portal counterpart as an image reference. Label its role.
- Prompt every room with exact aspect, baseline ratio, edge-safe widths, and declared openings. ImageGen must not invent topology.
- Keep generated masters immutable. Record rejected variants and why they failed when auditability is requested.

## Phase D — explicit local editing

Local editing is a named production stage, not an emergency shortcut.

1. Preserve the selected generated master under `source/generated/`.
2. Write the corrected file under `source/edited/` with a revision suffix; never overwrite the master.
3. Record an edit recipe containing input/output, tool/script, parameters, affected pixel bounds, reason, reviewer, and before/after checks.
4. Allowed deterministic operations:
   - exact aspect crop and LANCZOS resize;
   - user-authorized alpha extraction using `scripts/extract_alpha.py`;
   - removal of checkerboard/halo residue;
   - extension or cleanup limited to the declared edge-safe strip;
   - standardized doorframe/threshold compositing from the shared connection kit;
   - bounded edge color/brightness matching;
   - transparent padding and anchor correction.
   - splitting the approved shared doorframe across a declared touching seam with
     `scripts/apply_seam_door.py`; both room revisions must use the same baseline,
     aperture fill and frame source, and only the declared edge-safe bands may change.
5. Forbidden local operations:
   - drawing a route absent from `world.json`;
   - moving an undeclared port;
   - hiding a graph or capacity error with paint;
   - adding text, characters, clues, UI, or secrets;
   - painting directly on the final floor composite.
6. After every local edit, normalize from the revised source, rebuild, rerun edge validation, and inspect the QA sheet. If local correction would change more than the edge-safe strip or required structure, regenerate instead.

For a touching side-view seam, revise both sides as one atomic operation:

```text
python scripts/apply_seam_door.py left.png right.png door.png \
  left-revised.png right-revised.png --baseline 0.86
```

The script places the threshold on the shared movement baseline, creates one opaque
dark aperture, and splits the same transparent frame at the exact room boundary.
Do not run it on a route declared as `svg` or `portal`.

When ImageGen alpha fails and the user explicitly authorizes local extraction:

```text
python scripts/extract_alpha.py input.png output.png --preview alpha-qa.png
```

Inspect the result on light, dark, and high-chroma mattes before using it.
For a baked near-white checkerboard trapped inside a closed doorframe or between railings, use `--include-enclosed --background-floor 215 --neutral-spread 32`. This mode removes all matching near-white neutral pixels, not only border-connected pixels, so inspect pale wood, brass highlights, and paper surfaces for accidental loss before acceptance.

## Phase E – deterministic normalization

For a very wide room, do not stretch a single generated image. Generate an approved
repeatable module, resize it to the exact module dimensions first, then assemble it:

```text
python scripts/assemble_repeat_strip.py module.png strip.png \
  --module-width 384 --module-height 256 --repeat 4 --alternate-mirror
```

The output width must equal `module_width * repeat`. `exact` fit refuses aspect
changes; use `--fit cover` only when a centered crop is declared in the edit recipe.
Alternating mirrored modules join the same edge pixels and reduce visible boundary
breaks. Preserve the generated module under `source/generated/`, write the assembled
strip under `source/edited/`, and record both paths in the prompt ledger.

```text
python scripts/prepare_map_assets.py map_binding.json --output <versioned-build-dir>
```

For a calibration subset, repeat `--only <asset-id>`. The script derives all dimensions from the grid, preserves aspect ratio, uses LANCZOS, cover-crops opaque bases, alpha-trims and contains overlays, respects anchors, refuses excessive upscaling, preserves sources, and writes exact-size composites plus a build report.

Never stretch an image to make an edge fit. If cover crop removes required structure or contain makes it unusably small, regenerate at the correct aspect.

## Phase F — edge-connectivity QA

```text
python scripts/validate_side_edges.py map_binding.json \
  --normalized-root <versioned-build-dir>/normalized \
  --qa-output <versioned-build-dir>/edge-connectivity-qa.png
```

The script validates route-to-port equality, legal edges, baseline alignment, and direct-seam geometry. With normalized assets, it also creates paired edge crops for every direct seam. Inspect at 100% and expected UI scale for:

- equal sill and movement-baseline height;
- matching opening width and wall thickness;
- no gap, double post, clipped threshold, or prop obstruction;
- acceptable local palette/light transition;
- no opening on an unconnected edge;
- complete side-on stair/landing pair.

Repair the smallest revised source responsible, rebuild, and rerun. A QA sheet is evidence for review, not a substitute for visual inspection.

## Delivery ledger

Deliver prompt ledger, generated masters, edited revisions and recipes, normalized files, composites, edge-connectivity QA sheet, build report, validator output, visual notes, and remaining manual checks.
