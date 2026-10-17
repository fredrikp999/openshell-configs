# Print crop boxes (x y w h) for each panel of a sprite sheet: the full interior between the dark
# frame/grid lines, starting 1 px past each line. Use edge_check.py on the keyed cell to catch line residue.
# Usage: .venv/bin/python -I layout.py SHEET.png   (needs numpy, Pillow)
import sys
import numpy as np
from PIL import Image

im = np.asarray(Image.open(sys.argv[1]).convert('RGB')).astype(int)
h, w, _ = im.shape
dark = im.sum(2) < 200

def runs(idx):
    out, start, prev = [], None, None
    for i in idx:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            out.append((start, prev)); start = prev = i
    if start is not None:
        out.append((start, prev))
    return out

def lines(frac):
    return [i for i in range(len(frac)) if frac[i] > 0.5]

# A frame line is a run of dark pixels covering over half of the other axis
col_lines = runs(lines(dark.mean(0)))
row_lines = runs(lines(dark.mean(1)))
# Interior spans = gaps between consecutive line runs
def interiors(rs, size):
    spans = []
    edges = [(-1, -1)] + rs + [(size, size)]
    for (a, b), (c, d) in zip(edges[:-1], edges[1:]):
        lo, hi = b + 1, c - 1
        if lo > 0 and hi < size - 1 and hi - lo > 40:
            spans.append((lo, hi))
    return spans

cols = interiors(col_lines, w)
rows = interiors(row_lines, h)
print('panels', len(cols), 'x', len(rows), 'rows')
n = 0
for (ry0, ry1) in rows:
    for (cx0, cx1) in cols:
        n += 1
        x, y = cx0 + 1, ry0
        print(f'cell {n:02d} x={x} y={y} w={cx1 - cx0 - 1} h={ry1 - ry0 + 1}')
