"""The specifications on entrylib.org (portal issue #46): each one as a page and as plain text, from the Markdown that
ships with the installed claimset package (from the baseline on).

    /spec/                                   every specification
    /spec/claimset, /spec/claimset/0.40      the current version, a given version (+ .md: the text)
    /spec/lab-record/<v>, /spec/revision/<v>
    /spec/extensions, /spec/extensions/<name>, /spec/extensions/<name>/<v>

Written by the indexer when the app starts, so a new claimset release publishes its specifications.
"""

import re
from importlib import resources
from pathlib import Path

from . import markdown

KINDS = {"claimset": ("claimset", "Claimset"), "lab-record": ("lab-record", "Lab record"),
         "claimset-revision": ("revision", "Revision of published claimsets")}
FILE = re.compile(r"^(?P<name>[a-z][a-z0-9-]*?)-v(?P<version>\d+\.\d+)\.md$")
#: Headings left out of the contents: the change history at the top of each specification.
HISTORY = re.compile(r"^Changes in v")


def spec_dir():
    return Path(str(resources.files("claimset") / "data" / "spec"))


def _version_key(v):
    return tuple(int(x) for x in v.split("."))


def catalogue(root=None):
    """{address: {title, versions: {version: file}, current}}, address `claimset`, `extensions/qualitative`..."""
    root = Path(root) if root else spec_dir()
    found = {}
    for folder, prefix in ((root, ""), (root / "extensions", "extensions/")):
        if not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.md")):
            m = FILE.match(f.name)
            if not m:
                continue
            if prefix:
                address, label = prefix + m["name"], m["name"].replace("-", " ").capitalize()
            elif m["name"] in KINDS:
                address, label = KINDS[m["name"]]
            else:
                continue
            entry = found.setdefault(address, {"label": label, "versions": {}})
            entry["versions"][m["version"]] = f
    for entry in found.values():
        entry["current"] = max(entry["versions"], key=_version_key)
        entry["title"] = _title(entry["versions"][entry["current"]])
    return found


def _title(f):
    first = f.read_text(encoding="utf-8").split("\n", 1)[0]
    return first.lstrip("# ").strip() or f.stem


def _contents(headings):
    items = [(level, anchor, title) for level, anchor, title in headings
             if level in (2, 3) and not HISTORY.match(title)]
    rows = "".join(f'<li class="toc-l{level}"><a href="#{markdown.esc(anchor)}">{markdown.inline(title)}</a></li>'
                   for level, anchor, title in items)
    return (f'<nav class="cs-toc spec-toc" aria-label="Contents"><p class="cs-toc-title">Contents</p><ol>{rows}</ol>'
            "</nav>")


def page(shell, address, entry, version):
    """The page of one version of a specification, in the site's `shell`."""
    f = entry["versions"][version]
    body, headings = markdown.convert(f.read_text(encoding="utf-8"))
    current = version == entry["current"]
    others = [v for v in sorted(entry["versions"], key=_version_key, reverse=True) if v != version]
    links = " · ".join(f'<a href="/spec/{address}/{v}">{v}</a>' for v in others)
    text = f"/spec/{address}/{version}.md"
    meta = [f"Version {version}" + (" (current)" if current else
                                    f' · <a href="/spec/{address}">current: {entry["current"]}</a>'),
            f'<a href="{text}">Plain text</a>']
    if links:
        meta.append(f"Other versions: {links}")
    main = (f'<div class="wrap spec"><p class="entry-top"><a href="/spec/">Specifications</a> · '
            f'{" · ".join(meta)}</p><div class="cs-layout">{_contents(headings)}'
            f'<article class="spec-body prose-like">{body}</article></div></div>')
    head = f'<link rel="alternate" type="text/markdown" href="{text}">'
    canonical = f"/spec/{address}" if current else f"/spec/{address}/{version}"
    return shell(entry["title"], main, head=head, canonical=canonical, script="/toc.js",
                 description=f"{entry['label']} specification, version {version}.")


def index(shell, cat, root=None):
    root = Path(root) if root else spec_dir()
    rows = []
    for address in sorted(cat, key=lambda a: (a.startswith("extensions/"), a)):
        e = cat[address]
        older = [v for v in sorted(e["versions"], key=_version_key, reverse=True) if v != e["current"]]
        tail = (" · earlier: " + ", ".join(f'<a href="/spec/{address}/{v}">{v}</a>' for v in older)) if older else ""
        rows.append(f'<li><a href="/spec/{address}">{markdown.esc(e["label"])}</a> {e["current"]}'
                    f' <span class="muted">(<a href="/spec/{address}.md">text</a>{tail})</span></li>')
    main = ('<div class="wrap prose"><h1>Specifications</h1><p>The Claimset format is specified here: the claimset '
            "itself, the lab record it can come from, and how published claimsets are revised. Extensions add what "
            'one kind of work needs (<a href="/spec/extensions">about extensions</a>). Each page has a plain-text '
            "copy, for models and for diffing.</p>"
            f'<ul class="spec-list">{"".join(rows)}</ul></div>')
    return shell("Specifications", main, description="The Claimset specification, the lab record and the extensions.")


def extensions_page(shell, cat, root=None):
    root = Path(root) if root else spec_dir()
    readme = root / "extensions" / "README.md"
    body, _ = markdown.convert(readme.read_text(encoding="utf-8")) if readme.exists() else ("", [])
    rows = "".join(f'<li><a href="/spec/{a}">{markdown.esc(cat[a]["label"])}</a> {cat[a]["current"]}</li>'
                   for a in sorted(cat) if a.startswith("extensions/"))
    main = (f'<div class="wrap prose"><p class="entry-top"><a href="/spec/">Specifications</a></p>'
            f'<h1>Extensions</h1><ul class="spec-list">{rows}</ul>{body}</div>')
    return shell("Extensions", main)


def write(published_dir, shell, write_file, root=None):
    """Write every specification's pages and texts under `published_dir`/spec."""
    out = Path(published_dir) / "spec"
    cat = catalogue(root)
    for address, entry in cat.items():
        for version, f in entry["versions"].items():
            text = f.read_text(encoding="utf-8")
            write_file(out / address / f"{version}.html", page(shell, address, entry, version))
            write_file(out / address / f"{version}.md", text)
            if version == entry["current"]:
                write_file(out / f"{address}.html", page(shell, address, entry, version))
                write_file(out / f"{address}.md", text)
    write_file(out / "index.html", index(shell, cat, root))
    write_file(out / "extensions.html", extensions_page(shell, cat, root))
    return cat
