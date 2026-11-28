"""The site's chrome (design §7.1): the head of every page, its header and footer, and the addresses of its
stylesheets and scripts, with the shell that wraps a page's content in them.

It is kept apart from what draws a paper (site, page, paper, score_html) so that each has its own fingerprint: a
change here re-wraps the stored content of every page (Page.args, indexer.rewrap) without drawing any paper again.
"""

import functools
import hashlib
import html
import os
from importlib import resources

from . import page as pageview

SITE = "EntryLib"
CONTACT = "mail@entrylib.org"
SOURCE_CODE = "https://github.com/entrylib/portal"
CLAIMSET_REPO = "https://github.com/entrylib/claimset"

#: How many claimsets the home page lists.
RECENT = 10
#: How many entries the feed carries.
FEED_ENTRIES = 30

NAV = [("/read", "Read", "read"), ("/lab", "Lab", "lab"), ("/agents", "For agents", "agents"),
       ("/about", "About", "about")]
#: The header's Publish menu (design §7.4): everything an author needs, under one button.
PUBLISH = [("/submit", "Publish a paper", "Submit a paper your AI agent has prepared", "submit"),
           ("/convert", "Convert your paper", "Turn a paper you have already written into one", "convert"),
           ("/before-you-submit", "Before you publish", "What the responsible researcher checks", "before"),
           ("/submissions", "Your submissions", "Papers waiting for your confirmation", "submissions")]
BUTTON = ' class="button"'
CARET = ('<svg class="caret" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" focusable="false">'
         '<path d="M2 4l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>')
FOOTER = [("/about", "About"), ("/submissions", "Your submissions"),
          ("/privacy", "Privacy"),
          ("/removal", "Removal requests"), ("/spec/", "Specification"), ("/llms.txt", "llms.txt, for AI agents"),
          (SOURCE_CODE, "Source code"), (f"mailto:{CONTACT}", CONTACT)]


#: The modules of the chrome: fingerprint() hashes them, site.fingerprint() leaves them out.
CHROME_MODULES = ("chrome.py", "page_css.py")


def fingerprint():
    """A hash of the chrome: its modules and the stylesheets and script every page links (their addresses carry a
    hash of their content, asset). When it alone changes, every page is re-wrapped, none drawn again (design §7.1)."""
    from pathlib import Path
    h = hashlib.sha256()
    for name in CHROME_MODULES:
        h.update(name.encode() + b"\0" + (Path(__file__).parent / name).read_bytes())
    for name in ("site.css", "page.js", "fonts/fonts.css"):
        h.update(_static(name).read_bytes())
    return h.hexdigest()[:16]


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def _static(name):
    return resources.files("portal") / "static" / name


# --- the shell --------------------------------------------------------------------------------------------------------

#: The mark (static/img/entrylib-mark.svg) inline, its brackets in the text's colour so that it follows the theme.
MARK = ('<svg class="logo-mark" viewBox="0 0 32 32" width="30" height="30" aria-hidden="true" focusable="false">'
        '<path d="M11 5H6v22h5M21 5h5v22h-5" fill="none" stroke="currentColor" stroke-width="3.2" '
        'stroke-linecap="square"/><circle cx="16" cy="16" r="4" fill="#2e8b57"/></svg>')
#: The icons a browser, a phone's home screen and an installed site use (static/icons, written at the site's root).
ICONS = ('<link rel="icon" href="/favicon.ico" sizes="48x48"><link rel="icon" href="/favicon.svg" type="image/svg+xml">'
         '<link rel="apple-touch-icon" href="/apple-touch-icon.png"><link rel="manifest" href="/site.webmanifest">')


