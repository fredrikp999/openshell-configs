"""Tests for images/claude-graphics/graphics-key, run through its command line.

    GRAPHICS_KEY=path/to/graphics-key python3 test_graphics_key.py

Uses numpy and Pillow for the fast backend when they are installed, and always
tests the built-in code too (--pure).
"""
import importlib.machinery
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

TOOL = os.environ.get("GRAPHICS_KEY", os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../images/claude-graphics/graphics-key"))
loader = importlib.machinery.SourceFileLoader("graphics_key", TOOL)
spec = importlib.util.spec_from_loader("graphics_key", loader)
tool = importlib.util.module_from_spec(spec)
loader.exec_module(tool)
try:
    import numpy  # noqa: F401
    import PIL  # noqa: F401
    HAVE_FAST = True
except ImportError:
    HAVE_FAST = False

# name -> (r, g, b, alpha, what the default rule does)
PIXELS = {
    "pure":     ((255, 0, 255, 255), "removed"),     # #ff00ff
    "light":    ((252, 62, 251, 255), "removed"),    # #fc3efb, the lighter magenta of sheet 4
    "blend":    ((200, 90, 200, 255), "removed"),    # anti-aliased mix at an edge
    "hair":     ((30, 10, 30, 255), "kept"),         # dark: min(r,b) < 110
    "skin":     ((230, 180, 150, 255), "kept"),
    "outline":  ((200, 20, 40, 255), "kept"),        # red: min(r,b) < 110
    "fringe":   ((160, 140, 170, 255), "kept"),      # spill 20: counted as blended edge
    "clear":    ((255, 0, 255, 0), "kept"),          # already transparent
    "green":    ((0, 255, 0, 255), "kept"),          # a green-screen background
    "greenish": ((30, 230, 20, 255), "kept"),
}


def slurp(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


def spit(path, data):
    with open(path, "w" if isinstance(data, str) else "wb") as f:
        f.write(data)


def png(path, rows, alpha=True, depth=8, ctype=None):
    h, w = len(rows), len(rows[0])
    ctype = (6 if alpha else 2) if ctype is None else ctype
    raw = b""
    for row in rows:
        raw += b"\0" + b"".join(bytes(p if alpha else p[:3]) for p in row)

    def ch(k, d):
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, 0))
                + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))


def pixels(path):
    w, h, bpp, px = tool.read_png(path)
    assert bpp == 4, "expected RGBA"
    return [[tuple(px[(y * w + x) * 4:(y * w + x) * 4 + 4]) for x in range(w)] for y in range(h)]


class Base(unittest.TestCase):
    pure = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.rows = [[v[0] for v in PIXELS.values()]]
        self.src = self.path("sheet_rgb.png")
        png(self.src, self.rows)

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.dir, name)

    def run_tool(self, *args, expect=0):
        cmd = [sys.executable, TOOL] + list(args)
        if self.pure and args and args[0] in ("bg", "key", "check"):
            cmd.append("--pure")
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, expect, "args %s\nstdout: %s\nstderr: %s" % (args, p.stdout, p.stderr))
        return p


class DefaultRule(Base):
    def test_key_removes_magenta_and_keeps_the_art(self):
        p = self.run_tool("key", self.src)
        self.assertTrue(os.path.exists(self.path("sheet_key.png")), p.stdout)
        out = pixels(self.path("sheet_key.png"))[0]
        for (name, (px, what)), got in zip(PIXELS.items(), out):
            if what == "removed":
                self.assertEqual(got[3], 0, name)
            else:
                self.assertEqual(got, px, name)
        self.assertIn("3 background pixels made transparent", p.stdout)

    def test_input_without_alpha_gets_alpha(self):
        src = self.path("rgb_rgb.png")
        png(src, self.rows, alpha=False)
        self.run_tool("key", src)
        out = pixels(self.path("rgb_key.png"))[0]
        self.assertEqual([p[3] for p in out][:4], [0, 0, 0, 255])

    def test_check_passes_after_key_and_fails_before(self):
        self.run_tool("check", self.src, expect=1)
        self.run_tool("key", self.src)
        p = self.run_tool("check", self.path("sheet_key.png"))
        self.assertIn("background 0", p.stdout)
        self.assertIn("blended edge 1", p.stdout)   # the (160,140,170) pixel
        self.assertIn("OK", p.stdout)

    def test_check_max(self):
        self.run_tool("check", self.src, "--max", "3")
        self.run_tool("check", self.src, "--max", "2", expect=1)

    def test_a_pure_magenta_only_key_misses_light_magenta(self):
        # what the old strict key left behind, and what check must notice
        png(self.path("light_key.png"), [[(252, 62, 251, 255)] * 4])
        self.run_tool("check", self.path("light_key.png"), expect=1)

    def test_bg_says_whether_the_rule_catches_the_border(self):
        png(self.path("m.png"), [[(252, 62, 251, 255)] * 6] * 6)
        self.assertIn("removed by the current rule", self.run_tool("bg", self.path("m.png")).stdout)
        png(self.path("g.png"), [[(0, 255, 0, 255)] * 6] * 6)
        out = self.run_tool("bg", self.path("g.png")).stdout
        self.assertIn("NOT removed", out)
        self.assertIn('--color "#00ff00"', out)

    def test_spill_and_min_rb_options(self):
        # pure (spill 255) and light (189) go, the blended pixel (spill 110) stays at --spill 120
        self.run_tool("key", self.src, "--spill", "120", "-o", self.path("strict.png"))
        self.assertEqual([p[3] for p in pixels(self.path("strict.png"))[0]][:3], [0, 0, 255])
        # a high --min-rb keeps the blended pixel (min(r,b) = 200) too
        self.run_tool("key", self.src, "--min-rb", "210", "-o", self.path("high.png"))
        self.assertEqual([p[3] for p in pixels(self.path("high.png"))[0]][:3], [0, 0, 255])

    def test_low_spill_warns(self):
        p = self.run_tool("key", self.src, "--spill", "12", "-o", self.path("loose.png"))
        self.assertIn("below 25", p.stderr)


