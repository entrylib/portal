"""The site's menu (design §7.4, Header): Read, Lab, For agents, About, and one Publish menu with everything an author
needs; the phone menu holds the same links and the Publish group; the page a reader is on is marked."""

import re

from portal import site


def test_four_links_and_the_publish_menu():
    page = site.shell("Read", "<p>x</p>", active="read")
    nav = re.search(r'<nav class="site-nav".*?</nav>', page, re.S).group(0)
    assert re.findall(r'<a href="(/[a-z]+)"(?: aria-current="page")?>', nav) == ["/read", "/lab", "/agents", "/about"]
    assert '<details class="publish-menu"><summary class="button">Publish<svg' in nav
    for href, label in (("/submit", "Publish a paper"), ("/convert", "Convert your paper"),
                        ("/before-you-submit", "Before you publish"), ("/submissions", "Your submissions")):
        assert f'<a class="publish-item" href="{href}"><strong>{label}</strong>' in nav
        assert page.count(f'href="{href}"') >= 2                          # also in the phone menu
    assert '<p class="menu-group">Publish</p><a class="button" href="/submit">Publish a paper</a>' in page
    assert "Submit a claimset" not in page


def test_the_page_is_marked():
    page = site.shell(site.PAGES["convert"][1], "<p>x</p>", active=site.PAGES["convert"][2])
    assert '<a class="publish-item" href="/convert" aria-current="page">' in page
    assert '<summary class="button current">Publish' in page
    assert '<a href="/convert" aria-current="page">Convert your paper</a>' in page        # the phone menu
    assert 'href="/about" aria-current' not in page
