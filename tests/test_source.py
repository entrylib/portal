"""A claimset its authors prepared from their published paper (design §4.5): the paper is claimed once, and by one
of its authors. Crossref and DataCite are replaced by `record` in these tests."""

import json

import pytest
from publishing import example, write

from portal import source
from portal.publish import publish

DOI = "10.1016/j.ijforecast.2025.01.001"
JSON = {"Content-Type": "application/json"}


def from_paper(doi=DOI, guarantor=None):
    doc = example()
    doc["artefacts"].append({"id": f"A{len(doc['artefacts']) + 1}", "kind": "manuscript",
                             "uri": f"https://doi.org/{doi}", "description": "The published article",
                             "availability": {"level": "public"}, "licence": "CC-BY-4.0"})
    if guarantor:
        g = next(c for c in doc["contributors"] if "guarantor" in (c.get("positions") or []))
        g.update(guarantor)
    return doc


def the_guarantor(doc):
    return next(c for c in doc["contributors"] if "guarantor" in (c.get("positions") or []))


@pytest.fixture
def record(monkeypatch):
    """The paper's authors as Crossref would give them: set `record.value` (None: an unknown DOI)."""
    class R:
        value = None
        calls = []
    def lookup(doi):
        R.calls.append(doi)
        if isinstance(R.value, Exception):
            raise R.value
        return R.value
    monkeypatch.setattr(source, "lookup", lookup)
    return R


def test_the_doi_is_read_from_the_forms_a_claimset_uses():
    assert source.doi(from_paper()) == DOI
    for uri in (f"doi:{DOI.upper()}", f"http://dx.doi.org/{DOI}", DOI):
        doc = from_paper()
        doc["artefacts"][-1]["uri"] = uri
        assert source.doi(doc) == DOI
    doc = example()
    doc["paper"]["published_as"] = {"id_type": "doi", "id": DOI}
    assert source.doi(doc) == DOI
    assert source.doi(example()) is None
    doc = from_paper()
    doc["artefacts"][-1]["uri"] = "files/draft.pdf"                   # a draft: no DOI, nothing to check
    assert source.doi(doc) is None


def test_authorship_by_orcid_then_by_name():
    rec = {"authors": [{"name": "Ivan Svetunkov", "family": "Svetunkov", "orcid": "0000-0001-7826-0281"},
                       {"name": "Jöhn Smíth", "family": "Smíth", "orcid": None}]}
    assert source.authorship(rec, [("0000-0001-7826-0281", "I. Svetunkov")]) == "orcid"
    assert source.authorship(rec, [("0000-0000-0000-0002", "John Smith")]) == "name"     # accents folded
    assert source.authorship(rec, [("0000-0000-0000-0003", "Ann Other")]) == "absent"
    assert source.authorship({"authors": []}, [("0000-0000-0000-0003", "Ann Other")]) == "unknown"


def test_an_author_submits_their_paper(client, record):
    doc = from_paper()
    g = the_guarantor(doc)
    record.value = {"title": "T", "registry": "Crossref", "authors": [
        {"name": g["name"], "family": g["name"].split()[-1], "orcid": g["orcid"]},
        {"name": "Co Author", "family": "Author", "orcid": "0000-0002-1825-0097"}]}
    r = client.post("/api/submissions", content=json.dumps(doc).encode(), headers=JSON)
    assert r.status_code == 201, r.text
    out = r.json()["source"]
    assert out["doi"] == DOI and out["authorship"].startswith("confirmed")
    assert out["coauthor_orcids"] == ["Co Author: 0000-0002-1825-0097"]          # to add to the claimset


def test_someone_who_is_not_an_author_is_refused(client, record):
    record.value = {"title": "T", "registry": "Crossref", "authors": [
        {"name": "Ann Other", "family": "Other", "orcid": "0000-0002-1825-0097"}]}
    r = client.post("/api/submissions", content=json.dumps(from_paper()).encode(), headers=JSON)
    assert r.status_code == 403 and "not among the authors" in r.json()["error"]


def test_without_orcids_on_the_paper_it_is_flagged_not_refused(client, record):
    record.value = {"title": "T", "registry": "Crossref", "authors": [{"name": "Ann Other", "family": "Other",
                                                                       "orcid": None}]}
    r = client.post("/api/submissions", content=json.dumps(from_paper()).encode(), headers=JSON)
    assert r.status_code == 201 and r.json()["source"]["authorship"].startswith("not confirmed")


def test_an_unknown_doi_or_an_unreachable_registry_does_not_block(client, record):
    record.value = None
    r = client.post("/api/submissions", content=json.dumps(from_paper()).encode(), headers=JSON)
    assert r.status_code == 201 and "not registered" in r.json()["source"]["authorship"]
    record.value = source.Unavailable("timeout")
    r = client.post("/api/submissions", content=json.dumps(from_paper("10.1000/other")).encode(), headers=JSON)
    assert r.status_code == 201 and "could not be reached" in r.json()["source"]["authorship"]


def test_a_paper_is_published_once(env, client, record):
    ctx, tmp = env
    doc = from_paper()
    publish(write(tmp, doc), **ctx)
    assert ctx["conn"].execute("SELECT source_doi FROM papers").fetchone()[0] == DOI
    again = from_paper()
    again["paper"]["title"] = "Another title for the same paper"
    r = client.post("/api/submissions", content=json.dumps(again).encode(), headers=JSON)
    assert r.status_code == 409 and "already restates the paper" in r.json()["error"]
    assert record.calls == []                                            # refused before asking anyone


def test_lookups_are_off_when_asked(monkeypatch):
    monkeypatch.setenv("PORTAL_CROSSREF", "0")
    with pytest.raises(source.Unavailable):
        source.lookup(DOI)
    assert source.lookup("not a doi") is None


def test_the_guarantor_sees_the_paper_when_confirming(client, record):
    doc = from_paper()
    g = the_guarantor(doc)
    record.value = {"title": "Forecasting <things>", "registry": "Crossref", "authors": [
        {"name": g["name"], "family": g["name"].split()[-1], "orcid": g["orcid"]},
        {"name": "Co Author", "family": "Author", "orcid": "0000-0002-1825-0097"}]}
    out = client.post("/api/submissions", content=json.dumps(doc).encode(), headers=JSON).json()
    link = out["consent"][0]["consent_url"]
    page = client.get(link[link.index("/consent/"):]).text
    assert f'Converted by its authors from <a href="https://doi.org/{DOI}">Forecasting &lt;things&gt;</a>' in page
    assert "Authorship: confirmed" in page and "Co Author: 0000-0002-1825-0097" in page
