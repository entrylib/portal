"""The website for people (design §7.4): the page shell, the claimset pages, the home page and the other pages, the
citation files and the feed.

The claimset itself is rendered by the claimset package (`claimset.html.render_parts`); this module supplies the page
around it. Every value taken from a claimset is escaped; nothing submitted is rendered as HTML. Pages carry no scripts.

The indexer writes all of it as static files at publication and when the app starts (`write_site`); search is the one
page the app renders, on request (`search_page`).
"""

import hashlib
import html
import os
import re
import shutil
from importlib import resources
from pathlib import Path

from claimset import html as cshtml

from . import ids

SITE = "EntryLib"
CONTACT = "mail@entrylib.org"
SOURCE_CODE = "https://github.com/entrylib/portal"
CLAIMSET_REPO = "https://github.com/entrylib/claimset"

#: How many claimsets the home page lists.
RECENT = 10
#: How many entries the feed carries.
FEED_ENTRIES = 30

NAV = [("/search", "Read", "read"), ("/lab", "Lab", "lab"), ("/agents", "For agents", "agents"),
       ("/about", "About", "about")]
FOOTER = [("/about", "About"), ("/privacy", "Privacy"), ("/removal", "Removal requests"), ("/spec/", "Specification"),
          (SOURCE_CODE, "Source code"), (f"mailto:{CONTACT}", CONTACT)]

#: The fixed pages: address -> (file under static/pages, title, active nav item, description).
PAGES = {
    "lab": ("lab.html", "claimset-lab", "lab",
            "claimset-lab keeps the record of research while an agent does it, so that anyone can check it."),
    "about": ("about.html", "About EntryLib", "about",
              "What EntryLib is, what an entry is, who answers for it, and who runs the site."),
    "agents": ("agents.html", "For agents", "agents",
               "The MCP server, the API, the formats and the limits for programs and AI agents."),
    "privacy": ("privacy.html", "Privacy", None, "What EntryLib records about people, and why."),
    "removal": ("removal.html", "Retraction and removal", None, "How an entry is retracted or removed."),
}

STATUS_LABELS = {"active": "active", "corrected": "corrected", "retracted": "retracted", "withdrawn": "withdrawn",
                 "expression_of_concern": "expression of concern"}
STATUS_CLASS = {"active": "ok", "corrected": "warn", "retracted": "bad", "withdrawn": "bad",
                "expression_of_concern": "bad"}

TERM_MARKUP = re.compile(r"\[\[D\d+:([^\]]*)\]\]")


def esc(x):
    return html.escape("" if x is None else str(x), quote=True)


def plain(text):
    return TERM_MARKUP.sub(r"\1", text or "")


def _static(name):
    return resources.files("portal") / "static" / name


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def fingerprint():
    """A hash of everything here that shapes a page: when it changes, the pages are written again."""
    h = hashlib.sha256(Path(__file__).read_bytes())
    for name in ("site.css",):
        h.update(_static(name).read_bytes())
    for f in sorted((Path(str(_static("pages")))).glob("*.html")):
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


# --- the shell --------------------------------------------------------------------------------------------------------

def _header(active):
    links = "".join(f'<a href="{href}"' + (' aria-current="page"' if key == active else "") + f">{label}</a>"
                    for href, label, key in NAV)
    submit = '<a class="button" href="/submit">Submit a claimset</a>'
    return (f'<header class="site-header"><div class="wrap">'
            f'<a class="logo" href="/">{SITE}</a>'
            f'<nav class="site-nav" aria-label="Site">{links}{submit}</nav>'
            f'<details class="site-menu"><summary>Menu</summary><nav aria-label="Site">{links}{submit}</nav></details>'
            "</div></header>")


def _footer():
    links = "".join(f'<a href="{esc(href)}">{esc(label)}</a>' for href, label in FOOTER)
    return f'<footer class="site-footer"><div class="wrap">{links}</div></footer>'


