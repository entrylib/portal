"""EntryLib's good practice for planning a study on entrylib.org, and the message a researcher gives their assistant
on /lab to plan a study with it. Each guide the installed claimset package carries (from
https://github.com/entrylib/study-planning) is written as a page and as plain text, so that an assistant can read it
whatever it can do: open a page, fetch a text, or find it by search.

    /study-planning/                          the guides, with what a guide holds
    /study-planning/<guide>, <guide>.md       one guide, as a page and as text
    /study-planning/message.txt               the full message /lab offers to download and attach: the request, then
                                              every guide

/lab shows and copies the short message (short()): the request, with where to read the guides (the MCP tool `guide`,
the guides' addresses, the package), and to stop rather than plan from memory when none can be read.

Written by the indexer when the app starts, from the claimset package, like the skills (skills.py): a new claimset
release publishes the guides it carries. A claimset too old to carry them publishes nothing here, and the messages
name the guides' repository instead. The words around the guides (the request, the pages) are the portal's own.
"""

import json
import re
from importlib import resources
from pathlib import Path

from . import markdown

REPOSITORY = "https://github.com/entrylib/study-planning"


def planning_dir():
    return Path(str(resources.files("claimset") / "data" / "study-planning"))


def catalogue(root=None):
    """{"readme": text or None, "source": SOURCE.json or {}, "guides": {name: {text, title, version}}} of the guides
    under `root` (default: the installed package's copy). Empty when the package carries none."""
    root = Path(root) if root else planning_dir()
    if not (root / "SOURCE.json").is_file():
        return {"readme": None, "source": {}, "guides": {}}
    guides = {}
    for f in sorted(root.glob("*.md")):
        if f.name == "README.md":
            continue
        text = f.read_text(encoding="utf-8")
        title = re.search(r"^# (.+)$", text, re.M)
        version = re.search(r"^Version (\S+)", text, re.M)
        guides[f.stem] = {"text": text, "title": title[1].strip() if title else f.stem,
                          "version": version[1] if version else ""}
    readme = root / "README.md"
    return {"readme": readme.read_text(encoding="utf-8") if readme.is_file() else None,
            "source": json.loads((root / "SOURCE.json").read_text(encoding="utf-8")), "guides": guides}


def paths(cat):
    """The guides' addresses, for the sitemap."""
    return ["/study-planning/"] + [f"/study-planning/{n}" for n in cat["guides"]] if cat["guides"] else []


def _from(cat):
    s = cat["source"]
    commit = (s.get("commit") or "")[:7]
    return (f'From <a href="{REPOSITORY}">entrylib/study-planning</a>'
            + (f' at <a href="{REPOSITORY}/tree/{s["commit"]}">{commit}</a> ({markdown.esc(s.get("date", ""))})'
               if commit else "") + ", as the installed claimset package carries it.")


def page(shell, name, entry, cat):
    """The page of one guide, in the site's `shell`."""
    html, _ = markdown.convert(entry["text"])
    text = f"/study-planning/{name}.md"
    main = (f'<div class="wrap spec"><p class="entry-top"><a href="/study-planning/">Planning a study</a> · '
            f'<code>{name}</code> · <a href="{text}">Plain text</a></p>'
            f'<article class="spec-body prose-like">{html}</article>'
            f'<p class="muted small">{_from(cat)} Changes are proposed there, with the references that support them.'
            f"</p></div>")
    head = f'<link rel="alternate" type="text/markdown" href="{text}">'
    return shell(entry["title"], main, head=head, canonical=f"/study-planning/{name}", script="/page.js",
                 description=f"EntryLib's good practice for planning a study: {entry['title']}. Defaults for the "
                             f"choices a study makes, each with its reason and references.")


def index(shell, cat):
    """/study-planning/: the guides, then what a guide holds and how it changes (those sections of the repository's
    README; its opening and its list of guides are the page's own)."""
    rows = "".join(f'<li><a href="/study-planning/{n}">{markdown.esc(e["title"])}</a> '
                   f'<span class="muted">(v{markdown.esc(e["version"])}, <a href="/study-planning/{n}.md">text</a>)'
                   f"</span></li>" for n, e in cat["guides"].items())
    readme = ""
    if cat["readme"]:
        start = cat["readme"].find("\n## What a guide holds")
        text = cat["readme"][start:] if start >= 0 else ""
        text = re.sub(r"\]\((\w[\w-]*)\.md\)", r"](/study-planning/\1)", text)
        text = text.replace("`LICENSE`", f"[LICENSE]({REPOSITORY}/blob/main/LICENSE)")    # a file of the repository
        readme, _ = markdown.convert(text) if text else ("", None)
    main = ('<div class="wrap prose"><h1>Good practice for planning a study</h1>'
            "<p>Defaults for the choices a study makes before it is run: which measure, which test, which design fits "
            "a kind of study, and why. Each default cites the papers it rests on. They are proposals, never "
            "requirements: a study may choose otherwise, and says why. An assistant planning a study with you "
            'proposes them and asks you about the rest (<a href="/lab#plan">plan a study with any assistant</a>).</p>'
            f'<ul class="spec-list">{rows}</ul>'
            f'<article class="prose-like">{readme}</article><p class="muted small">{_from(cat)}</p></div>')
    return shell("Good practice for planning a study", main, canonical="/study-planning/",
                 description="Defaults for designing and evaluating research, each with its reason and references: "
                             "measures, tests and designs by kind of study.")


