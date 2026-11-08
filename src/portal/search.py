"""Full-text search over published claimsets (design §7.2): claims and papers of current versions, best match first.

The query is read as a web search would be (`websearch_to_tsquery`): words are reduced to their stems, quoted phrases
match as phrases, `-word` excludes, `or` gives alternatives. Ranking weighs where the words are found (the indexer
writes the weights: indexer.claim_text, indexer.paper_texts). Filters run on the closed vocabularies of the claimset
specification, which the claimset package defines; a value outside them is refused rather than matching nothing.
"""

from claimset.validate import ENUM

from . import ids

MAX_LIMIT = 50
MAX_QUERY = 500

#: Filters on claims: query parameter -> (column, the claimset vocabulary it takes values from).
CLAIM_FILTERS = {"type": ("type", "claim_type"), "role": ("role", "role"), "novelty": ("novelty", "novelty"),
                 "planning": ("planning", "planning")}


class SearchError(ValueError):
    """A request the search cannot answer: says what to change."""


def _page(limit, offset):
    try:
        limit, offset = int(limit), int(offset)
    except (TypeError, ValueError):
        raise SearchError("limit and offset are whole numbers") from None
    if not 1 <= limit <= MAX_LIMIT or offset < 0:
        raise SearchError(f"limit is 1 to {MAX_LIMIT}, offset 0 or more")
    return limit, offset


def _query(q):
    q = (q or "").strip()
    if not q:
        raise SearchError("q: the words to search for")
    if len(q) > MAX_QUERY:
        raise SearchError(f"q: at most {MAX_QUERY} characters")
    return q


def _vocabulary(name, value, enum):
    if value not in ENUM[enum]:
        raise SearchError(f"{name}: one of {', '.join(sorted(ENUM[enum]))}")
    return value


def _version_fields(row_paper_id, version, status, file, warnings, base_url):
    paper = file.get("paper") or {}
    key = ids.url_key(row_paper_id)
    out = {"paper": row_paper_id, "version": version, "status": status,
           "url": f"{base_url}/p/{key}@v{version}.json", "reading_view": f"{base_url}/p/{key}@v{version}.txt",
           "warnings": warnings or []}
    if paper.get("status_notice"):
        out["status_notice"] = paper["status_notice"]
    return out


def search_claims(conn, base_url, q, limit=10, offset=0, **filters):
    """Claims of current versions matching q, best first, with the filters given (None means no filter)."""
    q = _query(q)
    limit, offset = _page(limit, offset)
    where, args = [], [q]
    for name, (column, enum) in CLAIM_FILTERS.items():
        if filters.get(name) is not None:
            where.append(f"c.{column} = %s")
            args.append(_vocabulary(name, filters[name], enum))
    if filters.get("support") is not None:
        where.append("%s = ANY(c.support_kinds)")
        args.append(_vocabulary("support", filters["support"], "support_kind"))
    if filters.get("assumption") is not None:
        a = str(filters["assumption"]).lower()
        if a not in ("true", "false"):
            raise SearchError("assumption: true or false")
        where.append("c.is_assumption = %s")
        args.append(a == "true")
    if filters.get("licence") is not None:
        where.append("p.licence = %s")
        args.append(filters["licence"])
    extra = "".join(f" AND {w}" for w in where)
    rows = conn.execute(
        "WITH query AS (SELECT websearch_to_tsquery('english', %s) AS tsq)"
        " SELECT c.concept_id, c.version, c.claim_id, c.statement, c.type, c.role, c.novelty, c.planning,"
        " c.support_kinds, c.is_assumption, p.title, p.licence, v.status, v.file, v.warnings,"
        " ts_rank_cd(c.search, query.tsq) AS rank"
        " FROM claims c JOIN papers p ON p.concept_id = c.concept_id AND p.current_version = c.version"
        " JOIN versions v ON v.concept_id = c.concept_id AND v.version = c.version, query"
        f" WHERE c.search @@ query.tsq{extra}"
        " ORDER BY rank DESC, c.concept_id, c.claim_id LIMIT %s OFFSET %s",
        args + [limit, offset]).fetchall()
    results = []
    for (concept, version, cid, statement, typ, role, novelty, planning, support, assumption, title, licence, status,
         file, warnings, rank) in rows:
        key = ids.url_key(concept)
        r = {"id": f"{concept}@v{version}#{cid}", "claim": cid, "statement": statement, "type": typ, "role": role,
             "novelty": novelty, "planning": planning, "support": list(support), "assumption": assumption,
             "paper_title": title, "licence": licence, "rank": round(float(rank), 6),
             "bundle": f"{base_url}/p/{key}/{cid}.txt", "bundle_json": f"{base_url}/p/{key}/{cid}.json"}
        r.update(_version_fields(concept, version, status, file, warnings, base_url))
        results.append(r)
    return {"query": q, "limit": limit, "offset": offset, "results": results}


def search_papers(conn, base_url, q, limit=10, offset=0, licence=None):
    """Claimsets whose current versions match q, best first, as paper cards."""
    from .indexer import paper_card
    q = _query(q)
    limit, offset = _page(limit, offset)
    where, args = "", [q]
    if licence is not None:
        where, args = " AND p.licence = %s", args + [licence]
    rows = conn.execute(
        "WITH query AS (SELECT websearch_to_tsquery('english', %s) AS tsq)"
        " SELECT p.concept_id, p.current_version, v.status, v.file, v.warnings, ts_rank_cd(p.search, query.tsq)"
        " FROM papers p JOIN versions v ON v.concept_id = p.concept_id AND v.version = p.current_version, query"
        f" WHERE p.search @@ query.tsq{where}"
        " ORDER BY 6 DESC, p.concept_id LIMIT %s OFFSET %s",
        args + [limit, offset]).fetchall()
    results = []
    for concept, version, status, file, warnings, rank in rows:
        card = paper_card(file, base_url)
        card.update(_version_fields(concept, version, status, file, warnings, base_url))
        card["rank"] = round(float(rank), 6)
        results.append(card)
    return {"query": q, "limit": limit, "offset": offset, "results": results}
