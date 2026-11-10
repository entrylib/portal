"""Index the registry: database rows and static files, made from the registry alone.

Publication writes a version to the registry and then calls `index_version`; `reindex` rebuilds everything from
the registry, so the database and the static files are always derived from the record (design §2, principle 4).

Static files, under the published directory:

    p/<key>.json, p/<key>.txt              the current version: published file and reading view
    p/<key>@v<n>.json, p/<key>@v<n>.txt    every version
    p/<key>/versions.json                  versions, dates, status, notices, lab record links
    p/<key>/v<n>/lab.jsonl                 the registry's copy of a version's lab record
    p/<key>/<claim>.json, .txt             the claim bundles of the current version (claimset spec §2.3)
    p/<key>.html, p/<key>@v<n>.html        the page for people (site.claimset_page), current and every version
    p/<key>.bib, .ris, p/<key>@v<n>.bib    citations
    img/<sha256>.<ext>                     packaged images shown on the pages (links to files/<sha256>)
    index.jsonl                            one paper card per claimset, current versions
    llms.txt                               the entry point for agents (reading.llms_txt)
    index.html, all.html, feed.xml         the home page, all claimsets and the Atom feed
    lab.html, about.html, ..., spec/       the fixed pages, stylesheets, fonts and specifications (at start)

Each version's claims and paper get the weighted text full-text search runs on (design §7.2).
"""

import json
import os
import re
import shutil
import unicodedata
from pathlib import Path

from claimset.claim import claim_bundle, render_claim
from claimset.render import render
from claimset.revision import doc_hash
from psycopg.types.json import Jsonb

from . import crossref, ids, notices, reading, site


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _is_assumption(claim):
    return any(isinstance(s, dict) and s.get("kind") == "assumption" for s in claim.get("support") or [])


MARKED_TERM = re.compile(r"\[\[(D\d+):")
TERM_MARKUP = re.compile(r"\[\[D\d+:([^\]]*)\]\]")


def plain(statement):
    """A statement as words, without its term markup: '[[D3:seasonal naive method]]' becomes 'seasonal naive
    method', so search finds the words and not the IDs."""
    return TERM_MARKUP.sub(r"\1", statement or "")


def title_key(title):
    """A title reduced for the duplicate check (design §4.5): case-folded, with punctuation and spacing removed."""
    text = unicodedata.normalize("NFKC", title or "").casefold()
    return "".join(re.findall(r"[^\W_]+", text))


def guarantor_ids(doc):
    """The ORCID iDs of a claimset's guarantor (one person since claimset spec v0.36)."""
    return sorted({c["orcid"] for c in doc.get("contributors") or []
                   if isinstance(c, dict) and "guarantor" in (c.get("positions") or []) and c.get("orcid")})


def _strings(x):
    """Every string in a value, in order."""
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [s for v in x.values() for s in _strings(v)]
    if isinstance(x, list):
        return [s for v in x for s in _strings(v)]
    return []


def claim_text(claim, defs):
    """The text a claim is also found by (weight B): the terms of the definitions its statement and `about` cite,
    and its scope."""
    cited = MARKED_TERM.findall(claim.get("statement") or "")
    cited += [v for v in _strings(claim.get("about")) if v in defs]
    terms = [defs[d].get("term", "") for d in dict.fromkeys(cited) if d in defs]
    return " ".join(terms + _strings(claim.get("scope")))


def paper_texts(doc):
    """The weighted texts a paper is found by: title (A); keywords and principal claims (B); every claim and
    definition (C)."""
    paper = doc["paper"]
    claims = {c.get("id"): c for c in doc.get("claims") or [] if isinstance(c, dict)}
    keywords = (paper.get("classification") or {}).get("keywords") or paper.get("keywords") or []
    principal = [plain(claims[c].get("statement")) for c in paper.get("contributions") or [] if c in claims]
    rest = [plain(c.get("statement")) for c in claims.values()]
    rest += [f"{d.get('term', '')} {d.get('definition', '')}"
             for d in doc.get("definitions") or [] if isinstance(d, dict)]
    return paper.get("title", ""), " ".join(_strings(keywords) + principal), " ".join(rest)


def _validation(registry, folder, n):
    try:
        return registry.read(folder, n, "validation.json")
    except FileNotFoundError:
        return {}


