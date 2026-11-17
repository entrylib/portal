"""The paper view of a claimset (design §7.4, *Paper view*): the same file as the record page, set out as a paper.

The record page lists a claimset's objects by kind: definitions, claims, evidence. A reader who wants the argument
reads the paper view: the claims in the order the argument needs them, each with its name, its plain summary, its
statement, and under the statement what supports it (the proof in steps, or the figures and the rows it cites); beside
a claim, the other claims of the paper that bear on it, with the observations their relation names. What the record
holds of a claim besides (its plan, its checks, its score) is one click away, and everything else is on the record
page, which the view links to.

    render(doc, record, file_url=None, ref_text=None, number=None, scores=None)
        -> {"sections": [(id, title, count, html)], "extra": html}

Nothing here decides what a field means: the view reads the fields the claimset format defines (`name`, `summary`,
`symbol`, a relation's `results`, a figure's `shows`), and a file without them is shown without them. Everything
taken from the file is escaped.
"""

import re

from claimset.render import DIGITS

from . import page as pageview
from .page import esc

#: A formula, a term mark or code: claim IDs inside them are left alone.
SEGMENT = re.compile(r"\$\$.+?\$\$|\$[^$\s][^$]*?\$|\\\(.+?\\\)|\[\[[^\]]+\]\]|`[^`]+`", re.S)
CLAIM_REF = re.compile(r"\bC\d+\b")
#: The mark of a statement's part, (a), (b), … (claimset §8 rule 11).
PART = re.compile(r"(?:(?<=[\s:;.])|^)\(([a-h])\)\s")
#: How a claim's support is named in its heading, the first of its kinds that is listed here.
SUPPORT_WORDS = (("formal_proof", "proved"), ("empirical_quant", "evidence"), ("empirical_qual", "evidence"),
                 ("empirical_obs", "evidence"), ("simulation", "simulation"), ("demonstration", "demonstration"),
                 ("argument", "argued"), ("cited", "from earlier work"), ("consensus", "established knowledge"),
                 ("expert_judgement", "judgement"))
#: A relation to another claim of the paper, read from that claim's side.
INCOMING = {"supports": "Supported by", "qualifies": "Qualified by", "explains": "Explained by",
            "contradicts": "Contradicted by", "refines": "Refined by",
            "disputes_evidence": "Its evidence is disputed by"}
RELATION = {"supports": "Supports", "contradicts": "Contradicts", "extends": "Extends", "refines": "Refines",
            "replicates": "Repeats", "fails_to_replicate": "Does not repeat", "supersedes": "Supersedes",
            "addresses": "Answers", "explains": "Explains", "qualifies": "Qualifies",
            "disputes_evidence": "Disputes the evidence of"}
NOVELTY = {"extension": "extends earlier work", "no_prior_found": "no earlier result found",
           "replication": "repeats an earlier result", "refutation": "refutes an earlier result",
           "synthesis": "states what earlier work establishes"}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
#: The most figures shown under a claim; the rest open in the viewer.
SHOWN_FIGURES = 4


def _dicts(x):
    return [y for y in x if isinstance(y, dict)] if isinstance(x, list) else []


def _strs(x):
    return [y for y in x if isinstance(y, str)] if isinstance(x, list) else []


def _number_of(cid):
    m = re.search(r"\d+", cid)
    return int(m.group(0)) if m else 0


def _day(ts):
    try:
        y, m, d = str(ts)[:10].split("-")
        return f"{int(d)} {MONTHS[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return esc(str(ts))


