"""How pages behave in a browser: copying works in every browser, and the panel scrolls on its own only beside the
page."""

import re
from pathlib import Path

from portal import site

STATIC = Path(site.__file__).parent / "static"


def test_copying_works_in_every_browser():
    """A copy happens within the click, from text already on the page. A copy that first downloads its text (the
    message on /convert did, from November 2026) is refused by browsers that allow copying only during the click, and
    opened the text instead. Every copy button names an element of its page, and the page loads the script."""
    script = (STATIC / "page.js").read_text(encoding="utf-8")
    assert "data-copy-url" not in script and "fetch(" not in script
    for name, (file, *_rest) in site.PAGES.items():
        text = (STATIC / "pages" / file).read_text(encoding="utf-8")
        assert "data-copy-url" not in text, name
        page = site.fixed_page(name, "https://entrylib.test")
        for target in re.findall(r'data-copy="([^"]+)"', page):
            assert f'id="{target}"' in page, (name, target)
            assert re.search(r'<script src="/page\.js[^"]*" defer>', page), name
    convert = site.fixed_page("convert", "https://entrylib.test")
    assert 'data-copy="convert-prompt"' in convert and 'download="entrylib-convert-message.txt"' in convert
    box = convert.index('<div class="connect">')                     # the grey box holds only the message
    end = convert.index("</div>", box)
    button, paste = convert.index('data-copy="convert-prompt"'), convert.index("Paste it with the paper")
    assert end < button < paste < convert.index('download="entrylib-convert-message.txt"')
    assert "</button></p>\n<p>Paste it" in convert                    # the explanation under the button


def test_the_panel_scrolls_on_its_own_only_beside_the_page():
    """On a phone or tablet the panel is part of the page; a scroll box there (with overscroll-behavior: contain)
    kept a drag that started on it from scrolling the page, though it had nothing to scroll."""
    css = (STATIC / "site.css").read_text(encoding="utf-8")
    rule = re.search(r"@media ([^{]*)\{\s*\.entry > \.panel \{ max-height:[^}]*overflow-y: auto", css)
    assert rule and "min-width: 1101px" in rule.group(1) and "min-height: 701px" in rule.group(1)
    assert "@media (max-width: 1100px)" in css and ".entry > .panel { position: static;" in css
