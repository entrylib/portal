"""References given only by DOI, written out for people from Crossref (design §7.4; a first part of issue #22).

    texts(conn, dois, fetch=True) -> {doi: "Surname, A., & Other, B. (2018). Title. Journal, 3(2), 1–10."}

At publication (indexer.write_static) the portal asks Crossref about each DOI a claimset cites and keeps the answer,
so pages read "Surname and Other (2018)" instead of a bare DOI. The published file is not changed: the DOI stays the
reference, for models. A DOI Crossref does not know is asked again after RETRY_AFTER; meanwhile the page shows it as
a DOI. Set PORTAL_CROSSREF=0 to never ask (tests, offline use).
"""

import datetime as dt
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from psycopg.types.json import Jsonb

from . import __version__

log = logging.getLogger("portal")

API = "https://api.crossref.org/works/"
#: Crossref's etiquette: say who asks, with an address (its "polite pool").
USER_AGENT = f"EntryLib/{__version__} (https://entrylib.org; mailto:mail@entrylib.org)"
TIMEOUT = 10
RETRY_AFTER = dt.timedelta(days=30)
#: At most this many DOIs looked up for one claimset at once; the rest wait for the next indexing.
MAX_LOOKUPS = 60
DOI = re.compile(r"^10\.\d{4,9}/\S+$")


def enabled():
    return os.environ.get("PORTAL_CROSSREF", "1") != "0"


def normalise(doi):
    """10.1002/for.3980010202 from what a reference may hold: doi:..., https://doi.org/..., any case."""
    if not isinstance(doi, str):
        return None
    d = doi.strip()
    d = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", "", d, flags=re.I)
    d = d.lower()
    return d if DOI.match(d) else None


def fetch(doi):
    """Crossref's record of a DOI (its `message`), or None if it does not know it. Raises OSError when Crossref
    cannot be reached, so that the DOI is asked again next time."""
    req = urllib.request.Request(API + urllib.parse.quote(doi, safe="/:;()"), headers={
        "User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            return json.loads(res.read()).get("message")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise OSError(f"Crossref answered {exc.code}") from exc
    except (urllib.error.URLError, ValueError) as exc:
        raise OSError(str(exc)) from exc


def _clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")                     # Crossref titles may carry JATS tags
    return re.sub(r"\s+", " ", s).strip()


def _initials(given):
    parts = [p for p in re.split(r"[\s.]+", given or "") if p]
    return " ".join(("-".join(x[0] + "." for x in p.split("-") if x)) for p in parts)


def summary(msg):
    """What a page needs from a Crossref record: authors (family, initials), year, title, where and pages."""
    if not isinstance(msg, dict):
        return None
    authors = []
    for a in msg.get("author") or msg.get("editor") or []:
        if not isinstance(a, dict):
            continue
        if a.get("family"):
            authors.append({"family": _clean(a["family"]), "initials": _initials(a.get("given"))})
        elif a.get("name"):
            authors.append({"family": _clean(a["name"]), "initials": ""})
    year = None
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    title = _clean((msg.get("title") or [""])[0])
    container = _clean((msg.get("container-title") or [""])[0])
    if not (authors and year and title):
        return None
    return {"authors": authors, "year": year, "title": title, "container": container,
            "volume": _clean(msg.get("volume")), "issue": _clean(msg.get("issue")), "page": _clean(msg.get("page")),
            "publisher": _clean(msg.get("publisher")) if msg.get("type") in ("book", "monograph", "edited-book")
            else ""}


def written(s):
    """A summary as a reference, in the order the page view reads (authors, then the year in brackets):
    "Svetunkov, I., & Petropoulos, F. (2018). Title. Journal, 56(1), 1–10." """
    names = [f"{a['family']}, {a['initials']}".rstrip(", ") for a in s["authors"]]
    if len(names) > 20:
        names = names[:19] + ["…", names[-1]]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + ", & " + names[-1]
    out = f"{who} ({s['year']}). {s['title'].rstrip('.')}."
    if s.get("container"):
        where = s["container"]
        if s.get("volume"):
            where += f", {s['volume']}" + (f"({s['issue']})" if s.get("issue") else "")
        if s.get("page"):
            where += f", {s['page'].replace('-', '–')}"
        out += f" {where}."
    elif s.get("publisher"):
        out += f" {s['publisher']}."
    return out


def texts(conn, dois, fetch_missing=True, fetcher=None, now=None):
    """{doi: written reference} for the DOIs Crossref knows, asking it about those not asked yet (or asked more than
    RETRY_AFTER ago without an answer). Never raises: a DOI that cannot be looked up is left out."""
    now = now or dt.datetime.now(dt.UTC)
    wanted = sorted({d for d in (normalise(x) for x in dois) if d})
    if not wanted:
        return {}
    rows = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT doi, summary, fetched FROM doi_metadata WHERE doi = ANY(%s)", (wanted,)).fetchall()}
    if fetch_missing and enabled():
        fetcher = fetcher or fetch
        missing = [d for d in wanted if d not in rows or (rows[d][0] is None and rows[d][1] < now - RETRY_AFTER)]
        for d in missing[:MAX_LOOKUPS]:
            try:
                s = summary(fetcher(d))
            except OSError as exc:
                log.warning("Crossref lookup of %s failed (%s); asked again at the next indexing", d, exc)
                continue
            conn.execute("INSERT INTO doi_metadata (doi, summary, fetched) VALUES (%s, %s, %s) ON CONFLICT (doi)"
                         " DO UPDATE SET summary = EXCLUDED.summary, fetched = EXCLUDED.fetched",
                         (d, Jsonb(s) if s else None, now))
            rows[d] = (s, now)
    return {d: written(s) for d, (s, _) in rows.items() if s}
