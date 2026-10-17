#!/usr/bin/env python3
"""Build one standalone HTML page from the README, the docs and example files.

  bin/build-html.py [OUT]        (or: make html)

Writes OUT (default: openshell-configs.html in the repo root, ignored by git):
the README and docs/*.md, then the policies, provider profiles and the
claude-sandbox and opencode-sandbox images as highlighted files, with a
sidebar, links between the docs turned into links within the page, and an
Auto/Light/Dark theme switch. Links to other repo files go to GitHub, at the
repo of the `origin` remote. Needs pandoc (brew install pandoc).
"""
import html
import os
import posixpath
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "openshell-configs.html")
if len(sys.argv) > 2 or OUT in ("-h", "--help"):
    sys.exit(__doc__.strip())
if not shutil.which("pandoc"):
    sys.exit("pandoc not found. Install it with: brew install pandoc")


def github_url():
    """https://github.com/OWNER/REPO for the origin remote, from SSH or HTTPS form."""
    url = subprocess.run(["git", "-C", REPO, "remote", "get-url", "origin"],
                         capture_output=True, text=True).stdout.strip()
    m = re.match(r"^(?:git@github\.com:|https://github\.com/)(.+?)(?:\.git)?/?$", url)
    return "https://github.com/" + m.group(1) if m else "https://github.com/fredrikp999/openshell-configs"


GITHUB = github_url()

# Written as HTML, with diagrams; shown first, after the README.
CONCEPTS = "docs/concepts.html"
DOCS = ["README.md", "docs/setup.md", "docs/agents.md", "docs/working-in-sandboxes.md",
        "docs/extras.md", "docs/customizing.md", "docs/logging.md", "docs/isolation.md",
        "docs/troubleshooting.md"]
FILE_GROUPS = [
    ("Policies", "policies", ["vscode-terminal.yaml", "example.yaml", "browser.yaml",
                              "hyperframes.yaml", "graphics.yaml", "antigravity.yaml"]),
    ("Provider profiles", "providers", ["claude-code-oauth.yaml", "openrouter.yaml"]),
    ("Image: claude-sandbox", "images/claude-sandbox", ["Dockerfile", "claude-start",
                                                        "claude-acp-start", "claude-start.json"]),
    ("Image: opencode-sandbox", "images/opencode-sandbox", ["Dockerfile"]),
]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def doc_key(path):
    return "readme" if path == "README.md" else slug(os.path.basename(path)[:-3])


def file_anchor(path):
    return "file-" + slug(path)


DOC_KEYS = {p: doc_key(p) for p in DOCS}
DOC_KEYS[CONCEPTS] = "concepts"
FILES = {posixpath.join(d, f) for _, d, fs in FILE_GROUPS for f in fs}
DIRS = {d: posixpath.join(d, fs[0]) for _, d, fs in FILE_GROUPS}
DIR_SECTIONS = {"policies": "group-policies", "providers": "group-provider-profiles"}


def run(cmd, data):
    return subprocess.run(cmd, input=data, capture_output=True, text=True, check=True).stdout


def resolve(href, doc):
    """Map a link in a doc to an anchor on this page, or to GitHub."""
    if re.match(r"^[a-z]+:", href):
        return href
    path, _, frag = href.partition("#")
    key = DOC_KEYS[doc]
    if not path:
        return "#%s--%s" % (key, frag)
    target = posixpath.normpath(posixpath.join(posixpath.dirname(doc), path)).rstrip("/")
    if target in DOC_KEYS:
        k = DOC_KEYS[target]
        return "#%s--%s" % (k, frag) if frag else "#doc-" + k
    if target in FILES:
        return "#" + file_anchor(target)
    if target in DIR_SECTIONS:
        return "#" + DIR_SECTIONS[target]
    if target in DIRS:
        return "#" + file_anchor(DIRS[target])
    kind = "tree" if os.path.isdir(os.path.join(REPO, target)) else "blob"
    return "%s/%s/main/%s%s" % (GITHUB, kind, target, "#" + frag if frag else "")