def shell(title, main, *, active=None, description="", head="", canonical=None):
    """A whole page: head, site header, `main` (HTML), footer."""
    full = title if title == SITE else f"{title} · {SITE}"
    meta = f'<meta name="description" content="{esc(description)}">' if description else ""
    canon = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ""
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(full)}</title>{meta}{canon}"
            '<link rel="stylesheet" href="/fonts/fonts.css"><link rel="stylesheet" href="/claimset.css">'
            '<link rel="stylesheet" href="/site.css">'
            f'<link rel="alternate" type="application/atom+xml" title="{SITE}: recently published" href="/feed.xml">'
            f"{head}</head>\n<body>{_header(active)}<main>{main}</main>{_footer()}</body></html>\n")


# --- facts about a claimset -------------------------------------------------------------------------------------------

def _people(doc, position):
    return [c for c in doc.get("contributors") or []
            if isinstance(c, dict) and position in (c.get("positions") or [])]


def _humans(doc, position):
    return [c for c in _people(doc, position) if c.get("type") != "agent"]


def _claims(doc):
    return [c for c in doc.get("claims") or [] if isinstance(c, dict)]


def _principal(doc):
    by = {c.get("id"): c for c in _claims(doc)}
    ids_ = [x for x in (doc["paper"].get("contributions") or []) if x in by]
    return [by[x] for x in ids_] or [c for c in _claims(doc) if c.get("role") == "principal"]


def _year(doc):
    return str(doc["paper"].get("date") or "")[:4]


def _split_name(name):
    """('Svetunkov', 'Ivan') from 'Ivan Svetunkov'; a name given as 'Surname, Given' is kept as it is."""
    name = (name or "").strip()
    if "," in name:
        last, first = name.split(",", 1)
        return last.strip(), first.strip()
    parts = name.split()
    return (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (name, "")


def _initials(given):
    return " ".join(p[0] + "." for p in re.split(r"[\s.]+", given) if p)


def cited_people(doc):
    """Whom a citation names, and whether they are named as guarantor: the human authors of a native or lab entry,
    else (and for a converted entry) the guarantor."""
    authors = _humans(doc, "author")
    if authors and not isinstance(doc["paper"].get("converted_from"), dict):
        return authors, False
    return _people(doc, "guarantor"), True


def _source(doc):
    cf = doc["paper"].get("converted_from")
    if not isinstance(cf, dict) or not cf.get("source_id"):
        return None
    sid = str(cf["source_id"])
    return f"doi:{sid}" if cf.get("id_type", "doi") == "doi" and not sid.startswith("doi:") else sid


def _source_authors(doc):
    cf = doc["paper"].get("converted_from")
    names = [_split_name(a.get("name"))[0] for a in (cf or {}).get("source_authors") or [] if isinstance(a, dict)]
    names = [n for n in names if n]
    if len(names) > 3:
        return f"{names[0]} et al."
    return names[0] if len(names) == 1 else (", ".join(names[:-1]) + " and " + names[-1] if names else "")


def citation_text(doc, base_url):
    """The plain-text citation of a version."""
    p = doc["paper"]
    people, as_guarantor = cited_people(doc)
    names = []
    for c in people:
        last, given = _split_name(c.get("name"))
        names.append(f"{last}, {_initials(given)}".rstrip(", ") if given else last)
    who = ", ".join(names[:-1]) + (", & " if len(names) > 2 else " & ") + names[-1] if len(names) > 1 else \
        (names[0] if names else SITE)
    if as_guarantor and people:
        who += " (guarantor)"
    key, n = ids.url_key(p["id"]), p.get("version")
    src = _source(doc)
    title = p.get("title", "")
    if src:
        title += f" [Claimset converted from {src}]"
    return f"{who} ({_year(doc)}). {title}. {SITE}. {p['id']}@v{n}. {base_url}/p/{key}@v{n}"


def _bib_escape(s):
    s = str(s or "")
    s = s.replace("\\", r"\textbackslash{}")
    s = re.sub(r"([{}&%$#_])", r"\\\1", s)
    return s.replace("~", r"\textasciitilde{}").replace("^", r"\textasciicircum{}")


def bibtex(doc, base_url):
    p = doc["paper"]
    key, n = ids.url_key(p["id"]), p.get("version")
    people, _ = cited_people(doc)
    authors = " and ".join(_bib_escape(", ".join(x for x in _split_name(c.get("name")) if x)) for c in people)
    fields = [("title", _bib_escape(p.get("title"))), ("author", authors), ("year", _year(doc)),
              ("howpublished", f"{SITE}, claimset {p['id']}@v{n}"), ("url", f"{base_url}/p/{key}@v{n}")]
    src = _source(doc)
    if src:
        fields.append(("note", "Converted from " + _bib_escape(src)))
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v)
    return f"@misc{{entrylib{key}v{n},\n{body}\n}}\n"


