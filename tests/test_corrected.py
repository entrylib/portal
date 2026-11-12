"""One word for a correction (UX re-check, 12 November 2026): "corrected" when it changed what a paper claims,
"updated" otherwise, the same in the status tag and the notice; on cards, only papers whose claims were ever
corrected carry a tag."""

import copy
import json
from importlib import resources
from pathlib import Path

from portal import history, site

EXAMPLES = Path(str(resources.files("claimset") / "data" / "examples"))
NOTICE = {"date": "2026-11-12", "reason_code": "correction", "statement": "Adds a summary.", "issued_by": "platform"}


def corrected(changes, version=3):
    doc = json.loads((EXAMPLES / "published-native.json").read_text(encoding="utf-8"))
    doc["paper"].update({"id": "entrylib:2026.000003", "version": version, "status": "corrected",
                         "status_notice": dict(NOTICE), "changes": changes})
    return doc


def test_what_counts_as_a_change_of_claims():
    yes = ["/claims/3/statement", "/claims/0/hypothesis/outcome", "/claims/2/role", "/claims/1/type", "/claims/-",
           "/claims/4", "/claims"]
    no = ["/claims/0/support", "/claims/0/test/quantities/m/variable", "/claims/2/relations", "/paper/summary",
          "/artefacts/9/uri", "/contributors/1/label", "/claims/0/checks"]
    for path in yes:
        assert history.claims_changed([{"op": "replace", "path": path}]), path
    for path in no:
        assert not history.claims_changed([{"op": "replace", "path": path}]), path
    assert not history.claims_changed(None)


def test_tag_and_notice_agree():
    p = corrected([{"op": "add", "path": "/paper/summary", "value": "x"}])["paper"]
    assert ">updated</span>" in site._status(p) and "<strong>Updated</strong>" in site._notice(p)
    p = corrected([{"op": "replace", "path": "/claims/0/statement", "value": "x"}])["paper"]
    assert ">corrected</span>" in site._status(p) and "<strong>Corrected</strong>" in site._notice(p)


def test_cards_tag_only_papers_whose_claims_were_corrected():
    doc = corrected([{"op": "add", "path": "/paper/summary", "value": "x"}])
    plain = site.card(doc)
    assert "status-" not in plain and "v3" in plain                        # updated in other ways: no tag
    assert ">corrected</span>" in site._cards([doc], corrected={"entrylib:2026.000003"})   # an earlier version did
    assert "status-" not in site._cards([doc], corrected=set())
    retracted = copy.deepcopy(doc)
    retracted["paper"]["status"] = "retracted"
    assert ">retracted</span>" in site.card(retracted)


def test_the_home_page_tags_a_paper_whose_claims_were_corrected(env):
    """Published for real: v2 changes a claim's statement and v3 only the summary; the home page's card still says
    "corrected", and v3's own page says "updated" in its tag and its notice."""
    import datetime as dt

    from publishing import example, write

    from portal.publish import publish
    ctx, tmp = env
    concept, _ = publish(write(tmp, example()), **ctx)
    doc = example()
    doc["paper"]["id"] = concept
    doc["claims"][0]["statement"] = doc["claims"][0]["statement"].rstrip(".") + " in every run."
    doc["paper"]["correction_reason"] = "The first claim omitted that it held in every run."
    publish(write(tmp, doc, "v2.claimset.json"), **{**ctx, "today": dt.date(2026, 11, 5)})
    assert history.corrected_concepts(ctx["conn"]) == {concept}
    doc["paper"]["summary"] = "A summary in plain words."
    doc["paper"]["correction_reason"] = "Adds a summary."
    publish(write(tmp, doc, "v3.claimset.json"), **{**ctx, "today": dt.date(2026, 11, 6)})
    home = (ctx["published_dir"] / "index.html").read_text()
    assert '<span class="status status-neutral">corrected</span> · v3' in home
    page = (ctx["published_dir"] / "p" / "2026.000001.html").read_text()
    assert '<span class="status status-neutral">updated</span>' in page and "<strong>Updated</strong>" in page