def convert_doc(doc):
    md = open(os.path.join(REPO, doc), encoding="utf-8").read()
    out = run(["pandoc", "-f", "gfm", "-t", "html5", "--wrap=none"], md)
    key = DOC_KEYS[doc]
    out = re.sub(r'\bid="([^"]+)"', lambda m: 'id="%s--%s"' % (key, m.group(1)), out)

    def fix_href(m):
        new = resolve(html.unescape(m.group(1)), doc)
        ext = "" if new.startswith("#") else ' target="_blank" rel="noopener"'
        return 'href="%s"%s' % (html.escape(new, quote=True), ext)
    out = re.sub(r'href="([^"]+)"', fix_href, out)
    # Wide tables scroll inside their own box.
    out = out.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", out, re.S)
    title = re.sub(r"<[^>]+>", "", h1.group(1)) if h1 else doc
    h2s = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', out, re.S)
    return title, h2s, out


def convert_fragment(path, key):
    """A hand-written HTML page (docs/concepts.html) with inline SVG diagrams.

    <pre data-lang="bash"> blocks are syntax-highlighted like the code in the
    Markdown docs; ids get the page prefix; links between docs are resolved.
    """
    out = open(os.path.join(REPO, path), encoding="utf-8").read()

    def code(m):
        text = html.unescape(m.group(2)).rstrip("\n")
        md = "````%s\n%s\n````\n" % (m.group(1), text)
        out = run(["pandoc", "-f", "gfm", "-t", "html5", "--wrap=none"], md)
        return re.sub(r'\s(?:id|href)="#?cb[\w-]*"', "", out)
    out = re.sub(r'<pre data-lang="(\w+)">(.*?)</pre>', code, out, flags=re.S)
    out = re.sub(r'<(h[12]) id="concepts--([^"]+)"', r'<\1 id="%s--\2"' % key, out)
    out = re.sub(r'href="([^"]+)"', lambda m: 'href="%s"' % html.escape(
        resolve(html.unescape(m.group(1)), path) if not m.group(1).startswith("#") else m.group(1),
        quote=True), out)
    out = out.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    title = re.sub(r"<[^>]+>", "", re.search(r"<h1[^>]*>(.*?)</h1>", out, re.S).group(1))
    return title, re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', out, re.S), out


def lang_of(path):
    name = os.path.basename(path)
    if name == "Dockerfile":
        return "dockerfile"
    ext = os.path.splitext(name)[1]
    if ext in (".yaml", ".yml"):
        return "yaml"
    if ext == ".json":
        return "json"
    return "bash"


def convert_file(path):
    text = open(os.path.join(REPO, path), encoding="utf-8").read().rstrip("\n")
    fence = "````"
    md = "%s%s\n%s\n%s\n" % (fence, lang_of(path), text, fence)
    out = run(["pandoc", "-f", "gfm", "-t", "html5", "--wrap=none"], md)
    pre = file_anchor(path)
    out = re.sub(r'\bid="([^"]+)"', lambda m: 'id="%s--%s"' % (pre, m.group(1)), out)
    return re.sub(r'href="#([^"]+)"', lambda m: 'href="#%s--%s"' % (pre, m.group(1)), out)


def highlight_css():
    probe = run(["pandoc", "-f", "gfm", "-t", "html5", "-s", "--metadata", "title=x"],
                "```bash\necho hi\n```\n")
    css = "\n".join(re.findall(r"<style>(.*?)</style>", probe, re.S))
    # Keep only the syntax-highlighting rules (they all mention sourceCode or a token class).
    return "\n".join(r for r in re.findall(r"[^{}]+\{[^{}]*\}", css)
                     if "sourceCode" in r or re.search(r"code span\.", r))


commit = run(["git", "-C", REPO, "log", "-1", "--format=%h %cs"], "").strip()

