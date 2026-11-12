"""The site's menu (design §7, Header): every page offers Convert your paper, marked on its own page."""

from portal import site


def test_convert_your_paper_is_in_the_menu():
    page = site.shell("Read", "<p>x</p>", active="read")
    assert page.count('<a href="/convert">Convert your paper</a>') == 2        # the header and the phone menu


def test_it_is_marked_on_its_own_page():
    page = site.shell(site.PAGES["convert"][1], "<p>x</p>", active=site.PAGES["convert"][2])
    assert page.count('<a href="/convert" aria-current="page">Convert your paper</a>') == 2
    assert 'href="/about" aria-current' not in page