class _View:
    def __init__(self, doc, record, P, scores):
        self.doc, self.record, self.P = doc, record, P
        self.claims = {c["id"]: c for c in P.claims}
        self.evidence = {e["id"]: e for e in P.evidence}
        self.defs = {d["id"]: d for d in P.defs}
        self.arts = {a["id"]: a for a in P.artefacts}
        self.refs = {b["id"]: b for b in P.refs}
        self.warrants = {w["id"]: w for w in P.warrants}
        self.people = {c["id"]: c for c in _dicts(doc.get("contributors")) if isinstance(c.get("id"), str)}
        self.scores = (scores or {}).get("claims") if isinstance(scores, dict) else None
        self.shown = [cid for cid in self.order() if not P.is_assumption(self.claims[cid])]
        self.assumed = [c["id"] for c in P.claims if P.is_assumption(c)]
        self.galleries, self.panels, self.tables_shown = {}, [], set()
        # what bears on a claim from the paper's other claims: {target: [(claim, relation)]}
        self.incoming = {}
        for c in P.claims:
            for r in _dicts(c.get("relations")):
                if r.get("id_type") == "local" and r.get("target") in self.claims and r["target"] != c["id"]:
                    self.incoming.setdefault(r["target"], []).append((c, r))

    # ---------- order ----------
    def proof(self, c):
        """The evidence that holds a claim's proof in steps, or None."""
        for sp in _dicts(c.get("support")):
            e = self.evidence.get(sp.get("evidence")) if isinstance(sp.get("evidence"), str) else None
            if sp.get("kind") == "formal_proof" and e is not None and _dicts(e.get("steps")):
                return e
        return None

    def needs(self, c):
        out = _strs(c.get("depends_on"))
        e = self.proof(c)
        for st in _dicts((e or {}).get("steps")):
            out += [b for b in _strs(st.get("by")) if b in self.claims]
        return sorted({x for x in out if x in self.claims and x != c["id"]}, key=_number_of)

    def order(self):
        """Reading order: a claim after the claims it depends on and those its proof uses, otherwise by ID."""
        done, seen = [], set()

        def visit(cid):
            if cid in seen:
                return
            seen.add(cid)
            for n in self.needs(self.claims[cid]):
                visit(n)
            done.append(cid)
        for cid in sorted(self.claims, key=_number_of):
            visit(cid)
        return done

    # ---------- text ----------
    def name(self, cid):
        n = self.claims.get(cid, {}).get("name")
        return " ".join(n.split()) if isinstance(n, str) and n.strip() else ""

    def xref(self, cid, cap=True, bare=False):
        shown = cid if bare else ("Claim " if cap else "claim ") + cid
        title = f' title="{esc(self.name(cid))}"' if self.name(cid) else ""
        return f'<a class="pv-xref" href="#{esc(cid)}"{title}>{esc(shown)}</a>'

    def text(self, s, foreign=None, this=None):
        """A text of the file as the record page writes it (terms, formulae, code), with each ID of a claim of this
        paper as a link that names it: "claim C3". `foreign`: the ID, in this text, of a cited paper's claim;
        `this`: the claim the text stands under, written "this claim"."""
        if not isinstance(s, str):
            return esc(s)
        spans = [(m.start(), m.end()) for m in SEGMENT.finditer(s)]
        out, last = [], 0
        for m in CLAIM_REF.finditer(s):
            cid = m.group(0)
            if cid == foreign or cid not in self.claims or any(a <= m.start() < b for a, b in spans):
                continue
            before = s[:m.start()].rstrip()
            cap = not before or before[-1] in ".∎"
            if cid == this:
                out.append(s[last:m.start()] + ("This claim" if cap else "this claim"))
            else:
                out.append(s[last:m.start()] + f"\x00{cid}{'U' if cap else 'l'}\x00")
            last = m.end()
        out.append(s[last:])
        html = self.P.text("".join(out))
        return re.sub("\x00(C\\d+)([Ul])\x00", lambda m: self.xref(m.group(1), cap=m.group(2) == "U"), html)

    def statement(self, s):
        """A statement; its parts (a), (b), … as a list (claimset §8 rule 11)."""
        if not isinstance(s, str):
            return ""
        spans = [(m.start(), m.end()) for m in SEGMENT.finditer(s)]
        marks, want = [], "a"
        for m in PART.finditer(s):
            if m.group(1) == want and not any(a <= m.start() < b for a, b in spans):
                marks.append(m)
                want = chr(ord(want) + 1)
        if len(marks) < 2:
            return f'<p class="pv-statement">{self.text(s)}</p>'
        items = []
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(s)
            part = s[m.end():end].strip().rstrip(";")
            items.append(f'<li><span class="pv-mark">({m.group(1)})</span>'
                         f'<span class="pv-part">{self.text(part[:1].upper() + part[1:])}</span></li>')
        lead = s[:marks[0].start()].strip()
        return ((f'<p class="pv-statement">{self.text(lead)}</p>' if lead else "")
                + f'<ol class="pv-parts">{"".join(items)}</ol>')

    # ---------- figures and tables ----------
    def figures(self, e, named=None):
        """The figures of an evidence object that can be shown; with `named` (references to its observations), those
        whose `shows` names one of them or its table."""
        figs = [a for a in self.P.figures_of(e) if self.P.image_src(a)]
        if named:
            wanted = set(named) | {".".join(x.split(".")[:2]) for x in named if x.count(".") == 2}
            figs = [a for a in figs if wanted & set(_strs(a.get("shows")))]
        return figs

    def caption(self, a):
        return (f'<span class="cs-id">{esc(a["id"])}</span> '
                f'{self.text(a.get("description") or a.get("uri") or a["id"])}')

    def gallery(self, gid, figs):
        """The figures a viewer steps through, written once in the page; the id of the set."""
        if gid not in self.galleries:
            self.galleries[gid] = ('<ol class="pv-gallery" id="' + esc(gid) + '" hidden>' + "".join(
                f'<li data-src="{esc(self.P.image_src(a))}">{self.caption(a)}</li>' for a in figs) + "</ol>")
        return gid

    def figure(self, a, gid, i):
        src = self.P.image_src(a)
        return (f'<figure class="cs-figure"><a href="{esc(src)}" data-gallery="{esc(gid)}" data-i="{i}">'
                f'<img src="{esc(src)}" alt="{esc(pageview._first_sentence(a.get("description") or ""))}" '
                f'loading="lazy"></a><figcaption>{self.caption(a)}</figcaption></figure>')

    def rows(self, e, t, only):
        """A table with the rows named in `only` alone, without IDs of its own (it may stand twice in a page)."""
        P, eid = self.P, e["id"]
        head = [P.term(x) for x in t.get("row_labels") or []] + [P.column(c) for c in t.get("columns") or []]
        body = []
        for r in _dicts(t.get("rows")):
            if f"{eid}.{t.get('id')}.{r.get('id')}" in only:
                body.append("<tr>" + "".join(f'<th scope="row">{P.term(x)}</th>' for x in r.get("label") or [])
                            + "".join(pageview._cell(P, v) for v in r.get("values") or []) + "</tr>")
        return (f'<div class="cs-table"><table><caption>{esc(eid)}.{esc(t.get("id"))} · '
                f'{self.text(t.get("description", ""))}</caption><thead><tr>'
                + "".join(f'<th scope="col">{h}</th>' for h in head) + "</tr></thead><tbody>"
                + "".join(body) + "</tbody></table></div>")

    def named_rows(self, e, named, cited):
        """The rows a list of references names: a row itself; of a whole table, the rows `cited` holds of it, or all."""
        rows = set()
        for ref in named:
            parts = ref.split(".")
            if len(parts) == 3:
                rows.add(ref)
            elif len(parts) == 2:
                t = next((t for t in _dicts(e.get("tables")) if t.get("id") == parts[1]), None)
                if t is not None:
                    own = [x for x in cited if x.startswith(ref + ".")]
                    rows |= set(own or [f"{ref}.{r.get('id')}" for r in _dicts(t.get("rows"))])
        return rows

    # ---------- what supports a claim ----------
    def proof_block(self, e):
        steps = _dicts(e.get("steps"))
        end = ""
        if steps[-1].get("rule") == "conclusion" and len(steps) > 1:
            end = (f'<p class="pv-qed">{self.text(steps[-1].get("statement", ""))} '
                   f'<span class="pv-end" aria-label="end of proof">∎</span></p>')
            steps = steps[:-1]
        items = []
        for st in steps:
            s = st.get("statement", "")
            by = [b for b in _strs(st.get("by")) if b in self.claims and not re.search(rf"\b{b}\b", str(s))]
            tail = f' <span class="pv-by">(by {", ".join(self.xref(b, cap=False) for b in by)})</span>' if by else ""
            items.append(f"<li>{self.text(s)}{tail}</li>")
        if not end:
            items[-1] = items[-1][:-5] + ' <span class="pv-end" aria-label="end of proof">∎</span></li>'
        n = len(_dicts(e.get("steps")))
        return (f'<details class="pv-proof"><summary><span class="pv-proof-word">Proof</span> '
                f'<span class="pv-count">{n} step{"s" if n != 1 else ""}</span></summary>'
                f'<ol class="pv-steps">{"".join(items)}</ol>{end}</details>')

    def evidence_block(self, c, sp, e):
        """The observations a support entry cites, with the figures that show them; the whole of the evidence is on
        the record page."""
        P, eid, out = self.P, e["id"], []
        cited = _strs(sp.get("results"))
        figs = self.figures(e, cited) or self.figures(e)
        every = self.figures(e)
        if figs:
            gid = self.gallery(f"gal-{eid}", every)
            shown = figs[:SHOWN_FIGURES]
            many = " cs-figures-many" if len(shown) > 1 else ""
            out.append(f'<div class="cs-figures{many}">'
                       + "".join(self.figure(a, gid, every.index(a)) for a in shown) + "</div>")
            if len(every) > len(shown):
                out.append(f'<p class="pv-more"><a href="{esc(self.record)}#{esc(eid)}" data-gallery="{esc(gid)}" '
                           f'data-i="0">View all {len(every)} figures</a></p>')
        if e.get("estimate") is not None and not cited:
            out.append(f'<p>{esc(e.get("estimand", ""))} = {esc(pageview._num(e["estimate"]))} '
                       f'{esc(pageview._uncertainty(e.get("uncertainty")))} '
                       f'{esc(pageview._interval(e.get("interval")))}</p>')
        wanted = {x.split(".")[1] for x in cited if x.startswith(eid + ".") and x.count(".") >= 1}
        results = [r for r in _dicts(e.get("results")) if r.get("id") in wanted]
        if results:
            out.append('<ul class="cs-results">' + "".join(pageview._result(P, e, r, ids=False) for r in results)
                       + "</ul>")
        for t in _dicts(e.get("tables")):
            if t.get("id") in wanted:
                key = f"{eid}.{t.get('id')}"
                if key in self.tables_shown:
                    out.append(f'<p class="pv-more">Table {esc(key)}: <a href="#{esc(key)}">shown above</a>.</p>')
                else:
                    self.tables_shown.add(key)
                    out.append(pageview._table(P, eid, t))
        out.append(f'<p class="pv-more">Everything recorded for this evidence: '
                   f'<a href="{esc(self.record)}#{esc(eid)}">{esc(eid)} in the record</a>.</p>')
        return '<div class="pv-evidence"><p class="pv-label">Evidence</p>' + "".join(out) + "</div>"

    def support(self, c):
        """Under a statement: its proof, its evidence, its argument, the work it rests on."""
        out, proof = [], self.proof(c)
        if proof is not None:
            out.append(self.proof_block(proof))
        checked = []
        for sp in _dicts(c.get("support")):
            kind = sp.get("kind")
            e = self.evidence.get(sp.get("evidence")) if isinstance(sp.get("evidence"), str) else None
            if e is not None and e is not proof:
                if proof is not None:                       # beside a proof, other evidence is a check of it
                    checked.append(f'<a href="{esc(self.record)}#{esc(e["id"])}">{esc(e["id"])}</a>')
                else:
                    out.append(self.evidence_block(c, sp, e))
            elif kind == "cited":
                rid = sp.get("reference")
                where = (self.P.ref(rid, sp.get("locator")) if rid in self.refs
                         else esc(pageview._s(sp.get("target") or "")))
                out.append(f'<p class="pv-rests"><span class="pv-label">Rests on</span> {where}</p>')
            elif kind == "argument":
                w = self.warrants.get(sp.get("warrant") or c.get("warrant"))
                if w is not None:
                    out.append(f'<details class="pv-proof"><summary><span class="pv-proof-word">Argument</span>'
                               f'</summary><p>{self.text(w.get("text", ""))}</p></details>')
        if checked:
            out.append(f'<p class="pv-more">Its formulae were also checked on numbers: {", ".join(checked)} in the '
                       f'record.</p>')
        return "".join(out)

    def beside(self, c):
        """The paper's other claims that bear on this one: with the observations their relation names, a box with
        the figures that show them and the rows; otherwise a line."""
        boxes, lines = [], []
        for by, r in self.incoming.get(c["id"], []):
            word = INCOMING.get(r.get("type"), pageview._s(r.get("type")).replace("_", " "))
            note = self.text(r.get("note") or "", this=c["id"])
            named = _strs(r.get("results"))
            sp = next((x for x in _dicts(by.get("support")) if x.get("evidence") in self.evidence), None)
            e = self.evidence.get(sp["evidence"]) if sp else None
            figs = self.figures(e, named) if e is not None and named else []
            rows = self.named_rows(e, named, _strs(sp.get("results"))) if e is not None and named else set()
            if not figs and not rows:
                lines.append(f'<li><span class="pv-rel">{esc(word)} {self.xref(by["id"], cap=False)}.</span> '
                             f'{note}</li>')
                continue
            links = []
            thumb = ""
            if figs:
                gid = self.gallery(f"gal-{c['id']}-{by['id']}", figs)
                src = self.P.image_src(figs[0])
                thumb = (f'<a class="pv-thumb" href="{esc(src)}" data-gallery="{esc(gid)}" data-i="0" '
                         f'aria-label="Open the figures"><img src="{esc(src)}" alt="" loading="lazy"></a>')
                links.append(f'<a href="{esc(src)}" data-gallery="{esc(gid)}" data-i="0">{len(figs)} '
                             f'figure{"s" if len(figs) != 1 else ""}</a>')
            if rows:
                pid = f"rows-{c['id']}-{by['id']}"
                tables = [t for t in _dicts(e.get("tables"))
                          if any(f"{e['id']}.{t.get('id')}.{x.get('id')}" in rows for x in _dicts(t.get("rows")))]
                self.panels.append(f'<template id="{esc(pid)}">'
                                   + "".join(self.rows(e, t, rows) for t in tables)
                                   + f'<p><a href="#{esc(by["id"])}">The tables in full, under claim '
                                     f'{esc(by["id"])}</a></p></template>')
                links.append(f'<a href="#{esc(by["id"])}" data-rows="{esc(pid)}">{len(rows)} table '
                             f'row{"s" if len(rows) != 1 else ""}</a>')
            links.append(self.xref(by["id"]))
            boxes.append(f'<div class="pv-beside{"" if thumb else " pv-beside-plain"}">{thumb}<div>'
                         f'<p class="pv-label">{esc(word)} {esc("claim " + by["id"])}</p><p>{note}</p>'
                         f'<p class="pv-links">{" · ".join(links)}</p></div></div>')
        more = (f'<div class="pv-remarks"><p class="pv-label">Elsewhere in this paper</p><ul>{"".join(lines)}</ul>'
                f'</div>') if lines else ""
        return "".join(boxes) + more

    def remarks(self, c):
        """What the claim's relations say of earlier work and of the paper's other claims."""
        items = []
        for r in _dicts(c.get("relations")):
            word = RELATION.get(r.get("type"), pageview._s(r.get("type")).replace("_", " ").capitalize())
            note = r.get("note") or ""
            if r.get("id_type") == "local" and r.get("target") in self.claims:
                items.append(f'<li><span class="pv-rel">{esc(word)} {self.xref(r["target"], cap=False)}.</span> '
                             f'{self.text(note)}</li>')
                continue
            rid = r.get("reference")
            b = self.refs.get(rid) if isinstance(rid, str) else None
            if b is not None:
                target = b.get("target") if isinstance(b.get("target"), str) else ""
                foreign = target.split("#")[1] if b.get("id_type") == "claimset" and "#" in target else None
                where = self.P.ref(rid, r.get("locator"))
                items.append(f'<li><span class="pv-rel">{esc(word)} {where}.</span> {self.text(note, foreign)}</li>')
            else:
                shown = esc(pageview._s(r.get("target") or ""))
                items.append(f'<li><span class="pv-rel">{esc(word)} {shown}.</span> {self.text(note)}</li>')
        if not items:
            return ""
        return (f'<div class="pv-remarks"><p class="pv-label">Earlier work and other claims</p>'
                f'<ul>{"".join(items)}</ul></div>')

    # ---------- the record of a claim ----------
    def who(self, pid):
        p = self.people.get(pid, {})
        if p.get("type") == "agent":
            return "an AI agent" + (f" ({p['label']})" if isinstance(p.get("label"), str) else "")
        return pageview._s(p.get("name") or pid)

    def record_fold(self, c):
        cid, line, rows = c["id"], [], []
        kinds = [sp.get("kind") for sp in _dicts(c.get("support"))]
        if self.proof(c) is not None:
            line.append("Proved")
            last = {}
            for ch in _dicts(c.get("checks")):
                if isinstance(ch.get("by"), str):
                    last[ch["by"]] = ch
            for pid, ch in last.items():
                if ch.get("outcome") == "confirmed":
                    agent = self.people.get(pid, {}).get("type") == "agent"
                    line.append("checked independently by an AI agent" if agent
                                else f"confirmed by {esc(self.who(pid))}")
        plan = c.get("test") if isinstance(c.get("test"), dict) else c.get("estimate") if isinstance(
            c.get("estimate"), dict) else None
        if c.get("planning") in ("confirmatory", "confirmatory_with_deviations"):
            line.append("tested as planned" if c["planning"] == "confirmatory"
                        else "tested, with deviations from its plan")
        elif c.get("planning") == "planned_estimate":
            line.append("estimated as planned")
        elif c.get("planning") == "exploratory":
            line.append("exploratory")
        strengths = [f"{a.get('strength')} support, by its {a.get('by')}" for a in _dicts(c.get("assessments"))
                     if a.get("strength")]
        line += [esc(s) for s in strengths]
        rows.append(("Claim", " · ".join(esc(pageview._s(x).replace("_", " ")) for x in (
            cid, c.get("type"), c.get("role"), NOVELTY.get(c.get("novelty"), c.get("novelty"))) if x)))
        if plan and plan.get("lab_plan"):
            what = "Test" if isinstance(c.get("test"), dict) else "Estimate"
            when = f", recorded {_day(c['planned_at'])}" if c.get("planned_at") else ""
            rows.append(("Plan", f"{what} planned in lab plan {esc(plan['lab_plan'])}{when}"))
        ev = [f'<a href="{esc(self.record)}#{esc(sp["evidence"])}">{esc(sp["evidence"])}</a>'
              for sp in _dicts(c.get("support")) if isinstance(sp.get("evidence"), str)]
        if ev:
            rows.append(("Evidence", ", ".join(ev) + " in the record"))
        elif kinds:
            rows.append(("Support", esc(", ".join(pageview._s(k).replace("_", " ") for k in kinds if k))))
        for ch in _dicts(c.get("checks")):
            res = f" <i>{esc(ch['resolution'])}</i>" if isinstance(ch.get("resolution"), str) else ""
            rows.append((f"Check: {esc(pageview._s(ch.get('outcome')))}",
                         f"By {esc(self.who(ch.get('by')))}"
                         + (f", {esc(ch['extent'])}" if isinstance(ch.get("extent"), str) else "")
                         + f". {esc(pageview._s(ch.get('notes') or ''))}{res}"))
        if isinstance(c.get("scope"), dict) and c["scope"]:
            rows.append(("Scope", esc(pageview._scope(c["scope"]))))
        lims = [x for x in _strs(c.get("limitations")) if x in self.P.by_id]
        if lims:
            rows.append(("Limitations", ", ".join(f'<a href="#{esc(x)}">{esc(x)}</a>' for x in lims)))
        sc = self.scores.get(cid) if isinstance(self.scores, dict) else None
        if isinstance(sc, dict) and sc.get("score") is not None:
            rows.append(("Support score", f"{esc(sc['score'])} of 100. The score checks the record, not the science."))
        rows.append(("Record", f'<a href="{esc(self.record)}#{esc(cid)}">This claim on the record page</a>'))
        dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
        shown = " · ".join(line) if line else "What the record holds of this claim"
        return (f'<details class="pv-record"><summary><span class="pv-record-line">{shown}</span>'
                f'<span class="pv-record-word">Record</span></summary><dl>{dl}</dl></details>')

    # ---------- a claim ----------
    def claim(self, c):
        cid = c["id"]
        kinds = {sp.get("kind") for sp in _dicts(c.get("support"))}
        how = next((word for kind, word in SUPPORT_WORDS if kind in kinds), "")
        name = self.name(cid)
        head = (f'<h3><span class="pv-claim-id">Claim {esc(cid)}{"." if name else ""}</span> '
                f'{("<span class=" + chr(34) + "pv-name" + chr(34) + ">" + esc(name) + "</span> ") if name else ""}'
                f'{("<span class=" + chr(34) + "pv-how" + chr(34) + ">" + esc(how) + "</span>") if how else ""}</h3>')
        summary = c.get("summary")
        plain = (f'<p class="pv-summary">{self.text(summary)}</p>'
                 if isinstance(summary, str) and summary.strip() else "")
        return (f'<article class="pv-claim" id="{esc(cid)}">{head}{plain}{self.statement(c.get("statement"))}'
                f'{self.support(c)}{self.beside(c)}{self.remarks(c)}{self.record_fold(c)}</article>')

    # ---------- terms ----------
    def terms(self):
        """The definitions the claims shown name, with those these name in turn, in the file's order."""
        todo = []
        for cid in self.shown:
            c = self.claims[cid]
            todo += [m.group(1) for m in pageview.TERM.finditer(c.get("statement") or "")]
            about = c.get("about") if isinstance(c.get("about"), dict) else {}
            for key in ("subject", "object", "comparator", "conditions"):
                v = about.get(key)
                todo += _strs(v if isinstance(v, list) else [v])
        used = []
        while todo:
            d = todo.pop(0)
            if d in self.defs and d not in used:
                used.append(d)
                todo += [m.group(1) for m in pageview.TERM.finditer(self.defs[d].get("definition") or "")]
        return [d["id"] for d in self.P.defs if d["id"] in used]

    def term(self, did):
        d = self.defs[did]
        sym = d.get("symbol")
        symbol = f' <span class="pv-symbol">{self.text(sym)}</span>' if isinstance(sym, str) and sym.strip() else ""
        return (f'<div class="pv-term" id="{esc(did)}"><dt>{esc(pageview._s(d.get("term")))}{symbol}</dt>'
                f'<dd>{self.text(d.get("definition", ""))}</dd></div>')