sections, toc = [], []
for doc in [DOCS[0], CONCEPTS] + DOCS[1:]:
    title, h2s, body = (convert_fragment(doc, "concepts") if doc == CONCEPTS else convert_doc(doc))
    key = DOC_KEYS[doc]
    # The Concepts chapter exists only on this page, so it has no source link above its title.
    path = "" if doc == CONCEPTS else ('<p class="path"><a href="%s/blob/main/%s" target="_blank" '
                                       'rel="noopener">%s</a></p>' % (GITHUB, doc, doc))
    sections.append('<section class="doc" id="doc-%s">%s\n%s</section>' % (key, path, body))
    sub = "".join('<li><a href="#%s">%s</a></li>' % (i, re.sub(r"<[^>]+>", "", t)) for i, t in h2s)
    toc.append('<li><a href="#doc-%s">%s</a>%s</li>' % (key, html.escape(title),
                                                        "<ul>%s</ul>" % sub if sub else ""))

file_toc = []
for label, d, names in FILE_GROUPS:
    gid = "group-" + slug(label)
    parts = ['<section class="files" id="%s"><h1>%s</h1>' % (gid, html.escape(label))]
    items = []
    for n in names:
        p = posixpath.join(d, n)
        parts.append('<h2 id="%s"><code>%s</code> <a class="gh" href="%s/blob/main/%s" '
                     'target="_blank" rel="noopener">GitHub</a></h2>%s'
                     % (file_anchor(p), p, GITHUB, p, convert_file(p)))
        items.append('<li><a href="#%s"><code>%s</code></a></li>' % (file_anchor(p), n))
    parts.append("</section>")
    sections.append("\n".join(parts))
    file_toc.append('<li><a href="#%s">%s</a><ul>%s</ul></li>' % (gid, html.escape(label), "".join(items)))

