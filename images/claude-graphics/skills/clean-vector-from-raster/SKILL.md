---
name: clean-vector-from-raster
description: Turn a raster character/cartoon illustration (e.g. a sprite sheet on a chroma-key background) into a clean, print-ready SVG using PhotoCraft + VectorCraft MCP tools. Use for "crop one figure, remove background, vectorize for T-shirt/print", including whole sheets of cells.
---

# Clean vector from a raster illustration (PhotoCraft -> VectorCraft)

Proven workflow (about 100 cells from sprite sheets on a magenta key background: 6x2 grid sheets, and single-row framed sheets with 8 panels). Paths are relative to the PhotoCraft read/write roots (`/sandbox` in the claude-graphics image); VectorCraft opens files from the same working folder.

`layout.py`, `gaps.py` and `edge_check.py` need numpy and Pillow. Once per sandbox, in the working folder: `uv venv && uv pip install numpy pillow`; the commands below use that `.venv/bin/python`.

Run one cell at a time in one session. Do not run several agents against the same PhotoCraft/VectorCraft instance: they close each other's documents and trace into the wrong one (seen in a 2-agent test).

## 0. Load tools
PhotoCraft/VectorCraft tools are deferred: `ToolSearch select:` the ones you need (`mcp__photocraft__doc_open`, `command_run`, `command_batch`, `doc_save`, `render_preview`, `session_list`, `doc_close`; `mcp__vectorcraft__open_file`, `command_batch`, `export`, `save_file`, `render_preview`, `inspect_document`) before calling.
- `unzip` is not installed: extract with `python3 -m zipfile -e FILE.zip DIR`. Build zips with Python's `zipfile`, next to the output folder, not inside it.
- Create output and work folders first (`mkdir -p /sandbox/output /sandbox/work`): `doc_save` fails with NotFound if the folder is missing.
- Keep intermediates (cropped, keyed PNGs, raw traces) in `/sandbox/work`, and only the finished SVGs in `/sandbox/output`.

## 1. Clarify only what matters
- Which figure/region (or "all cells"), and target colors (keep **original colors** unless told otherwise; recolor is trivial in vector later).
- The user wants **none** of the background color in the output. Say so in the plan and check for it (step 2).
- Use bare filenames; if a name has odd characters (`%2D`, commas) try the cleaned name.
- Sheets: look at each one first (`Read` the PNG; the preview is downscaled, so multiply coordinates by original width / displayed width). **Do not assume the grid.** Sheets in one batch differ: 3168x1344 sheets were 6 columns x 2 rows (cells 528x672), while another was 8 panels in one row with a dark frame, 1040 px tall. Run the layout script on every sheet first:
  ```sh
  .venv/bin/python -I ~/.claude/skills/clean-vector-from-raster/layout.py SHEET.png
  ```
  It finds the dark frame or grid lines from the pixels and prints one crop box per panel (`x= y= w= h=`), already set in from the frame. **It only works on sheets with dark frame or grid lines** (sheets 8, 9, 10 and 17-style).
- **Sheets with no lines** (figures on a plain background, in one or more rows): use `gaps.py`. It splits the sheet into rows, then finds each figure from the background gaps between figures, and prints a box per figure with a small pad:
  ```sh
  .venv/bin/python -I ~/.claude/skills/clean-vector-from-raster/gaps.py SHEET.png
  ```
  Use those boxes in step 2. Overlapping figures (walking strips, figures touching each other) have no gap and come out as one box: crop those by hand from a view of the sheet, one pose per crop, and say so in the summary.

## 2. Prepare the trace source (the step that decides quality)
1. `doc_open` the original. In one `command_batch`: `layer.new.layerFromBackground`, `image.crop` to the one figure, `image.imageSize {percent:300, resample:"preserveDetails"}`, then `filter.blur.surfaceBlur {radius:8, threshold:30}` **twice**. This removes fabric/noise texture while keeping outlines crisp. Skipping it gives speckled jeans and 18k-anchor mush; tracing the 1x image gives blotchy results.
   - **Crop boxes: get them from `layout.py`, not from a fixed inset.** A fixed 8 px inset failed both ways in practice:
     - Figures often reach the frame (arms, feet, mohawks). An 8 px inset clipped them. Use the full interior, starting 1 px past each dark line.
     - On 6x2 grid sheets the dark grid line is about 8 px wide, and its anti-aliased edge runs 2-4 px further. Any part of it left in the crop stays as a dark strip. If `edge_check.py` reports a side touching, move that side inward 3-4 px and rebuild the cell.
     - If the first cell of a new layout shows a clipped figure or a strip along an edge, fix the box before running the rest of the sheet.
   - If the image would be larger than about 4000 px after upscaling (e.g. a single 2000x2000 bust), use 200%: keying and tracing a 6000 px image is very slow.
