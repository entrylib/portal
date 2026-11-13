"""The page view: a claimset as HTML for people, in the order of the paper's argument. EntryLib's own (design
§7.1): moved here from the claimset package, which keeps only the reading view for models (claimset.render), whose way
of writing values (numbers, intervals, statistics) this view shares.

    render_parts(doc, file_url=None, ref_text=None, digits=None, number=None, person=None, marker=None,
                 claim_url=None) -> HTML fragments: header,
                                       nav, body (and the title, the origin label, the brief, the sections)
    render_html(doc)  -> a whole page, with the stylesheet inline, for previewing a claimset locally
    origin(doc)       -> the origin label: lab, lab · record withheld, converted or native

The view is derived mechanically from a valid claimset file, like the reading view (render.py), and adds nothing that
is not in the file except what is computed from it: the support lights (from verifiability, §5), the selection of
claims under Highlights when the authors gave no highlights, and the author-year labels of references.

Everything taken from the file is escaped: the view is safe to publish however the file was written. Links are made
only to the file's own objects (#C3), to ORCID and doi.org, and to http(s) addresses the file gives. Images (figures,
and the images behind observation records) are shown only from addresses the caller gives for the claimset's own files
(`file_url`); an image elsewhere is linked, never embedded, so reading the page loads nothing from other sites.
A site may also write out references the file gives only by identifier (`ref_text(reference)`: a DOI's metadata, as
"Surname, A., & Other, B. (2018). Title. Journal."), so that they read as author (year) too.

Maths in text ($...$) is MathML (mathml.py), which browsers show without a script; `code` in backticks is code.

Order: Summary (when the paper has one), Highlights, Context, Definitions (grouped by kind), Assumptions, Principal claims, Supporting claims, Evidence,
Limitations, Open questions, References, Artefacts. The classes are stable: a site styles them with claimset.css, or
its own rules.
"""

import html
import json
import re

from claimset.render import DIGITS
from claimset.render import interval as _interval
from claimset.render import number as _num
from claimset.render import statistic as _statistic
from claimset.render import statistic_note as _stat_note
from claimset.render import uncertainty as _uncertainty
from claimset.render import value as _val

from . import source as source_paper
from .mathml import to_mathml


def _s(x):
    return x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)


def _join(items, sep="; "):
    return sep.join(i for i in items if i)

#: How many principal claims Highlights shows at most.
BRIEF_MAX = 5

TERM = re.compile(r"\[\[([^:\]]+):([^\]]+)\]\]")
YEAR = re.compile(r"\((\d{4}[a-z]?)\)")
SURNAME = re.compile(r"(?:^|,\s*|&\s*|and\s+)([^\W\d_][^,&()]*?),\s*(?:[^\W\d_]\.)")

#: Definition groups, in the order a reader meets them, with their headings.
KIND_GROUPS = [("method", "Methods"), ("data", "Data"), ("variable", "Variables and measures"),
               ("design", "Study design"), ("population", "Populations"), ("intervention", "Interventions"),
               ("setting", "Settings"), ("substance", "Substances"), ("organism", "Organisms"),
               ("biological_material", "Biological materials"), ("entity", "Entities"), ("process", "Processes"),
               ("source", "Sources"), ("concept", "Concepts"), ("theory", "Theories"), ("other", "Other terms")]

#: Files shown as images, by extension.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")

SUPPORT_LABELS = {"empirical_quant": "Data", "empirical_qual": "Qualitative data", "empirical_obs": "Observations",
                  "simulation": "Simulation", "formal_proof": "Proof", "demonstration": "Demonstration",
                  "argument": "Argument", "cited": "Cited", "expert_judgement": "Expert judgement",
                  "consensus": "Consensus", "unstated": "Support not stated"}

#: The file's vocabularies as a reader would say them (the reading view, for models, keeps the values).
SCOPE_WORDS = {"population": "population", "setting": "setting", "geography": "where", "language": "language",
               "period": "period", "data_type": "data", "conditions": "conditions", "excludes": "not for"}
NOVELTY_WORDS = {"replication": "replicates earlier work", "extension": "extends earlier work",
                 "refutation": "refutes earlier work"}
VERIFICATION_WORDS = {"machine_checked": "checked by a proof assistant", "agent_checked": "checked by an agent",
                      "peer_checked": "checked by a person", "disputed": "disputed", "unchecked": "not checked"}
VERDICT_WORDS = {"computed": "computed from the recorded results", "judged": "judged by the writer"}
FLAG_WORDS = {"code_changed_after_plan": "the code changed after the plan",
              "holdout_used_elsewhere": "the held-out data was used elsewhere",
              "reproduces_prompting_result": "it repeats the result that suggested it",
              "sources_captured_after_plan": "sources were captured after the plan",
              "diagnostic_missing": "a run left out a check the plan required",
              "coded_before_plan": "material was coded before the plan",
              "codebook_changed_after_plan": "the codebook changed after the plan"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]

#: Lights (§2.3 of the website design): from the claim's verifiability and the kinds of its support.
LIGHTS = {"green": "checkable", "amber": "supported, not checkable", "red": "unsupported"}
NOT_CHECKABLE = {"argument", "cited", "expert_judgement", "consensus"}


MATH = re.compile(r"\$\$(.+?)\$\$|\$([^$\s][^$]*?)\$|\\\((.+?)\\\)", re.S)
CODE = re.compile(r"(`+)(.+?)\1", re.S)


def math(tex, display=False):
    """An expression as MathML (claimset.mathml), on a line of its own when the author wrote it as $$...$$ (spec §8
    rule 6), in the sentence when written as $...$; one it cannot read is shown as written, as code."""
    out = to_mathml(tex, display)
    return out if out is not None else f'<code class="math-tex">{esc(tex)}</code>'


def esc(x):
    return html.escape(x if isinstance(x, str) else _s(x), quote=True)


def _safe_url(url):
    """An address a site gives for a link (a path on the site or an http(s) address), safe to put in an attribute."""
    return (url.startswith("/") and not url.startswith("//") or url.startswith(("https://", "http://"))) \
        and not any(ch in url for ch in "\"'<> ")


def _href(uri):
    """A link only to an http(s) address; anything else is shown as text."""
    return isinstance(uri, str) and uri.startswith(("https://", "http://")) and not any(c in uri for c in "\"'<> ")


def _link(uri, text=None):
    text = esc(text if text is not None else uri)
    return f'<a href="{esc(uri)}">{text}</a>' if _href(uri) else text


