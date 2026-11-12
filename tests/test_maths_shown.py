"""No formula is shown as its source (UX re-check, 12 November 2026): every free text of a paper that may hold maths
goes through the same renderer as claim statements, so no "$…$" pair is left in what a reader sees."""

import html
import json
import re
from importlib import resources
from pathlib import Path

import pytest

from portal import page

DATA = Path(__file__).parent / "data"
EXAMPLES = Path(str(resources.files("claimset") / "data" / "examples"))
FILES = sorted(EXAMPLES.glob("*.json")) + sorted(DATA.glob("*.json"))
RAW_MATHS = re.compile(r"\$[^$\s][^$]*?\$")


def visible_text(fragment):
    """The text a reader sees: formulas (MathML) and scripts out, tags out, entities decoded. Attributes (tooltips,
    labels) are not text on the page."""
    fragment = re.sub(r"<math\b.*?</math>", " ", fragment, flags=re.S)
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


@pytest.mark.parametrize("path", FILES, ids=[f.name for f in FILES])
def test_no_formula_is_shown_as_its_source(path):
    parts = page.render_parts(json.loads(path.read_text(encoding="utf-8")))
    text = visible_text(parts["header"] + parts["body"])
    left = RAW_MATHS.findall(text)
    assert not left, f"{path.name}: {left[:5]}"


def test_the_paper_that_showed_it():
    """entrylib:2026.000003 v3 (CC BY 4.0) showed proof-step rules and an artefact description as LaTeX."""
    doc = json.loads((DATA / "2026.000003.json").read_text(encoding="utf-8"))
    body = page.render_parts(doc)["body"]
    assert "differentiation in $" not in visible_text(body)
    assert "<math" in body.split('id="E6.3"')[-1][:3000] or "<math" in body


def test_a_repository_at_a_commit_is_named_so():
    assert page._link_name("https://github.com/o/r/tree/8a5fbbb334b0d6192a3c3e8a5773f512e548e891") == \
        "repository at 8a5fbbb"
    assert page._link_name("https://github.com/o/r/blob/abc/python/x.csv") == "x.csv"
