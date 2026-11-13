"""EntryLib's good practice for planning a study on entrylib.org and the message of /lab (design §7.4, *Planning a
study*): every guide the claimset package carries as a page and as text, the message that carries the guides
themselves, and the short message /lab copies."""

import json
from pathlib import Path

from publishing import BASE

from portal import indexer, markdown, planning, reading, site

GUIDE = ("# {title}\n\nVersion 0.2 (draft) · 2026-11-13\n\n## Principle\n\nWhy.\n\n## first-entry\n\n"
         "- **Default:** do this ([Someone 2020](https://doi.org/10.1/x)).\n\n## References\n\n"
         "- Someone, A. (2020). A paper. *A Journal*, 1. [doi:10.1/x](https://doi.org/10.1/x)\n"
         "- Other, B. (1999). A book. <https://example.org/book>\n")
README = ("# Good practice for planning a study\n\nDefaults for the choices a study makes.\n\n"
          "| Guide | Kinds of study |\n|---|---|\n| [prediction.md](prediction.md) | predictions |\n\n"
          "## What a guide holds\n\n- A principle first; see [prediction.md](prediction.md).\n")


def fake(tmp, names=("prediction", "experiments")):
    root = tmp / "study-planning"
    root.mkdir()
    for n in names:
        (root / f"{n}.md").write_text(GUIDE.format(title=f"The {n} guide"), encoding="utf-8")
    (root / "README.md").write_text(README, encoding="utf-8")
    (root / "SOURCE.json").write_text(json.dumps({"commit": "104ba1c" + "0" * 33, "date": "2026-11-13"}),
                                      encoding="utf-8")
    return root


def test_catalogue_and_messages(tmp_path):
    cat = planning.catalogue(fake(tmp_path))
    assert list(cat["guides"]) == ["experiments", "prediction"]
    guide = cat["guides"]["prediction"]
    assert guide["title"] == "The prediction guide" and guide["version"] == "0.2"
    short = planning.short(BASE, cat)
    assert "Why." not in short and len(short) < 3000                     # short: it copies in every browser
    assert "call its guide tool with name study-planning" in short
    assert f"{BASE}/study-planning/experiments.md, {BASE}/study-planning/prediction.md" in short
    assert "pip install claimset" in short and "do not plan from memory" in short
    assert "A precedent is not a reason" in short and "one choice at a time" in short
    assert "claimset lab plan --choice" in short                          # the plan carries over to the lab
    full = planning.message(BASE, cat)
    assert full.startswith("Help me plan a study") and "never from memory" in full
    order = [full.index(x) for x in ("WHAT A GUIDE HOLDS", "GUIDE study-planning/experiments (v0.2)",
                                     "GUIDE study-planning/prediction (v0.2)")]
    assert order == sorted(order) and full.count("Why.") == 2


def test_without_guides_in_the_package_the_messages_name_the_repository(tmp_path):
    empty = tmp_path / "none"
    empty.mkdir()
    cat = planning.catalogue(empty)
    assert cat["guides"] == {} and planning.paths(cat) == []
    assert planning.REPOSITORY in planning.short(BASE, cat)
    assert planning.message(BASE, cat) == planning.short(BASE, cat)
    written = []
    planning.write(tmp_path / "out", site.shell, lambda p, t: written.append(p), BASE, root=empty)
    assert written == []


def test_pages_and_texts(tmp_path):
    root, out, written = fake(tmp_path), tmp_path / "out", {}

    def write_file(path, text):
        written[Path(path).relative_to(out).as_posix()] = text

    cat = planning.write(out, site.shell, write_file, BASE, root=root)
    assert {"study-planning/index.html", "study-planning/prediction.html", "study-planning/prediction.md",
            "study-planning/README.md", "study-planning/message.txt"} <= set(written)
    assert written["study-planning/prediction.md"] == cat["guides"]["prediction"]["text"]
    page = written["study-planning/prediction.html"]
    assert '<a href="https://doi.org/10.1/x">Someone 2020</a>' in page
    assert '<a href="https://example.org/book">https://example.org/book</a>' in page      # an autolink
    assert 'href="/study-planning/prediction.md"' in page and "/tree/104ba1c" in page
    index = written["study-planning/index.html"]
    assert 'href="/study-planning/prediction"' in index and 'href="prediction.md"' not in index
    assert "What a guide holds" in index and "Kinds of study" not in index   # the README's sections, not its list
    assert 'href="/lab#plan"' in index
    assert planning.paths(cat) == ["/study-planning/", "/study-planning/experiments", "/study-planning/prediction"]


def test_autolinks_only_for_web_addresses():
    assert markdown.inline("<https://a.org/b>") == '<a href="https://a.org/b">https://a.org/b</a>'
    assert markdown.inline("<javascript:alert(1)> <b>") == "&lt;javascript:alert(1)&gt; &lt;b&gt;"


def test_the_site_publishes_the_installed_guides(env):
    ctx, _ = env
    out = ctx["published_dir"]
    indexer.refresh_if_claimset_changed(ctx["conn"], None, out, BASE, "0.40.1")
    cat = planning.catalogue()
    if not cat["guides"]:                                   # a claimset older than 0.42.6 carries none
        assert not (out / "study-planning").exists()
        return
    name = next(iter(cat["guides"]))
    assert (out / "study-planning" / f"{name}.md").read_text() == cat["guides"][name]["text"]
    assert (out / "study-planning" / "index.html").exists()
    assert (out / "study-planning" / "message.txt").read_text() == planning.message(BASE, cat)
    lab = (out / "lab.html").read_text()
    assert 'id="plan"' in lab and 'data-copy="plan-prompt"' in lab and "do not plan from memory" in lab
    assert '<a href="/study-planning/message.txt"\ndownload="entrylib-study-planning-message.txt">' in lab
    assert f"/study-planning/{name}</loc>" in site.sitemap([], BASE)
    caddy = (Path(__file__).resolve().parent.parent / "deploy" / "Caddyfile").read_text()
    assert " /study-planning /study-planning/* " in caddy and "/study-planning/*.md" in caddy
    assert f"{BASE}/study-planning/" in reading.llms_txt(BASE)