def _link_name(uri, limit=40):
    """What a link to an artefact is called: its file's name, or else its site (`model.R`, `zenodo.org`)."""
    path = re.sub(r"[?#].*$", "", str(uri)).rstrip("/")
    host = re.sub(r"^https?://", "", path).split("/")[0]
    tail = path.rsplit("/", 1)[-1] if "/" in re.sub(r"^https?://", "", path) else ""
    name = tail or host or str(uri)
    if re.fullmatch(r"[0-9a-f]{40}", name) and re.search(r"/(tree|commit)/[0-9a-f]{40}$", path):
        name = f"repository at {name[:7]}"           # a repository at a commit: its hash says nothing to a reader
    return name if len(name) <= limit else name[:limit - 1] + "…"


def _doi(x):
    return _link(f"https://doi.org/{x}", f"doi:{x}") if isinstance(x, str) and x.startswith("10.") else esc(x)


def _readable(text):
    """Text for a tooltip, which shows no markup: terms as shown, formulas as the characters their MathML shows
    ("$\\epsilon_t$" as "ϵt"), never as LaTeX."""
    text = TERM.sub(lambda m: m.group(2), text or "")

    def formula(m):
        tex = m.group(1) or m.group(2) or m.group(3) or ""
        shown = to_mathml(tex)
        if shown is None:
            return tex
        shown = re.sub(r"<annotation\b.*?</annotation>", "", shown, flags=re.S)    # the TeX it was made from
        return html.unescape(re.sub(r"<[^>]+>", "", shown))
    return MATH.sub(formula, text)


def _first_sentence(text, limit=160):
    text = _readable(text)
    m = re.search(r"(?<=[.;])\s", text)
    text = text[:m.start()] if m and m.start() < limit else text
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