class Safety(Base):
    def test_never_overwrites_the_input(self):
        before = slurp(self.src, "rb")
        self.assertIn("overwrite", self.run_tool("key", self.src, "-o", self.src, expect=2).stderr)
        self.assertEqual(slurp(self.src, "rb"), before)
        # the default name for a keyed file is NAME_key.png: a file called that is not touched either
        keyed = self.path("a_key.png")
        png(keyed, self.rows)
        before = slurp(keyed, "rb")
        self.run_tool("key", keyed)
        self.assertEqual(slurp(keyed, "rb"), before)
        self.assertTrue(os.path.exists(self.path("a_key_key.png")))

    def test_in_place(self):
        self.run_tool("key", self.src, "--in-place")
        self.assertEqual(pixels(self.src)[0][0][3], 0)

    def test_out_dir_and_rgb_suffix(self):
        out = self.path("out")
        self.run_tool("key", self.src, "--out-dir", out)
        self.assertTrue(os.path.exists(os.path.join(out, "sheet_key.png")))

    def test_o_with_several_inputs(self):
        other = self.path("other_rgb.png")
        png(other, self.rows)
        self.run_tool("key", self.src, other, "-o", self.path("x.png"), expect=2)

    def test_unsupported_png_gives_a_clear_error(self):
        if not self.pure:
            self.skipTest("Pillow reads these")
        gray = self.path("gray.png")
        png(gray, [[(10,), (20,)]], alpha=False, ctype=0)
        # one byte per pixel for color type 0
        raw = b"\0\x10\x20"
        def ch(k, d):
            return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d))
        spit(gray, b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 0, 0, 0, 0))
                               + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))
        p = self.run_tool("key", gray, expect=2)
        self.assertIn("8-bit RGB and RGBA", p.stderr)
        sixteen = self.path("sixteen.png")
        spit(sixteen, b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 16, 2, 0, 0, 0))
                                  + ch(b"IDAT", zlib.compress(b"\0" + bytes(6))) + ch(b"IEND", b""))
        self.assertIn("16-bit", self.run_tool("key", sixteen, expect=2).stderr)

    def test_missing_and_damaged_files(self):
        self.assertIn("no such file", self.run_tool("key", self.path("nope.png"), expect=2).stderr)
        bad = self.path("bad.png")
        spit(bad, b"not a png")
        self.run_tool("key", bad, expect=2)


class OtherBackground(Base):
    def test_color_with_tolerance(self):
        self.run_tool("key", self.src, "--color", "#00ff00", "--tolerance", "50", "-o", self.path("g.png"))
        got = [p[3] for p in pixels(self.path("g.png"))[0]]
        names = list(PIXELS)
        self.assertEqual(got[names.index("green")], 0)
        self.assertEqual(got[names.index("greenish")], 0)       # (30,230,20) is within 50
        self.assertEqual(got[names.index("pure")], 255)         # magenta is no longer the background
        self.assertEqual(got[names.index("skin")], 255)

    def test_default_tolerance(self):
        self.run_tool("key", self.src, "--color", "#00ff00", "-o", self.path("g.png"))
        got = [p[3] for p in pixels(self.path("g.png"))[0]]
        self.assertEqual(got[list(PIXELS).index("greenish")], 0)  # within 40

    def test_range(self):
        self.run_tool("key", self.src, "--range", "0-90,170-255,0-90", "-o", self.path("r.png"))
        got = [p[3] for p in pixels(self.path("r.png"))[0]]
        self.assertEqual(got[list(PIXELS).index("green")], 0)
        self.assertEqual(got[list(PIXELS).index("pure")], 255)

    def test_check_with_a_custom_color(self):
        self.run_tool("check", self.src, "--color", "#00ff00", expect=1)
        self.run_tool("key", self.src, "--color", "#00ff00", "-o", self.path("g.png"))
        self.run_tool("check", self.path("g.png"), "--color", "#00ff00")

    def test_bad_combinations(self):
        for args in (["--color", "#00ff00", "--range", "0-1,0-1,0-1"],
                     ["--color", "#00ff00", "--spill", "40"],
                     ["--range", "0-1,0-1,0-1", "--min-rb", "100"],
                     ["--tolerance", "20"],
                     ["--color", "green-ish"],
                     ["--color", "#00ff00", "--tolerance", "300"],
                     ["--range", "10-5,0-1,0-1"],
                     ["--range", "0-1,0-1"]):
            self.assertTrue(self.run_tool("key", self.src, *args, expect=2).stderr, args)