def ris(doc, base_url):
    p = doc["paper"]
    key, n = ids.url_key(p["id"]), p.get("version")
    people, _ = cited_people(doc)
    lines = ["TY  - GEN", f"TI  - {p.get('title', '')}"]
    lines += [f"AU  - {', '.join(x for x in _split_name(c.get('name')) if x)}" for c in people]
    lines += [f"PY  - {_year(doc)}", f"DA  - {str(p.get('date') or '').replace('-', '/')}", f"PB  - {SITE}",
              f"ID  - {p['id']}@v{n}", f"UR  - {base_url}/p/{key}@v{n}"]
    src = _source(doc)
    if src:
        lines.append(f"N1  - Converted from {src}")
    lines.append("ER  - ")
    return "\r\n".join(line.replace("\r", " ").replace("\n", " ") for line in lines) + "\r\n"


# --- claimset page ----------------------------------------------------------------------------------------------------

def lab_summary(events):
    """What the header says about a lab record: counts of its hypotheses, planned tests, deviations and runs."""
    from claimset.lab import summary
    try:
        s = summary.build(events)
    except Exception:  # noqa: BLE001 - a record the summary cannot read still links; the counts are left out
        return None
    counts = s.get("counts") or {}
    planned = sum(1 for p in s.get("plans") or [] if p.get("kind") == "confirmatory")
    parts = [(len(s.get("hypotheses") or []), "hypothesis", "hypotheses"), (planned, "planned test", "planned tests"),
             (counts.get("deviation", 0), "deviation from plans", "deviations from plans"),
             (counts.get("run", 0), "run", "runs")]
    return ", ".join(f"{n} {one if n == 1 else many}" for n, one, many in parts)


def _status(p):
    status = p.get("status") or "active"
    label = esc(STATUS_LABELS.get(status, status))
    return f'<span class="status status-{STATUS_CLASS.get(status, "warn")}">{label}</span>'


def _notice(p):
    n = p.get("status_notice")
    if not isinstance(n, dict) or (p.get("status") or "active") == "active":
        return ""
    who = n.get("issued_by")
    who = who.get("name") if isinstance(who, dict) else who
    bits = [esc(n.get("date")), esc(who)]
    return (f'<div class="notice notice-{STATUS_CLASS.get(p.get("status"), "warn")}" role="note">'
            f'<p><strong>{esc(STATUS_LABELS.get(p.get("status"), p.get("status")))}</strong>'
            f'{" · " + " · ".join(b for b in bits if b) if any(bits) else ""}</p>'
            f'<p>{esc(n.get("statement"))}</p></div>')


def _origin_line(doc, origin, lab):
    if origin == "lab":
        rec = ""
        if lab and lab.get("copy"):
            rec = f'<a href="{esc(lab["copy"])}">Lab record</a>'
            if lab.get("summary"):
                rec += f": {esc(lab['summary'])}"
            if lab.get("verified"):                     # the registry's copy, checked before publication
                rec += " · hash chain verified"
        return f'<p class="origin-line">Made with <a href="/lab">claimset-lab</a>.{" " + rec if rec else ""}</p>'
    if origin.startswith("lab"):
        return ('<p class="origin-line">Made with <a href="/lab">claimset-lab</a>; the record is kept for audit, '
                "not public.</p>")
    if origin == "converted":
        src, by = _source(doc), _source_authors(doc)
        link = esc(src)
        if src and src.startswith("doi:"):
            link = f'<a href="https://doi.org/{esc(src[4:])}">{esc(src)}</a>'
        return (f'<p class="origin-line">Made from a published paper, {esc(by) + ", " if by else ""}{link}. '
                "The conversion guarantor answers for its faithfulness to the paper.</p>")
    return ""


