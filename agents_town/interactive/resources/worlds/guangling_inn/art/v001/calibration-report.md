# v001 calibration report

Status: `superseded_by_v002_side_elevation`

This overhead calibration is retained for audit only. It must not be used as the camera or composition reference for new Guangling Inn artwork.

## Accepted

- `dark-han-inn-anchor.png`: selected style anchor; projection, palette, material scale, and forbidden-content checks passed.
- `room-lobby-base.png`: lobby candidate 3 selected. Source is 1619×971 RGB; deterministic cover normalization produced the required 640×384 room asset.
- `portal-main-stairs-lower.png`: lower-flight candidate 1 selected. User-authorized deterministic local extraction produced full-range RGBA, then contain normalization produced the required 384×256 portal asset.
- `portal-main-stairs-upper.png`: upper-landing candidate 1 selected. The same extraction and normalization process produced the required 384×256 matching portal asset.
- `calibration-build/composite/floor-1.png`: partial 1536×1024 composite containing the lobby and lower flight at their grid-derived positions.
- `calibration-build/composite/floor-2.png`: partial 1536×1024 composite containing the upper landing at its grid-derived position.

## Alpha extraction and QA

- Original generated candidates remain unchanged in `source/candidates/` for audit.
- Extraction used only border-connected light-neutral pixels, followed by 0.8 px feathering and white-matte color decontamination. It did not erase enclosed openings or dark structural detail.
- Both production files have alpha extrema `(0, 255)`.
- Both assets were inspected on cream, charcoal, and magenta backgrounds. No baked checkerboard or obvious light halo remained; rails, posts, treads, landing, and opening stayed complete.
- QA previews: `calibration-build/qa-stairs-lower-alpha.png` and `calibration-build/qa-stairs-upper-alpha.png`.

## Review gate

The calibration assets now pass the technical image, alpha, size, and placement gates. The remaining v001 assets must not be generated until the user approves this calibration style and staircase pair.
