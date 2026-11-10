"""References given by DOI, written out from Crossref at publication (crossref.py)."""

import datetime as dt

from publishing import example, write

from portal import crossref
from portal.publish import publish

RECORD = {"author": [{"given": "Ivan", "family": "Svetunkov"}, {"given": "Fotios", "family": "Petropoulos"}],
          "issued": {"date-parts": [[2018, 3]]}, "title": ["Old dog, new tricks: a <i>modelling</i> view"],
          "container-title": ["International Journal of Production Research"], "volume": "56", "issue": "18",
          "page": "6034-6047", "type": "journal-article"}


def test_written():
    s = crossref.summary(RECORD)
    assert crossref.written(s) == ("Svetunkov, I., & Petropoulos, F. (2018). Old dog, new tricks: a modelling view. "
                                   "International Journal of Production Research, 56(18), 6034–6047.")
    book = {"author": [{"given": "J. K.", "family": "Ord"}], "issued": {"date-parts": [[2017]]},
            "title": ["Forecasting"], "publisher": "Springer", "type": "book"}
    assert crossref.written(crossref.summary(book)) == "Ord, J. K. (2017). Forecasting. Springer."
    assert crossref.summary({"title": ["No authors"]}) is None
    assert crossref.normalise("https://doi.org/10.1002/FOR.3980010202") == "10.1002/for.3980010202"
    assert crossref.normalise("not a doi") is None


def test_texts_are_asked_once_and_kept(env, monkeypatch):
    ctx, _ = env
    monkeypatch.setenv("PORTAL_CROSSREF", "1")
    asked = []

    def fake(doi):
        asked.append(doi)
        if doi == "10.1000/down":
            raise OSError("unreachable")
        return RECORD if doi == "10.1000/known" else None
    conn = ctx["conn"]
    out = crossref.texts(conn, ["doi:10.1000/known", "10.1000/unknown", "10.1000/down"], fetcher=fake)
    assert list(out) == ["10.1000/known"] and out["10.1000/known"].startswith("Svetunkov, I., & Petropoulos, F. (2018)")
    assert sorted(asked) == ["10.1000/down", "10.1000/known", "10.1000/unknown"]
    asked.clear()
    crossref.texts(conn, ["10.1000/known", "10.1000/unknown", "10.1000/down"], fetcher=fake)
    assert asked == ["10.1000/down"]                                  # known and unknown are kept; down is asked again
    later = dt.datetime.now(dt.UTC) + crossref.RETRY_AFTER + dt.timedelta(days=1)
    asked.clear()
    crossref.texts(conn, ["10.1000/unknown"], fetcher=fake, now=later)
    assert asked == ["10.1000/unknown"]                               # an unknown DOI is asked again after a while
    monkeypatch.setenv("PORTAL_CROSSREF", "0")
    asked.clear()
    assert crossref.texts(conn, ["10.1000/new"], fetcher=fake) == {} and asked == []


def test_the_page_shows_author_year(env, monkeypatch):
    ctx, tmp = env
    monkeypatch.setenv("PORTAL_CROSSREF", "1")
    monkeypatch.setattr(crossref, "fetch", lambda doi: RECORD)
    doc = example()
    doc["references"] = [{"id": "B1", "id_type": "doi", "target": "10.1080/00207543.2017.1380326"}]
    doc["definitions"][0]["source"] = "B1"
    concept, _ = publish(write(tmp, doc), **ctx)
    page = (ctx["published_dir"] / "p" / f"{concept.split(':', 1)[1]}.html").read_text()
    from claimset import html as cshtml
    if "ref_text" in cshtml.render_parts.__code__.co_varnames:     # claimset 0.40.4 and later
        assert "Svetunkov and Petropoulos (2018)" in page and "Old dog, new tricks" in page
    assert 'href="https://doi.org/10.1080/00207543.2017.1380326"' in page
    served = (ctx["published_dir"] / "p" / f"{concept.split(':', 1)[1]}.json").read_text()
    assert "Svetunkov" not in served                               # the published file is unchanged
