---
name: clean-vector-from-raster
description: Turn a raster character/cartoon illustration (e.g. a sprite sheet on a chroma-key background) into a clean, print-ready SVG using PhotoCraft + VectorCraft MCP tools. Use for "crop one figure, remove background, vectorize for T-shirt/print".
---

# Clean vector from a raster illustration (PhotoCraft -> VectorCraft)

Proven workflow. Paths are relative to the PhotoCraft read/write roots; VectorCraft opens files from the same working folder.

## 0. Load tools
PhotoCraft/VectorCraft tools are deferred: `ToolSearch select:` the ones you need (doc_open, command_run/batch, doc_save, render_preview; vectorcraft open_file, command_run, export, save_file, render_preview) before calling.

## 1. Clarify only what matters
- Which figure/region, and target colors (keep **original colors** unless told otherwise; recolor is trivial in vector later).
- Use bare filenames; if a name has odd characters (`%2D`, commas) try the cleaned name.

## 2. Prepare the trace source in PhotoCraft (the step that decides quality)
1. `doc_open` the original. `layer.new.layerFromBackground`.
2. `image.crop` to the one figure (`deleteCroppedPixels:false` if you want it non-destructive). Preview first to pick coordinates (preview is downscaled: multiply by width/preview width).
3. `image.imageSize {percent:300, resample:"preserveDetails"}` - upscale 3x so traced curves are smooth.
4. `filter.blur.surfaceBlur {radius:8, threshold:30}` **twice**. This removes fabric/noise texture while keeping outlines crisp. Skipping it gives speckled jeans and 18k-anchor mush.
5. Leave a solid chroma-key background (e.g. magenta) in place; exclude it in the trace. `doc_save` as PNG.
   - Do NOT flatten if the user wants layers; keep the cropped/masked PSD separately (mask via `select.magicWand` on key color + `layer.layerMask.hideSelection`; kill halo by `select.loadSelection mask` -> `select.modify.contract 3` -> delete mask -> `layer.layerMask.revealSelection`).

## 3. Trace in VectorCraft
1. `open_file` the PNG; find the image object id with `inspect_document depth:1`.
2. `imageTrace.make {id, preset:"16 Colors", params:{colors:14, noise:150, paths:60, corners:60, method:"overlapping", ignoreWhite:true, ignoreColor:"#ff00ff"}}`
   - **method must be `overlapping`**. `abutting` leaves hairline gaps between shapes that show as white strokes on print.
3. `imageTrace.expand {id:<trace id returned>}` (use the id from make's result, not the image id).
4. `object.path.simplify {tolerance:1.5}` acts on the current selection (expand selects the paths). Cuts anchors ~8x.
5. `render_preview max_side:2400`, inspect for seams, speckle, muddy small details.

## 4. Export
`export path:<name>.svg format:svg` and `save_file path:<name>.vectorcraft`. Don't overwrite earlier versions silently unless replacing a known-bad one.

## Known limits (tell the user)
- Auto-trace is not hand-drawn: tiny detail (shirt graphics, hair strands) stays rough. Offer hand cleanup, or fewer flat colors for screen printing.
- Preview is not a print-size check; say what was and wasn't verified.
- `colors` 14 / noise 150 worked on a ~2200x3700 px source (guy) and `colors` 16 / noise 150 on ~2550x3780 (robot); scale noise with source size.
- Texture such as rust, grime or speckle traces as mottled blobs at 14-16 colors. Offer fewer colors for a cleaner look or hand smoothing; don't hide it.
- Expect ~20k anchors after simplify for detailed art (robot: 134k -> 21k, ~1 MB SVG); ~14k for simpler art.

## Pitfalls seen
- Sprite sheets hold several poses: crop exactly the pose asked for ("second from left" = by position in the preview). Preview-to-pixel scale = doc width / preview width; leave margin so a neighbor's hand/shield isn't clipped in, and confirm the crop preview shows one figure.
- A rejected/interrupted batch may have partly run (e.g. upscale + blur applied). Check `session_list` (size, revision); if unsure, `doc_close` and reopen the original rather than stacking edits.
- In a fresh VectorCraft doc the image id was 2, but confirm with `inspect_document`; the trace id returned by `make` is different.
- Global color adjustments also shift the key background; select first. Color-range on near-neutral charcoal bleeds into hair/jeans/glasses - avoid recoloring before tracing.
- Tracing the 1x image gives blotchy results; always upscale + blur first.
- JPG cannot hold transparency: deliver PNG/PSD/SVG for cutouts.