def index_version(conn, registry, folder, n, published_dir, base_url):
    """Index version n of the claimset in `folder`: database rows and static files. Idempotent."""
    raw = registry.read(folder, n)
    doc = notices.overlay(raw, registry.notices(folder))   # retracted: as readers see it (notices.py)
    paper = doc["paper"]
    concept = paper["id"]
    key = ids.url_key(concept)
    validation = _validation(registry, folder, n)
    classifier = validation.get("classifier")
    warnings = (validation.get("submission") or {}).get("warnings") or []
    defs = {d.get("id"): d for d in doc.get("definitions") or [] if isinstance(d, dict)}
    title, keyword_text, rest_text = paper_texts(doc)
    paper_c = f"{title} {keyword_text}"
    with conn.transaction():
        conn.execute(
            "INSERT INTO papers (concept_id, url_key, folder, current_version, title, status, first_published, updated)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (concept_id) DO UPDATE SET current_version = GREATEST(papers.current_version,"
            " EXCLUDED.current_version), title = CASE WHEN EXCLUDED.current_version >= papers.current_version"
            " THEN EXCLUDED.title ELSE papers.title END, status = CASE WHEN EXCLUDED.current_version >="
            " papers.current_version THEN EXCLUDED.status ELSE papers.status END,"
            " first_published = LEAST(papers.first_published, EXCLUDED.first_published),"
            " updated = GREATEST(papers.updated, EXCLUDED.updated)",
            (concept, key, folder, n, paper["title"], paper["status"], paper["date"], paper["date"]))
        conn.execute("DELETE FROM versions WHERE concept_id = %s AND version = %s", (concept, n))
        conn.execute("INSERT INTO versions (concept_id, version, published, status, hash, file, classifier, warnings)"
                     " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                     (concept, n, paper["date"], paper["status"], doc_hash(raw), Jsonb(doc), classifier,
                      Jsonb(warnings)))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO claims (concept_id, version, claim_id, role, type, novelty, is_assumption, statement,"
                " planning, support_kinds, search) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                " setweight(to_tsvector('english', %s), 'A') || setweight(to_tsvector('english', %s), 'B')"
                " || setweight(to_tsvector('english', %s), 'C'))",
                [(concept, n, c["id"], c.get("role"), c.get("type"), c.get("novelty"), _is_assumption(c),
                  c.get("statement", ""), c.get("planning"),
                  sorted({s.get("kind") for s in c.get("support") or [] if isinstance(s, dict) and s.get("kind")}),
                  plain(c.get("statement")), claim_text(c, defs), paper_c)
                 for c in doc.get("claims") or [] if isinstance(c, dict)])
        conn.execute("UPDATE papers SET licence = %s, guarantors = %s, title_key = %s,"
                     " search = setweight(to_tsvector('english', %s), 'A')"
                     " || setweight(to_tsvector('english', %s), 'B') || setweight(to_tsvector('english', %s), 'C')"
                     " WHERE concept_id = %s AND current_version = %s",
                     (paper.get("licence"), guarantor_ids(doc), title_key(title), title, keyword_text, rest_text,
                      concept, n))
    write_static(conn, registry, folder, published_dir, base_url)


def write_static(conn, registry, folder, published_dir, base_url):
    """The static files of one claimset, from its registry folder, and the index."""
    published_dir = Path(published_dir)
    versions = registry.versions(folder)
    notes = registry.notices(folder)
    raws = {n: registry.read(folder, n) for n in versions}
    docs = {n: notices.overlay(raw, notes) for n, raw in raws.items()}
    current = docs[versions[-1]]
    key = ids.url_key(current["paper"]["id"])
    p = published_dir / "p"
    listing, labs = [], {}
    for n, doc in docs.items():
        text = (registry.version_dir(folder, n) / "claimset.json").read_text(encoding="utf-8")
        if docs[n] is not raws[n]:                       # retracted: the file with the status the platform assigned
            text = json.dumps(docs[n], indent=1, ensure_ascii=False) + "\n"
        view = render(doc)
        _write(p / f"{key}@v{n}.json", text)
        _write(p / f"{key}@v{n}.txt", view)
        if n == versions[-1]:
            _write(p / f"{key}.json", text)
            _write(p / f"{key}.txt", view)
            write_bundles(p / key, doc)
        lab_copy = registry.version_dir(folder, n) / "lab.jsonl"
        lab = {}
        if lab_copy.exists():
            record = lab_copy.read_text(encoding="utf-8")
            _write(p / key / f"v{n}" / "lab.jsonl", record)
            lab["copy"] = f"{base_url}/p/{key}/v{n}/lab.jsonl"
            labs[n] = {"copy": f"/p/{key}/v{n}/lab.jsonl", "summary": _lab_summary(record), "verified": True}
        lab_artefacts = [a.get("uri") for a in doc.get("artefacts") or []
                         if isinstance(a, dict) and a.get("kind") == "lab_record" and a.get("uri")]
        if lab_artefacts:
            lab["artefact"] = lab_artefacts[0]
            if n not in labs and str(lab_artefacts[0]).startswith("https://"):
                labs[n] = {"copy": lab_artefacts[0], "summary": None}
        pp = doc["paper"]
        entry = {"id": f"{pp['id']}@v{n}", "version": n, "date": pp["date"], "status": pp["status"],
                 "hash": doc_hash(raws[n]), "json": f"{base_url}/p/{key}@v{n}.json",
                 "reading_view": f"{base_url}/p/{key}@v{n}.txt",
                 "classifier": _validation(registry, folder, n).get("classifier")}
        for f in ("status_notice", "previous_version"):
            if pp.get(f):
                entry[f] = pp[f]
        if lab:
            entry["lab_record"] = lab
        listing.append(entry)
    head = {"id": current["paper"]["id"], "current_version": versions[-1]}
    if notes:
        head["notices"] = notes["notices"]
    _write(p / key / "versions.json", json.dumps({**head, "versions": listing}, indent=1, ensure_ascii=False) + "\n")
    dois = [b.get("target") for d in docs.values() for b in d.get("references") or []
            if isinstance(b, dict) and b.get("id_type") == "doi"]
    written = crossref.texts(conn, dois)                 # asks Crossref about DOIs not seen before
    site.write_claimset(published_dir, base_url, key, docs, listing, labs,
                        ref_text=lambda b: written.get(crossref.normalise(b.get("target"))))
    write_index(conn, published_dir, base_url)