def _panel(doc, parts, base_url, key):
    p = doc["paper"]
    n = p.get("version")
    lights = parts["lights"]
    names = {"green": "checkable", "amber": "not checkable", "red": "unsupported"}
    light_rows = "".join(f'<li><span class="light light-{k}"></span>{lights.get(k, 0)} {v}</li>'
                         for k, v in names.items())
    cite = esc(citation_text(doc, base_url))
    original = ""
    src = _source(doc)
    if src and src.startswith("doi:"):
        original = (f'<p class="small">Original paper: <a href="https://doi.org/{esc(src[4:])}">{esc(src)}</a>'
                    "</p>")
    return (f'<aside class="panel" aria-label="About this entry">'
            f'<div class="panel-row"><h2>Quality</h2><p class="score">–</p>'
            f'<p class="small"><a href="/about#quality">How it is computed</a></p></div>'
            f'<div class="panel-row"><h2>Claims</h2><ul class="lights">{light_rows}</ul></div>'
            f'<div class="panel-row"><h2>Cite</h2><p class="small"><code>{esc(p["id"])}@v{n}</code></p>'
            f'<details class="cite"><summary>Citation</summary><p class="cite-text">{cite}</p></details>'
            f'<p class="small"><a href="/p/{key}@v{n}.bib" download>BibTeX</a> · '
            f'<a href="/p/{key}@v{n}.ris" download>RIS</a></p>{original}</div>'
            f'<div class="panel-row"><h2>For models</h2><p class="small"><a href="/p/{key}@v{n}.json">JSON</a> · '
            f'<a href="/p/{key}@v{n}.txt">Reading view</a></p></div></aside>')


def _versions(listing, key, current):
    rows = []
    for v in reversed(listing):
        n = v["version"]
        label = f"Version {n}" + (" (this page)" if n == current else "")
        link = label if n == current else f'<a href="/p/{key}@v{n}">{label}</a>'
        bits = [esc(v.get("date")), esc(STATUS_LABELS.get(v.get("status"), v.get("status")))]
        if v.get("changes"):
            bits.append(esc(v["changes"]))
        rows.append(f"<li>{link} · {' · '.join(b for b in bits if b)}</li>")
    return (f'<section class="cs-section" id="versions"><h2>Versions</h2><ul class="versions">{"".join(rows)}</ul>'
            "<p class=\"cs-note\">Every version is kept in the public registry "
            '(<a href="https://github.com/entrylib/registry">github.com/entrylib/registry</a>).</p></section>')


def claimset_page(doc, *, base_url, listing, lab=None, file_url=None, current=None):
    """The page of one version of a claimset. `listing`: its versions (versions.json entries); `lab`: {copy,
    summary} when the registry holds its lab record; `current`: the claimset's current version number."""
    p = doc["paper"]
    key, n = ids.url_key(p["id"]), p.get("version")
    parts = cshtml.render_parts(doc, file_url=file_url)
    origin = parts["origin"]
    # The subfield is an OpenAlex ID; it is shown once the site has the subfields' names.
    top = [f'<span class="origin">{esc(origin)}</span>', _status(p), f'<span class="id">{esc(p["id"])}</span>',
           f"version {esc(n)} · {esc(p.get('date'))}"]
    newer = ""
    if current and current != n:
        newer = (f'<p class="notice notice-warn">This is version {esc(n)}. '
                 f'<a href="/p/{key}">The current version is {esc(current)}</a>.</p>')
    nav = parts["nav"].replace("</ol></nav>", f'<li><a href="#versions">Versions</a> '
                                              f'<span class="count">{len(listing)}</span></li></ol></nav>')
    main = (f'<div class="cs-page"><div class="entry-head"><div class="cs-header">'
            f'<p class="entry-top">{" · ".join(top)}</p>{newer}{_notice(p)}{parts["header"]}'
            f'{_origin_line(doc, origin, lab)}</div>{_panel(doc, parts, base_url, key)}</div>'
            f'<div class="cs-layout">{nav}<article class="cs-body">{parts["body"]}'
            f'{_versions(listing, key, n)}</article></div></div>')
    first = _principal(doc)[:1]
    description = plain(first[0].get("statement")) if first else ""
    head = (f'<link rel="alternate" type="application/json" href="/p/{key}@v{n}.json">'
            f'<link rel="alternate" type="text/plain" href="/p/{key}@v{n}.txt">'
            f'<link rel="alternate" type="application/x-bibtex" href="/p/{key}@v{n}.bib">')
    canonical = f"{base_url}/p/{key}" if not current or current == n else f"{base_url}/p/{key}@v{n}"
    return shell(p.get("title", ""), main, active="read", description=description, head=head, canonical=canonical)


