"""The published paper a claimset restates, when its authors prepared it from their own paper (claimset spec v0.42
§3.6; design §4.5).

    doi(doc)                    -> the paper's DOI (lower case, no prefix), or None
    lookup(doi)                 -> {"title", "authors": [{"name", "family", "orcid"}]} from Crossref or DataCite,
                                   None if neither knows the DOI; raises Unavailable when they cannot be reached
    authorship(record, people)  -> how the guarantor appears among the paper's authors
    author_order(record, doc)   -> whether the claimset lists the paper's authors in the order of its byline

The DOI is read from `paper.published_as` when a claimset has it, and else from a `manuscript` artefact's `uri`.
Lookups follow crossref.py (its address, User-Agent and PORTAL_CROSSREF=0). Only these two fixed hosts are asked,
with the DOI checked first, so a submission cannot point the portal anywhere.
"""

import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .crossref import API as CROSSREF
from .crossref import TIMEOUT, USER_AGENT

#: A DOI as Crossref and DataCite register them.
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
DATACITE = "https://api.datacite.org/dois/"


class Unavailable(Exception):
    """Neither Crossref nor DataCite answered: the checks that need them are skipped, and say so."""


def _clean(value):
    """A DOI from the forms a claimset uses: `10.x/y`, `doi:10.x/y`, `https://doi.org/10.x/y`."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    v = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", v, flags=re.I)
    v = urllib.parse.unquote(v).strip().lower()
    return v if DOI.match(v) else None


def doi(doc):
    """The DOI of the published paper this claimset restates, or None."""
    paper = doc.get("paper") or {}
    if paper.get("origin") == "converted":
        cf = paper.get("converted_from") or {}
        return _clean(cf.get("source_id")) if cf.get("id_type") == "doi" else None
    pub = paper.get("published_as")
    if isinstance(pub, dict) and pub.get("id_type") in (None, "doi"):
        found = _clean(pub.get("id"))
        if found:
            return found
    for a in doc.get("artefacts") or []:
        if isinstance(a, dict) and a.get("kind") == "manuscript":
            found = _clean(a.get("uri"))
            if found:
                return found
    return None


def _get(url):
    if os.environ.get("PORTAL_CROSSREF") == "0":            # as crossref.py: never ask (tests, offline use)
        raise Unavailable("lookups are off (PORTAL_CROSSREF=0)")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read(2_000_000))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise Unavailable(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise Unavailable(str(exc)) from exc


def _orcid(value):
    m = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", str(value or ""))
    return m.group(1) if m else None


def lookup(doi_):
    """The paper's title and authors, from Crossref (journal articles, most DOIs) or else DataCite (arXiv, data)."""
    if not DOI.match(doi_ or ""):
        return None
    quoted = urllib.parse.quote(doi_, safe="/")
    data = _get(f"{CROSSREF}{quoted}")
    if data and isinstance(data.get("message"), dict):
        m = data["message"]
        authors = [{"name": " ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name") or "",
                    "family": a.get("family") or a.get("name") or "", "orcid": _orcid(a.get("ORCID"))}
                   for a in m.get("author") or [] if isinstance(a, dict)]
        return {"title": " ".join(m.get("title") or []) or None, "authors": authors, "registry": "Crossref"}
    data = _get(f"{DATACITE}{quoted}")
    if data and isinstance(data.get("data"), dict):
        attrs = data["data"].get("attributes") or {}
        authors = []
        for c in attrs.get("creators") or []:
            if not isinstance(c, dict):
                continue
            ids = [i.get("nameIdentifier") for i in c.get("nameIdentifiers") or [] if isinstance(i, dict)]
            authors.append({"name": c.get("name") or "", "family": c.get("familyName") or c.get("name") or "",
                            "orcid": next((_orcid(i) for i in ids if _orcid(i)), None)})
        titles = [t.get("title") for t in attrs.get("titles") or [] if isinstance(t, dict) and t.get("title")]
        return {"title": titles[0] if titles else None, "authors": authors, "registry": "DataCite"}
    return None


