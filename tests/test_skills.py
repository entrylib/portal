"""The skills on entrylib.org and the message of /convert (design §7.4, *Skills*): every skill the claimset package
ships as a page and as text, the message that carries the skills themselves, and the MCP tool guide."""

from pathlib import Path

import pytest
from publishing import BASE

from portal import indexer, reading, site, skills

SKILL = "---\nname: {n}\ndescription: What {n} is for.\n---\n\n# The {n} skill\n\nBody of {n}.\n"


def fake(tmp, names=("claimset-from-paper", "claimset-submit")):
    root, examples = tmp / "skills", tmp / "examples"
    for n in names:
        (root / n).mkdir(parents=True)
        (root / n / "SKILL.md").write_text(SKILL.format(n=n), encoding="utf-8")
    examples.mkdir()
    (examples / skills.EXAMPLE).write_text('{"schema_version": "0.42"}\n', encoding="utf-8")
    return root, examples


def test_the_message_carries_the_skills(tmp_path):
    root, examples = fake(tmp_path)
    cat = skills.catalogue(root)
    assert cat["claimset-submit"]["title"] == "The claimset-submit skill"
    msg = skills.message(BASE, cat, (examples / skills.EXAMPLE).read_text())
    assert msg.startswith("I am an author of the attached paper")
    assert "never" not in msg.split("\n\n")[0]
    assert "Do not write it from memory and do not invent a format: use only the structure of the example" in msg
    order = [msg.index(x) for x in ("Body of claimset-from-paper", "Body of claimset-submit", '"schema_version"')]
    assert order == sorted(order)
    assert "name: claimset-submit" not in msg                       # front matter left out
    shown = skills.shown(BASE, cat)
    assert "Body of" not in shown and len(shown) < 3000                 # short: it copies in every browser
    assert "call its guide tool with name claimset-from-paper" in shown
    assert f"{BASE}/skills/claimset-from-paper.md and {BASE}/skills/claimset-submit.md" in shown
    assert "pip install claimset" in shown and "do not write a claimset from memory" in shown


def test_without_the_from_paper_skill_the_request_names_where_to_read(tmp_path):
    root, _ = fake(tmp_path, names=("claimset-submit",))
    cat = skills.catalogue(root)
    msg = skills.message(BASE, cat)
    assert skills.RAW.format(name="claimset-from-paper") in msg
    assert f"{BASE}/skills/claimset-submit.md" in msg and "Body of" not in msg
    assert "if you cannot read them, say so and stop" in msg
    assert skills.RAW.format(name="claimset-from-paper") in skills.shown(BASE, cat)


def test_pages_texts_and_guide(tmp_path):
    root, examples = fake(tmp_path)
    out, written = tmp_path / "out", {}

    def write_file(path, text):
        written[Path(path).relative_to(out).as_posix()] = text

    skills.write(out, site.shell, write_file, BASE, root=root, examples=examples)
    assert {"skills/index.html", "skills/claimset-submit.html", "skills/claimset-submit.md",
            "convert/message.txt"} <= set(written)
    assert written["skills/claimset-submit.md"] == SKILL.format(n="claimset-submit")
    assert "Body of claimset-submit" in written["skills/claimset-submit.html"]
    assert 'href="/skills/claimset-submit.md"' in written["skills/claimset-submit.html"]
    assert "Body of claimset-submit" in written["convert/message.txt"]
    assert skills.paths(skills.catalogue(root)) == ["/skills/", "/skills/claimset-from-paper",
                                                    "/skills/claimset-submit"]
    assert "claimset-submit" in skills.guide(root=root) and "never from memory" in skills.guide(root=root)
    assert skills.guide("claimset-submit", root=root) == SKILL.format(n="claimset-submit")
    with pytest.raises(KeyError):
        skills.guide("nothing", root=root)


def test_a_section_of_the_specification():
    spec = ("# Spec\n\n## 3. Objects\n\nintro\n\n### 3.4 Evidence\n\nev\n\n#### 3.4.1 Tables\n\nt\n\n"
            "### 3.5 Other\n\nx\n")
    part = skills.guide("specification", "3.4", spec_text=spec)
    assert part.startswith("### 3.4 Evidence") and "3.4.1 Tables" in part and "3.5" not in part
    assert skills.guide("specification", spec_text=spec) == spec
    with pytest.raises(KeyError):
        skills.guide("specification", "9.9", spec_text=spec)


def test_the_site_publishes_the_installed_skills(env):
    ctx, _ = env
    out = ctx["published_dir"]
    indexer.refresh_if_claimset_changed(ctx["conn"], None, out, BASE, "0.40.1")
    cat = skills.catalogue()
    assert "claimset-submit" in cat                                  # every claimset release ships it
    assert (out / "skills" / "claimset-submit.md").read_text() == cat["claimset-submit"]["text"]
    assert (out / "skills" / "claimset-submit.html").exists() and (out / "skills" / "index.html").exists()
    assert (out / "convert" / "message.txt").read_text() == skills.message(
        BASE, cat, (skills.examples_dir() / skills.EXAMPLE).read_text(encoding="utf-8"))
    convert = (out / "convert.html").read_text()
    assert "do not write a claimset from memory" in convert and 'data-copy="convert-prompt"' in convert
    assert '<a href="/convert/message.txt"\ndownload="entrylib-convert-message.txt">' in convert
    assert "/skills/claimset-submit</loc>" in site.sitemap([], BASE)
    caddy = (Path(__file__).resolve().parent.parent / "deploy" / "Caddyfile").read_text()
    assert " /skills /skills/* " in caddy and " /convert/message.txt " in caddy and "/skills/*.md" in caddy
    llms = reading.llms_txt(BASE)
    assert f"{BASE}/skills/claimset-from-paper.md" in llms and "never from memory" in llms and " guide," in llms


def test_guide_gives_good_practice_for_planning_a_study():
    asked = []

    def planning(ref):
        asked.append(ref)
        if ref.endswith("#nothing"):
            raise ValueError("no entry 'nothing' in study-planning/prediction: the entries are mean-forecasts")
        return f"text of {ref}"

    assert skills.guide("study-planning", planning=planning) == "text of study-planning"
    assert skills.guide("study-planning/prediction", "mean-forecasts", planning=planning) == \
        "text of study-planning/prediction#mean-forecasts"
    assert skills.guide("study-planning/prediction#mean-forecasts", "ignored", planning=planning) == \
        "text of study-planning/prediction#mean-forecasts"
    with pytest.raises(KeyError, match="the entries are"):
        skills.guide("study-planning/prediction", "nothing", planning=planning)
    assert "study-planning" in skills.guide()


def test_guide_without_a_copy_of_good_practice_points_to_the_repository():
    def planning(ref):
        raise FileNotFoundError(ref)

    text = skills.guide("study-planning/prediction", planning=planning)
    assert skills.PLANNING_URL in text and "study-planning/prediction" in text


def test_guide_reads_the_copy_the_installed_claimset_carries():
    bundle = pytest.importorskip("claimset.bundle")
    if not hasattr(bundle, "study_planning"):
        pytest.skip("the installed claimset carries no study-planning")
    text = skills.guide("study-planning/prediction", "mean-forecasts")
    assert "## mean-forecasts" in text and "## References" in text
