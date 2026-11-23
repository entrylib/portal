"""The Read page, /read (design §7.7): what EntryLib holds, as a tree of OpenAlex domains, fields and subfields (only
those with claimsets), and for the part chosen its claimsets or its principal claims (or all claims), filtered and
sorted; with a query, the search of the whole library (site.search_page). Rendered by the app, without scripts.

Scores come from the rubric over each claimset's current file; they are kept in memory per version and rubric
version. Fine while the library has hundreds of claimsets; past that, the indexer should store them.
"""

import functools
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import areas, ids, score_html, site
from . import scores as score_data

PAGE = 50
TYPES = ["descriptive", "associational", "causal", "mechanistic", "predictive", "interpretive", "formal",
         "methodological"]
NOVELTY = {"no_prior_found": "New", "extension": "Extends", "replication": "Replicates", "refutation": "Refutes",
           "synthesis": "Summarises"}                                   # claimset v0.43
PLANNING = {"confirmatory": "Planned test", "planned_estimate": "Planned estimate",
            "exploratory": "Exploratory"}
BANDS = {b: f"{w} ({r})" for (b, w), r in zip(score_html.BANDS.items(), ("80+", "60–79", "under 60"), strict=True)}
#: Newest first by default: sorted by score, the library reads as a league table (UX audit, 11 November 2026).
SORTS = {"newest": "Newest", "support": f"{score_html.NAME}, highest first"}
#: The sort by score was `reliability` until 16 November 2026: links made then still work.
OLD_SORTS = {"reliability": "support"}


def taxonomy():
    domains, fields, _ = areas.taxonomy()
    return domains, fields


area_of, in_area = areas.area_of, areas.in_area


def area_name(area):
    return areas.name(area)


@functools.lru_cache(maxsize=2048)
def _scores(concept, version, rubric, text):
    return score_data.compute(None, json.loads(text))


@functools.lru_cache(maxsize=4096)
def _stored(path, mtime_ns, rubric):
    try:
        held = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return held if isinstance(held, dict) and held.get("rubric") == rubric else None


def scores_of(doc, published_dir=None):
    """A published version's scores: those written with its files (`p/<key>@v<n>.score.json`, indexer), when they
    are by the rubric installed; else computed, once per process. Computing them for every paper made the first
    visit to Read after each start take seconds per paper."""
    p = doc["paper"]
    if score_data.rubric is None:
        return None
    if published_dir is not None and p.get("version") is not None:
        path = Path(published_dir) / "p" / f"{ids.url_key(p['id'])}@v{p['version']}.score.json"
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime is not None:
            held = _stored(str(path), mtime, score_data.version())
            if held is not None:
                return held
    return _scores(p["id"], p.get("version"), score_data.version(), json.dumps(doc, sort_keys=True))


@dataclass
class Query:
    area: str = ""
    view: str = "claimsets"
    all: bool = False
    type: str = ""
    band: str = ""
    novelty: str = ""
    planning: str = ""
    sort: str = "newest"
    offset: int = 0
    errors: list = field(default_factory=list)

    @classmethod
    def parse(cls, params):
        q = cls()
        area = str(params.get("area") or "")
        q.area = area if areas.valid(area) else ""
        q.view = "claims" if params.get("view") == "claims" else "claimsets"
        q.all = params.get("all") in ("1", "on", "true")
        q.type = params.get("type") if params.get("type") in TYPES else ""
        q.band = params.get("band") if params.get("band") in BANDS else ""
        q.novelty = params.get("novelty") if params.get("novelty") in NOVELTY else ""
        q.planning = params.get("planning") if params.get("planning") in PLANNING else ""
        sort = OLD_SORTS.get(params.get("sort"), params.get("sort"))
        q.sort = sort if sort in SORTS else "newest"
        try:
            q.offset = max(0, int(params.get("offset") or 0))
        except ValueError:
            q.offset = 0
        return q

    def url(self, **change):
        """The address of this view with `change`: the area as a path (/read/social-sciences/decision-sciences),
        the rest as parameters."""
        area = change.pop("area", self.area)
        values = {"view": self.view, "all": "1" if self.all else "", "type": self.type,
                  "band": self.band, "novelty": self.novelty, "planning": self.planning,
                  "sort": self.sort if self.sort != "newest" else "", "offset": ""}
        values.update({k: v for k, v in change.items()})
        if values["view"] == "claimsets":
            values["view"] = ""
        parts = [f"{k}={site.esc(v)}" for k, v in values.items() if v not in ("", None, 0, "0")]
        return areas.path(area) + ("?" + "&amp;".join(parts) if parts else "")


