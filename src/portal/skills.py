"""The claimset skills on entrylib.org, and the message an author gives their assistant on /convert. Each skill the
installed claimset package ships is written as a page and as plain text, so that an assistant can read it whatever
it can do: open a page, fetch a text, or find it by search. The message carries the skills themselves, so that an
assistant that can do none of these still has them.

    /skills/                                  every skill
    /skills/<name>, /skills/<name>.md         one skill, as a page and as text
    /convert/message.txt                      the full message /convert offers to download and attach: the
                                              request, then the skills it needs and an example claimset

/convert shows and copies the short message (short()): the request, with where to read the rules (the MCP tool
`guide`, the skills' addresses, the package), and to stop rather than write from memory when none can be read.

Written by the indexer when the app starts, from the claimset package, like the specifications (specs.py): a new
claimset release publishes its skills. The words around them (the request, the page) are the portal's own.
"""

import re
from importlib import resources
from pathlib import Path

from . import markdown

FRONTMATTER = re.compile(r"\A---\n(?P<meta>.*?)\n---\n", re.S)
#: The skill /convert sends an author's assistant to, and the skill it builds on.
FROM_PAPER, SUBMIT = "claimset-from-paper", "claimset-submit"
#: The example the message carries: a complete native claimset, as an author's paper becomes.
EXAMPLE = "submission-native.json"
#: Where a skill the installed package does not ship yet is read (the claimset repository's main branch, as text).
RAW = "https://raw.githubusercontent.com/entrylib/claimset/main/skills/{name}/SKILL.md"


def skills_dir():
    return Path(str(resources.files("claimset") / "data" / "skills"))


def examples_dir():
    return Path(str(resources.files("claimset") / "data" / "examples"))


def parse(text):
    """(description from the front matter, title, body without the front matter) of a skill's text."""
    m = FRONTMATTER.match(text)
    meta, body = (m["meta"], text[m.end():]) if m else ("", text)
    found = re.search(r"^description:\s*(.+)$", meta, re.M)
    title = re.search(r"^# (.+)$", body, re.M)
    return (found[1].strip() if found else ""), (title[1].strip() if title else ""), body


def catalogue(root=None):
    """{name: {text, title, description}} of the skills under `root` (default: the installed package's)."""
    root = Path(root) if root else skills_dir()
    found = {}
    for f in sorted(root.glob("*/SKILL.md")) if root.is_dir() else []:
        text = f.read_text(encoding="utf-8")
        description, title, _ = parse(text)
        found[f.parent.name] = {"text": text, "title": title or f.parent.name, "description": description}
    return found


def page(shell, name, entry):
    """The page of one skill, in the site's `shell`."""
    _, _, body = parse(entry["text"])
    html, _ = markdown.convert(body)
    text = f"/skills/{name}.md"
    main = (f'<div class="wrap spec"><p class="entry-top"><a href="/skills/">Skills</a> · <code>{name}</code> · '
            f'<a href="{text}">Plain text</a></p><article class="spec-body prose-like">{html}</article></div>')
    head = f'<link rel="alternate" type="text/markdown" href="{text}">'
    return shell(entry["title"], main, head=head, canonical=f"/skills/{name}", script="/page.js",
                 description=entry["description"][:300] or f"The {name} skill for agents.")


def index(shell, cat):
    rows = "".join(f'<li><a href="/skills/{n}"><code>{n}</code></a> {markdown.esc(e["title"])} '
                   f'<span class="muted">(<a href="/skills/{n}.md">text</a>)</span></li>' for n, e in cat.items())
    main = ('<div class="wrap prose"><h1>Skills</h1><p>The instructions an agent follows to write, submit, revise and '
            "review claimsets, from the claimset package. Each has a plain-text copy, for agents that fetch text. An "
            'author turning their own paper into a claimset starts at <a href="/convert">Convert your paper</a>.</p>'
            f'<ul class="spec-list">{rows}</ul></div>')
    return shell("Skills", main, description="The claimset skills: what an agent follows to write and submit a "
                                             "claimset.")


def complete(cat):
    """Whether the package ships both skills the message carries."""
    return FROM_PAPER in cat and SUBMIT in cat


def request(base_url, cat):
    """The words an author sends with their paper: what to do, where the rules are, and to stop rather than guess.
    With both skills in the package they follow the request; otherwise it names where to read them."""
    base = base_url.rstrip("/")
    rule = ("- Write the claimset only from what you have read: these skills, the example claimset and, if you can "
            "open it, the specification. Do not write it from memory and do not invent a format: use only the "
            "structure of the example and the fields these texts name, and ask me when you need something they do "
            "not give.\n" if complete(cat) else
            "- Write the claimset only from the skills and the specification. Do not write it from memory and do "
            "not invent a format: if you cannot read them, say so and stop.\n")
    where = ("The skills you need follow this request: claimset-from-paper first, then claimset-submit, which it "
             "builds on, then an example claimset." if complete(cat) else
             "Read the skills at " + " and ".join(f"{base}/skills/{n}.md" if n in cat else RAW.format(name=n)
                                                  for n in (FROM_PAPER, SUBMIT)) + ".")
    return (
        f"I am an author of the attached paper and want to publish it on EntryLib ({base}) as a claimset.\n\n"
        f"Follow the claimset-from-paper skill. {where} The specification is at {base}/spec/claimset.md (also as a "
        f"page at {base}/spec/claimset); if you can run commands, `pip install claimset` gives you all of it "
        "(`claimset guide claimset-from-paper`).\n\n"
        + rule +
        "- Ask me the skill's questions before you build anything.\n"
        "- Use only what the paper says: add nothing, drop no condition, and keep results where the method did "
        "worse.\n"
        "- Draft a plain-language summary of at most 150 words for me to approve.\n"
        "- Before submitting, give me every claim with where it comes from in the paper, so I can check it.\n"
        f"- Validate the file (the validate tool of {base}/mcp, or I upload it at {base}/submit, which checks it), "
        "and submit only when I say so.\n")