CSS = """
:root { --bg:#ffffff; --fg:#1f2328; --muted:#59636e; --border:#d1d9e0; --code-bg:#f6f8fa;
        --link:#0969da; --side-bg:#f6f8fa; --accent:#0969da;
        --ok:#1a7f37; --bad:#cf222e; --acc-bg:#ddf4ff; --ok-bg:#dafbe1; --bad-bg:#ffebe9; --note-bg:#fff8c5; }
/* Dark: chosen with the switch, or Auto and the system is dark. */
:root[data-theme="dark"] { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --border:#3d444d; --code-bg:#151b23;
        --link:#4493f8; --side-bg:#010409; --accent:#4493f8; color-scheme:dark;
        --ok:#3fb950; --bad:#f85149; --acc-bg:#0c2d4d; --ok-bg:#0f2f1b; --bad-bg:#3d1a1c; --note-bg:#2e2a10; }
:root[data-theme="dark"] code span { filter: brightness(1.45) saturate(0.9); }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme]) { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --border:#3d444d; --code-bg:#151b23;
          --link:#4493f8; --side-bg:#010409; --accent:#4493f8; color-scheme:dark;
          --ok:#3fb950; --bad:#f85149; --acc-bg:#0c2d4d; --ok-bg:#0f2f1b; --bad-bg:#3d1a1c; --note-bg:#2e2a10; }
  :root:not([data-theme]) code span { filter: brightness(1.45) saturate(0.9); }
}
.theme { display:flex; gap:2px; margin:0 0 1rem; padding:2px; border:1px solid var(--border);
         border-radius:6px; background:var(--bg); }
.theme button { flex:1; font:inherit; font-size:12px; padding:.25rem 0; border:0; border-radius:4px;
                background:none; color:var(--muted); cursor:pointer; }
.theme button:hover { color:var(--fg); }
.theme button[aria-pressed="true"] { background:var(--border); color:var(--fg); font-weight:600; }
* { box-sizing: border-box; }
html { scroll-padding-top: 1rem; }
body { margin:0; background:var(--bg); color:var(--fg);
       font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
nav { position:fixed; top:0; left:0; bottom:0; width:300px; overflow-y:auto; padding:1.25rem 1rem 2rem;
      background:var(--side-bg); border-right:1px solid var(--border); font-size:14px; }
nav .brand { font-weight:600; font-size:16px; margin:0 0 .25rem; }
nav .meta { color:var(--muted); font-size:12px; margin:0 0 1rem; }
nav h3 { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:1.25rem 0 .4rem; }
nav ul { list-style:none; margin:0; padding:0; }
nav ul ul { padding-left:.85rem; margin:.15rem 0 .5rem; border-left:1px solid var(--border); }
nav li { margin:.1rem 0; }
nav a { color:var(--fg); text-decoration:none; display:block; padding:.1rem .3rem; border-radius:4px; }
nav ul ul a { color:var(--muted); }
nav a:hover { background:var(--border); }
nav a.active { color:var(--accent); font-weight:600; }
main { margin-left:300px; padding:2rem 3rem 6rem; max-width:1100px; }
section { border-bottom:1px solid var(--border); padding-bottom:2.5rem; margin-bottom:2.5rem; }
.path { font-size:13px; color:var(--muted); margin:0; }
.path a, a.gh { color:var(--muted); }
a.gh { font-size:13px; font-weight:400; margin-left:.5rem; }
h1 { font-size:2rem; margin:.3rem 0 1rem; padding-bottom:.3rem; border-bottom:1px solid var(--border); }
h2 { font-size:1.45rem; margin:2rem 0 .75rem; padding-bottom:.25rem; border-bottom:1px solid var(--border); }
h3 { font-size:1.15rem; margin:1.6rem 0 .5rem; }
h4 { font-size:1rem; margin:1.3rem 0 .4rem; }
a { color:var(--link); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:.875em;
       background:var(--code-bg); padding:.15em .35em; border-radius:5px; }
pre { background:var(--code-bg); border:1px solid var(--border); border-radius:6px; padding:.9rem 1rem;
      overflow-x:auto; line-height:1.45; }
pre code, pre > code.sourceCode { background:none; padding:0; font-size:13px; white-space:pre !important; }
div.sourceCode { margin:1rem 0; }
.table-wrap { overflow-x:auto; margin:1rem 0; }
table { border-collapse:collapse; font-size:14px; }
th, td { border:1px solid var(--border); padding:.4rem .7rem; text-align:left; vertical-align:top; }
th { background:var(--code-bg); }
blockquote { margin:1rem 0; padding:0 1rem; color:var(--muted); border-left:.25em solid var(--border); }
/* Diagrams on the Concepts page */
figure.diagram { margin:1.25rem 0 1.75rem; padding:1rem; border:1px solid var(--border); border-radius:8px;
                 background:var(--bg); }
figure.diagram figcaption { margin-top:.6rem; font-size:14px; color:var(--muted); }
svg.dg { display:block; width:100%; height:auto; }
svg.dg text { fill:var(--fg); font:13px -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
svg.dg text.b { font-weight:600; }
svg.dg text.s { fill:var(--muted); font-size:11.5px; }
svg.dg text.m { font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:11px; }
svg.dg text.ok-t { fill:var(--ok); font-size:11.5px; font-weight:600; }
svg.dg text.bad-t { fill:var(--bad); font-size:11.5px; font-weight:600; }
svg.dg .box { fill:var(--code-bg); stroke:var(--border); stroke-width:1.5; }
svg.dg .chip { fill:var(--bg); stroke:var(--border); stroke-width:1.2; }
svg.dg .acc { fill:var(--acc-bg); stroke:var(--accent); }
svg.dg .okbox { fill:var(--ok-bg); stroke:var(--ok); }
svg.dg .badbox { fill:var(--bad-bg); stroke:var(--bad); }
svg.dg .note { fill:var(--note-bg); stroke:var(--border); }
svg.dg .zone { fill:none; stroke:var(--border); stroke-width:1.5; stroke-dasharray:6 5; }
svg.dg .zone.vm { fill:var(--side-bg); }
svg.dg .ring { stroke:var(--border); stroke-width:1.5; }
svg.dg .r1 { fill:var(--side-bg); } svg.dg .r2 { fill:var(--code-bg); } svg.dg .r3 { fill:var(--side-bg); }
svg.dg .r4 { fill:var(--acc-bg); stroke:var(--accent); } svg.dg .r5 { fill:var(--bg); stroke:var(--fg); }
svg.dg .arrow { fill:none; stroke:var(--muted); stroke-width:1.8; }
svg.dg .arrow.ok { stroke:var(--ok); } svg.dg .arrow.bad { stroke:var(--bad); }
svg.dg .dash { stroke-dasharray:6 4; }
svg.dg .life { stroke:var(--border); stroke-width:1.5; stroke-dasharray:3 4; }
svg.dg .cross { stroke:var(--bad); stroke-width:3; stroke-linecap:round; }
svg.dg .dot { fill:var(--fg); }
svg.dg .agentbox { fill:var(--ok-bg); stroke:var(--ok); stroke-width:2.5; }
svg.dg text.ag { font-size:15px; letter-spacing:.06em; }
svg.dg .mk { fill:var(--muted); }
svg.dg .num { fill:var(--accent); }
svg.dg text.n { fill:#fff; font-size:11px; font-weight:700; text-anchor:middle; }
ol.legend { margin:.5rem 0 1.5rem; padding-left:1.4rem; font-size:15px; }
ol.legend li { margin:.3rem 0; }
.cards { display:grid; gap:1rem; margin:1rem 0; }
.cards.three { grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); }
.card { border:1px solid var(--border); border-radius:8px; padding:.75rem 1rem; background:var(--bg); min-width:0; }
.card .tag { font-size:12px; font-weight:600; letter-spacing:.03em; text-transform:uppercase; color:var(--accent); }
.card p { margin:.4rem 0; font-size:14px; }
.card div.sourceCode { margin:.5rem 0; }
.card pre { font-size:12px; }
.note-line { color:var(--muted); }
td div.sourceCode { margin:.2rem 0; }
@media (max-width: 900px) {
  nav { position:static; width:auto; border-right:none; border-bottom:1px solid var(--border); }
  main { margin-left:0; padding:1.25rem; }
}
@media print { nav { display:none; } main { margin:0; max-width:none; } }
"""