class _Paper:
    """The claimset's objects indexed, and what is computed once for the whole view."""

    def __init__(self, doc, file_url=None, ref_text=None):
        self.doc = doc
        self.person = None                                  # the site's choices (render_parts): people,
        self.marker = None                                  # what marks a claim,
        self.claim_url = None                               # and a claim's own page
        self.file_url = file_url
        self.ref_text = ref_text
        self.paper = doc.get("paper") if isinstance(doc.get("paper"), dict) else {}
        def listed(k):
            return [x for x in doc.get(k) or [] if isinstance(x, dict) and isinstance(x.get("id"), str)]
        self.claims, self.defs, self.evidence = listed("claims"), listed("definitions"), listed("evidence")
        self.limitations, self.questions = listed("limitations"), listed("open_questions")
        self.refs, self.artefacts, self.warrants = listed("references"), listed("artefacts"), listed("warrants")
        self.by_id = {x["id"]: x for lst in (self.claims, self.defs, self.evidence, self.limitations, self.refs,
                                             self.artefacts, self.warrants, self.questions) for x in lst}
        self.labels = self._reference_labels()
        self.computed = self._verifiability()
        self.used_by = self._uses()

    # ---------- references ----------
    def _reference_labels(self):
        """Author (year) for each reference: "Hyndman et al. (2008)", "Kolassa (2011)"; a, b for repeats."""
        labels, self.written = {}, {}
        for b in self.refs:
            t, kind = b.get("target"), b.get("id_type")
            if kind not in (None, "reference") and self.ref_text is not None:
                written = self.ref_text(b)                    # the site's lookup (a DOI's metadata, say)
                if isinstance(written, str) and written.strip():
                    self.written[b["id"]] = t = written.strip()
                    kind = "reference"
            if kind == "doi":
                labels[b["id"]] = f"doi:{t}"
                continue
            if kind not in (None, "reference") or not isinstance(t, str):
                labels[b["id"]] = _s(t)
                continue
            y = YEAR.search(t)
            if not y:
                labels[b["id"]] = t if len(t) <= 40 else t[:39].rstrip() + "…"
                continue
            names = [n.strip() for n in SURNAME.findall(t[:y.start()])] or [t.split(",")[0].strip()]
            who = (names[0] if len(names) == 1 else f"{names[0]} and {names[1]}" if len(names) == 2
                   else f"{names[0]} et al.")
            labels[b["id"]] = f"{who} ({y.group(1)})"
        seen = {}
        for rid, lab in labels.items():
            seen.setdefault(lab, []).append(rid)
        for lab, rids in seen.items():
            if len(rids) > 1 and lab.endswith(")"):
                for i, rid in enumerate(rids):
                    labels[rid] = f"{lab[:-1]}{chr(97 + i)})"
        return labels

    def ref(self, rid, locator=None):
        lab = self.labels.get(rid, rid)
        return f'<a class="ref" href="#{esc(rid)}">{esc(lab)}</a>' + (f", {esc(locator)}" if locator else "")

    # ---------- verifiability and lights ----------
    def _verifiability(self):
        """The platform's verifiability where the file lacks it (a submission being previewed)."""
        if all("verifiability" in c for c in self.claims):
            return {}
        try:
            from claimset.validate import validate
            return {cid: v.get("verifiability") for cid, v in (validate(self.doc).computed or {}).items()}
        except Exception:                                   # noqa: BLE001 - a preview without lights is still a preview
            return {}

    def is_assumption(self, c):
        return bool(c.get("assumption_category")) or any(
            isinstance(s, dict) and s.get("kind") == "assumption" for s in c.get("support") or [])

    def light(self, c):
        if self.is_assumption(c):
            return None
        v = c.get("verifiability") or self.computed.get(c["id"])
        kinds = {s.get("kind") for s in c.get("support") or [] if isinstance(s, dict)}
        if v == "unverifiable" or not kinds or kinds == {"unstated"}:
            return "red"
        if v == "audit_only" or kinds <= NOT_CHECKABLE:
            return "amber"
        return "green"

    def mark(self, c, where):
        """What comes before a claim (`where`: `claim` or `brief`) and after its meta line: the site's (`marker`,
        render_parts), or the claim's support light before and nothing after."""
        if self.marker is not None:
            shown = self.marker(c, where)
            if isinstance(shown, str):
                return shown, ""
            if isinstance(shown, tuple) and len(shown) == 2 and all(isinstance(x, str) for x in shown):
                return shown
        return self.lamp(c), ""

    def claim_id(self, c):
        """A claim's ID in its meta line: linked to the claim's own page when the site gives one (`claim_url`)."""
        url = self.claim_url(c["id"]) if self.claim_url is not None else None
        if isinstance(url, str) and _safe_url(url):
            return f'<a class="cs-claim-page" href="{esc(url)}">{esc(c["id"])}</a>'
        return esc(c["id"])

    def lamp(self, c):
        light = self.light(c)
        if not light:
            return ""
        return f'<span class="light light-{light}" role="img" aria-label="{LIGHTS[light]}" title="{LIGHTS[light]}"></span>'

    # ---------- who uses what ----------
    def _uses(self):
        """For each object, the objects that point to it: claims using a claim, claims citing evidence, places
        citing a reference."""
        used = {}

        def add(target, by):
            if isinstance(target, str) and target in self.by_id and by not in used.setdefault(target, []):
                used[target].append(by)
        for c in self.claims:
            for t in (c.get("depends_on") or []) + (c.get("assumptions") or []) + (c.get("limitations") or []):
                add(t, c["id"])
            for s in c.get("support") or []:
                if isinstance(s, dict):
                    for key in ("evidence", "warrant", "reference"):
                        add(s.get(key), c["id"])
            for rel in c.get("relations") or []:
                if isinstance(rel, dict):
                    add(rel.get("reference"), "context")
            if isinstance(c.get("test"), dict):
                add(c["test"].get("registration"), c["id"])
        for d in self.defs + self.evidence:
            for t in d.get("assumptions") or []:
                add(t, d["id"])
            src = d.get("source")
            add(src.get("reference") if isinstance(src, dict) else src, d["id"])
        for lim in self.limitations:
            for t in lim.get("affects") or []:
                add(lim["id"], t)
        for a in self.artefacts:
            add(a.get("reference"), a["id"])
        return used

    def users(self, oid, skip=()):
        out = []
        for u in self.used_by.get(oid, []):
            if u in skip:
                continue
            out.append('<a href="#context">Context</a>' if u == "context" else f'<a href="#{esc(u)}">{esc(u)}</a>')
        return ", ".join(out)

    # ---------- text ----------
    def text(self, s):
        """A statement or description: escaped, with [[D1:term]] as a link to the definition, inline LaTeX
        ($...$, $$...$$, \\(...\\)) as MathML and `code` as code."""
        if not isinstance(s, str):
            return esc(s)
        out, last = [], 0
        for m in CODE.finditer(s):
            out.append(self._maths(s[last:m.start()]))
            out.append(f'<code class="cs-code">{esc(m.group(2).strip())}</code>')
            last = m.end()
        out.append(self._maths(s[last:]))
        return "".join(out)

    def _maths(self, s):
        out, last = [], 0
        for m in MATH.finditer(s):
            out.append(self._terms(s[last:m.start()]))
            tex, end = m.group(1) or m.group(2) or m.group(3), m.end()
            display = m.group(1) is not None             # the author's choice: $$…$$ (§8 rule 6)
            if display and end < len(s) and s[end] in ",.;:":   # a formula on its own line keeps its punctuation
                tex, end = tex + s[end], end + 1
            out.append(math(tex, display=display))
            last = end
        out.append(self._terms(s[last:]))
        return "".join(out)

    def _terms(self, s):
        out, last = [], 0
        for m in TERM.finditer(s):
            out.append(esc(s[last:m.start()]))
            tid, shown = m.group(1), m.group(2)
            d = self.by_id.get(tid)
            if d is not None and d in self.defs:
                tip = f"{d.get('term', '')}: " + _first_sentence(d.get("definition", ""))
                out.append(f'<a class="term" href="#{esc(tid)}" title="{esc(tip)}">{esc(shown)}</a>')
            else:
                out.append(esc(shown))
            last = m.end()
        out.append(esc(s[last:]))
        return "".join(out)

    # ---------- images ----------
    def image_src(self, a):
        """Where an artefact's image is shown from, or None: only a file of the claimset. With `file_url`, the site
        says (a published file's address need not end in its type, so the site, which holds the file, decides
        whether it is an image); without it, a relative path ending in an image extension (a local preview)."""
        uri = a.get("uri")
        if not isinstance(uri, str):
            return None
        if self.file_url is not None:
            src = self.file_url(a)
        elif not uri.lower().split("?")[0].endswith(IMAGE_EXTENSIONS):
            return None
        else:
            src = None if "://" in uri or uri.startswith(("/", "\\")) or ".." in uri.split("/") else uri
        return src if isinstance(src, str) and src and not any(c in src for c in "\"'<> ") else None

    def figure(self, a, small=False):
        """An artefact shown as an image with its caption, or linked when it is not a file of the claimset."""
        desc = a.get("description") or a.get("uri") or a["id"]
        src = self.image_src(a)
        caption = f'<span class="cs-id">{esc(a["id"])}</span> {self.text(desc)}'
        if src is None:
            return (f'<p class="cs-links"><span class="k">Figure:</span> {caption}'
                    + (f" ({_link(a['uri'], 'open')})" if _href(a.get("uri")) else "") + "</p>")
        cls = "cs-figure cs-figure-small" if small else "cs-figure"
        return (f'<figure class="{cls}"><a href="{esc(src)}"><img src="{esc(src)}" alt="{esc(_first_sentence(desc))}" '
                f'loading="lazy"></a><figcaption>{caption}</figcaption></figure>')

    def figures_of(self, e):
        """The artefacts that show this evidence: the images its observation records are read from, figures whose
        `shows` names its results or tables, and figures named in the support that cites it."""
        eid, found = e["id"], []
        for x in e.get("records") or []:
            if isinstance(x, dict) and x.get("artefact") in self.by_id:
                found.append(x["artefact"])
        for a in self.artefacts:
            shows = a.get("shows") or []
            if a.get("kind") == "figure" and any(isinstance(s, str) and (s == eid or s.startswith(eid + "."))
                                                 for s in shows):
                found.append(a["id"])
        for c in self.claims:
            for s in c.get("support") or []:
                if isinstance(s, dict) and s.get("evidence") == eid:
                    found += [x for x in s.get("artefacts") or [] if x in self.by_id
                              and self.by_id[x].get("kind") == "figure"]
        out = []
        for aid in found:
            if aid not in out:
                out.append(aid)
        return [self.by_id[aid] for aid in out]

    def term(self, x):
        """A value that is a definition's ID, shown as its term (linked); anything else as text."""
        if isinstance(x, str) and x in self.by_id and self.by_id[x] in self.defs:
            d = self.by_id[x]
            tip = f"{d.get('term', '')}: " + _first_sentence(d.get("definition", ""))
            return f'<a class="term" href="#{esc(x)}" title="{esc(tip)}">{esc(d.get("term", x))}</a>'
        return esc(_s(x))

    def conditions(self, c):
        if not isinstance(c, dict) or not c:
            return ""
        return "(" + ", ".join(f"{self.term(k)}: {self.term(v)}" for k, v in c.items()) + ")"

    def column(self, c):
        if isinstance(c, dict):
            note = _stat_note(c)
            return _join([self.term(c.get("variable")), self.conditions(c.get("conditions"))], " ") + esc(note)
        return self.term(c)

    def value(self, v):
        return self.term(v) if isinstance(v, str) else esc(_val(v))

    def ids(self, ids):
        return ", ".join(f'<a href="#{esc(i)}">{esc(i)}</a>' if i in self.by_id else esc(i)
                         for i in ids if isinstance(i, str))


