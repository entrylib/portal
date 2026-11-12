"""The five parts of a score (UX re-check, 12 November 2026): named Evidence, not Support, inside a score called
Support; on a paper, each part's average loss over its principal claims, not the largest cost of each problem; a
claim's dots a link to its breakdown, named for a screen reader."""

import json
import re
from pathlib import Path

from portal import score_html, scores

DOC = json.loads((Path(__file__).parent / "data" / "2026.000003.json").read_text(encoding="utf-8"))
RESULT = scores.compute(None, DOC)


def test_the_part_is_called_evidence():
    labels = [label for _n, label in score_html._groups()]
    assert labels[0] == "Evidence" and "Support" not in labels
    assert ">Evidence<" in score_html.dot_list(RESULT)


def test_the_papers_parts_are_averages_over_its_principal_claims():
    panel = score_html.dot_list(RESULT)
    pattern = r'aria-hidden="true"></span>([^<]+)(?:<span class="lost">−(\d+)</span>)?'
    lost = {k.strip(): v for k, v in re.findall(pattern, panel)}
    principal = RESULT["paper"]["principal"]
    for name, label in score_html._groups():
        mean = sum(c for cid in principal for p, c in RESULT["claims"][cid]["costs"].items()
                   if RESULT["problems"][p]["group"] == name) / len(principal)
        assert int(lost[label] or 0) == int(mean + 0.5), label
    assert "mean of" not in panel.lower() and "together" not in panel.lower()     # no accounting in the panel
    assert "Plan <span class=\"lost\">−1</span>" in panel and "nothing lost" not in panel.split("Plan")[1][:40]


def test_a_claims_dots_open_its_breakdown():
    row = score_html.dots(RESULT, "C11")
    assert row.startswith('<a class="dots" href="#score-C11" data-popup="score-C11" aria-label="C11, parts of the '
                          'score: Evidence, ')
    assert "Show the breakdown." in row and 'role="img"' not in row
    assert score_html.dots(RESULT, "C11", href=False).startswith('<span class="dots" role="img"')
    assert 'href="/p/2026.000003#score-C11"' in score_html.dots(RESULT, "C11", href="/p/2026.000003#score-C11")
