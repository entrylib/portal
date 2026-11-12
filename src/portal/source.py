"""The published paper a claimset restates, when its authors prepared it from their own paper (claimset spec v0.42
§3.6; design §4.5).

    doi(doc)                    -> the paper's DOI (lower case, no prefix), or None
    lookup(doi)                 -> {"title", "authors": [{"name", "family", "orcid"}]} from Crossref or DataCite,
                                   None if neither knows the DOI; raises Unavailable when they cannot be reached
    authorship(record, people)  -> how the guarantor appears among the paper's authors

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