# ---------- Highlights ----------
def brief(doc):
    """The IDs shown under Highlights, and whether they were selected automatically. The authors' highlights when the file
    has them (principal claims and terms the paper introduces, spec §3.1); otherwise all principal claims when there are at most five; otherwise a computed choice:
    ranked by how many claims, warrants and open questions use them (directly or through other claims), one per claim
    type first, near-duplicates skipped, shown in the file's order."""
    P = doc if isinstance(doc, _Paper) else _Paper(doc)
    principal = [c for c in P.claims if c.get("role") == "principal"]
    order = [cid for cid in P.paper.get("contributions") or [] if cid in P.by_id] or [c["id"] for c in principal]
    hl = [h for h in P.paper.get("highlights") or [] if isinstance(h, str) and h in P.by_id
          and (P.by_id[h] in P.defs or P.by_id[h] in P.claims)]
    if hl:
        return hl[:BRIEF_MAX], False
    if len(order) <= BRIEF_MAX:
        return order, False
    users = {}
    for c in P.claims:
        for t in c.get("depends_on") or []:
            users.setdefault(t, set()).add(c["id"])
    for q in P.questions:
        for t in q.get("claims") or []:
            users.setdefault(t, set()).add(q["id"])
    for w in P.warrants:
        for t in w.get("premises") or []:
            users.setdefault(t, set()).add(w["id"])

    def reach(cid, seen=None):
        seen = set() if seen is None else seen
        for u in users.get(cid, ()):
            if u not in seen:
                seen.add(u)
                reach(u, seen)
        return seen
    score = {cid: len(reach(cid)) for cid in order}
    ranked = sorted(order, key=lambda cid: (-score[cid], order.index(cid)))
    words = {cid: set(re.findall(r"\w+", TERM.sub(lambda m: m.group(2), P.by_id[cid].get("statement", "")).lower()))
             for cid in order}

    def near(a, b):
        u = words[a] | words[b]
        return bool(u) and len(words[a] & words[b]) / len(u) > 0.7
    chosen, types = [], set()
    for first_pass in (True, False):
        for cid in ranked:
            if len(chosen) >= BRIEF_MAX or cid in chosen or any(near(cid, x) for x in chosen):
                continue
            t = P.by_id[cid].get("type")
            if first_pass and t in types:
                continue
            chosen.append(cid)
            types.add(t)
    return sorted(chosen, key=order.index), True


# ---------- the parts ----------
def _origin(P):
    if isinstance(P.paper.get("converted_from"), dict) or P.paper.get("origin") == "converted":
        return "converted"
    lab = any(a.get("kind") == "lab_record" for a in P.artefacts) or isinstance(P.paper.get("exploration"), dict)
    if lab:
        withheld = any(a.get("kind") == "lab_record" and (a.get("availability") or {}).get("level") not in (None, "public")
                       for a in P.artefacts)
        return "lab · record withheld" if withheld else "lab"
    return "native"


def origin(doc):
    """Where a claimset comes from, as its label reads: `lab`, `lab · record withheld`, `converted` or `native`."""
    return _origin(_Paper(doc))


def _person(c, verified=False):
    name = esc(c.get("name", ""))
    orcid = c.get("orcid")
    if not isinstance(orcid, str) or not orcid:
        return name
    cls = "orcid orcid-verified" if verified else "orcid"
    return (f'{name} <span class="orcid-wrap">(<a class="{cls}" href="https://orcid.org/{esc(orcid)}">'
            f'{esc(orcid)}</a>)</span>')


def _author(c, P=None, where="author"):
    """A person or agent named in the header: the site's way (`person`, render_parts), or plain text: a person with
    their ORCID link; an agent with its label after its name (v0.41: `Claude Code · drafting`) and "(AI agent)"."""
    if P is not None and P.person is not None:
        shown = P.person(c, where)
        if isinstance(shown, str):
            return shown
    if where == "guarantor":
        return _person(c, True)
    if c.get("type") == "agent":
        label = c.get("label") if isinstance(c.get("label"), str) and c.get("label").strip() else None
        return (f'{esc(c.get("name") or "an AI agent")}'
                + (f' <span class="cs-label">· {esc(label.strip())}</span>' if label else "") + " (AI agent)")
    return _person(c)


def _line(P, role, people, default):
    """One line of people in the header: the site's (`byline`) or `default`."""
    if getattr(P, "byline", None):
        shown = P.byline(role, people)
        if isinstance(shown, str):
            return shown
    return default


def _header(P):
    p, out = P.paper, []
    out.append(f'<h1 class="cs-title">{esc(p.get("title", ""))}</h1>')
    people = [c for c in P.doc.get("contributors") or [] if isinstance(c, dict)]
    guarantors = [c for c in people if "guarantor" in (c.get("positions") or [])]
    if guarantors:
        out.append('<p class="cs-guarantor">' + _line(P, "guarantor", guarantors, "Guarantor: " + ", ".join(
            _author(g, P, "guarantor") for g in guarantors)) + "</p>")
    cf = p.get("converted_from") if isinstance(p.get("converted_from"), dict) else None
    if cf:
        authors = [a for a in cf.get("source_authors") or [] if isinstance(a, dict)]
        if authors:
            source = [{**a, "type": "human"} for a in authors]
            out.append('<p class="cs-authors">' + _line(P, "source_authors", source, "Authors of the source paper: "
                       + ", ".join(_author(a, P, "source_author") for a in source)) + "</p>")
        converters = [c for c in people if "converter" in (c.get("positions") or [])]
        by = ", ".join(_author(c, P, "converter") for c in converters)
        src = _doi(cf.get("source_id")) if cf.get("id_type", "doi") == "doi" else esc(cf.get("source_id"))
        out.append(f'<p class="cs-source">Converted from {src}'
                   + (f" ({esc(cf['source_version'])})" if cf.get("source_version") else "")
                   + (f" by {by}" if by else "") + "</p>")
    else:
        # People besides the responsible researcher (design §7.4): every author of the original paper, for a paper its
        # authors converted, in the file's order; else the co-authors, those who supervised and those who contributed.
        # The position `author` is for agents.
        humans = [c for c in people if c.get("type") != "agent"]
        if source_paper.own_paper(P.doc) and len(humans) > 1:
            out.append('<p class="cs-authors">' + _line(P, "paper_authors", humans, "Authors of the original paper: "
                       + ", ".join(_author(c, P, "author") for c in humans)) + "</p>")
        else:
            for role, label, position in (("coauthors", "Co-authors: ", "coauthor"),
                                          ("supervisors", "Supervised by: ", "supervisor"),
                                          ("contributors", "Contributors: ", "contributor")):
                group = [c for c in humans if position in (c.get("positions") or [])
                         and "guarantor" not in (c.get("positions") or [])]
                if group:
                    out.append('<p class="cs-authors">' + _line(P, role, group, label
                               + ", ".join(_author(c, P, "author") for c in group)) + "</p>")
        authors = [c for c in people if "author" in (c.get("positions") or [])]
        if authors:
            out.append('<p class="cs-authors">' + _line(P, "authors", authors, "Authors: "
                       + ", ".join(_author(c, P) for c in authors)) + "</p>")
    kw = (p.get("classification") or {}).get("keywords") if isinstance(p.get("classification"), dict) else None
    meta = [esc(p["licence"]) if p.get("licence") else "",
            ("Keywords: " + esc(", ".join(k for k in kw if isinstance(k, str)))) if isinstance(kw, list) and kw else ""]
    if isinstance(P.doc.get("extensions"), dict) and P.doc["extensions"]:
        meta.append("Extensions: " + esc(", ".join(f"{k} {v}" for k, v in P.doc["extensions"].items())))
    meta = [m for m in meta if m]
    if meta:
        out.append('<p class="cs-meta">' + " · ".join(meta) + "</p>")
    return "\n".join(out)