def apply_notices(conn, registry, folder, published_dir, base_url):
    """After a claimset's notices changed in the registry: a retracted claimset is indexed again with its notice; a
    removed one is taken out of the index and the site, its addresses answering with the notice."""
    if registry.versions(folder):
        for n in registry.versions(folder):
            index_version(conn, registry, folder, n, published_dir, base_url)
        return
    write_removed(conn, registry.notices(folder), published_dir, base_url)


def write_removed(conn, notes, published_dir, base_url):
    """Take a removed claimset out of the index, the site and the file store, and write its notice at its
    addresses."""
    concept = notes["id"]
    notice = notices.latest(notes)
    key = ids.url_key(concept)
    published_dir = Path(published_dir)
    rows = conn.execute("SELECT version, file FROM versions WHERE concept_id = %s", (concept,)).fetchall()
    versions = sorted({r[0] for r in rows} | set(notice.get("versions") or []))
    digests = {d for _, f in rows for d in _stored_digests(f, base_url)}
    with conn.transaction():
        conn.execute("DELETE FROM papers WHERE concept_id = %s", (concept,))
        conn.execute("INSERT INTO removed (concept_id, url_key, notice) VALUES (%s, %s, %s) ON CONFLICT (concept_id)"
                     " DO UPDATE SET notice = EXCLUDED.notice", (concept, key, Jsonb(notice)))
    for digest in digests:                                  # packaged files no other claimset uses
        if not conn.execute("SELECT 1 FROM versions WHERE strpos(file::text, %s) > 0 LIMIT 1",
                            (digest,)).fetchone():
            (published_dir / "files" / digest).unlink(missing_ok=True)
            for img in (published_dir / "img").glob(f"{digest}.*"):
                img.unlink()
    p = published_dir / "p"
    for f in list(p.glob(f"{key}.*")) + list(p.glob(f"{key}@v*.*")):
        f.unlink()
    if (p / key).is_dir():
        shutil.rmtree(p / key)
    gone = {"id": concept, "status": "removed", "notice": notices.status_notice(notice)}
    page = site.removed_page(concept, notice)
    text = site.removed_text(concept, notice)
    for name in [key] + [f"{key}@v{n}" for n in versions]:
        _write(p / f"{name}.html", page)
        _write(p / f"{name}.json", json.dumps(gone, indent=1, ensure_ascii=False) + "\n")
        _write(p / f"{name}.txt", text)
    _write(p / key / "versions.json", json.dumps({**gone, "notices": notes["notices"]}, indent=1,
                                                 ensure_ascii=False) + "\n")
    write_index(conn, published_dir, base_url)


def _stored_digests(doc, base_url):
    prefix = f"{base_url.rstrip('/')}/files/"
    for a in doc.get("artefacts") or []:
        uri = a.get("uri") if isinstance(a, dict) else None
        if isinstance(uri, str) and uri.startswith(prefix) and re.fullmatch(r"[0-9a-f]{64}", uri[len(prefix):]):
            yield uri[len(prefix):]