def render(doc, record, file_url=None, ref_text=None, number=None, scores=None):
    """The sections of the paper view that are its own, [(id, title, count, html)]: *Terms*, the definitions the
    claims name, and *Claims*, in reading order; and `extra`, what the page holds besides (the sets of figures the
    viewer steps through, the rows a pop-up shows). `record`: the address of the record page of the same version;
    `number`: how numbers are written, as the record page writes them (`render_parts`)."""
    token = DIGITS.set(number if callable(number) else None)
    try:
        P = pageview._Paper(doc, file_url=file_url, ref_text=ref_text)
        V = _View(doc, record, P, scores)
        claims = "".join(V.claim(V.claims[cid]) for cid in V.shown)
        terms = V.terms()
        rest = len(P.defs) - len(terms)
        other = (f'<p class="pv-more">{rest} more definition{"s" if rest != 1 else ""} (designs, data, cases) '
                 f'{"are" if rest != 1 else "is"} on <a href="{esc(record)}#definitions">the record page</a>.</p>'
                 if rest > 0 else "")
        sections = []
        if terms:
            sections.append(("terms", "Terms", len(terms),
                             '<section class="cs-section pv-section" id="terms"><h2>Terms</h2>'
                             '<p class="pv-lead">What the claims below name. A term in the text links back here.</p>'
                             f'<dl class="pv-terms">{"".join(V.term(d) for d in terms)}</dl>{other}</section>'))
        sections.append(("claims", "Claims", len(V.shown),
                         '<section class="cs-section pv-section" id="claims"><h2>Claims</h2>'
                         '<p class="pv-lead">In the order the argument needs them. What supports a claim stands '
                         'under its statement.<button type="button" class="button-quiet pv-open-all" hidden '
                         'data-open="Open all proofs" data-close="Close all proofs">Open all proofs</button></p>'
                         f'{claims}</section>'))
        return {"sections": sections, "extra": "".join(V.galleries.values()) + "".join(V.panels)}
    finally:
        DIGITS.reset(token)