def _support(P, c):
    parts = []
    for s in c.get("support") or []:
        if not isinstance(s, dict) or s.get("kind") == "assumption":
            continue
        label = SUPPORT_LABELS.get(s.get("kind"), esc(s.get("kind")))
        ptr = []
        if s.get("evidence"):
            e = s["evidence"]
            res = [r[len(e) + 1:] if isinstance(r, str) and r.startswith(f"{e}.") else r for r in s.get("results") or []]
            ptr.append(f'<a href="#{esc(e)}">{esc(e)}</a>' + (f" ({esc(', '.join(map(str, res)))})" if res else ""))
        if s.get("warrant"):
            ptr.append(f'<a href="#{esc(s["warrant"])}">{esc(s["warrant"])}</a>')
        if s.get("reference"):
            ptr.append(P.ref(s["reference"], s.get("locator")))
        elif s.get("target"):
            ptr.append(_doi(s["target"]) if s.get("id_type") == "doi" else esc(s["target"]))
        if s.get("artefacts"):
            ptr.append("artefacts " + P.ids(s["artefacts"]))
        if s.get("self"):
            ptr.append("own earlier work")
        parts.append(f"{label}: " + ", ".join(ptr) if ptr else label)
    return parts


def _scope(sc):
    """A claim's scope in words: "data: M4 yearly series; conditions: backcasting, smooth 1.3.0"."""
    if not isinstance(sc, dict):
        return ""
    out = []
    for k, v in sc.items():
        vals = v if isinstance(v, list) else [v]
        vals = [_s(x) for x in vals if x not in (None, "")]
        if vals:
            out.append(f"{SCOPE_WORDS.get(k, _words(k))}: " + ", ".join(vals))
    return "; ".join(out)


def _words(x):
    """A value of the file's vocabularies as words: code_changed_after_plan -> code changed after plan."""
    return _s(x).replace("_", " ")


