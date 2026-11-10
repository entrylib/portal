"""The parts of research a claimset can belong to (design §7.7): OpenAlex's four domains, 26 fields and its subfields,
each with an address on the Read page.

    area_of(doc)       -> (domain, field, subfield) numbers of a claimset, from its classification
    name(area)         -> "Decision Sciences"; an area is "d2" (a domain), "18" (a field) or "1803" (a subfield)
    path(area)         -> "/read/social-sciences/decision-sciences"
    from_path(parts)   -> the area at a path under /read, or None
    paths(docs)        -> the paths of every area that holds a claimset, for the sitemap
"""

import functools
import json
import re
from importlib import resources


def _data(name):
    return json.loads(resources.files("portal").joinpath(f"data/{name}").read_text(encoding="utf-8"))


@functools.cache
def taxonomy():
    """(domains {number: name}, fields {number: {name, domain}}, subfields {number: name})."""
    f = _data("fields.json")
    return f["domains"], f["fields"], _data("subfields.json")["subfields"]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def area_of(doc):
    c = doc["paper"].get("classification")
    sub = c.get("subfield") if isinstance(c, dict) else None
    sub = sub.rsplit("/", 1)[-1] if isinstance(sub, str) else None
    domains, fields, subs = taxonomy()
    if not sub or sub[:2] not in fields:
        return None, None, None
    return fields[sub[:2]]["domain"], sub[:2], sub


def valid(area):
    domains, fields, subs = taxonomy()
    return bool(area) and (area in {f"d{d}" for d in domains} or area in fields or area in subs)


def name(area):
    domains, fields, subs = taxonomy()
    if not area:
        return "Everything"
    if area.startswith("d"):
        return domains.get(area[1:], area)
    if len(area) == 2:
        return fields.get(area, {}).get("name", area)
    return subs.get(area, area)


def chain(area):
    """The area and those above it, from the domain down: ["d2", "18", "1803"]."""
    domains, fields, subs = taxonomy()
    if not valid(area):
        return []
    if area.startswith("d"):
        return [area]
    fld = area[:2]
    top = [f"d{fields[fld]['domain']}", fld]
    return top if len(area) == 2 else top + [area]


def path(area):
    return "/read" + "".join(f"/{slug(name(a))}" for a in chain(area))


@functools.cache
def _by_path():
    domains, fields, subs = taxonomy()
    areas = [f"d{d}" for d in domains] + list(fields) + list(subs)
    return {path(a): a for a in areas}


def from_path(rest):
    """The area whose address is /read/<rest>, or None."""
    return _by_path().get("/read/" + rest.strip("/")) if rest.strip("/") else None


def in_area(where, area):
    domain, fld, sub = where
    if not area:
        return True
    if area.startswith("d"):
        return domain == area[1:]
    return fld == area if len(area) == 2 else sub == area


def paths(docs):
    """The Read addresses of every area that holds at least one of `docs`, sorted."""
    out = set()
    for d in docs:
        dom, fld, sub = area_of(d)
        if dom:
            out.update(path(a) for a in (f"d{dom}", fld, sub))
    return sorted(out)
