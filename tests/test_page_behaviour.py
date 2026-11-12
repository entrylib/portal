"""How pages behave in a browser: a link that copies a text (`data-copy-url`, the message on /convert) needs page.js's
handler and a page that loads it, or it only opens the text (#119 removed the handler while #120 added such a link);
the panel scrolls on its own only beside the page."""

import re
from pathlib import Path

from portal import site

STATIC = Path(site.__file__).parent / "static"


def test_every_copy_link_is_handled():
    script = (STATIC / "page.js").read_text(encoding="utf-8")
    assert 'querySelectorAll("a[data-copy-url]")' in script and "navigator.clipboard" in script
    used = [name for name in site.PAGES if "data-copy-url" in (STATIC / "pages" / site.PAGES[name][0]).read_text()]
    assert "convert" in used
    for name in used:
        page = site.fixed_page(name, "https://entrylib.test")
        assert re.search(r'<script src="/page\.js[^"]*" defer>', page), name


def test_the_panel_scrolls_on_its_own_only_beside_the_page():
    """On a phone or tablet the panel is part of the page; a scroll box there (with overscroll-behavior: contain)
    kept a drag that started on it from scrolling the page, though it had nothing to scroll."""
    css = (STATIC / "site.css").read_text(encoding="utf-8")
    rule = re.search(r"@media ([^{]*)\{\s*\.entry > \.panel \{ max-height:[^}]*overflow-y: auto", css)
    assert rule and "min-width: 1101px" in rule.group(1) and "min-height: 701px" in rule.group(1)
    assert "@media (max-width: 1100px)" in css and ".entry > .panel { position: static;" in css