def tree_counts(docs):
    """{area: how many of `docs` it holds} for the tree: each domain (d<id>), field and subfield."""
    count = {}
    for d in docs:
        dom, fld, sub = area_of(d)
        for key in (f"d{dom}", fld, sub):
            if dom:
                count[key] = count.get(key, 0) + 1
    return count


def _tree(count, total, q):
    domains, fields, subs = areas.taxonomy()

    def link(area, name):
        current = ' aria-current="page"' if area == q.area else ""
        return f'<a href="{q.url(area=area)}"{current}>{site.esc(name)}</a> <span class="count">{count[area]}</span>'

    out = [f'<li><a href="{q.url(area="")}"' + (' aria-current="page"' if not q.area else "")
           + f'>Everything</a> <span class="count">{total}</span></li>']
    for dom, dname in domains.items():
        if not count.get(f"d{dom}"):
            continue
        inner = []
        for fld, f in fields.items():
            if f["domain"] != dom or not count.get(fld):
                continue
            leaves = "".join(f"<li>{link(sub, name)}</li>" for sub, name in sorted(subs.items())
                             if sub[:2] == fld and count.get(sub))
            inner.append(f"<li>{link(fld, f['name'])}<ul>{leaves}</ul></li>")
        out.append(f"<li>{link(f'd{dom}', dname)}<ul>{''.join(inner)}</ul></li>")
    return f'<nav class="read-tree" aria-label="Fields"><ul>{"".join(out)}</ul></nav>'


def _select(name, label, options, value):
    opts = '<option value="">Any</option>' + "".join(
        f'<option value="{site.esc(k)}"' + (" selected" if k == value else "") + f">{site.esc(v)}</option>"
        for k, v in options.items())
    return f'<label>{site.esc(label)} <select name="{name}">{opts}</select></label>'


def _filters(q):
    hidden = f'<input type="hidden" name="view" value="{q.view}">' if q.view != "claims" else ""
    sort = "".join(f'<option value="{k}"' + (" selected" if k == q.sort else "") + f">{v}</option>"
                   for k, v in SORTS.items())
    claim_filters = ""
    if q.view == "claims":
        claim_filters = (_select("type", "Type", {t: t for t in TYPES}, q.type)
                         + _select("novelty", "Novelty", NOVELTY, q.novelty)
                         + _select("planning", "Plan", PLANNING, q.planning)
                         + '<label class="check"><input type="checkbox" name="all" value="1"'
                         + (" checked" if q.all else "") + "> All claims, not only principal</label>")
    return (f'<form class="read-filters" action="{areas.path(q.area)}" method="get">{hidden}{claim_filters}'
            + _select("band", score_html.NAME, BANDS, q.band)
            + f'<label>Sort <select name="sort">{sort}</select></label><button type="submit">Apply</button></form>')


def _claim_item(doc, c, sc):
    key = ids.url_key(doc["paper"]["id"])
    cid = c["id"]
    item = sc["claims"].get(cid) if sc else None
    mark = ""
    if item:
        mark = (f'<a class="score-badge band-{item["band"]}" href="/p/{key}#score-{site.esc(cid)}" '
                f'aria-label="{score_html.NAME} {item["score"]}, {score_html.BANDS[item["band"]].lower()}">'
                f'{item["score"]}</a>'
                + score_html.dots(sc, cid, href=f"/p/{key}#score-{cid}"))
    meta = [site.esc(cid), site.esc(c.get("type")), site.esc(c.get("role"))]
    n = score_data.label((sc or {}).get("novelty", {}).get(cid)) if sc else ""
    if n:
        meta.append(f"novelty: {site.esc(n)}")
    return (f'<li class="result"><p class="card-top">{mark}{" · ".join(m for m in meta if m)}</p>'
            f'<p class="card-claim">{site.plain_html(c.get("statement"))}</p>'
            f'<p class="card-who"><a href="/p/{key}#{site.esc(cid)}">{site.esc(doc["paper"].get("title"))}</a> · '
            f'{site.esc(doc["paper"]["id"])}@v{site.esc(doc["paper"].get("version"))}</p></li>')


