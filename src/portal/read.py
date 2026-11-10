"""The Read page, /read (design §7.7): what EntryLib holds, as a tree of OpenAlex domains, fields and subfields (only
those with claimsets), and for the part chosen its principal claims (or all claims) or its claimsets, filtered and
sorted. Rendered by the app, without scripts.

Scores come from the rubric over each claimset's current file; they are kept in memory per version and rubric
version. Fine while the library has hundreds of claimsets; past that, the indexer should store them.
"""

import functools
import json
from dataclasses import dataclass, field
from importlib import resources

from . import ids, score_html, site
from . import scores as score_data

PAGE = 50
TYPES = ["descriptive", "associational", "causal", "mechanistic", "predictive", "interpretive", "formal",
         "methodological"]
NOVELTY = {"no_prior_found": "New", "extension": "Extends", "replication": "Replicates", "refutation": "Refutes"}
PLANNING = {"confirmatory": "Planned test", "exploratory": "Exploratory"}
BANDS = {"high": "High (80+)", "medium": "Medium (60–79)", "low": "Low (under 60)"}
SORTS = {"reliability": "Reliability", "newest": "Newest"}


@functools.cache
def taxonomy():
    data = json.loads(resources.files("portal").joinpath("data/fields.json").read_text(encoding="utf-8"))
    return data["domains"], data["fields"]


def area_of(doc):
    """(domain, field, subfield) numbers of a claimset, by its subfield; (None, None, None) without one."""
    c = doc["paper"].get("classification")
    sub = c.get("subfield") if isinstance(c, dict) else None
    sub = sub.rsplit("/", 1)[-1] if isinstance(sub, str) else None
    domains, fields = taxonomy()
    if not sub or sub[:2] not in fields:
        return None, None, None
    return fields[sub[:2]]["domain"], sub[:2], sub


def area_name(area):
    domains, fields = taxonomy()
    if not area:
        return "Everything"
    if area.startswith("d"):
        return domains.get(area[1:], area)
    if len(area) == 2:
        return fields.get(area, {}).get("name", area)
    return site._subfields().get(area, area)


def in_area(where, area):
    domain, fld, sub = where
    if not area:
        return True
    if area.startswith("d"):
        return domain == area[1:]
    return fld == area if len(area) == 2 else sub == area


@functools.lru_cache(maxsize=2048)
def _scores(concept, version, rubric, text):
    return score_data.compute(None, json.loads(text))


def scores_of(doc):
    p = doc["paper"]
    if score_data.rubric is None:
        return None
    return _scores(p["id"], p.get("version"), score_data.version(), json.dumps(doc, sort_keys=True))


@dataclass
class Query:
    area: str = ""
    view: str = "claims"
    all: bool = False
    type: str = ""
    band: str = ""
    novelty: str = ""
    planning: str = ""
    sort: str = "reliability"
    offset: int = 0
    errors: list = field(default_factory=list)

    @classmethod
    def parse(cls, params):
        q = cls()
        domains, fields = taxonomy()
        area = str(params.get("area") or "")
        if area and not (area in {f"d{d}" for d in domains} or area in fields or area in site._subfields()):
            area = ""
        q.area = area
        q.view = "claimsets" if params.get("view") == "claimsets" else "claims"
        q.all = params.get("all") in ("1", "on", "true")
        q.type = params.get("type") if params.get("type") in TYPES else ""
        q.band = params.get("band") if params.get("band") in BANDS else ""
        q.novelty = params.get("novelty") if params.get("novelty") in NOVELTY else ""
        q.planning = params.get("planning") if params.get("planning") in PLANNING else ""
        q.sort = params.get("sort") if params.get("sort") in SORTS else "reliability"
        try:
            q.offset = max(0, int(params.get("offset") or 0))
        except ValueError:
            q.offset = 0
        return q

    def url(self, **change):
        values = {"area": self.area, "view": self.view, "all": "1" if self.all else "", "type": self.type,
                  "band": self.band, "novelty": self.novelty, "planning": self.planning,
                  "sort": self.sort if self.sort != "reliability" else "", "offset": ""}
        values.update({k: v for k, v in change.items()})
        parts = [f"{k}={site.esc(v)}" for k, v in values.items() if v not in ("", None, 0, "0")]
        return "/read" + ("?" + "&amp;".join(parts) if parts else "")