class Svg(Base):
    SVG = ('<svg xmlns="http://www.w3.org/2000/svg"><title>sheet1_cell01_key.png</title>'
           '<path d="M0 0" fill="#ff00ff"/>'                       # 1 self-closing
           '<path d="M1 1" fill="#fc3efb"></path>'                 # 2 open/close
           '<path d="M2 2" style="fill:#e040e0;stroke:none"/>'     # 3 style
           '<path d="M3 3" fill="#f0f"/>'                          # 4 3-digit
           '<path d="M4 4" fill="rgb(250,60,250)"/>'               # 5 rgb()
           '<path fill="#fc3efb" d="M5 5"/>'                       # 6 fill before d
           '<path d="M6 6" fill="#301030"/>'                       # kept: dark
           '<path d="M7 7" fill="#e6b496"/>'                       # kept: skin
           '<path d="M8 8" fill="none"/>'                          # kept
           '<path d="M9 9" fill="url(#g)"/>'                       # kept
           '<path d="M10 10" fill="salmon"/>'                      # kept, not understood
           '<path d="M11 11" fill="#00ff00"/>'                     # kept by the default
           '<path d="M12 12" fill="#ff00ff" fill-opacity="0.5"/>'  # 7 removed
           '</svg>')

    def setUp(self):
        super().setUp()
        self.svg = self.path("raw.svg")
        spit(self.svg, self.SVG)

    def test_strip_removes_every_spelling_and_keeps_the_rest(self):
        p = self.run_tool("strip", self.svg, "-o", self.path("sheet1_cell01.svg"))
        out = slurp(self.path("sheet1_cell01.svg"))
        self.assertIn("removed 7 paths", p.stdout)
        for kept in ("#301030", "#e6b496", 'fill="none"', "url(#g)", "salmon", "#00ff00"):
            self.assertIn(kept, out)
        for gone in ("#ff00ff", "#fc3efb", "#e040e0", "#f0f", "rgb(250"):
            self.assertNotIn(gone, out)
        self.assertIn("salmon", p.stderr)                     # warned about a fill it could not read
        self.assertIn("<title>sheet1_cell01</title>", out)    # not the PNG's name

    def test_strip_default_name_and_no_overwrite(self):
        self.run_tool("strip", self.svg)
        self.assertTrue(os.path.exists(self.path("raw_clean.svg")))
        self.assertEqual(slurp(self.svg), self.SVG)
        self.run_tool("strip", self.svg, "-o", self.svg, expect=2)
        self.run_tool("strip", self.svg, "--out-dir", self.dir, expect=2)    # same name, same folder
        self.assertEqual(slurp(self.svg), self.SVG)

    def test_strip_custom_color(self):
        self.run_tool("strip", self.svg, "--color", "#00ff00", "--tolerance", "10", "-o", self.path("g.svg"))
        out = slurp(self.path("g.svg"))
        self.assertNotIn("#00ff00", out)
        self.assertIn("#ff00ff", out)


@unittest.skipUnless(HAVE_FAST, "numpy and Pillow are not installed")
class FastBackend(Base):
    pure = False

    def test_same_result_as_the_built_in_code(self):
        import random
        rnd = random.Random(7)
        rows = [[(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256), rnd.choice((0, 255, 255, 255)))
                 for _ in range(60)] for _ in range(40)]
        rows[0][:20] = [(255, 0, 255, 255)] * 20
        src = self.path("big_rgb.png")
        png(src, rows)
        for extra in ([], ["--spill", "50", "--min-rb", "90"], ["--color", "#c8c8c8", "--tolerance", "60"],
                      ["--range", "0-120,100-255,0-120"]):
            a, b = self.path("fast.png"), self.path("pure.png")
            self.run_tool("key", src, *extra, "-o", a)
            subprocess.run([sys.executable, TOOL, "key", src, *extra, "--pure", "-o", b], check=True, capture_output=True)
            self.assertEqual(pixels(a), pixels(b), extra)
            fa = self.run_tool("check", a, *extra).stdout.split("  ", 1)[1]
            fb = subprocess.run([sys.executable, TOOL, "check", a, *extra, "--pure"], capture_output=True, text=True).stdout.split("  ", 1)[1]
            self.assertEqual(fa, fb, extra)

    def test_reads_other_png_types(self):
        from PIL import Image
        Image.new("L", (4, 4), 128).save(self.path("gray_rgb.png"))
        Image.new("RGB", (4, 4), (255, 0, 255)).save(self.path("p_rgb.png"))
        self.run_tool("key", self.path("gray_rgb.png"))
        self.run_tool("key", self.path("p_rgb.png"))
        self.assertEqual(pixels(self.path("p_key.png"))[0][0][3], 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
