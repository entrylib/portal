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


def test_the_submit_page_offers_its_findings_to_the_assistant():
    """Errors and warnings at /submit, refused or accepted, are copied as one block with what to do with them."""
    script = (STATIC / "submit.js").read_text(encoding="utf-8")
    for label in ("Copy the errors for your assistant", "Copy the errors and warnings for your assistant",
                  "Copy the warnings for your assistant"):
        assert label in script
    assert "never from " in script and "give me the whole corrected file" in script
    assert "tell me why in one line" in script and 'link.href = "/submissions"' in script
    assert "fetch(" in script and script.count("fetch(") == 1           # the upload only: copies need no download


def test_consent_pages_are_in_the_sites_shell():
    """A guarantor who confirms, or opens a consent link, can go on to the rest of the site: the header with its
    menu, the footer and the site's styles, as on every other page."""
    from portal import pages
    for html_ in (pages.message("Confirmed", "Thank you.", "https://entrylib.test/api/submissions/s1",
                                back=("/submissions", "Your submissions")),
                  pages.message("Sign-in cancelled", "ORCID sign-in was not completed.")):
        assert '<header class="site-header">' in html_ and '<footer class="site-footer">' in html_
        assert 'href="/site.css' in html_ and "<style>" not in html_
        assert '<meta name="robots" content="noindex">' in html_


def test_the_score_popups_copy_their_issues_for_the_agent():
    """"Why 91?" and a claim's score: the pop-up copies the issues it lists, with what the agent is to do, naming the
    version and where it is; a formula goes as its source, $…$, not as its symbols followed by its source."""
    import json

    from portal import scores
    script = (STATIC / "page.js").read_text(encoding="utf-8")
    assert "Copy the issues for your agent" in script and ".problems > li" in script
    assert 'annotation[encoding="application/x-tex"]' in script and "never from memory" in script
    assert "suggest how to fix it" in script and "Do not rewrite the claimset yet" in script
    assert "give me the whole corrected claimset" not in script                 # the authors decide what changes
    doc = json.loads((Path(__file__).parent / "data" / "2026.000003.json").read_text(encoding="utf-8"))
    listing = [{"version": n, "published_at": f"2026-11-1{n}T10:00:00Z"} for n in (1, 2, 3)]
    page = site.claimset_page(doc, base_url="https://entrylib.test", listing=listing, current=3,
                              scores=scores.compute(None, doc))
    assert ('<section class="cs-section score-section" id="score" data-paper="entrylib:2026.000003@v3" '
            'data-url="https://entrylib.test/p/2026.000003@v3">') in page