# --- cards, home, all, feed -------------------------------------------------------------------------------------------

def card(doc):
    """A claimset as a card: the home page, the list of all claimsets and search results."""
    p = doc["paper"]
    key = ids.url_key(p["id"])
    top = [f'<span class="origin">{esc(cshtml.origin(doc))}</span>', esc(p["id"]), esc(p.get("date"))]
    status = p.get("status") or "active"
    if status != "active":
        top.append(_status(p))
    if (p.get("version") or 1) > 1:
        top.append(f"v{esc(p['version'])}")
    who = ", ".join(esc(g.get("name")) for g in _people(doc, "guarantor"))
    src = _source_authors(doc)
    if src:
        who += f" · from {esc(src)}"
    principal = _principal(doc)
    first = f'<p class="card-claim">{esc(plain(principal[0].get("statement")))}</p>' if principal else ""
    claims = _claims(doc)
    counts = [f"{len(principal)} principal claim{'s' if len(principal) != 1 else ''}",
              f"{len(claims)} claim{'s' if len(claims) != 1 else ''}"]
    ev = len([e for e in doc.get("evidence") or [] if isinstance(e, dict)])
    if ev:
        counts.append(f"{ev} piece{'s' if ev != 1 else ''} of evidence")
    return (f'<article class="card"><p class="card-top">{" · ".join(top)}</p>'
            f'<h3><a href="/p/{key}">{esc(p.get("title"))}</a></h3>'
            + (f'<p class="card-who">{who}</p>' if who else "") + first
            + f'<p class="card-counts">{" · ".join(counts)}</p></article>')


def _search_form(q="", kind="papers", big=False):
    cls = "search search-big" if big else "search"
    hidden = f'<input type="hidden" name="kind" value="{esc(kind)}">' if kind != "papers" else ""
    return (f'<form class="{cls}" action="/search" method="get" role="search">'
            f'<label class="visually-hidden" for="q">Search claimsets</label>'
            f'<input id="q" name="q" type="search" value="{esc(q)}" placeholder="Search claimsets">{hidden}'
            '<button type="submit">Search</button></form>')


def home(docs):
    """The home page; `docs` are the current versions, newest first."""
    cards = "".join(card(d) for d in docs[:RECENT]) or '<p class="muted">Nothing is published yet.</p>'
    intro = _static("pages/home.html").read_text(encoding="utf-8")
    main = (f'<div class="wrap home">{intro.replace("{search}", _search_form(big=True))}'
            f'<section class="recent"><div class="section-head"><h2>Recently published</h2>'
            f'<p><a href="/all">All claimsets</a> · <a href="/feed.xml">RSS</a></p></div>'
            f'<div class="cards">{cards}</div></section></div>')
    return shell(SITE, main, description="EntryLib publishes research in a form that both people and AI can read "
                 "and check: each paper broken down into its findings, each with what it rests on.")


def all_page(docs):
    cards = "".join(card(d) for d in docs) or '<p class="muted">Nothing is published yet.</p>'
    main = (f'<div class="wrap"><h1>All claimsets</h1><p class="muted">{len(docs)} '
            f'claimset{"s" if len(docs) != 1 else ""}, newest first · <a href="/feed.xml">RSS</a> · '
            f'<a href="/index.jsonl">index.jsonl</a></p><div class="cards">{cards}</div></div>')
    return shell("All claimsets", main, active="read")