def _header(active):
    """The site's header: four links and the Publish menu (a <details>: it works without scripts and from the
    keyboard); on a phone, one Menu with the same links and the Publish group."""
    def cur(key):
        return ' aria-current="page"' if key == active else ""
    links = "".join(f'<a href="{href}"{cur(key)}>{label}</a>' for href, label, key in NAV)
    items = "".join(f'<a class="publish-item" href="{href}"{cur(key)}><strong>{label}</strong><span>{what}</span></a>'
                    for href, label, what, key in PUBLISH)
    mine = any(key == active for *_rest, key in PUBLISH)
    publish = (f'<details class="publish-menu"><summary class="button{" current" if mine else ""}">Publish{CARET}'
               f'</summary><div class="publish-list">{items}</div></details>')
    phone = "".join(f'<a{BUTTON if i == 0 else ""} href="{href}"{cur(key)}>{label}</a>'
                    for i, (href, label, _what, key) in enumerate(PUBLISH))
    return (f'<header class="site-header"><div class="wrap">'
            f'<a class="logo" href="/">{MARK}<span>{SITE}</span></a>'
            f'<nav class="site-nav" aria-label="Site">{links}{publish}</nav>'
            f'<details class="site-menu"><summary>Menu</summary><nav aria-label="Site">{links}'
            f'<p class="menu-group">Publish</p>{phone}</nav></details>'
            "</div></header>")


def _footer():
    links = "".join(f'<a href="{esc(href)}">{esc(label)}</a>' for href, label in FOOTER)
    return f'<footer class="site-footer"><div class="wrap">{links}</div></footer>'


@functools.cache
def asset(path):
    """A stylesheet's or script's address with a version from its content (/site.css?v=1a2b3c4d), so that a browser
    or Cloudflare never pairs a new page with an old stylesheet."""
    if path == "/claimset.css":
        data = pageview.stylesheet().encode()
    else:
        data = _static(path.lstrip("/")).read_bytes()
    return f"{path}?v={hashlib.sha256(data).hexdigest()[:10]}"


class Page(str):
    """A whole page as written (shell), which keeps what it was made from (`args`), so that a change to the chrome
    alone wraps the same content again (design §7.1)."""
    args = None


def base_url():
    """The site's address, as the app's configuration reads it (config.py), for the line for AI assistants."""
    return os.environ.get("PORTAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def for_ai(url, *more):
    """The small line for AI assistants under a page's title (design §7.4, *For AI assistants*), the same on every
    page: "AI assistants, your instructions:" and where an assistant given this page, perhaps copied into a chat,
    should look. `more`: further (what, address) pairs, after the first address."""
    def link(u):
        return f'<a href="{esc(u)}">{esc(u)}</a>'
    rest = "".join(f"; {esc(what)}: {link(u)}" for what, u in more)
    return f'<p class="for-ai">AI assistants, your instructions: {link(url)}{rest}</p>'


def _with_for_ai(main, line):
    """`main` with the line for AI assistants under its title: after the first heading, else at the top of its first
    block. A page that has its own line keeps it."""
    if 'class="for-ai"' in main:
        return main
    line = line or for_ai(f"{base_url()}/llms.txt")
    if "</h1>" in main:
        return main.replace("</h1>", "</h1>" + line, 1)
    end = main.find(">") + 1 if main.startswith("<div") else 0
    return main[:end] + line + main[end:]


def shell(title, main, *, active=None, description="", head="", canonical=None, script=None, ai=None):
    """A whole page: head, site header, `main` (HTML), footer. A Page, which keeps its arguments. `ai`: the page's
    own line for AI assistants (for_ai()); without it, a page that has none points to /llms.txt."""
    full = title if title == SITE else f"{title} · {SITE}"
    meta = f'<meta name="description" content="{esc(description)}">' if description else ""
    canon = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ""
    page = Page("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(full)}</title>{meta}{canon}{ICONS}"
            f'<link rel="stylesheet" href="{asset("/fonts/fonts.css")}">'
            f'<link rel="stylesheet" href="{asset("/claimset.css")}">'
            f'<link rel="stylesheet" href="{asset("/site.css")}">'
            f'<link rel="alternate" type="application/atom+xml" title="{SITE}: recently published" href="/feed.xml">'
            f'{head}</head>\n<body id="top"><a class="skip-link" href="#content">Skip to content</a>{_header(active)}'
            f'<main id="content">{_with_for_ai(main, ai)}</main>{_footer()}'
            + "".join(f'<script src="{asset(s)}" defer></script>' for s in ([script] if isinstance(script, str)
                                                                             else script or []))
                + "</body></html>\n")
    page.args = {"title": title, "main": main, "active": active, "description": description, "head": head,
                 "canonical": canonical, "script": script, "ai": ai}
    return page


