# Report whether opaque (keyed-in) art touches each edge of a keyed cell PNG.
# Run with the venv python (numpy, Pillow): .venv/bin/python -I edge_check.py KEYED.png [...]
# Any side reported as touching means the crop cut the figure, or left a grid/frame line in it.
import sys
import numpy as np
from PIL import Image

for path in sys.argv[1:]:
    alpha = np.asarray(Image.open(path).convert('RGBA'))[..., 3] > 0
    sides = {
        'L': alpha[:, :4].sum(),
        'R': alpha[:, -4:].sum(),
        'T': alpha[:4].sum(),
        'B': alpha[-4:].sum(),
    }
    touching = ''.join(k for k, v in sides.items() if v)
    print(f"{path}  touching: {touching or 'none'}")