def feed(docs, base_url):
    """An Atom feed of the latest versions."""
    updated = max((str(d["paper"].get("date")) for d in docs), default="2026-01-01")
    entries = []
    for d in docs[:FEED_ENTRIES]:
        p = d["paper"]
        key, n = ids.url_key(p["id"]), p.get("version")
        principal = _principal(d)
        summary = plain(principal[0].get("statement")) if principal else ""
        authors = "".join(f"<author><name>{esc(g.get('name'))}</name></author>" for g in _people(d, "guarantor"))
        entries.append(f"<entry><title>{esc(p.get('title'))}</title><id>{base_url}/p/{key}@v{n}</id>"
                       f'<link href="{base_url}/p/{key}@v{n}"/><updated>{esc(p.get("date"))}T00:00:00Z</updated>'
                       f"{authors}<summary>{esc(summary)}</summary></entry>")
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<title>{SITE}: recently published</title><id>{base_url}/feed.xml</id>"
            f'<link rel="self" href="{base_url}/feed.xml"/><link href="{base_url}/"/>'
            f"<updated>{esc(updated)}T00:00:00Z</updated>{''.join(entries)}</feed>\n")


# --- fixed pages ------------------------------------------------------------------------------------------------------

def fixed_page(name, base_url):
    file, title, active, description = PAGES[name]
    body = _static(f"pages/{file}").read_text(encoding="utf-8").replace("{base}", base_url)
    return shell(title, f'<div class="wrap prose">{body}</div>', active=active, description=description)


def spec_index():
    """The specifications as published with the installed claimset package (design §7.1; portal issue #46)."""
    rows = []
    for f in _spec_files():
        rows.append(f'<li><a href="/spec/{esc(f.name)}">{esc(_spec_title(f))}</a> <span class="muted">'
                    f"({esc(f.name)})</span></li>")
    main = ('<div class="wrap prose"><h1>Specifications</h1><p>The Claimset format, the lab record and the revision '
            "of published claimsets, as plain text (Markdown). They follow the claimset package this site runs; "
            f'their history is in <a href="{CLAIMSET_REPO}">{CLAIMSET_REPO.removeprefix("https://")}</a>.</p>'
            f'<ul class="spec-list">{"".join(rows)}</ul></div>')
    return shell("Specifications", main)


def _spec_dir():
    return Path(str(resources.files("claimset") / "data" / "spec"))


def _spec_files():
    d = _spec_dir()
    return sorted(d.glob("*.md")) + sorted((d / "extensions").glob("*.md")) if d.exists() else []


def _spec_title(f):
    first = f.read_text(encoding="utf-8").split("\n", 1)[0].lstrip("# ").strip()
    return first or f.stem


# --- search -----------------------------------------------------------------------------------------------------------

#: Results per search page.
SEARCH_PAGE = 20


def search_page(q, kind, results=None, error=None, offset=0, limit=SEARCH_PAGE, files=None):
    """The search page. `results`: the search API's answer; `files`: {paper id: current file} for paper cards."""
    tabs = "".join(
        f'<a href="/search?q={html.escape(q, quote=True)}&amp;kind={k}"'
        + (' aria-current="page"' if k == kind else "") + f">{label}</a>"
        for k, label in (("papers", "Claimsets"), ("claims", "Claims")))
    out = [f'<div class="wrap"><h1>Read</h1>{_search_form(q, kind)}<nav class="tabs" aria-label="Search in">{tabs}'
           "</nav>"]
    if error:
        out.append(f'<p class="notice notice-warn">{esc(error)}</p>')
    elif results is None:
        out.append('<p class="muted">Search the claims and claimsets published on EntryLib, or see '
                   '<a href="/all">all claimsets</a>.</p>')
    else:
        rows = results.get("results") or []
        if not rows:
            out.append('<p class="muted">Nothing found. Search matches words, not meaning: try the words a paper '
                       "would use, and synonyms.</p>")
        elif kind == "papers":
            out.append('<div class="cards">' + "".join(card(files[r["id"]]) for r in rows if r["id"] in (files or {}))
                       + "</div>")
        else:
            items = []
            for r in rows:
                key = ids.url_key(r["paper"])
                meta = [esc(r["claim"]), esc(r.get("type")), esc(r.get("role"))]
                items.append(f'<li class="result"><p class="card-top">{" · ".join(m for m in meta if m)}</p>'
                             f'<p class="card-claim">{esc(plain(r.get("statement")))}</p>'
                             f'<p class="card-who"><a href="/p/{key}#{esc(r["claim"])}">{esc(r.get("paper_title"))}'
                             f'</a> · {esc(r["paper"])}@v{esc(r.get("version"))}</p></li>')
            out.append(f'<ol class="results">{"".join(items)}</ol>')
        more = []
        if offset > 0:
            more.append(f'<a href="/search?q={esc(q)}&amp;kind={kind}&amp;offset={max(0, offset - limit)}">Previous'
                        "</a>")
        if len(rows) == limit:
            more.append(f'<a href="/search?q={esc(q)}&amp;kind={kind}&amp;offset={offset + limit}">Next</a>')
        if more:
            out.append(f'<p class="pager">{" · ".join(more)}</p>')
    out.append("</div>")
    title = f"{q} · Read" if q else "Read"
    return shell(title, "".join(out), active="read")