2. `doc_save` the result as `sheetN_cellNN_rgb.png` in `/sandbox/work` (still on the solid key background).
3. **Key the background out to transparency with a script, not in PhotoCraft.** In this environment `select.magicWand` at (2,2) followed by `edit.clear` or `layer.layerMask.hideSelection` cleared only a sliver of the background (27k of 1.5M pixels in the test cell). The exported PNG does keep alpha, so key it yourself:
   - **Use `graphics-key`** (`graphics-key --help`; it is on the PATH). Its default rule is the magenta **spill** rule: a pixel is background when `min(r, b) - g >= 30` and `min(r, b) >= 110`. Dark hair and outlines (`min(r,b) < 110`) are untouched.
     ```sh
     graphics-key bg   /sandbox/work/sheet1_cell*_rgb.png   # the background color of each file, and whether the rule removes it
     graphics-key key  /sandbox/work/sheet1_cell*_rgb.png   # writes sheet1_cellNN_key.png next to each (never overwrites the input)
     graphics-key check /sandbox/work/sheet1_cell*_key.png  # background pixels left; exit status 1 if any
     ```
   - **Do not use a strict key** (`r >= 200, b >= 200, g <= 60`). It works on pure `#ff00ff` but leaves the anti-aliased blend at hair edges (traced as a purple/pink fill: "pink left in the edge of the hair") and leaves **lighter magenta** backgrounds such as `#fc3efb` almost untouched (sheet 4: about 850,000 background pixels survived and traced as orange and purple fills). Backgrounds differ between sheets of the same batch, so run `graphics-key bg` on each sheet first.
   - **Do not lower `--spill` below 25.** A rule of `min(r,b) - g >= 12` ate edge detail, the trace got noisy, and the user rejected the result ("totally bad"); the tool warns about it.
   - **A different background** (green screen, blue, white): `bg` prints the command to use. Give a color and how far each of r, g, b may differ, or explicit ranges: `graphics-key key --color "#00ff00" --tolerance 50 FILE.png` or `--range "0-90,170-255,0-90"`. These replace the default rule in `key`, `check` and `strip`. A color range has no notion of blended edges: pixels between the background and the art stay, `check` counts them as "blended edge", and a larger `--tolerance` removes more of them (and more of the art), so render a sample.
   - **Large images:** with numpy and Pillow installed, `graphics-key` is faster, uses less memory and reads any PNG type (the built-in code handles only 8-bit RGB/RGBA and takes minutes on 8+ megapixel images; a tool call times out after about 2 minutes, so start long runs with `nohup ... > log 2>&1 &` and poll the log). Install them and run the tool with that Python: `uv venv && uv pip install numpy pillow && .venv/bin/python /usr/local/bin/graphics-key key ...`. Both give identical output (tested).
4. **Check the keyed PNG before tracing**:
   - `graphics-key check` must report `background 0` ("blended edge" pixels are the anti-aliased mix next to the art and are not an error). A check for pure `#ff00ff` only reports 0 for a lighter background that is still there, which is why `check` uses the same rule as `key`.
   - **Edge check**: `.venv/bin/python -I ~/.claude/skills/clean-vector-from-raster/edge_check.py KEYED.png`. It lists the sides where opaque pixels reach the crop edge. A side that touches is either a figure cut by the crop (fix the box) or a grid/frame line left in (move that side inward 3-4 px). Do not trace a cell with a touching side until it is resolved or noted as a real figure edge.
   - Render it. A cell with more than about 5,000 blended-edge pixels deserves a closer look at the hair/outline edges.
   - Do NOT flatten if the user wants layers; keep a cropped/masked PSD separately.

## 3. Trace in VectorCraft
1. `open_file` the keyed PNG; find the image object id with `inspect_document depth:1` (it was 2 in a fresh document, but not always).
2. `imageTrace.make {id, preset:"16 Colors", params:{colors:14, noise:150, paths:60, corners:60, method:"overlapping", ignoreWhite:true, ignoreColor:"#ff00ff"}}`
   - **method must be `overlapping`**. `abutting` leaves hairline gaps between shapes that show as white strokes on print.