def _date(x):
    """An ISO date or time as a reader's date: 2026-11-05T11:37:01Z -> 5 November 2026; anything else as written."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?", _s(x).strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        return _s(x)
    return f"{int(m.group(3))} {MONTHS[int(m.group(2)) - 1]} {m.group(1)}"


def _claim(P, c, principal=False):
    head = [P.claim_id(c), esc(c.get("type"))]
    if NOVELTY_WORDS.get(c.get("novelty")):
        head.append(NOVELTY_WORDS[c["novelty"]])
    if c.get("planning") == "confirmatory":
        head.append("planned test")
    elif c.get("planning") == "planned_estimate":
        head.append("planned estimate")
    before, after = P.mark(c, "claim")
    lines = [f'<p class="cs-claim-meta">{before}' + " · ".join(h for h in head if h) + f"{after}</p>",
             f'<p class="cs-statement">{P.text(c.get("statement", ""))}</p>']
    links = []
    if c.get("scope"):
        links.append(f'<span class="k">Scope:</span> {P.text(_scope(c["scope"]))}')
    sup = _support(P, c)
    if sup:
        links.append(" · ".join(sup))
    if c.get("depends_on"):
        links.append('<span class="k">Uses:</span> ' + P.ids(c["depends_on"]))
    if c.get("assumptions"):
        links.append('<span class="k">Assumes:</span> ' + P.ids(c["assumptions"]))
    if c.get("limitations"):
        links.append('<span class="k">Limitations:</span> ' + P.ids(c["limitations"]))
    rels = []
    for rel in c.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        target = (P.ref(rel["reference"], rel.get("locator")) if rel.get("reference")
                  else P.ids([rel.get("target")]) if rel.get("id_type") == "local"
                  else _doi(rel.get("target")) if rel.get("id_type") == "doi" else esc(rel.get("target")))
        rels.append(f'<span class="k">{esc(str(rel.get("type", "")).replace("_", " ").capitalize())}:</span> {target}')
    links += rels
    if c.get("warrant"):
        links.append('<span class="k">Warrant:</span> ' + P.ids([c["warrant"]]))
    if c.get("verification"):
        links.append(f'<span class="k">Verification:</span> '
                     f'{esc(VERIFICATION_WORDS.get(c["verification"], _words(c["verification"])))}')
    t = c.get("test")
    if isinstance(t, dict):
        plan = _join([f"lab plan {t['lab_plan']}" if t.get("lab_plan") else "",
                      f"registered {t['registration']}" if t.get("registration") else "",
                      f"planned {_date(c['planned_at'])}" if c.get("planned_at") else ""], ", ")
        if plan:
            links.append(f'<span class="k">Planned:</span> {esc(plan)}')
        if t.get("verdict"):
            links.append(f'<span class="k">Outcome:</span> {esc(VERDICT_WORDS.get(t["verdict"], _words(t["verdict"])))}')
        if t.get("flags"):
            links.append('<span class="k">Weaknesses:</span> '
                         + esc("; ".join(FLAG_WORDS.get(f, _words(f)) for f in t["flags"])))
    e = c.get("estimate")
    if isinstance(e, dict):
        plan = _join([f"lab plan {e['lab_plan']}" if e.get("lab_plan") else "",
                      f"registered {e['registration']}" if e.get("registration") else "",
                      f"planned {_date(c['planned_at'])}" if c.get("planned_at") else ""], ", ")
        if plan:
            links.append(f'<span class="k">Planned:</span> {esc(plan)}')
        if e.get("not_obtained"):
            links.append('<span class="k">Not obtained:</span> ' + esc(", ".join(map(str, e["not_obtained"]))))
        if e.get("flags"):
            links.append('<span class="k">Weaknesses:</span> '
                         + esc("; ".join(FLAG_WORDS.get(f, _words(f)) for f in e["flags"])))
    if not principal:
        used = P.users(c["id"])
        if used:
            links.append(f'<span class="k">Used by:</span> {used}')
    if links:
        lines.append('<p class="cs-links">' + " · ".join(links) + "</p>")
    return f'<div class="cs-item cs-claim" id="{esc(c["id"])}">' + "".join(lines) + "</div>"


def _definition(P, d, nested=False):
    head = f'<span class="cs-id">{esc(d["id"])}</span>'
    rel = []
    for key, label in (("part_of", "part of"), ("broader", "a kind of")):
        if d.get(key):
            rel.append(f"{label} " + P.ids(d[key] if isinstance(d[key], list) else [d[key]]))
    tail = []
    if d.get("members"):
        tail.append("Members: " + P.ids(d["members"]))
    if d.get("assumptions"):
        tail.append("Assumes " + P.ids(d["assumptions"]))
    src = d.get("source")
    if src:
        rid = src.get("reference") if isinstance(src, dict) else src
        tail.append("Source: " + (P.ref(rid) if rid in P.labels else esc(rid if isinstance(rid, str) else src)))
    if d.get("identifiers"):
        tail.append("Identifiers: " + esc(", ".join(map(str, d["identifiers"]))))
    cls = "cs-def cs-def-nested" if nested else "cs-def"
    return (f'<div class="{cls}" id="{esc(d["id"])}"><p><span class="cs-def-head">{head}'
            + (f' · {" · ".join(rel)}' if rel and nested else "")
            + f' <strong>{esc(d.get("term", ""))}</strong></span>: {P.text(d.get("definition", ""))}'
            + (f' <span class="cs-tail">{". ".join(tail)}.</span>' if tail else "") + "</p></div>")


def _definitions(P):
    if not P.defs:
        return ""
    ids = {d["id"] for d in P.defs}
    parent = {}
    for d in P.defs:
        for key in ("part_of", "broader"):
            v = d.get(key)
            v = v[0] if isinstance(v, list) and v else v
            if isinstance(v, str) and v in ids and P.by_id[v].get("kind") == d.get("kind"):
                parent[d["id"]] = v
                break
    kids = {}
    for cid, pid in parent.items():
        kids.setdefault(pid, []).append(cid)
    out = ['<section class="cs-section" id="definitions"><h2>Definitions</h2>']
    for kind, heading in KIND_GROUPS + [(None, "Other terms")]:
        group = [d for d in P.defs if (d.get("kind") == kind if kind else d.get("kind") not in dict(KIND_GROUPS))]
        if not group:
            continue
        out.append(f'<h3>{heading} <span class="count">{len(group)}</span></h3>')

        def tree(d, depth=0):
            yield _definition(P, d, nested=depth > 0)
            for k in kids.get(d["id"], []):
                yield from tree(P.by_id[k], depth + 1)
        for d in group:
            if d["id"] not in parent:
                out += list(tree(d))
    out.append("</section>")
    return "\n".join(out)


def _table(P, eid, t):
    cols = [P.column(c) for c in t.get("columns") or []]
    units = t.get("units")
    if isinstance(units, list):
        cols = [f"{c} ({esc(u)})" if u else c for c, u in zip(cols, units, strict=False)]
    head = ["Row"] + [P.term(x) for x in t.get("row_labels") or []] + cols
    caption = (f"{esc(eid)}.{esc(t.get('id'))} · {P.text(t.get('description', ''))}"
               + (f" {P.conditions(t.get('conditions'))}" if t.get("conditions") else ""))
    rows = []
    for r in t.get("rows") or []:
        if isinstance(r, dict):
            labels = [P.term(x) for x in r.get("label") or []]
            vals = r.get("values") or []
            rows.append(f'<tr id="{esc(eid)}.{esc(t.get("id", ""))}.{esc(r.get("id", ""))}">'
                        + f'<th scope="row">{esc(r.get("id", ""))}{esc(_stat_note(r))}</th>'
                        + "".join(f"<td>{x}</td>" for x in labels)
                        + "".join(_cell(P, v) for v in vals) + "</tr>")
    return (f'<div class="cs-table" id="{esc(eid)}.{esc(t.get("id", ""))}"><table><caption>{caption}</caption>'
            "<thead><tr>" + "".join(f'<th scope="col">{h}</th>' for h in head) + "</tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table></div>")


def _evidence(P, e, source_link):
    head = [esc(e["id"]), esc(e.get("profile"))]
    for key in ("design", "data_origin", "analytic_approach", "sampling"):
        if e.get(key):
            head.append(esc(_s(e[key]).replace("_", " ")))
    if e.get("n") is not None:
        head.append(f"n {esc(_num(e['n']))}")
    if e.get("preregistered"):
        head.append("preregistered")
    cited = P.users(e["id"])
    if cited:
        head.append(f"cited by {cited}")
    out = [f'<p class="cs-claim-meta">{" · ".join(head)}</p>', f'<p>{P.text(e.get("description", ""))}</p>']
    setup = e.get("setup") if isinstance(e.get("setup"), dict) else {}
    parts = [f"{role} " + ", ".join(P.term(x) for x in setup[role]) for role in ("studied", "cases", "procedure", "lens", "context")
             if isinstance(setup.get(role), list) and setup[role]]
    if parts:
        out.append(f'<p class="cs-links"><span class="k">Setup:</span> {" · ".join(parts)}</p>')
    extra = []
    if e.get("foundation"):
        extra.append(f'<span class="k">Foundation:</span> {esc(e["foundation"])}')
    if e.get("assumptions"):
        extra.append('<span class="k">Assumes:</span> ' + P.ids(e["assumptions"]))
    if e.get("checker"):
        extra.append(f'<span class="k">Checked by:</span> {esc(e["checker"])}')
    if e.get("proof_artefact"):
        extra.append('<span class="k">Proof:</span> ' + P.ids([e["proof_artefact"]]))
    if e.get("profile") == "formal" and not e.get("steps") and not e.get("proof_artefact") and e.get("source_spans"):
        extra.append(f'<span class="k">Derivation:</span> in the source{(", " + source_link) if source_link else ""}')
    if extra:
        out.append('<p class="cs-links">' + " · ".join(extra) + "</p>")
    if e.get("estimate") is not None:
        out.append(f'<p>{esc(e.get("estimand", ""))} = {esc(_num(e["estimate"]))} '
                   f'{esc(_uncertainty(e.get("uncertainty")))} {esc(_interval(e.get("interval")))}</p>')
    results = []
    for r in e.get("results") or []:
        if isinstance(r, dict):
            stat = _statistic(r.get("statistic"))
            more = esc(_join([_uncertainty(r.get("uncertainty")), r.get("unit"), _interval(r.get("interval")),
                              f"n {_num(r['n'])}" if r.get("n") is not None else ""], " "))
            cond = P.conditions(r.get("conditions"))
            var = r.get("variable")
            shown = P.term(var) if isinstance(var, str) and var in P.by_id else P.text(_s(var))
            results.append(f'<li id="{esc(e["id"])}.{esc(r.get("id", ""))}"><span class="cs-id">{esc(r.get("id", ""))}</span> '
                           f'{shown}{(" (" + esc(stat) + ")") if stat else ""} = '
                           f'{"about " if r.get("approximate") is True else ""}{P.value(r.get("value"))}'
                           f'{(" " + more) if more.strip() else ""}{(" " + cond) if cond else ""}</li>')
    if results:
        out.append('<ul class="cs-results">' + "".join(results) + "</ul>")
    for t in e.get("tables") or []:
        if isinstance(t, dict):
            out.append(_table(P, e["id"], t))
    steps = [s for s in e.get("steps") or [] if isinstance(s, dict)]
    if steps:
        out.append('<ol class="cs-steps">' + "".join(
            f'<li id="{esc(e["id"])}.{esc(s.get("id", ""))}">{P.text(s.get("statement", ""))}'
            f' <span class="cs-tail">({P.text(s.get("rule", ""))}'
            f'{"; from " + P.ids(s["by"]) if s.get("by") else ""})</span></li>' for s in steps) + "</ol>")
    for x in e.get("records") or []:
        if isinstance(x, dict):
            out.append(f'<p class="cs-links"><span class="k">Record:</span> {esc(x.get("kind"))}'
                       f'{" in " + P.ids([x["artefact"]]) if x.get("artefact") else ""} · {P.text(x.get("description", ""))}</p>')
    figures = P.figures_of(e)
    if figures:
        out.append('<div class="cs-figures">' + "".join(P.figure(a) for a in figures) + "</div>")
    return f'<div class="cs-item cs-evidence" id="{esc(e["id"])}">' + "".join(out) + "</div>"


def _section(sid, title, items, intro=""):
    if not items:
        return ""
    return (f'<section class="cs-section" id="{sid}"><h2>{title}</h2>{intro}' + "\n".join(items) + "</section>")


def render_parts(doc, file_url=None, ref_text=None, digits=None, number=None, person=None, marker=None,
                 claim_url=None, byline=None):
    """The page view of a claimset in parts, each HTML: `header` (title, guarantor, authors, source, licence and
    keywords), `nav` (the sections with their counts), `body` (the sections), plus `title`, `origin` (lab, converted,
    native), `brief` (the IDs shown under Highlights, and whether they were selected automatically) and `lights` (claims per
    light). `file_url(artefact)` gives the address an image of the claimset is served at, or None when the
    artefact is not an image the site shows; without it, image files are shown from their relative paths (a local
    preview beside the package's files). `ref_text(reference)` writes out a reference the file gives only by
    identifier (a DOI), or returns None. How numbers are written is the site's choice: `number(value)` returns the
    text to show for a number of the file (int or float), or None for the default; `digits` (when there is no
    `number`) shows non-integer numbers to that many significant digits. The file keeps every digit, and a table cell
    shown otherwise than as written carries the exact value as its title. `sections` lists the sections shown, as
    (id, title, count), for a site that builds its own navigation instead of using `nav`. How people are shown is the
    site's choice too: `person(contributor, where)` returns the HTML for a person or agent in the header (`where`:
    `guarantor`, `author`, `converter`, `source_author`), escaping what it takes from the file, or None for the
    default (a name, a person's ORCID link, an agent's label and "(AI agent)"). `byline(role, people)` returns the
    HTML inside one line of people in the header, its label included (`role`: `guarantor`, `authors`,
    `source_authors`; `people`: their contributor objects), or None for the default ("Guarantor: …", "Authors: …",
    "Authors of the source paper: …"). `marker(claim, where)` gives what
    marks a claim (`where`: `claim`, before its meta line, or `brief`, before its statement under Highlights): HTML, or a pair
    (before, after the meta line), or None for its support light. `claim_url(id)` gives the address of a claim's own
    page, which its ID then links to, or None. `blocks` holds each section's HTML by its id, for a site that arranges
    the sections itself."""
    if callable(number):
        rounding = number
    elif isinstance(digits, int) and not isinstance(digits, bool) and digits > 0:
        rounding = ("digits", digits)
    else:
        rounding = None
    token = DIGITS.set(rounding)
    try:
        return _render_parts(doc, file_url, ref_text, person, marker, claim_url, byline)
    finally:
        DIGITS.reset(token)


def _render_parts(doc, file_url, ref_text, person=None, marker=None, claim_url=None, byline=None):
    P = _Paper(doc, file_url, ref_text)
    P.byline = byline if callable(byline) else None
    P.person = person if callable(person) else None
    P.marker = marker if callable(marker) else None
    P.claim_url = claim_url if callable(claim_url) else None
    source_link = ""
    cf = P.paper.get("converted_from")
    if isinstance(cf, dict) and isinstance(cf.get("source_id"), str):
        source_link = _doi(cf["source_id"])

    brief_ids, automatic = brief(P)
    def brief_item(oid):
        x = P.by_id[oid]
        if x in P.defs:                                     # a term the paper introduces (highlights, §3.1)
            return (f'<li class="cs-brief-term"><span class="kind-tag">Definition</span>'
                    f'<span><strong>{esc(x.get("term", ""))}</strong>: '
                    f'{P.text(x.get("definition", ""))} <a class="cs-id" href="#{esc(oid)}">{esc(oid)}</a></span></li>')
        return (f'<li>{P.mark(x, "brief")[0]}<span>{P.text(x.get("statement", ""))} '
                f'<a class="cs-id" href="#{esc(oid)}">{esc(oid)}</a></span></li>')
    brief_items = [brief_item(oid) for oid in brief_ids]
    principal = [c for c in P.claims if c.get("role") == "principal" and not P.is_assumption(c)]
    assumptions = [c for c in P.claims if P.is_assumption(c)]
    supporting = [c for c in P.claims if c.get("role") != "principal" and not P.is_assumption(c)]
    note = ""
    if automatic:
        note = (f'<p class="cs-note">Selected automatically; the authors chose no highlights. '
                f'<a href="#principal">All {len(principal)} principal claims</a></p>')

    context = []
    for c in P.claims:
        for rel in c.get("relations") or []:
            if isinstance(rel, dict) and rel.get("id_type") != "local" and rel.get("type") in (
                    "extends", "addresses", "contradicts", "replicates", "fails_to_replicate", "supersedes",
                    "refines", "qualifies", "supports", "explains", "disputes_evidence"):
                target = (P.ref(rel["reference"], rel.get("locator")) if rel.get("reference")
                          else _doi(rel.get("target")) if rel.get("id_type") == "doi" else esc(rel.get("target")))
                own = ' <span class="cs-tail">· own earlier work</span>' if rel.get("self") else ""
                context.append(f'<dt>{esc(str(rel["type"]).replace("_", " ").capitalize())} {target}{own}'
                               f' <span class="cs-tail">· from <a href="#{esc(c["id"])}">{esc(c["id"])}</a></span></dt>'
                               f'<dd>{P.text(rel.get("note", ""))}</dd>')

    def rested(c):
        r = P.users(c["id"])
        return f' <span class="cs-tail">Rested on by {r}.</span>' if r else ""

    assumption_items = [
        f'<div class="cs-item" id="{esc(c["id"])}"><p class="cs-claim-meta">{esc(c["id"])}'
        + (f' · {esc(c["assumption_category"])}' if c.get("assumption_category") else "")
        + f' · {esc(c.get("check", "unchecked"))}</p><p>{P.text(c.get("statement", ""))}{rested(c)}</p></div>'
        for c in assumptions]

    warrants = [f'<div class="cs-item" id="{esc(w["id"])}"><p class="cs-claim-meta">{esc(w["id"])} · argument'
                + (f' · {esc(w["reasoning"])}' if w.get("reasoning") else "")
                + (f' · premises {P.ids(w["premises"])}' if w.get("premises") else "")
                + f'</p><p>{P.text(w.get("text", ""))}</p></div>' for w in P.warrants]

    limitation_items = [
        f'<div class="cs-item" id="{esc(lim["id"])}"><p class="cs-claim-meta">{esc(lim["id"])}'
        + "".join(f" · {esc(str(lim[k]).replace('_', ' '))}" for k in ("category", "impact") if lim.get(k))
        + (f' · affects {P.ids(lim["affects"])}' if lim.get("affects") else "")
        + (f' · mitigation: {esc(lim["mitigation"])}' if lim.get("mitigation") else "")
        + f'</p><p>{P.text(lim.get("statement", ""))}</p></div>' for lim in P.limitations]

    question_items = [
        f'<div class="cs-item" id="{esc(q["id"])}"><p class="cs-claim-meta">{esc(q["id"])}'
        + (f' · from {P.ids(q["claims"])}' if q.get("claims") else "")
        + f'</p><p>{P.text(q.get("question", ""))}</p></div>' for q in P.questions]

    def reference(b):
        t = b.get("target")
        shown = _doi(t) if b.get("id_type") == "doi" else (_link(t) if b.get("id_type") == "url" else esc(t))
        if b["id"] in P.written:                              # written out by the site, then its identifier
            shown = f"{esc(P.written[b['id']])} {shown}"
        used = P.users(b["id"])
        return (f'<li id="{esc(b["id"])}"><span class="cs-id">{esc(P.labels.get(b["id"], b["id"]))}</span> {shown}'
                + (f' <span class="cs-tail">Used by: {used}</span>' if used else "") + "</li>")

    def artefact(a):
        desc = a.get("description") or a.get("uri") or ""
        src = P.image_src(a)
        uri = a.get("uri")                               # the description is read; the link is its file or site
        target = src or (uri if _href(uri) and desc != uri else None)
        name = (f'{P.text(desc)} <a class="cs-open" href="{esc(target)}">{esc(_link_name(target))}</a>' if target
                else _link(uri) if _href(uri) and desc == uri else P.text(desc))
        bits = [esc(x) for x in (a.get("kind"), a.get("function")) if x]
        if a.get("reference"):
            bits.append(P.ref(a["reference"]))
        return (f'<li id="{esc(a["id"])}"><span class="cs-id">{esc(a["id"])} · {" · ".join(bits)}</span> {name}</li>')

    summary = P.paper.get("summary") if isinstance(P.paper.get("summary"), str) and P.paper["summary"].strip() \
        else None                                       # the authors' summary, first (spec §3.1)
    sections = [
        ("summary", "Summary", [f'<p class="cs-summary">{P.text(summary)}</p>'] if summary else []),
        ("highlights", "Highlights", [f'<ul class="cs-brief">{"".join(brief_items)}</ul>{note}'] if brief_items else []),
        ("context", "Context", [f'<dl class="cs-context">{"".join(context)}</dl>'] if context else []),
        ("definitions", "Definitions", None),
        ("assumptions", "Assumptions", assumption_items),
        ("principal", "Principal claims", [_claim(P, c, True) for c in principal]),
        ("supporting", "Supporting claims", [_claim(P, c) for c in supporting]),
        ("evidence", "Evidence", [_evidence(P, e, source_link) for e in P.evidence] + warrants),
        ("limitations", "Limitations", limitation_items),
        ("questions", "Open questions", question_items),
        ("references", "References", [f'<ol class="cs-refs">{"".join(reference(b) for b in P.refs)}</ol>']
         if P.refs else []),
        ("artefacts", "Artefacts", [f'<ul class="cs-artefacts">{"".join(artefact(a) for a in P.artefacts)}</ul>']
         if P.artefacts else []),
    ]
    counts = {"definitions": len(P.defs), "assumptions": len(assumptions), "principal": len(principal),
              "supporting": len(supporting), "evidence": len(P.evidence) + len(P.warrants),
              "limitations": len(P.limitations), "questions": len(P.questions), "references": len(P.refs),
              "artefacts": len(P.artefacts)}
    body, nav, shown, blocks = [], [], [], {}
    for sid, title, items in sections:
        part = _definitions(P) if items is None else _section(sid, title, items)
        if part:
            body.append(part)
            blocks[sid] = part
            n = counts.get(sid)
            nav.append(f'<li><a href="#{sid}">{title}</a>' + (f' <span class="count">{n}</span>' if n else "") + "</li>")
            shown.append((sid, title, n or 0))
    return {"title": P.paper.get("title", ""), "origin": _origin(P), "brief": (brief_ids, automatic),
            "header": _header(P),
            "nav": '<nav class="cs-toc" aria-label="Sections of the claimset"><p class="cs-toc-title">On this page</p>'
                   f'<ol>{"".join(nav)}</ol></nav>',
            "body": "\n".join(body), "sections": shown, "blocks": blocks,
            "lights": {lt: sum(1 for c in P.claims if P.light(c) == lt) for lt in LIGHTS}}


def _cell(P, v):
    """A table cell: a number (with its exact value as the title when the view rounds it), or anything else."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        shown = P.value(v)
        exact = repr(v) if isinstance(v, float) else str(v)
        title = f' title="{esc(exact)}"' if DIGITS.get() and shown != exact else ""
        return f'<td class="num"{title}>{shown}</td>'
    return f'<td class="txt">{P.value(v)}</td>'


def stylesheet():
    """The stylesheet for the page view, for a site to serve (as claimset.css) or a page to inline."""
    from .page_css import CSS
    return CSS


def render_html(doc, file_url=None):
    """A whole page for previewing a claimset locally: the page view, with its stylesheet inline and no scripts."""
    parts = render_parts(doc, file_url)
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(parts['title'])}</title><style>{stylesheet()}</style></head>\n"
            f'<body><div class="cs-page"><div class="cs-header"><p class="cs-origin">{esc(parts["origin"])}</p>'
            f'{parts["header"]}</div><div class="cs-layout">{parts["nav"]}<article class="cs-body">'
            f'{parts["body"]}</article></div></div></body></html>\n')