JS = """
const themeButtons = [...document.querySelectorAll('.theme button')];
function showTheme() {
  const t = document.documentElement.dataset.theme || 'auto';
  themeButtons.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.theme === t)));
}
themeButtons.forEach(b => b.addEventListener('click', () => {
  const t = b.dataset.theme;
  if (t === 'auto') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  try { t === 'auto' ? localStorage.removeItem('theme') : localStorage.setItem('theme', t); } catch (e) {}
  showTheme();
}));
showTheme();
const links = [...document.querySelectorAll('nav a[href^="#"]')];
const byId = new Map(links.map(a => [a.getAttribute('href').slice(1), a]));
const targets = [...byId.keys()].map(id => document.getElementById(id)).filter(Boolean);
let current;
function update() {
  let best = targets[0];
  for (const t of targets) { if (t.getBoundingClientRect().top <= 80) best = t; else break; }
  const a = best && byId.get(best.id);
  if (a !== current) {
    if (current) current.classList.remove('active');
    if (a) { a.classList.add('active'); a.scrollIntoView({block: 'nearest'}); }
    current = a;
  }
}
targets.sort((x, y) => x.compareDocumentPosition(y) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1);
document.addEventListener('scroll', update, {passive: true});
update();
"""

page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OpenShell configs</title>
<script>
// Apply the saved theme before the page is drawn, so it doesn't flash.
try { const t = localStorage.getItem('theme'); if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; } catch (e) {}
</script>
<style>%s
%s</style>
</head>
<body>
<nav>
<p class="brand">OpenShell configs</p>
<p class="meta">Built from <a href="%s">%s</a> at commit %s</p>
<div class="theme" role="group" aria-label="Color theme">
<button type="button" data-theme="auto" title="Follow the system setting">Auto</button>
<button type="button" data-theme="light">Light</button>
<button type="button" data-theme="dark">Dark</button>
</div>
<h3>Documentation</h3>
<ul>%s</ul>
<h3>Example files</h3>
<ul>%s</ul>
</nav>
<main>
%s
</main>
<script>%s</script>
</body>
</html>
""" % (CSS, highlight_css(), GITHUB, GITHUB.replace("https://", ""), html.escape(commit),
       "".join(toc), "".join(file_toc), "\n".join(sections), JS)

open(OUT, "w", encoding="utf-8").write(page)
print("wrote %s (%d KB)" % (OUT, len(page.encode()) // 1024))