def claims(docs, q, published_dir=None):
    """The claims shown: (doc, claim, scores, score) of every current claimset in the area, filtered."""
    out = []
    for d in docs:
        if not in_area(area_of(d), q.area):
            continue
        sc = scores_of(d, published_dir)
        for c in d.get("claims") or []:
            if not isinstance(c, dict) or not isinstance(c.get("id"), str):
                continue
            if sc is not None and c["id"] not in sc["claims"]:
                continue                                    # assumptions are not listed
            if not q.all and c.get("role") != "principal":
                continue
            if q.type and c.get("type") != q.type or q.novelty and c.get("novelty") != q.novelty:
                continue
            if q.planning and (c.get("planning") or "exploratory") != q.planning:
                continue
            item = sc["claims"].get(c["id"]) if sc else None
            if q.band and (not item or item["band"] != q.band):
                continue
            out.append((d, c, sc, item["score"] if item else -1))
    if q.sort == "newest":
        out.sort(key=lambda r: (str(r[0]["paper"].get("date")), -r[3]), reverse=True)
    else:
        out.sort(key=lambda r: (-r[3], str(r[0]["paper"].get("date"))), reverse=False)
    return out


def claimsets(docs, q, published_dir=None):
    out = []
    for d in docs:
        if not in_area(area_of(d), q.area):
            continue
        sc = scores_of(d, published_dir)
        paper = sc["paper"] if sc else None
        if q.band and (not paper or paper["band"] != q.band):
            continue
        out.append((d, paper["score"] if paper else -1))
    if q.sort == "newest":
        out.sort(key=lambda r: str(r[0]["paper"].get("date")), reverse=True)
    else:
        out.sort(key=lambda r: -r[1])
    return [d for d, _ in out]


def page(docs, q, base_url="", corrected=None, published_dir=None):
    """The Read page from `docs`, the current version of every published claimset, held in memory: the reference
    page_from_db must give the same page as (tests/test_read.py)."""
    if q.view == "claims":
        rows = claims(docs, q, published_dir)
    else:
        rows = claimsets(docs, q, published_dir)
    area_count = sum(1 for d in docs if in_area(area_of(d), q.area))
    return _layout(q, base_url, corrected, tree_counts(docs), len(docs), len(rows),
                   rows[q.offset:q.offset + PAGE], area_count)


#: SQL for an area of Read: a domain (d<id>), a field (two digits) or a subfield.
def _area_sql(area):
    if not area:
        return "true", []
    if area.startswith("d"):
        return "p.domain = %s", [area[1:]]
    return ("p.field = %s", [area]) if len(area) == 2 else ("p.subfield = %s", [area])


def page_from_db(conn, q, base_url="", corrected=None, published_dir=None):
    """The Read page from the index (design §7.7): filters, sorts, counts and pages by the columns the indexer keeps
    (migration 0018), and loads the files of the papers shown alone. The same page as page() on every paper's file,
    which the app read on each visit."""
    count, total = {}, 0
    for dom, fld, sub, n in conn.execute("SELECT domain, field, subfield, count(*) FROM papers p"
                                         " GROUP BY 1, 2, 3").fetchall():
        total += n
        if dom:
            for key in (f"d{dom}", fld, sub):
                count[key] = count.get(key, 0) + n
    where, args = _area_sql(q.area)
    area_count = conn.execute(f"SELECT count(*) FROM papers p WHERE {where}", args).fetchone()[0]
    if q.view == "claims":
        cond, cargs = [where, "c.listed"], list(args)
        if not q.all:
            cond.append("c.role = 'principal'")
        for col, val in (("c.type", q.type), ("c.novelty", q.novelty)):
            if val:
                cond.append(f"{col} = %s")
                cargs.append(val)
        if q.planning:
            cond.append("coalesce(c.planning, 'exploratory') = %s")
            cargs.append(q.planning)
        if q.band:
            cond.append("c.band = %s")
            cargs.append(q.band)
        order = ("p.updated DESC, coalesce(c.score, -1) ASC" if q.sort == "newest" else
                 "coalesce(c.score, -1) DESC, p.updated ASC")
        sql = (" FROM claims c JOIN papers p ON p.concept_id = c.concept_id AND c.version = p.current_version"
               f" WHERE {' AND '.join(cond)}")
        n_rows = conn.execute("SELECT count(*)" + sql, cargs).fetchone()[0]
        page_rows = conn.execute(f"SELECT c.concept_id, c.claim_id{sql} ORDER BY {order}, p.concept_id, c.position"
                                 " LIMIT %s OFFSET %s", cargs + [PAGE, q.offset]).fetchall()
        docs = _files(conn, [r[0] for r in page_rows])
        shown = []
        for concept, cid in page_rows:
            d = docs.get(concept)
            c = next((x for x in (d or {}).get("claims") or [] if isinstance(x, dict) and x.get("id") == cid), None)
            if c is None:
                continue
            sc = scores_of(d, published_dir)
            item = sc["claims"].get(cid) if sc else None
            shown.append((d, c, sc, item["score"] if item else -1))
    else:
        cond, cargs = [where], list(args)
        if q.band:
            cond.append("p.band = %s")
            cargs.append(q.band)
        order = "p.updated DESC" if q.sort == "newest" else "coalesce(p.score, -1) DESC, p.updated DESC"
        sql = f" FROM papers p WHERE {' AND '.join(cond)}"
        n_rows = conn.execute("SELECT count(*)" + sql, cargs).fetchone()[0]
        page_rows = conn.execute(f"SELECT p.concept_id{sql} ORDER BY {order}, p.concept_id LIMIT %s OFFSET %s",
                                 cargs + [PAGE, q.offset]).fetchall()
        docs = _files(conn, [r[0] for r in page_rows])
        shown = [docs[r[0]] for r in page_rows if r[0] in docs]
    return _layout(q, base_url, corrected, count, total, n_rows, shown, area_count)