def short(base_url, cat=None):
    """The message /lab shows and copies: plan the study with me, one choice at a time, from the guides; where to
    read them, in the order an assistant can use them (EntryLib's connector, an address, the package); and to stop
    if it can use none. It is short, so that it copies in every browser; the full message, with the guides in it, is
    downloaded instead (message())."""
    cat = catalogue() if cat is None else cat
    base = base_url.rstrip("/")
    web = (", ".join(f"{base}/study-planning/{n}.md" for n in cat["guides"]) if cat["guides"]
           else f"the .md files at {REPOSITORY}")
    return (
        "Help me plan a study before we run it. I will describe the question, the data or material, and what I "
        "want to compare or find out.\n\n"
        "Use EntryLib's good practice for planning a study, read from the first of these you can use:\n"
        f"1. EntryLib's connector (the MCP server at {base}/mcp): call its guide tool with name study-planning, then "
        "the guide that fits the study (for example study-planning/prediction).\n"
        f"2. The web: {web}.\n"
        "3. A terminal: pip install claimset, then claimset guide study-planning.\n"
        "If you can use none of these, tell me and stop: do not plan from memory. I will attach the guides instead."
        "\n\n" + _rules())


def _rules():
    return (
        "- Agree the design with me one choice at a time: what is measured or compared, the data, the measures, the "
        "test or analysis, the decision rule, the sample and when to stop.\n"
        "- When a guide entry fits, propose its default with its reason and its reference (for example "
        "study-planning/prediction#mean-forecasts) and ask whether I agree. When none fits, ask me openly, or "
        "propose a methodological source you can cite; never a choice you cannot justify.\n"
        "- A precedent is not a reason: that a well-known study or competition used a measure says what it did, not "
        "why it fits this study.\n"
        "- Do not decide for me. When I choose otherwise, record my choice and my reason.\n"
        "- End with the agreed plan as a list: each choice, what was chosen, and where it came from (me, a guide "
        "entry, a paper with its DOI). If the research is then done with an agent that can run commands, this list "
        "becomes the plan of its lab record (claimset lab plan --choice), recorded before any data is seen.\n")


def message(base_url, cat=None):
    """/study-planning/message.txt: the request, then every guide, so that an assistant that can open no address
    still has them. Without guides in the package, the short message alone."""
    cat = catalogue() if cat is None else cat
    if not cat["guides"]:
        return short(base_url, cat)
    base = base_url.rstrip("/")
    head = ("Help me plan a study before we run it. I will describe the question, the data or material, and what I "
            "want to compare or find out.\n\n"
            "Use EntryLib's good practice for planning a study: the guides follow this request, from "
            f"{REPOSITORY} (also at {base}/study-planning/). Plan only from them and from what I tell you, never "
            "from memory.\n\n" + _rules())
    parts = [head]
    if cat["readme"]:
        parts.append(f"===== WHAT A GUIDE HOLDS (study-planning README) =====\n\n{cat['readme'].strip()}\n")
    for name, entry in cat["guides"].items():
        parts.append(f"===== GUIDE study-planning/{name} (v{entry['version']}) =====\n\n{entry['text'].strip()}\n")
    return "\n".join(parts)


def write(published_dir, shell, write_file, base_url, root=None):
    """Write the guides' pages and texts under `published_dir`/study-planning, with the full message. Returns the
    catalogue; a package that carries no guides writes nothing."""
    out = Path(published_dir) / "study-planning"
    cat = catalogue(root)
    if not cat["guides"]:
        return cat
    for name, entry in cat["guides"].items():
        write_file(out / f"{name}.html", page(shell, name, entry, cat))
        write_file(out / f"{name}.md", entry["text"])
    if cat["readme"]:
        write_file(out / "README.md", cat["readme"])
    write_file(out / "index.html", index(shell, cat))
    write_file(out / "message.txt", message(base_url, cat))
    return cat