def submit_page(body):
    """The upload page: its form and script (static/submit.html) in the site's page."""
    return shell("Submit a claimset", f'<div class="wrap prose">{body}</div>', description="Submit a claimset to "
                 "EntryLib: upload a package or a claimset file; its guarantor confirms with ORCID.")


# --- writing ----------------------------------------------------------------------------------------------------------

IMAGE_MAGIC = [(b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif")]


def image_type(path):
    """The extension of an image file by its content (PNG, JPEG, GIF, WebP, SVG), or None."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(512)
    except OSError:
        return None
    for magic, ext in IMAGE_MAGIC:
        if head.startswith(magic):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    text = head.lstrip().lower()
    if text.startswith(b"<svg") or (text.startswith(b"<?xml") and b"<svg" in text):
        return "svg"
    return None


def file_url_for(published_dir, base_url):
    """The `file_url` for claimset.html: an artefact stored here (its uri is <base>/files/<sha256>) whose file is an
    image is shown from /img/<sha256>.<ext>, a link to the stored file written once, with its type in its name."""
    published_dir = Path(published_dir)
    prefix = f"{base_url.rstrip('/')}/files/"

    def file_url(a):
        uri = a.get("uri")
        if not isinstance(uri, str) or not uri.startswith(prefix):
            return None
        digest = uri[len(prefix):]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None
        stored = published_dir / "files" / digest
        ext = image_type(stored)
        if ext is None:
            return None
        shown = published_dir / "img" / f"{digest}.{ext}"
        if not shown.exists():
            shown.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(stored, shown)
            except OSError:
                shutil.copyfile(stored, shown)
        return f"/img/{digest}.{ext}"
    return file_url


def write_claimset(published_dir, base_url, key, docs, listing, labs):
    """The pages and citation files of one claimset: every version, and the current one at /p/<key>."""
    p = Path(published_dir) / "p"
    file_url = file_url_for(published_dir, base_url)
    current = max(docs)
    for n, doc in docs.items():
        page = claimset_page(doc, base_url=base_url, listing=listing, lab=labs.get(n), file_url=file_url,
                             current=current)
        _write(p / f"{key}@v{n}.html", page)
        _write(p / f"{key}@v{n}.bib", bibtex(doc, base_url))
        _write(p / f"{key}@v{n}.ris", ris(doc, base_url))
        if n == current:
            _write(p / f"{key}.html", page)
            _write(p / f"{key}.bib", bibtex(doc, base_url))
            _write(p / f"{key}.ris", ris(doc, base_url))


def write_listings(published_dir, base_url, docs):
    """The pages that list claimsets: home, all claimsets and the feed. `docs`: current versions, newest first."""
    published_dir = Path(published_dir)
    _write(published_dir / "index.html", home(docs))
    _write(published_dir / "all.html", all_page(docs))
    _write(published_dir / "feed.xml", feed(docs, base_url))


def write_fixed(published_dir, base_url):
    """The pages and files that do not depend on what is published: fixed pages, stylesheets, fonts, images and the
    specifications."""
    published_dir = Path(published_dir)
    for name in PAGES:
        _write(published_dir / f"{name}.html", fixed_page(name, base_url))
    _write(published_dir / "site.css", _static("site.css").read_text(encoding="utf-8"))
    _write(published_dir / "claimset.css", cshtml.stylesheet())
    for folder in ("fonts", "img"):
        src = Path(str(_static(folder)))
        for f in src.iterdir():
            if f.is_file():
                dest = published_dir / folder / f.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dest)
    spec = published_dir / "spec"
    _write(spec / "index.html", spec_index())
    for f in _spec_files():
        _write(spec / f.name, f.read_text(encoding="utf-8"))