3. `imageTrace.expand {id:<trace id returned by make>}` in a **separate** batch (a `$0.result.id` reference inside the same batch does not resolve).
4. `object.path.simplify {tolerance:1.5}` acts on the current selection (expand selects the paths). Cuts anchors ~4-8x.
5. `render_preview max_side:1200`, inspect for seams, speckle, muddy small details, and background color at hair edges.
6. Safety net, not a substitute for step 2: `graphics-key strip /sandbox/work/raw/*.svg --out-dir /sandbox/output` drops paths filled with magenta/pink spill (stricter than the key: `min(r,b) >= 120` and `min(r,b) - g >= 60`, so dark colors are never matched; `--color`/`--range` for another background). It reads `fill="#rrggbb"`, `#rgb`, `rgb(...)` and `style="fill:..."`, warns about fills it cannot read, and sets the SVG's title to its own name. It only catches pink-ish fills: leftover background that traced as orange or purple slips through, so a clean key comes first.

## 4. Export
`export path:<name>.svg format:svg` and `save_file path:<name>.vectorcraft`. Don't overwrite earlier versions silently unless replacing a known-bad one. Export the raw trace to `/sandbox/work/raw/`, run the strip script into `/sandbox/output/`, so a different cleanup can be tried without tracing again.

## Working through many cells
- Do **one cell first**, render it and get approval, then batch the rest with identical settings. Render at least one cell per sheet before rebuilding anything.
- If a fix changes the result for the whole set, test it on one cell and compare with the approved version before re-running everything. (A stronger re-key once made all 21 cells worse and had to be redone from the original keys.)
- Name outputs `sheetN_cellNN.svg`; a summary should say per sheet how many cells were done and which were **checked by eye** and which only by a color scan.

## Known limits (tell the user)
- Auto-trace is not hand-drawn: tiny detail (shirt graphics, hair strands) stays rough. Offer hand cleanup, or fewer flat colors for screen printing.
- Preview is not a print-size check; say what was and wasn't verified.
- `colors` 14 / noise 150 worked on a ~2200x3700 px source and `colors` 16 / noise 150 on ~2550x3780; scale noise with source size (sheets with 1.5x larger sources used noise 225, a guess that was not tested).
- Texture such as rust, grime or speckle traces as mottled blobs at 14-16 colors. Offer fewer colors for a cleaner look or hand smoothing; don't hide it.
- Expect ~7k-20k anchors after simplify for detailed art (about 1 MB SVG); ~14k for simpler art.
- Anything in the artwork that resembles the key color (a red offset outline, a magenta reflection in glasses, pink details) is removed or damaged by the key. Name those cells in the summary instead of silently dropping the detail.
- Pixelated or particle-dissolve art (many 1-pixel squares) loses colors under the spill key; check those cells by eye.

## Pitfalls seen
- Sprite sheets hold several poses: crop exactly the pose asked for ("second from left" = by position in the preview). Leave margin so a neighbor's hand/shield isn't clipped in, and confirm the crop preview shows one figure.
- MCP connections drop now and then (`Connection closed`, `timed out connecting`, then `no document open`). After a drop: `session_list`, reopen the original and redo the whole crop batch; a batch that was interrupted may have partly run (upscale + blur applied), so don't stack edits on a half-processed document. VectorCraft after a drop has an empty document: `open_file` again.
- In VectorCraft, `object.delete` does not exist; `edit.clear {ids:[...]}` deletes objects. The trace id returned by `make` is different from the image id.
- Global color adjustments also shift the key background; select first. Color-range on near-neutral charcoal bleeds into hair/jeans/glasses - avoid recoloring before tracing.
- JPG cannot hold transparency: deliver PNG/PSD/SVG for cutouts.
- `photocraft doc_close` with no index closes the **active** document, and the active one may not be the document you meant. Pass the index from `session_list`. A stray document left open from an earlier run is harmless, but check it is not the one being edited.
- Send `doc_save` only after the crop `command_batch` has returned. Running them in the same turn once let the save run before the batch had finished.
- `imageTrace.expand` followed by `object.path.simplify` must run in the same session as `make`. In the parallel-agent test they failed with "Simplify: select paths" and "no such object". After a failure, re-run `make` on a freshly opened keyed file rather than patching the failed step.
- The trace id from `make` changes for each cell and each run. Always use the id that `make` returned, not one from an earlier cell.
