# Suggest crop boxes for sheets WITHOUT frame lines: finds runs of figure columns separated by
# background gaps. Usage: .venv/bin/python -I gaps.py SHEET.png [--gap 6] [--pad 4]
# Prints one box per run: x y w h (the figure's extent plus a pad). Check each box visually and with
# edge_check.py; figures that overlap in x have no gap and come out as one run (crop those by hand).
import argparse
import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument('sheet')
ap.add_argument('--gap', type=int, default=6, help='background columns that separate two figures')
ap.add_argument('--pad', type=int, default=4, help='pixels added around each figure box')
ap.add_argument('--min-width', type=int, default=60, help='ignore runs narrower than this')
args = ap.parse_args()

im = np.asarray(Image.open(args.sheet).convert('RGB')).astype(int)
h, w, _ = im.shape
magenta = (np.minimum(im[..., 0], im[..., 2]) - im[..., 1] >= 30) & (np.minimum(im[..., 0], im[..., 2]) >= 110)
art = ~magenta & (im.sum(2) < 740)  # not key colour, and not pure white margin

def runs_of(profile):
    """Start/end indices of non-zero runs in profile, joining runs separated by fewer than --gap zeros."""
    out, start, last, gap = [], None, None, 0
    for i, v in enumerate(profile):
        if v:
            if start is None:
                start = i
            last, gap = i, 0
        elif start is not None:
            gap += 1
            if gap >= args.gap:
                out.append((start, last))
                start, gap = None, 0
    if start is not None:
        out.append((start, last))
    return out

# Split into horizontal bands (rows of figures), then find the figures in each band by columns.
boxes = []
for y0b, y1b in runs_of(art.sum(1) > 0):
    if y1b - y0b + 1 < args.min_width:
        continue
    band = art[y0b:y1b + 1]
    for x0, x1 in runs_of(band.sum(0) > 0):
        if x1 - x0 + 1 < args.min_width:
            continue
        rows = np.where(band[:, x0:x1 + 1].any(1))[0]
        fy0, fy1 = y0b + rows.min(), y0b + rows.max()
        boxes.append((x0, fy0, x1, fy1))

n = 0
for x0, y0, x1, y1 in sorted(boxes, key=lambda b: (b[1] // 400, b[0])):
    n += 1
    bx, by = max(x0 - args.pad, 0), max(y0 - args.pad, 0)
    bw = min(x1 + args.pad, w - 1) - bx + 1
    bh = min(y1 + args.pad, h - 1) - by + 1
    print(f'fig {n:02d} x={bx} y={by} w={bw} h={bh}   (art x {x0}-{x1}, y {y0}-{y1})')
print(f'{n} figure runs')