def _lab_summary(record):
    try:
        events = [json.loads(line) for line in record.splitlines() if line.strip()]
    except ValueError:
        return None
    return site.lab_summary(events)


def write_bundles(directory, doc):
    """The claim bundles of a version, replacing those of the version before (whose claims may differ)."""
    directory = Path(directory)
    for old in directory.glob("C*.*") if directory.exists() else []:
        if re.fullmatch(r"C\d+\.(json|txt)", old.name):
            old.unlink()
    for c in doc.get("claims") or []:
        cid = c.get("id") if isinstance(c, dict) else None
        if isinstance(cid, str) and re.fullmatch(r"C\d+", cid):
            _write(directory / f"{cid}.json", json.dumps(claim_bundle(doc, cid), indent=1, ensure_ascii=False) + "\n")
            _write(directory / f"{cid}.txt", render_claim(doc, cid))


def paper_card(doc, base_url):
    """A search result card, made mechanically from the file (PLT-79)."""
    paper = doc["paper"]
    claims = {c.get("id"): c for c in doc.get("claims") or [] if isinstance(c, dict)}
    cls = paper.get("classification") or {}
    key = ids.url_key(paper["id"])
    return {"id": paper["id"], "version": paper["version"], "status": paper["status"], "date": paper["date"],
            "title": paper["title"], "url": f"{base_url}/p/{key}.json", "reading_view": f"{base_url}/p/{key}.txt",
            "principal_claims": [{"id": cid, "statement": claims[cid].get("statement", "")}
                                 for cid in paper.get("contributions") or [] if cid in claims],
            "keywords": cls.get("keywords") or [], "subfield": cls.get("subfield"), "topics": cls.get("topics") or []}


def write_index(conn, published_dir, base_url):
    rows = conn.execute("SELECT v.file FROM papers p JOIN versions v"
                        " ON v.concept_id = p.concept_id AND v.version = p.current_version"
                        " ORDER BY p.first_published, p.concept_id").fetchall()
    lines = [json.dumps(paper_card(r[0], base_url), ensure_ascii=False) for r in rows]
    _write(Path(published_dir) / "index.jsonl", "".join(line + "\n" for line in lines))
    _write(Path(published_dir) / "llms.txt", reading.llms_txt(base_url))
    site.write_listings(published_dir, base_url, [r[0] for r in reversed(rows)])


def reindex(conn, registry, published_dir, base_url):
    """Rebuild the database index, the identifier counters and the static files from the registry alone."""
    with conn.transaction():
        conn.execute("DELETE FROM papers")
        conn.execute("DELETE FROM removed")
        counters = {}
        for folder in registry.folders():
            concept = registry.read(folder, registry.versions(folder)[0])["paper"]["id"]
            if concept.startswith(ids.PREFIX):
                year, number = ids.year_number(concept)
                counters[year] = max(counters.get(year, 0), number)
        for folder in registry.removed_folders():            # a removed claimset's number is never given again
            concept = (registry.notices(folder) or {}).get("id", "")
            if concept.startswith(ids.PREFIX):
                year, number = ids.year_number(concept)
                counters[year] = max(counters.get(year, 0), number)
        for year, last in counters.items():
            conn.execute("INSERT INTO id_counters (year, last) VALUES (%s, %s) ON CONFLICT (year)"
                         " DO UPDATE SET last = GREATEST(id_counters.last, EXCLUDED.last)", (year, last))
    folders = registry.folders()
    for folder in folders:
        for n in registry.versions(folder):
            index_version(conn, registry, folder, n, published_dir, base_url)
    for folder in registry.removed_folders():
        write_removed(conn, registry.notices(folder), published_dir, base_url)
    write_index(conn, published_dir, base_url)
    return folders


#: In the published directory: which claimset rendered the static files.
RENDERED_BY = ".rendered-by"


def refresh_if_claimset_changed(conn, registry, published_dir, base_url, version):
    """At the app's start, after it installed the newest claimset: write /llms.txt and /index.jsonl, and rebuild the
    index and the static files when claimset `version` is not the one that wrote them (design §7.1: reading views are
    regenerated when the renderer changes, and the pages when the site's look changes). Returns True if it
    rebuilt."""
    site.write_fixed(published_dir, base_url)
    write_index(conn, published_dir, base_url)          # /llms.txt and /index.jsonl exist before anything is published
    marker = Path(published_dir) / RENDERED_BY
    version = f"{version} site {site.fingerprint()}"
    try:
        if marker.read_text(encoding="utf-8").strip() == version:
            return False
    except FileNotFoundError:
        pass
    if registry is not None:
        reindex(conn, registry, published_dir, base_url)
    _write(marker, version + "\n")
    return True