def _files(conn, concepts):
    """{concept: its current version's file} for the papers a page shows."""
    if not concepts:
        return {}
    return {c: f for c, f in conn.execute(
        "SELECT p.concept_id, v.file FROM papers p JOIN versions v ON v.concept_id = p.concept_id"
        " AND v.version = p.current_version WHERE p.concept_id = ANY(%s)", (list(set(concepts)),)).fetchall()}


def _layout(q, base_url, corrected, count, total, n_rows, shown, area_count):
    """The Read page: the tree (`count` per area, `total` papers), the tabs and filters, `n_rows` results of which
    `shown` (this page's), and the pager. Its canonical address is the area's own, without filters, so that search
    engines index one page per area."""
    tabs = "".join(f'<a href="{q.url(view=v, offset="")}"' + (' aria-current="page"' if v == q.view else "")
                   + f">{label}</a>" for v, label in (("claimsets", "Papers"), ("claims", "Claims")))
    if q.view == "claims":
        what = "claims" if q.all else "principal claims"
        body = (f'<ol class="results">{"".join(_claim_item(d, c, sc) for d, c, sc, _ in shown)}</ol>' if shown
                else '<p class="muted">No claims here match.</p>')
    else:
        what = "papers"
        body = (f'<div class="cards">{site._cards(shown, corrected)}</div>' if shown
                else '<p class="muted">No papers here match.</p>')
    more = []
    if q.offset:
        more.append(f'<a href="{q.url(offset=max(0, q.offset - PAGE))}">Previous</a>')
    if q.offset + PAGE < n_rows:
        more.append(f'<a href="{q.url(offset=q.offset + PAGE)}">Next</a>')
    main = (f'<div class="wrap"><h1>Read</h1>{site._search_form(view=q.view)}'
            f'<div class="read-layout">{_tree(count, total, q)}<div class="read-main">'
            f'<h2>{site.esc(area_name(q.area))}</h2><nav class="tabs" aria-label="Show">{tabs}</nav>{_filters(q)}'
            f'<p class="muted">{n_rows} {what}' + (f", {q.offset + 1}–{q.offset + len(shown)}" if n_rows > PAGE
                                                  else "") + "</p>"
            f'{body}' + (f'<p class="pager">{" · ".join(more)}</p>' if more else "") + "</div></div></div>")
    title = "Read" if not q.area else f"{area_name(q.area)}: papers and claims"
    description = (f"{area_name(q.area)} on EntryLib: {area_count} paper{'s' if area_count != 1 else ''}, their "
                   "claims with their support scores, each with what it rests on." if q.area else
                   "What EntryLib holds, by field: its papers, and their claims with their support scores.")
    return site.shell(title, main, active="read", description=description,
                      canonical=base_url + areas.path(q.area) if base_url else None)
