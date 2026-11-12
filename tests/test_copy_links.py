"""A link that copies a text (`data-copy-url`, the message on /convert) needs page.js's handler and a page that loads
it; without them the link only opens the text. #119 removed the handler while #120 added such a link."""

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