def _tree(docs, q):
    domains, fields = taxonomy()
    subs = site._subfields()
    count = {}
    for d in docs:
        dom, fld, sub = area_of(d)
        for key in (f"d{dom}", fld, sub):
            if dom:
                count[key] = count.get(key, 0) + 1

    def link(area, name):
        current = ' aria-current="page"' if area == q.area else ""
        return f'<a href="{q.url(area=area)}"{current}>{site.esc(name)}</a> <span class="count">{count[area]}</span>'

    out = [f'<li><a href="{q.url(area="")}"' + (' aria-current="page"' if not q.area else "")
           + f'>Everything</a> <span class="count">{len(docs)}</span></li>']
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
    hidden = f'<input type="hidden" name="area" value="{site.esc(q.area)}">' if q.area else ""
    hidden += f'<input type="hidden" name="view" value="{q.view}">' if q.view != "claims" else ""
    sort = "".join(f'<option value="{k}"' + (" selected" if k == q.sort else "") + f">{v}</option>"
                   for k, v in SORTS.items())
    claim_filters = ""
    if q.view == "claims":
        claim_filters = (_select("type", "Type", {t: t for t in TYPES}, q.type)
                         + _select("novelty", "Novelty", NOVELTY, q.novelty)
                         + _select("planning", "Plan", PLANNING, q.planning)
                         + '<label class="check"><input type="checkbox" name="all" value="1"'
                         + (" checked" if q.all else "") + "> All claims, not only principal</label>")
    return (f'<form class="read-filters" action="/read" method="get">{hidden}{claim_filters}'
            + _select("band", "Reliability", BANDS, q.band)
            + f'<label>Sort <select name="sort">{sort}</select></label><button type="submit">Apply</button></form>')


def _claim_item(doc, c, sc):
    key = ids.url_key(doc["paper"]["id"])
    cid = c["id"]
    item = sc["claims"].get(cid) if sc else None
    mark = ""
    if item:
        mark = (f'<a class="score-badge band-{item["band"]}" href="/p/{key}#score-{site.esc(cid)}" '
                f'aria-label="Reliability {item["score"]}, {item["band"]}">{item["score"]}</a>'
                + score_html.dots(sc, cid))
    meta = [site.esc(cid), site.esc(c.get("type")), site.esc(c.get("role"))]
    n = score_data.label((sc or {}).get("novelty", {}).get(cid)) if sc else ""
    if n:
        meta.append(f"novelty: {site.esc(n)}")
    return (f'<li class="result"><p class="card-top">{mark}{" · ".join(m for m in meta if m)}</p>'
            f'<p class="card-claim">{site.plain_html(c.get("statement"))}</p>'
            f'<p class="card-who"><a href="/p/{key}#{site.esc(cid)}">{site.esc(doc["paper"].get("title"))}</a> · '
            f'{site.esc(doc["paper"]["id"])}@v{site.esc(doc["paper"].get("version"))}</p></li>')


def claims(docs, q):
    """The claims shown: (doc, claim, scores, score) of every current claimset in the area, filtered."""
    out = []
    for d in docs:
        if not in_area(area_of(d), q.area):
            continue
        sc = scores_of(d)
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


def claimsets(docs, q):
    out = []
    for d in docs:
        if not in_area(area_of(d), q.area):
            continue
        sc = scores_of(d)
        paper = sc["paper"] if sc else None
        if q.band and (not paper or paper["band"] != q.band):
            continue
        out.append((d, paper["score"] if paper else -1))
    if q.sort == "newest":
        out.sort(key=lambda r: str(r[0]["paper"].get("date")), reverse=True)
    else:
        out.sort(key=lambda r: -r[1])
    return [d for d, _ in out]


def page(docs, q):
    """The Read page. `docs`: the current version of every published claimset."""
    tabs = "".join(f'<a href="{q.url(view=v, offset="")}"' + (' aria-current="page"' if v == q.view else "")
                   + f">{label}</a>" for v, label in (("claims", "Claims"), ("claimsets", "Claimsets")))
    if q.view == "claims":
        rows = claims(docs, q)
        shown = rows[q.offset:q.offset + PAGE]
        what = "claims" if q.all else "principal claims"
        body = (f'<ol class="results">{"".join(_claim_item(d, c, sc) for d, c, sc, _ in shown)}</ol>' if shown
                else '<p class="muted">No claims here match.</p>')
    else:
        rows = claimsets(docs, q)
        shown = rows[q.offset:q.offset + PAGE]
        what = "claimsets"
        body = (f'<div class="cards">{"".join(site.card(d) for d in shown)}</div>' if shown
                else '<p class="muted">No claimsets here match.</p>')
    more = []
    if q.offset:
        more.append(f'<a href="{q.url(offset=max(0, q.offset - PAGE))}">Previous</a>')
    if q.offset + PAGE < len(rows):
        more.append(f'<a href="{q.url(offset=q.offset + PAGE)}">Next</a>')
    main = (f'<div class="wrap"><h1>Read</h1>{site._search_form()}'
            f'<div class="read-layout">{_tree(docs, q)}<div class="read-main">'
            f'<h2>{site.esc(area_name(q.area))}</h2><nav class="tabs" aria-label="Show">{tabs}</nav>{_filters(q)}'
            f'<p class="muted">{len(rows)} {what}' + (f", {q.offset + 1}–{q.offset + len(shown)}" if len(rows) > PAGE
                                                     else "") + "</p>"
            f'{body}' + (f'<p class="pager">{" · ".join(more)}</p>' if more else "") + "</div></div></div>")
    return site.shell("Read", main, active="read", description="What EntryLib holds, by field: its claims with "
                      "their reliability, and its claimsets.")