def message(base_url, cat, example=None):
    """/convert/message.txt: the request, then the skills it names and the example, so that an assistant that can
    open no address still has them. Without claimset-from-paper in the package, the request with addresses."""
    if not complete(cat):
        return request(base_url, cat)
    parts = [request(base_url, cat)]
    for name in (FROM_PAPER, SUBMIT):
        parts.append(f"===== SKILL {name} (from the claimset package) =====\n\n{parse(cat[name]['text'])[2].strip()}\n")
    if example:
        parts.append(f"===== EXAMPLE CLAIMSET ({EXAMPLE}, from the claimset package) =====\n\n{example.strip()}\n")
    return "\n".join(parts)


def short(base_url, cat):
    """The message /convert shows and copies: what to do, and where to read the rules, in the order an assistant can
    use them (EntryLib's connector, an address, the package), then to stop if it can use none. It is short, so that
    it copies in every browser; the full message, with the rules in it, is downloaded instead (message())."""
    base = base_url.rstrip("/")
    texts = " and ".join(f"{base}/skills/{n}.md" if n in cat else RAW.format(name=n) for n in (FROM_PAPER, SUBMIT))
    return (
        f"I am an author of the attached paper and want to publish it on EntryLib ({base}) as a claimset.\n\n"
        f"Follow the claimset-from-paper skill, which builds on claimset-submit. Read both before you build anything, "
        f"from the first of these you can use:\n"
        f"1. EntryLib's connector (the MCP server at {base}/mcp): call its guide tool with name claimset-from-paper, "
        f"then claimset-submit, and specification for the format.\n"
        f"2. The web: read {texts}, and the specification at {base}/spec/claimset.md.\n"
        "3. A terminal: pip install claimset, then claimset guide claimset-from-paper.\n"
        "If you can use none of these, tell me and stop: do not write a claimset from memory. I will attach the "
        "rules instead.\n\n"
        "- Write the claimset only from what you have read. Do not invent a format: use only the fields these texts "
        "name, and ask me when you need something they do not give.\n"
        "- Ask me the skill's questions before you build anything.\n"
        "- Use only what the paper says: add nothing, drop no condition, and keep results where the method did "
        "worse.\n"
        "- Draft a plain-language summary of at most 150 words for me to approve.\n"
        "- Before submitting, give me every claim with where it comes from in the paper, so I can check it.\n"
        f"- Validate the file (the validate tool of {base}/mcp, or I upload it at {base}/submit, which checks it), "
        "and submit only when I say so.\n")


def shown(base_url, cat=None):
    """The message as /convert shows and copies it: the short one (short())."""
    return short(base_url, catalogue() if cat is None else cat)


def paths(cat):
    """The skills' addresses, for the sitemap."""
    return ["/skills/"] + [f"/skills/{n}" for n in cat]


def write(published_dir, shell, write_file, base_url, root=None, examples=None):
    """Write the skills' pages and texts under `published_dir`/skills and the message of /convert."""
    out = Path(published_dir)
    cat = catalogue(root)
    for name, entry in cat.items():
        write_file(out / "skills" / f"{name}.html", page(shell, name, entry))
        write_file(out / "skills" / f"{name}.md", entry["text"])
    write_file(out / "skills" / "index.html", index(shell, cat))
    ex = Path(examples) if examples else examples_dir()
    example = (ex / EXAMPLE).read_text(encoding="utf-8") if (ex / EXAMPLE).exists() else None
    write_file(out / "convert" / "message.txt", message(base_url, cat, example))
    return cat


def guide(name=None, section=None, root=None, spec_text=None):
    """The text the MCP tool `guide` returns: the list of skills; one skill; or the specification, whole or one
    numbered section (`3.4`, with its subsections)."""
    cat = catalogue(root)
    if not name:
        return ("Skills: " + ", ".join(cat) + ". Ask for one by name, or for name='specification' (optionally a "
                "section such as '3.4'). Write a claimset only from these texts, never from memory.")
    if name == "specification":
        text = spec_text if spec_text is not None else _spec()
        return _section(text, section) if section else text
    if name not in cat:
        raise KeyError(f"no skill {name}: the skills are {', '.join(cat)}, and 'specification'")
    return cat[name]["text"]


def _spec():
    from . import specs
    entry = specs.catalogue()["claimset"]
    return entry["versions"][entry["current"]].read_text(encoding="utf-8")


def _section(text, number):
    """Section `number` of a Markdown specification, from its heading to the next heading of its level or above."""
    lines = text.split("\n")
    head = re.compile(rf"^(#+) {re.escape(number)}\.? ")
    start = next((i for i, line in enumerate(lines) if head.match(line)), None)
    if start is None:
        raise KeyError(f"the specification has no section {number}")
    level = len(head.match(lines[start])[1])
    end = next((i for i in range(start + 1, len(lines))
                if re.match(r"^(#+) ", lines[i]) and len(re.match(r"^(#+) ", lines[i])[1]) <= level), len(lines))
    return "\n".join(lines[start:end]).strip() + "\n"
