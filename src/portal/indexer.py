"""Index the registry: database rows and static files, made from the registry alone.

Publication writes a version to the registry and then calls `index_version`; `reindex` rebuilds everything from
the registry, so the database and the static files are always derived from the record (design §2, principle 4).

Static files, under the published directory:

    p/<key>.json, p/<key>.txt              the current version: published file and reading view
    p/<key>@v<n>.json, p/<key>@v<n>.txt    every version
    p/<key>/versions.json                  versions, dates, status, notices, lab record links
    p/<key>/v<n>/lab.jsonl                 the registry's copy of a version's lab record
    p/<key>/<claim>.json, .txt             the claim bundles of the current version (claimset spec §2.3)
    p/<key>.html                           the current reading view as a minimal page, for a human given an ID
    index.jsonl                            one paper card per claimset, current versions
    llms.txt                               the entry point for agents (reading.llms_txt)

Each version's claims and paper get the weighted text full-text search runs on (design §7.2).
"""

import json
import os
import re
from pathlib import Path

from claimset.claim import claim_bundle, render_claim
from claimset.render import render
from claimset.revision import doc_hash
from psycopg.types.json import Jsonb

from . import ids, reading


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
    doc = registry.read(folder, n)
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
                     (concept, n, paper["date"], paper["status"], doc_hash(doc), Jsonb(doc), classifier,
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
        conn.execute("UPDATE papers SET licence = %s, search = setweight(to_tsvector('english', %s), 'A')"
                     " || setweight(to_tsvector('english', %s), 'B') || setweight(to_tsvector('english', %s), 'C')"
                     " WHERE concept_id = %s AND current_version = %s",
                     (paper.get("licence"), title, keyword_text, rest_text, concept, n))
    write_static(conn, registry, folder, published_dir, base_url)


def write_static(conn, registry, folder, published_dir, base_url):
    """The static files of one claimset, from its registry folder, and the index."""
    published_dir = Path(published_dir)
    versions = registry.versions(folder)
    docs = {n: registry.read(folder, n) for n in versions}
    current = docs[versions[-1]]
    key = ids.url_key(current["paper"]["id"])
    p = published_dir / "p"
    listing = []
    for n, doc in docs.items():
        text = (registry.version_dir(folder, n) / "claimset.json").read_text(encoding="utf-8")
        view = render(doc)
        _write(p / f"{key}@v{n}.json", text)
        _write(p / f"{key}@v{n}.txt", view)
        if n == versions[-1]:
            _write(p / f"{key}.json", text)
            _write(p / f"{key}.txt", view)
            _write(p / f"{key}.html", reading.html_page(f"{doc['paper']['id']}@v{n}", view))
            write_bundles(p / key, doc)
        lab_copy = registry.version_dir(folder, n) / "lab.jsonl"
        lab = {}
        if lab_copy.exists():
            _write(p / key / f"v{n}" / "lab.jsonl", lab_copy.read_text(encoding="utf-8"))
            lab["copy"] = f"{base_url}/p/{key}/v{n}/lab.jsonl"
        lab_artefacts = [a.get("uri") for a in doc.get("artefacts") or []
                         if isinstance(a, dict) and a.get("kind") == "lab_record" and a.get("uri")]
        if lab_artefacts:
            lab["artefact"] = lab_artefacts[0]
        pp = doc["paper"]
        entry = {"id": f"{pp['id']}@v{n}", "version": n, "date": pp["date"], "status": pp["status"],
                 "hash": doc_hash(doc), "json": f"{base_url}/p/{key}@v{n}.json",
                 "reading_view": f"{base_url}/p/{key}@v{n}.txt",
                 "classifier": _validation(registry, folder, n).get("classifier")}
        for f in ("status_notice", "previous_version"):
            if pp.get(f):
                entry[f] = pp[f]
        if lab:
            entry["lab_record"] = lab
        listing.append(entry)
    _write(p / key / "versions.json",
           json.dumps({"id": current["paper"]["id"], "current_version": versions[-1], "versions": listing},
                      indent=1, ensure_ascii=False) + "\n")
    write_index(conn, published_dir, base_url)


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


def reindex(conn, registry, published_dir, base_url):
    """Rebuild the database index, the identifier counters and the static files from the registry alone."""
    with conn.transaction():
        conn.execute("DELETE FROM papers")
        counters = {}
        for folder in registry.folders():
            concept = registry.read(folder, registry.versions(folder)[0])["paper"]["id"]
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
    if not folders:
        write_index(conn, published_dir, base_url)
    return folders