def _fold(text):
    """Lower case, without accents or punctuation, for comparing names."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    return re.sub(r"[^a-z ]", " ", "".join(ch for ch in t if not unicodedata.combining(ch)).lower())


def authorship(record, people):
    """How the guarantor (people: [(orcid, name)]) appears among the paper's authors:
    `orcid` (their ORCID iD is on the paper), `name` (their family name is, with no ORCID iD to compare),
    `absent` (neither), or `unknown` (the registry lists no authors)."""
    authors = record.get("authors") or []
    if not authors:
        return "unknown"
    orcids = {a["orcid"] for a in authors if a.get("orcid")}
    if any(o in orcids for o, _ in people):
        return "orcid"
    families = {_fold(a.get("family")).strip() for a in authors} - {""}
    for _, name in people:
        words = set(_fold(name).split())
        if any(f in words or all(w in words for w in f.split()) for f in families):
            return "name"
    return "absent"


def _matches(author, person):
    """Whether a contributor is this author of the paper: the same ORCID iD, or, when either has none, the author's
    family name among the words of the contributor's name (accents and punctuation folded)."""
    if author.get("orcid") and person.get("orcid"):
        return author["orcid"] == person["orcid"]
    names = str(author.get("name") or "").split()
    family = _fold(author.get("family") or (names[-1] if names else "")).split()
    words = set(_fold(person.get("name")).split())
    return bool(family) and all(w in words for w in family)


def author_order(record, doc):
    """Whether the claimset lists the paper's authors first, in the order of its byline (claimset spec §3.11, Order):
    {"follows": bool, "expected": [names], "given": [names], "unmatched": [names]}, or None when the registry lists
    no authors or none of them is a contributor. An author is matched to the one contributor who is them (_matches);
    an author matched to none, or to more than one, is `unmatched` and left out of the comparison. `given` is the
    contributors as listed, up to the last matched author; it follows the byline when it is exactly the matched
    authors in the byline's order, with no one, agent or other person, before or between them."""
    authors = [a for a in record.get("authors") or [] if isinstance(a, dict)]
    people = [c for c in doc.get("contributors") or [] if isinstance(c, dict)]
    humans = [c for c in people if c.get("type") != "agent"]
    matched, unmatched = [], []
    for a in authors:
        hits = [c for c in humans if _matches(a, c)]
        if len(hits) == 1 and all(hits[0] is not m for _, m in matched):
            matched.append((a, hits[0]))
        else:
            unmatched.append(a.get("name") or a.get("family") or "")
    if not matched:
        return None
    last = max(people.index(m) for _, m in matched)
    given = people[:last + 1]
    follows = len(given) == len(matched) and all(g is m for g, (_, m) in zip(given, matched, strict=True))
    return {"follows": follows, "expected": [a.get("name") or _name(m) for a, m in matched],
            "given": [_name(c) for c in given], "unmatched": unmatched}


def _name(c):
    return str(c.get("name") or c.get("label") or c.get("id") or "")


def own_paper(doc):
    """The paper its authors converted into this claimset (a native claimset with `paper.published_as`, or, before
    that field, a `manuscript` artefact with its DOI or other address in `uri`): (address or None, description), or
    None."""
    pub = (doc.get("paper") or {}).get("published_as")
    if isinstance(pub, dict) and pub.get("id"):
        doi_ = doi({"paper": {"published_as": pub}})
        href = f"https://doi.org/{doi_}" if doi_ else (pub["id"] if str(pub["id"]).startswith("https://") else None)
        named = next((str(a.get("description")) for a in doc.get("artefacts") or []
                      if isinstance(a, dict) and a.get("kind") == "manuscript" and a.get("description")), None)
        return href, named or (f"doi:{doi_}" if doi_ else str(pub["id"]))
    for a in doc.get("artefacts") or []:
        if isinstance(a, dict) and a.get("kind") == "manuscript":
            uri = a.get("uri") if isinstance(a.get("uri"), str) else ""
            href = uri if uri.startswith(("https://", "http://")) else (
                f"https://doi.org/{uri[4:]}" if uri.startswith("doi:") else None)
            return href, str(a.get("description") or uri or "")
    return None
