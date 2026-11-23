"""A LaTeX draft of a published claimset, for its guarantor to finish as a paper for people (design §4.6).

    build(doc, base_url, references=None, figure_file=None) -> (file name, zip bytes)
    known_references(conn, doc, base_url) -> {reference ID: what the portal knows of it}

The draft sets out what the claimset holds as a paper, in a plain `article`, and adds nothing: what a paper needs and
the claimset does not hold (the motivation, a discussion, a conclusion, an affiliation) is a visible gap, `\\gap{…}`,
listed in GAPS.md with its line. Every line that comes from the claimset is listed in traceability.csv with the
object and field it comes from. It is made by this code alone, the same every time for the same file.

Nothing from the file becomes a TeX command: text is escaped, and a formula is set as mathematics only when every
command in it is one the portal's MathML reader knows and it holds nothing TeX reads otherwise (`%`, `#`, `$`, `^^`);
otherwise it is written as text. Standard library only.
"""

import csv
import io
import re
import urllib.parse
import zipfile
from pathlib import Path

from claimset.render import interval, number, statistic, statistic_note, uncertainty, value

from . import crossref, ids, mathml, site
from . import page as pageview
from . import paper as paperview

DRAFT_LABEL = "Draft for a preprint"
#: The largest figure put in a draft; a larger one is a gap.
MAX_FIGURE_BYTES = 20 * 1024 * 1024
FIGURE_TYPES = {".png", ".jpg", ".jpeg", ".pdf"}
#: Rows over which a table prints only the rows its claims cite (all are in its CSV file), and over which what it
#: prints breaks across pages.
LONG_TABLE = 40

#: A formula, a term mark or code (paper.SEGMENT), for splitting a text.
SEGMENT = re.compile(r"\$\$.+?\$\$|\$[^$\s][^$]*?\$|\\\(.+?\\\)|\[\[[^\]]+\]\]|`[^`]+`", re.S)
FENCED = re.compile(r"```[^\n]*\n(.*?)```", re.S)
URL = re.compile(r"https?://[^\s<>\"{}\\^`|]+[^\s<>\"{}\\^`|.,;:!?)\]]")
CLAIM_ID = re.compile(r"\b(C\d+)\b")

# ---------- characters ----------

#: Characters pdflatex sets as text without help: ASCII, Latin-1, Latin Extended-A and the usual punctuation.
TEXT_OK = set("–—‘’“”…•†‡‰€‹›„‚") | {chr(i) for i in range(0x20, 0x7F)} | {chr(i) for i in range(0xA0, 0x180)}
#: Symbols a text may hold, as TeX writes them in mathematics.
MATH_SYMBOLS = {}
for _table in (mathml.GREEK, mathml.OPERATORS, mathml.BIG):
    for _name, _char in _table.items():
        if _name.isalpha() and len(_char) == 1 and ord(_char) > 0x7F:
            MATH_SYMBOLS.setdefault(_char, "\\" + _name)
MATH_SYMBOLS.update({"−": "-", "·": "\\cdot", "∎": "\\blacksquare", "′": "\\prime", "″": "\\prime\\prime",
                     "²": "^{2}", "³": "^{3}", "¹": "^{1}", "½": "\\tfrac{1}{2}", "¼": "\\tfrac{1}{4}",
                     "×": "\\times", "±": "\\pm", "÷": "\\div", "¬": "\\neg", "°": "^{\\circ}"})
TEXT_SPECIAL = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "#": r"\#",
                "^": r"\textasciicircum{}", "_": r"\_", "%": r"\%", "~": r"\textasciitilde{}", "<": r"\textless{}",
                ">": r"\textgreater{}", "|": r"\textbar{}"}

# ---------- mathematics ----------

#: The commands a formula may use: those the MathML reader knows (mathml.py), and nothing else.
MATH_COMMANDS = (set(mathml.GREEK) | {n for n in mathml.OPERATORS if n.isalpha()} | mathml.LETTERLIKE
                 | set(mathml.BIG) | mathml.FUNCTIONS | set(mathml.ACCENTS) | set(mathml.UNDER)
                 | {n for n in mathml.SPACES if n.isalpha()}
                 | (mathml.IGNORED - {"label", "tag"}) | set(mathml.SIZED) | set(mathml.FONT_COMMANDS)
                 | mathml.TEXT_COMMANDS | {"frac", "dfrac", "tfrac", "cfrac", "binom", "dbinom", "tbinom", "sqrt",
                                           "overset", "stackrel", "underset", "left", "right", "middle", "begin",
                                           "end", "not", "pmod"})
#: Commands of one character other than a letter: spaces, escaped symbols and the line break of an environment.
MATH_SINGLE = {",", ":", ">", ";", " ", "!", "{", "}", "|", "%", "$", "_", "&", "#", "\\"}
#: Environments a formula may hold; `align` is set as `aligned` inside a formula.
MATH_ENVIRONMENTS = {"matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "cases",
                     "aligned", "array", "gathered", "split"}
#: Text inside a formula: its group is set as text, where a sub- or superscript is an error.
TEXT_GROUPS = {"text", "textrm", "textit", "textnormal", "mbox", "textbf"}
#: Named functions TeX does not define, defined in the preamble (those in mathml.LIMITS take limits).
STANDARD_FUNCTIONS = {"log", "ln", "lg", "exp", "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
                      "sinh", "cosh", "tanh", "max", "min", "sup", "inf", "lim", "liminf", "limsup", "arg", "det",
                      "dim", "ker", "deg", "gcd", "Pr", "mod"}
OPERATOR_NAMES = {"argmax": r"arg\,max", "argmin": r"arg\,min"}


def _tokens(tex):
    return mathml.TOKEN.findall(tex)


def _group_end(toks, i):
    """The index after the group that opens at toks[i] ("{"), or None."""
    if i >= len(toks) or toks[i] != "{":
        return None
    depth = 0
    for j in range(i, len(toks)):
        if toks[j] == "{":
            depth += 1
        elif toks[j] == "}":
            depth -= 1
            if depth == 0:
                return j + 1
    return None


def safe_math(tex):
    """The formula `tex` as it can be set in the draft, or None when it is to be written as text: an expression the
    MathML reader cannot read, a command it does not know, or a character TeX reads otherwise."""
    if not isinstance(tex, str) or not tex.strip() or "^^" in tex:
        return None
    tex = re.sub(r"\\(begin|end)\{align\*?\}", r"\\\1{aligned}", tex)
    if mathml.to_mathml(tex) is None:
        return None
    toks = _tokens(tex)
    env = "\\begin" in tex
    out = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("%", "#", "$"):
            return None
        if t == "&" and not env:
            return None
        if t.startswith("\\") and len(t) > 1:
            name = t[1:]
            if name[0].isalpha():
                if name not in MATH_COMMANDS:
                    return None
                if name in ("begin", "end"):
                    end = _group_end(toks, i + 1)
                    if end is None or "".join(toks[i + 2:end - 1]) not in MATH_ENVIRONMENTS:
                        return None
                if name in TEXT_GROUPS:
                    end = _group_end(toks, i + 1)
                    if end is None:
                        return None
                    inner = toks[i + 2:end - 1]
                    if any(x in ("_", "^", "&", "$", "~") or (x.startswith("\\") and x[1:2].isalpha()) for x in inner):
                        return None
            elif name not in MATH_SINGLE or (name == "\\" and not env):
                return None
        if len(t) == 1 and ord(t) > 0x7F:
            t = MATH_SYMBOLS.get(t, t) + (" " if MATH_SYMBOLS.get(t, "").rstrip("}")[-1:].isalpha() else "")
        out.append(t)
        i += 1
    return "".join(out).strip()


# ---------- the draft ----------

class _Draft:
    """The lines of paper.tex, with where each came from and the gaps among them."""

    def __init__(self):
        self.lines, self.trace, self.gaps, self._pending = [], [], [], []
        self.unknown = set()

    # ----- text -----
    def esc(self, s):
        """Plain text, escaped; a character pdflatex cannot set is declared in the preamble."""
        out = []
        for ch in str(s):
            if ch in TEXT_SPECIAL:
                out.append(TEXT_SPECIAL[ch])
            elif ch in "\n\r\t":
                out.append(" ")
            elif ord(ch) < 0x20:
                continue
            elif ch in TEXT_OK:
                out.append(ch)
            elif ch in MATH_SYMBOLS:
                out.append(f"\\ensuremath{{{MATH_SYMBOLS[ch]}}}")
            else:
                self.unknown.add(ch)
                out.append(ch)
        return "".join(out).replace("--", "-{}-").replace("--", "-{}-")     # no en or em dash from hyphens

    def url(self, u):
        u = str(u)
        if re.fullmatch(r"https?://[^\s{}\\]+", u):
            return "\\url{" + u.replace("%", r"\%").replace("#", r"\#") + "}"
        return self.esc(u)

    def plain(self, s, claims=()):
        """Text with no formulae: URLs as links, the IDs of the paper's claims as links to them."""
        out, last = [], 0
        for m in re.finditer(URL.pattern + r"|" + CLAIM_ID.pattern, s):
            out.append(self.esc(s[last:m.start()]))
            word = m.group(0)
            if word.startswith("http"):
                out.append(self.url(word))
            elif word in claims:
                out.append(f"\\hyperref[claim:{word}]{{{word}}}")
            else:
                out.append(self.esc(word))
            last = m.end()
        out.append(self.esc(s[last:]))
        return "".join(out)

    def math(self, tex, display=False):
        safe = safe_math(tex)
        if safe is None:
            return f"\\texttt{{{self.esc(tex)}}}"
        return f"\\[{safe}\\]" if display else f"${safe}$"

    def text(self, s, claims=()):
        """A text of the claimset (claimset §8): its formulae as mathematics, its term marks as their words, its code
        as typewriter text, paragraphs kept."""
        if not isinstance(s, str):
            return self.esc("" if s is None else s)
        blocks, last = [], 0
        for m in FENCED.finditer(s):
            blocks.append(self._inline(s[last:m.start()], claims))
            body = m.group(1).replace("\\end{verbatim}", "\\end {verbatim}")
            blocks.append("\n\\begin{verbatim}\n" + body.rstrip("\n") + "\n\\end{verbatim}\n")
            last = m.end()
        blocks.append(self._inline(s[last:], claims))
        return "".join(blocks).strip()

    def _inline(self, s, claims):
        out, last = [], 0
        for m in SEGMENT.finditer(s):
            out.append(self._paragraphs(s[last:m.start()], claims))
            seg = m.group(0)
            if seg.startswith("$$"):
                out.append(self.math(seg[2:-2], display=True))
            elif seg.startswith("\\("):
                out.append(self.math(seg[2:-2]))
            elif seg.startswith("$"):
                out.append(self.math(seg[1:-1]))
            elif seg.startswith("[["):
                out.append(self.esc(seg[2:-2].split(":", 1)[-1]))
            else:
                out.append(f"\\texttt{{{self.esc(seg[1:-1])}}}")
            last = m.end()
        out.append(self._paragraphs(s[last:], claims))
        return "".join(out)

    def _paragraphs(self, s, claims):
        parts = re.split(r"\n\s*\n", s)
        return "\n\n".join(self.plain(p, claims) for p in parts)

    # ----- lines -----
    def gap(self, what):
        """A visible gap for people to fill: what a paper needs that the claimset does not hold."""
        self._pending.append(what)
        return f"\\gap{{{self.esc(what)}}}"

    def add(self, tex="", obj=None, field=None):
        start = len(self.lines) + 1
        for line in str(tex).split("\n"):
            self.lines.append(line)
            n = len(self.lines)
            for _ in range(line.count("\\gap{")):
                if self._pending:
                    self.gaps.append((n, self._pending.pop(0)))
        if obj is not None:
            self.trace.append((start, len(self.lines), obj, field or ""))

    def blank(self):
        if self.lines and self.lines[-1] != "":
            self.lines.append("")


def _dicts(x):
    return [y for y in x if isinstance(y, dict)] if isinstance(x, list) else []


def _strs(x):
    return [y for y in x if isinstance(y, str)] if isinstance(x, list) else []


def _words(s):
    return str(s or "").replace("_", " ")


def _sentence(s):
    s = _words(s)
    return s[:1].upper() + s[1:]


def _day(ts):
    try:
        y, m, d = str(ts)[:10].split("-")
        return f"{int(d)} {paperview.MONTHS[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return str(ts or "")


def _list(items):
    items = [x for x in items if x]
    if len(items) < 3:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _label(s):
    return re.sub(r"[^A-Za-z0-9.:-]", "-", str(s))


def _bibkey(s):
    return re.sub(r"[^A-Za-z0-9.:_-]", "", str(s)) or "ref"


AUTONOMY = {"autonomous": "AI agents ran the work end to end.",
            "human_supervised": "People oversaw the agents' work and approved it.",
            "human_assisted": "People carried out substantial parts of the research.",
            "unknown": "How much of the work the agents did is not recorded."}
IMPACT = {"could_reverse": "could reverse the claims it affects", "could_bias_magnitude": "could bias their size",
          "reduces_precision": "reduces their precision", "reduces_transferability": "limits where they transfer"}
MITIGATION = {"none": "not mitigated", "partial": "partly mitigated", "addressed": "addressed"}
CREDIT = {"conceptualization": "Conceptualization", "data_curation": "Data curation",
          "formal_analysis": "Formal analysis", "funding_acquisition": "Funding acquisition",
          "investigation": "Investigation", "methodology": "Methodology",
          "project_administration": "Project administration", "resources": "Resources", "software": "Software",
          "supervision": "Supervision", "validation": "Validation", "visualization": "Visualization",
          "writing_original_draft": "Writing – original draft", "writing_review_editing": "Writing – review & editing"}
KINDS = (("concept", "Concepts"), ("method", "Methods"), ("model", "Models"), ("data", "Data"),
         ("setting", "Settings"), ("population", "Populations"), ("design", "Design"), ("variable", "Variables"),
         ("instrument", "Instruments"), ("material", "Materials"))
BYLINE = ("guarantor", "coauthor", "supervisor")


class _Paper:
    def __init__(self, doc, base_url, references, figure_file):
        self.doc, self.base = doc, base_url.rstrip("/")
        self.p = doc.get("paper") or {}
        self.D = _Draft()
        self.refs_known = references or {}
        self.figure_file = figure_file
        self.files = {}                                   # name in the zip -> bytes
        P = pageview._Paper(doc)
        self.P = P
        self.view = paperview._View(doc, "", P, None)
        self.claims = {c["id"]: c for c in P.claims}
        self.defs = {d["id"]: d for d in P.defs}
        self.evidence = {e["id"]: e for e in P.evidence}
        self.arts = {a["id"]: a for a in P.artefacts}
        self.refs = {b["id"]: b for b in P.refs}
        self.warrants = {w["id"]: w for w in P.warrants}
        self.key = ids.url_key(self.p.get("id", "entrylib:0000.000000"))
        self.n = self.p.get("version") or 1
        self.global_id = f"{self.p.get('id')}@v{self.n}"
        self.url = f"{self.base}/p/{self.key}/v{self.n}"
        self.self_key = f"entrylib{self.key}v{self.n}"
        self.tables_placed = set()
        self.cited = []                                   # bib keys cited, in order
        self.bib = {}                                     # reference ID -> bib key

    # ----- helpers -----
    def t(self, s):
        return self.D.text(s, self.claims)

    def term(self, x):
        """A definition ID as its term; anything else as text."""
        if isinstance(x, str) and x in self.defs:
            return self.D.esc(self.defs[x].get("term") or x)
        return self.t(x) if isinstance(x, str) else self.D.esc(number(x) if isinstance(x, (int, float))
                                                                 and not isinstance(x, bool) else x)

    def conditions(self, c):
        if not isinstance(c, dict) or not c:
            return ""
        return "; ".join(f"{self.term(k)}: {self.term(v)}" for k, v in c.items())

    def cite(self, ref_id, locator=None, text=False):
        key = self.bib.get(ref_id)
        if key is None:
            return self.D.esc(ref_id)
        if key not in self.cited:
            self.cited.append(key)
        loc = f"[{self.D.esc(locator)}]" if locator else ""
        return f"\\citet{loc}{{{key}}}" if text else f"\\citep{loc}{{{key}}}"

    def xref(self, cid):
        return f"\\hyperref[claim:{cid}]{{Claim~{cid}}}" if cid in self.claims else self.D.esc(cid)

    def claim_name(self, c):
        n = c.get("name")
        return " ".join(n.split()) if isinstance(n, str) and n.strip() else ""

    # ----- references -----
    def references(self):
        """references.bib: the claimset itself, then each reference as the portal knows it."""
        entries = [site.bibtex(self.doc, self.base)]
        for b in self.refs.values():
            key = _bibkey(b["id"])
            self.bib[b["id"]] = key
            entries.append(self.entry(key, b))
        return "\n".join(entries)

    def entry(self, key, b):
        target, kind = b.get("target"), b.get("id_type")
        known = self.refs_known.get(b["id"])
        fields = []
        if isinstance(known, dict) and known.get("title"):
            authors = " and ".join(
                site._bib_escape(f"{a.get('family', '')}, {a.get('initials', '')}".strip(", "))
                for a in known.get("authors") or [] if isinstance(a, dict))
            fields += [("author", authors), ("title", "{" + site._bib_escape(known["title"]) + "}"),
                       ("year", known.get("year"))]
            if known.get("container"):
                kind_ = "article"
                fields += [("journal", site._bib_escape(known["container"])), ("volume", known.get("volume")),
                           ("number", known.get("issue")), ("pages", str(known.get("page") or "").replace("-", "--"))]
            elif known.get("publisher"):
                kind_ = "book"
                fields.append(("publisher", site._bib_escape(known["publisher"])))
            else:
                kind_ = "misc"
            if known.get("url"):
                fields.append(("url", known["url"]))
            if known.get("note"):
                fields.append(("note", site._bib_escape(known["note"])))
        else:
            kind_ = "misc"
            fields.append(("key", key))
            if kind == "reference":
                fields.append(("note", site._bib_escape(target)))
            elif kind == "url":
                fields.append(("url", str(target)))
            elif kind == "arxiv":
                fields += [("title", f"arXiv:{site._bib_escape(target)}"), ("eprint", site._bib_escape(target)),
                           ("archiveprefix", "arXiv"), ("url", f"https://arxiv.org/abs/{target}")]
            elif kind == "claimset" and isinstance(target, str):
                m = pageview.GLOBAL_ID.fullmatch(target)
                fields.append(("title", site._bib_escape(target)))
                if m:
                    fields.append(("url", f"{self.base}/p/{m.group(1)}{m.group(2) or ''}"))
            elif kind != "doi":
                fields.append(("note", site._bib_escape(f"{kind}: {target}")))
        if kind == "doi" and target:
            fields.append(("doi", site._bib_escape(target)))
        if b.get("archive_uri"):
            fields.append(("note", "Archived at \\url{" + str(b["archive_uri"]).replace("%", r"\%") + "}"))
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v)
        return f"@{kind_}{{{key},\n{body}\n}}\n"

    def source(self, s):
        """A definition's `source`, or a cited support's target, as a citation."""
        if isinstance(s, str) and s in self.bib:
            return self.cite(s)
        if isinstance(s, dict):
            if s.get("reference") in self.bib:
                return self.cite(s["reference"], s.get("locator"))
            if s.get("target"):
                return self.D.esc(f"{s.get('id_type', '')}: {s['target']}".lstrip(": "))
        if isinstance(s, str):
            return self.D.esc(s)
        return ""

    # ----- the parts -----
    def preamble(self):
        D = self.D
        ops = []
        for f in sorted(mathml.FUNCTIONS - STANDARD_FUNCTIONS):
            star = "*" if f in mathml.LIMITS else ""
            ops.append(f"\\providecommand{{\\{f}}}{{\\operatorname{star}{{{OPERATOR_NAMES.get(f, f)}}}}}")
        unknown = [f"  \\DeclareUnicodeCharacter{{{ord(c):04X}}}{{\\unknownchar{{{ord(c):04X}}}}}"
                   for c in sorted(D.unknown)]
        return "\n".join([
            "\\documentclass[11pt]{article}",
            "\\usepackage{iftex}",
            "\\ifPDFTeX",
            "  \\usepackage[T1]{fontenc}",
            "  \\usepackage{lmodern}",
            "\\else",
            "  \\usepackage{fontspec}",
            "\\fi",
            "\\usepackage[margin=2.5cm]{geometry}",
            "\\usepackage{amsmath,amssymb,amsthm,mathtools,bm,mathrsfs}",
            "\\usepackage{graphicx,booktabs,longtable,array}",
            "\\usepackage{xcolor,enumitem}",
            "\\setlength{\\emergencystretch}{3em}",
            "\\usepackage[round,authoryear]{natbib}",
            "\\usepackage[hidelinks]{hyperref}",
            "\\newcommand{\\gap}[1]{{\\color{red}\\textbf{[To write: #1]}}}",
            "\\newcommand{\\unknownchar}[1]{\\text{[U+#1]}}",
            *ops,
            *(["\\ifPDFTeX", *unknown, "\\fi"] if unknown else []),
            "",
        ])

    def title(self):
        D, p = self.D, self.p
        thanks = (f"This paper is the human edition of the claimset \\href{{{self.url}}}{{{D.esc(self.global_id)}}} "
                  f"\\citep{{{self.self_key}}}, published on EntryLib, which records each of its claims with the "
                  "evidence, assumptions and limitations it rests on.")
        self.cited.append(self.self_key)
        D.add(f"\\title{{{D.text(p.get('title') or '')}\\thanks{{{thanks}}}}}", "paper", "title")
        people = [c for c in _dicts(self.doc.get("contributors")) if c.get("type") == "human"
                  and set(_strs(c.get("positions"))) & set(BYLINE)]
        blocks = []
        for c in people:
            lines = [D.esc(c.get("name") or "")]
            if "guarantor" in _strs(c.get("positions")):
                lines[0] += "\\thanks{Corresponding author: " + D.gap(f"an email address for {c.get('name')}") + "}"
            lines.append(D.esc(c["affiliation"]) if c.get("affiliation")
                         else D.gap(f"the affiliation of {c.get('name')}"))
            if c.get("orcid"):
                lines.append(f"ORCID \\href{{https://orcid.org/{D.esc(c['orcid'])}}}{{{D.esc(c['orcid'])}}}")
            blocks.append("\\\\\\relax\n".join(lines))
        D.add("\\author{" + "\n\\and\n".join(blocks) + "}", "contributors", "name, affiliation, orcid")
        D.add(f"\\date{{{DRAFT_LABEL}\\\\ made from {D.esc(self.global_id)} of {D.esc(_day(p.get('date')))}}}",
              "paper", "date")
        D.add("")

    def abstract(self):
        D, p = self.D, self.p
        D.add("\\begin{abstract}")
        if isinstance(p.get("summary"), str) and p["summary"].strip():
            D.add(self.t(p["summary"]), "paper", "summary")
        else:
            D.add(D.gap("an abstract: the claimset has no summary"))
        D.add("\\end{abstract}")
        kw = _strs((p.get("classification") or {}).get("keywords"))
        if kw:
            D.add("\\noindent\\textbf{Keywords:} " + "; ".join(D.esc(k) for k in kw), "paper",
                  "classification.keywords")
        D.blank()

    def introduction(self):
        D, p = self.D, self.p
        D.add("\\section{Introduction}\\label{sec:introduction}")
        D.add(D.gap("the motivation: why the question matters, and to whom"))
        D.blank()
        contributions = [c for c in _strs(p.get("contributions")) if c in self.claims]
        if contributions:
            D.add("The contributions of this paper are the following.")
            D.add("\\begin{enumerate}")
            for cid in contributions:
                c = self.claims[cid]
                name = self.claim_name(c)
                lead = f"\\textbf{{{D.esc(name)}.}} " if name else ""
                body = c.get("summary") if isinstance(c.get("summary"), str) and c["summary"].strip() \
                    else c.get("statement")
                D.add(f"\\item {lead}{self.t(body)} ({self.xref(cid)})", cid,
                      "name, summary" if c.get("summary") else "name, statement")
            D.add("\\end{enumerate}")
        terms = [d for d in _strs(p.get("highlights")) if d in self.defs]
        if terms:
            D.add("The paper introduces " + _list([f"\\emph{{{self.term(d)}}}" for d in terms]) + " (Section~"
                  "\\ref{sec:terms}).", "paper", "highlights")
        D.blank()
        D.add(f"The claims of this paper, with the evidence, assumptions and limitations each rests on, are recorded "
              f"in a claimset \\citep{{{self.self_key}}}; Section~\\ref{{sec:provenance}} says where.")
        D.blank()
        related = []
        for c in self.claims.values():
            for r in _dicts(c.get("relations")):
                if r.get("id_type") == "local":
                    continue
                target = (self.cite(r["reference"], r.get("locator"), text=True) if r.get("reference") in self.bib
                          else self.D.esc(f"{r.get('id_type', '')}: {r.get('target', '')}"))
                verb = paperview.RELATION.get(r.get("type"), _words(r.get("type")))
                note = f" {self.t(r['note'])}" if isinstance(r.get("note"), str) else ""
                related.append((c["id"], f"\\item {self.xref(c['id'])} {verb.lower()} {target}.{note}"))
        D.add("\\subsection{Earlier work}")
        D.add(D.gap("the earlier work this paper builds on, and what it leaves open"))
        if related:
            D.blank()
            D.add("The claims of this paper stand in these relations to earlier work.")
            D.add("\\begin{itemize}")
            for cid, line in related:
                D.add(line, cid, "relations")
            D.add("\\end{itemize}")
        D.blank()

    def terms(self):
        D = self.D
        if not self.defs:
            return
        D.add("\\section{Terms and methods}\\label{sec:terms}")
        groups = {}
        for d in self.defs.values():
            groups.setdefault(d.get("kind") or "other", []).append(d)
        order = [k for k, _ in KINDS if k in groups] + sorted(k for k in groups if k not in dict(KINDS))
        for kind in order:
            if len(groups) > 1:
                D.add(f"\\subsection{{{D.esc(dict(KINDS).get(kind, _sentence(kind)))}}}")
            D.add("\\begin{description}[style=unboxed]")
            for d in groups[kind]:
                sym = f" ({self.t(d['symbol'])})" if isinstance(d.get("symbol"), str) and d["symbol"].strip() else ""
                src = self.source(d.get("source")) if d.get("source") else ""
                D.add(f"\\item[{{{self.t(d.get('term') or d['id'])}}}]{sym} {self.t(d.get('definition'))}"
                      + (f" {src}." if src and not src.startswith("\\cite") else (f" {src}" if src else "")),
                      d["id"], "term, symbol, definition, source")
            D.add("\\end{description}")
        D.blank()

    def design(self):
        D = self.D
        shown = [e for e in self.evidence.values() if e.get("profile") != "formal"]
        if not shown:
            return
        D.add("\\section{Data and design}\\label{sec:design}")
        for e in shown:
            facts = []
            for key in ("design", "data_origin", "analytic_approach", "sampling"):
                if isinstance(e.get(key), str) and e[key] != "other":
                    facts.append(_sentence(e[key]) if not facts else _words(e[key]))
            if e.get("n") is not None:
                facts.append(f"$n = {number(e['n'])}$" if isinstance(e["n"], int) else D.esc(f"n {e['n']}"))
            if e.get("preregistered") is True:
                facts.append("preregistered")
            line = (f"\\paragraph{{Evidence {D.esc(e['id'])}.}}\\label{{ev:{_label(e['id'])}}} "
                    f"{self.t(e.get('description'))}")
            if facts:
                line += " " + D.esc("; ".join(f for f in facts if not f.startswith("$"))).rstrip()
                line += "".join(f"; {f}" for f in facts if f.startswith("$"))
                line += "."
            arts = [a for a in _strs(e.get("artefacts")) if a in self.arts]
            listed = [a for a in arts if self.arts[a].get("kind") not in ("figure", "lab_record")]
            if listed:
                line += (f" Its materials: {_list([self.art_link(a) for a in listed])}"
                         " (Section~\\ref{sec:provenance}).")
            D.add(line, e["id"], "description, design, n, artefacts")
        D.blank()

    def art_link(self, aid):
        return f"\\hyperref[art:{_label(aid)}]{{{self.D.esc(aid)}}}"

    def artefact_ref(self, aid):
        a = self.arts.get(aid) or {}
        kind = _words(a.get("kind") or "artefact")
        uri = a.get("uri")
        return f"{self.D.esc(aid)} ({self.D.esc(kind)}{', ' + self.D.url(uri) if isinstance(uri, str) else ''})"

    def results(self):
        D, v = self.D, self.view
        D.add("\\section{Results}\\label{sec:results}")
        if v.parts:
            for title, cids in v.parts:
                D.add(f"\\subsection{{{D.esc(title)}}}", "paper", "sections")
                for cid in cids:
                    self.claim(self.claims[cid])
        else:
            for cid in v.shown:
                self.claim(self.claims[cid])
        D.blank()

    def claim(self, c):
        D, cid = self.D, c["id"]
        name = self.claim_name(c)
        D.blank()
        D.add(f"\\paragraph{{Claim {D.esc(cid)}{': ' + D.esc(name) if name else ''}.}}\\label{{claim:{cid}}}",
              cid, "name")
        D.add(self.statement(c.get("statement")), cid, "statement")
        scope = c.get("scope") if isinstance(c.get("scope"), dict) else {}
        conds = _strs(scope.get("conditions"))
        if conds:
            D.add("It holds for " + "; ".join(self.t(x) for x in conds) + ".", cid, "scope")
        for sp in _dicts(c.get("support")):
            self.support(c, sp)
        assumed = [a for a in _strs(c.get("assumptions")) if a in self.claims]
        if assumed:
            D.add(f"It assumes {_list([self.xref(a) for a in assumed])} (Section~\\ref{{sec:assumptions}}).", cid,
                  "assumptions")
        lims = [x for x in _strs(c.get("limitations"))]
        if lims:
            D.add(f"Limitation{'s' if len(lims) > 1 else ''} {_list([D.esc(x) for x in lims])} "
                  f"{'apply' if len(lims) > 1 else 'applies'} (Section~\\ref{{sec:limitations}}).", cid, "limitations")
        local = []
        for r in _dicts(c.get("relations")):
            if r.get("id_type") == "local" and r.get("target") in self.claims:
                local.append(f"{paperview.RELATION.get(r.get('type'), _words(r.get('type')))} "
                             f"{self.xref(r['target'])}")
        if local:
            D.add("; ".join(local) + ".", cid, "relations")

    def statement(self, s):
        """A statement, its parts (a), (b), … as a list (claimset §8 rule 11)."""
        if not isinstance(s, str):
            return ""
        spans = [(m.start(), m.end()) for m in SEGMENT.finditer(s)]
        marks, want = [], "a"
        for m in paperview.PART.finditer(s):
            if m.group(1) == want and not any(a <= m.start() < b for a, b in spans):
                marks.append(m)
                want = chr(ord(want) + 1)
        if len(marks) < 2:
            return f"\\emph{{{self.t(s)}}}" if "$$" not in s and "```" not in s else self.t(s)
        items = []
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(s)
            part = s[m.end():end].strip().rstrip(";")
            items.append(f"\\item[({m.group(1)})] {self.t(part)}")
        lead = s[:marks[0].start()].strip()
        return (self.t(lead) + "\n" if lead else "") + "\\begin{itemize}\n" + "\n".join(items) + "\n\\end{itemize}"

    def support(self, c, sp):
        D, cid, kind = self.D, c["id"], sp.get("kind")
        e = self.evidence.get(sp.get("evidence")) if isinstance(sp.get("evidence"), str) else None
        if kind == "formal_proof" and e is not None:
            self.proof(cid, e)
        elif kind in ("empirical_quant", "empirical_qual", "empirical_obs", "simulation") and e is not None:
            self.evidence_of(cid, sp, e)
        elif kind == "argument":
            w = self.warrants.get(sp.get("warrant"))
            if w is not None:
                premises = [p for p in _strs(w.get("premises")) if p in self.claims]
                lead = f"The argument ({_words(w.get('reasoning'))}" + (
                    f", from {_list([self.xref(p) for p in premises])}" if premises else "") + "): "
                D.add(lead + self.t(w.get("text")), w["id"], "text, premises")
        elif kind == "cited":
            ref = sp.get("reference")
            where = self.cite(ref, sp.get("locator"), text=True) if ref in self.bib else self.source(sp)
            D.add(f"It is a result of {where}.", cid, "support")
        elif kind == "consensus":
            srcs = [self.source(s) for s in sp.get("sources") or []]
            D.add("It is established knowledge" + (f" {', '.join(s for s in srcs if s)}" if srcs else "") + ".",
                  cid, "support")
        elif kind == "expert_judgement":
            D.add("It is the judgement of " + D.esc(sp.get("holder") or "its authors") + ".", cid, "support")
        elif kind == "demonstration":
            arts = [a for a in _strs(sp.get("artefacts")) if a in self.arts]
            D.add("It is shown by construction in " + _list([self.artefact_ref(a) for a in arts]) + ".", cid,
                  "support")
        figs = [a for a in _strs(sp.get("artefacts")) if (self.arts.get(a) or {}).get("kind") == "figure"]
        cited = _strs(sp.get("results"))
        if e is not None and cited:
            # the figures of the evidence that show what the claim cites, as the paper view shows them
            named = set(cited) | {".".join(x.split(".")[:2]) for x in cited if x.count(".") == 2}
            figs += [a for a in _strs(e.get("artefacts")) if (self.arts.get(a) or {}).get("kind") == "figure"
                     and named & set(_strs(self.arts[a].get("shows")))]
        for a in list(dict.fromkeys(figs))[:paperview.SHOWN_FIGURES]:
            self.figure(cid, a)

    def proof(self, cid, e):
        D = self.D
        steps = _dicts(e.get("steps"))
        if not steps:
            where = e.get("proof_artefact")
            D.add("Its proof is " + (f"in {self.artefact_ref(where)}" if where in self.arts else "in the source")
                  + ".", e["id"], "proof_artefact")
            return
        lead = f" (in {D.esc(e['foundation'])})" if isinstance(e.get("foundation"), str) else ""
        D.add(f"\\begin{{proof}}[Proof{lead}]", e["id"], "foundation")
        D.add("\\leavevmode\n\\begin{enumerate}")
        for st in steps:
            s = st.get("statement", "")
            shown = (D.math(s.strip(), display=True) if pageview.bare_formula(s) else self.t(s))
            by = [b for b in _strs(st.get("by")) if b in self.claims or b in self.defs]
            tail = f" (by {_list([self.xref(b) if b in self.claims else D.esc(b) for b in by])})" if by else ""
            D.add(f"\\item {shown}{tail}", e["id"], f"steps.{st.get('id', '')}")
        D.add("\\end{enumerate}")
        D.add("\\end{proof}")

    def evidence_of(self, cid, sp, e):
        D, eid = self.D, e["id"]
        cited = _strs(sp.get("results"))
        parts = [f"Evidence \\hyperref[ev:{_label(eid)}]{{{D.esc(eid)}}}"]
        if e.get("estimate") is not None and not cited:
            est = (f"{D.esc(e.get('estimand') or 'the estimate')} is {D.esc(number(e['estimate']))}"
                   + "".join(f", {D.esc(x)}" for x in (uncertainty(e.get("uncertainty")),
                                                       interval(e.get("interval"))) if x))
            parts.append(est)
        wanted = {x.split(".")[1] for x in cited if x.startswith(eid + ".") and x.count(".") >= 1}
        for r in _dicts(e.get("results")):
            if r.get("id") in wanted:
                parts.append(self.result(r))
        line = parts[0] + (": " + "; ".join(parts[1:]) if len(parts) > 1 else "") + "."
        tables = [t for t in _dicts(e.get("tables")) if t.get("id") in wanted]
        if tables:
            line += " " + "; ".join(self.table_ref(eid, t) for t in tables) + "."
        D.add(line, eid, "estimate, results")
        for t in tables:
            self.table(e, t)

    def printed_rows(self, tid, t):
        """The rows of a table the paper prints: all, or of a long table those its claims cite."""
        rows = _dicts(t.get("rows"))
        if len(rows) > LONG_TABLE:
            rows = [r for r in rows if f"{tid}.{r.get('id')}" in self.P.cited_rows]
        return rows

    def table_ref(self, eid, t):
        tid = f"{eid}.{t.get('id')}"
        if self.printed_rows(tid, t):
            return f"Table~\\ref{{tab:{_label(tid)}}}"
        src = t.get("rows_file")
        where = (self.artefact_ref(src) if src in self.arts else f"\\texttt{{tables/{self.D.esc(tid)}.csv}}") \
            if src or _dicts(t.get("rows")) else "the claimset"
        return f"table {self.D.esc(tid)}, in {where}"

    def result(self, r):
        D = self.D
        var = r.get("variable")
        stat = statistic(r.get("statistic"))
        extra = "; ".join(x for x in (uncertainty(r.get("uncertainty")), r.get("unit") or "",
                                       interval(r.get("interval"))) if x)
        cond = self.conditions(r.get("conditions"))
        return (f"{self.term(var)}{' (' + D.esc(stat) + ')' if stat else ''} = "
                f"{'about ' if r.get('approximate') is True else ''}{D.esc(value(r.get('value')))}"
                f"{' ' + D.esc(extra) if extra else ''}{' (' + cond + ')' if cond else ''}")

    def column(self, c):
        if isinstance(c, dict):
            out = self.term(c.get("variable"))
            if c.get("conditions"):
                out += f" ({self.conditions(c['conditions'])})"
            note = statistic_note(c)
            return out + self.D.esc(note)
        return self.term(c)

    def table(self, e, t):
        """A result table where a claim first cites it, and its values in tables/<E>.<T>.csv, exact."""
        D, eid = self.D, e["id"]
        tid = f"{eid}.{t.get('id')}"
        if tid in self.tables_placed:
            return
        self.tables_placed.add(tid)
        rows = _dicts(t.get("rows"))
        cols = [self.column(c) for c in t.get("columns") or []]
        units = t.get("units") if isinstance(t.get("units"), list) else []
        cols = [f"{c} ({D.esc(u)})" if isinstance(u, str) and u and u != "1" else c
                for c, u in zip(cols, units + [None] * len(cols), strict=False)]
        labels = [self.term(x) for x in t.get("row_labels") or []]
        caption = f"{D.esc(tid)}: {self.t(t.get('description', ''))}"
        if t.get("conditions"):
            caption += f" ({self.conditions(t['conditions'])})"
        if not rows:
            src = t.get("rows_file")
            D.add(f"Table {D.esc(tid)} keeps its rows in "
                  f"{self.artefact_ref(src) if src in self.arts else 'a file'}.", tid, "rows_file")
            return
        spec = "l" * max(len(labels), 1) + "r" * len(cols)
        head = (labels or ["Row"]) + cols
        shown = self.printed_rows(tid, t)                  # a paper prints the rows its claims cite; the CSV, all
        body = []
        for r in shown:
            left = [self.term(x) for x in r.get("label") or []] or [D.esc(r.get("id", ""))]
            note = statistic_note(r)
            if note:
                left[-1] += D.esc(note)
            vals = [D.esc(value(v)) for v in r.get("values") or []]
            cells = ["{}" + x if x.startswith("[") else x for x in left + vals]   # not an option of the row end
            body.append(" & ".join(cells) + " \\\\")
        whole = f"tables/{tid}.csv"
        if len(shown) < len(rows):
            caption += (f". The {len(shown)} rows the claims cite, of {len(rows)}; all are in "
                        f"\\texttt{{{D.esc(whole)}}}")
        if not shown:
            D.add(f"Table {D.esc(tid)}, {self.t(t.get('description', ''))}, has {len(rows)} rows, too many to print: "
                  f"they are in \\texttt{{{D.esc(whole)}}}.", tid, "rows")
        elif len(shown) > LONG_TABLE:
            D.add(f"\\begin{{longtable}}{{{spec}}}")
            D.add(f"\\caption{{{caption}}}\\label{{tab:{_label(tid)}}}\\\\", tid, "description, conditions")
            D.add("\\toprule\n" + " & ".join(head) + " \\\\\n\\midrule\n\\endhead")
            D.add("\n".join(body), tid, "rows")
            D.add("\\bottomrule\n\\end{longtable}")
        else:
            D.add("\\begin{table}[htbp]\n\\centering\\small")
            D.add(f"\\caption{{{caption}}}\\label{{tab:{_label(tid)}}}", tid, "description, conditions")
            # shrunk to the width of the text when it is wider, never enlarged
            D.add("\\resizebox{\\ifdim\\width>\\linewidth\\linewidth\\else\\width\\fi}{!}{%")
            D.add(f"\\begin{{tabular}}{{{spec}}}\n\\toprule\n" + " & ".join(head) + " \\\\\n\\midrule")
            D.add("\n".join(body), tid, "rows")
            D.add("\\bottomrule\n\\end{tabular}}")
            D.add("\\end{table}")
        self.csv(e, t, tid)

    def csv(self, e, t, tid):
        """The table's values as the claimset records them, every digit kept."""
        def raw(x):
            if isinstance(x, str) and x in self.defs:
                return self.defs[x].get("term") or x
            if isinstance(x, bool):
                return "true" if x else "false"
            if isinstance(x, (int, float)):
                return repr(x) if isinstance(x, float) else str(x)
            return value(x)

        def col(c):
            if isinstance(c, dict):
                name = raw(c.get("variable"))
                if c.get("conditions"):
                    name += " (" + "; ".join(f"{raw(k)}: {raw(v)}" for k, v in c["conditions"].items()) + ")"
                return name + statistic_note(c)
            return raw(c)
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\n")
        w.writerow(["row"] + [raw(x) for x in t.get("row_labels") or []] + [col(c) for c in t.get("columns") or []])
        for r in _dicts(t.get("rows")):
            w.writerow([r.get("id", "")] + [raw(x) for x in r.get("label") or []]
                       + [raw(v) for v in r.get("values") or []])
        self.files[f"tables/{tid}.csv"] = out.getvalue().encode("utf-8")

    def figure(self, cid, aid):
        D = self.D
        if aid in self.tables_placed:
            return
        self.tables_placed.add(aid)
        a = self.arts[aid]
        caption = f"{D.esc(aid)}: {self.t(a.get('description') or '')}"
        path = self.figure_file(a) if self.figure_file else None
        if path is not None:
            name = f"figures/{_label(aid)}{path.suffix.lower()}"
            self.files[name] = path.read_bytes()
            D.add(f"\\begin{{figure}}[htbp]\n\\centering\n\\includegraphics[width=\\linewidth]{{{name}}}", aid,
                  "uri")
        else:
            uri = a.get("uri")
            D.add("\\begin{figure}[htbp]\n\\centering")
            D.add(D.gap(f"figure {aid}" + (f", at {uri}" if isinstance(uri, str) else "")), aid, "uri")
        D.add(f"\\caption{{{caption}}}\\label{{fig:{_label(aid)}}}\n\\end{{figure}}", aid, "description")

    def assumptions(self):
        D = self.D
        assumed = [self.claims[c] for c in self.view.assumed]
        D.add("\\section{Assumptions}\\label{sec:assumptions}")
        if not assumed:
            D.add("The claims of this paper rest on no assumption of their own.")
            D.blank()
            return
        D.add("\\begin{itemize}")
        for c in assumed:
            cat = f" ({D.esc(_words(c['assumption_category']))})" if isinstance(c.get("assumption_category"), str) \
                else ""
            D.add(f"\\item\\label{{claim:{c['id']}}}\\textbf{{{D.esc(c['id'])}}}{cat}. {self.t(c.get('statement'))}",
                  c["id"], "statement, assumption_category")
        D.add("\\end{itemize}")
        D.blank()

    def limitations(self):
        D = self.D
        lims = self.P.limitations
        D.add("\\section{Limitations}\\label{sec:limitations}")
        if not lims:
            D.add(D.gap("the limitations of the work: the claimset records none"))
            D.blank()
            return
        D.add("\\begin{itemize}")
        for x in lims:
            affects = _list([self.xref(a) for a in _strs(x.get("affects"))])
            how = "; ".join(s for s in (IMPACT.get(x.get("impact"), ""), MITIGATION.get(x.get("mitigation"), "")) if s)
            D.add(f"\\item \\textbf{{{D.esc(x['id'])}}} ({D.esc(_words(x.get('category')))}). "
                  f"{self.t(x.get('statement'))}" + (f" It affects {affects}" if affects else "")
                  + (f"; it {D.esc(how)}" if how else "") + ".", x["id"], "statement, affects, impact, mitigation")
        D.add("\\end{itemize}")
        D.blank()

    def discussion(self):
        D = self.D
        D.add("\\section{Discussion}\\label{sec:discussion}")
        D.add(D.gap("the discussion: what the results mean, how they compare with earlier work, and what they are "
                    "good for"))
        qs = self.P.questions
        if qs:
            D.blank()
            D.add("\\subsection{Open questions}")
            D.add("\\begin{itemize}")
            for q in qs:
                D.add(f"\\item {self.t(q.get('question'))}", q["id"], "question")
            D.add("\\end{itemize}")
        D.blank()
        D.add("\\section{Conclusion}\\label{sec:conclusion}")
        D.add(D.gap("the conclusion"))
        D.blank()

    def back_matter(self):
        D, p = self.D, self.p
        people = _dicts(self.doc.get("contributors"))
        humans = [c for c in people if c.get("type") == "human" and _strs(c.get("credit_roles"))]
        D.add("\\section*{Author contributions}")
        if humans:
            D.add("; ".join(f"{D.esc(c.get('name') or c.get('id'))}: "
                            + ", ".join(D.esc(CREDIT.get(r, _sentence(r))) for r in _strs(c.get("credit_roles")))
                            for c in humans) + ".", "contributors", "credit_roles")
        else:
            D.add(D.gap("what each author did (CRediT roles)"))
        D.blank()
        self.ai_statement(people)
        decl = p.get("declarations") if isinstance(p.get("declarations"), dict) else {}
        D.add("\\section*{Funding}")
        funding = decl.get("funding")
        if isinstance(funding, list):
            items = []
            for f in _dicts(funding):
                bits = [D.esc(f.get("funder") or "")]
                if f.get("award"):
                    bits.append(f"award {D.esc(f['award'])}")
                if f.get("kind") == "in_kind":
                    bits.append("in kind")
                s = ", ".join(b for b in bits if b)
                if f.get("role"):
                    s += f"; the funder had {D.esc(f['role'])}" if not str(f["role"]).lower().startswith("the ") \
                        else f"; {D.esc(f['role'])}"
                items.append(s)
            D.add(("This work was funded by " + "; ".join(items) + ".") if items else "No funding was declared.",
                  "paper", "declarations.funding")
        else:
            D.add(D.gap("the funding of the work, or that there was none"))
        D.blank()
        D.add("\\section*{Competing interests}")
        if isinstance(decl.get("competing_interests"), str):
            D.add(self.t(decl["competing_interests"]), "paper", "declarations.competing_interests")
        else:
            D.add(D.gap("competing interests, or that there are none"))
        D.blank()
        ethics = decl.get("ethics")
        if isinstance(ethics, list):
            D.add("\\section*{Ethics}")
            items = [f"{D.esc(x.get('body') or '')}" + (f", reference {D.esc(x['reference'])}" if x.get("reference")
                                                         else "") + f": {D.esc(_words(x.get('decision')))}"
                     for x in _dicts(ethics)]
            D.add("; ".join(items) + "." if items else "The work needed no ethics review.", "paper",
                  "declarations.ethics")
            D.blank()
        if isinstance(decl.get("consent"), str):
            D.add("\\section*{Consent}")
            D.add(self.t(decl["consent"]), "paper", "declarations.consent")
            D.blank()
        self.provenance()
        D.add("\\section*{Acknowledgements}")
        D.add(D.gap("acknowledgements"))
        D.blank()

    def ai_statement(self, people):
        D = self.D
        models = {m["id"]: m for m in _dicts(self.doc.get("models")) if isinstance(m.get("id"), str)}
        agents = [c for c in people if c.get("type") == "agent"]
        D.add("\\section*{Use of AI}")
        lines = []
        for c in agents:
            used = [models[m.get("model")] for m in _dicts(c.get("models")) if m.get("model") in models]
            names = [" ".join(str(x) for x in (m.get("provider"), m.get("name"), m.get("version")) if x)
                     for m in used]
            system = c.get("system") if isinstance(c.get("system"), dict) else {}
            where = system.get("name") or c.get("name")
            tasks = [f"{_words(t.get('task'))} ({t.get('extent')})" if t.get("extent") else _words(t.get("task"))
                     for t in _dicts(c.get("ai_tasks"))]
            s = (_list(names) or "An AI model") + (f", run in {where}" if where else "")
            if tasks:
                s += ", did " + ", ".join(tasks)
            lines.append(D.esc(s))
        if lines:
            D.add("The claimset this paper is made from was written with AI. " + "; ".join(lines) + ". "
                  + D.esc(AUTONOMY.get(self.p.get("autonomy"), "")), "contributors", "models, ai_tasks, system")
        D.add("This draft was then made from the claimset by EntryLib's converter, a program that sets out what the "
              "claimset holds and adds nothing to it; the passages marked as gaps were left for the authors.")
        D.blank()

    def provenance(self):
        D = self.D
        D.add("\\section*{Data, materials and provenance}\\label{sec:provenance}")
        D.add(f"This paper is the human edition of the claimset {D.esc(self.global_id)} \\citep{{{self.self_key}}}: "
              f"the paper at \\url{{{self.url}}}, its record of claims, evidence and limitations at "
              f"\\url{{{self.base}/p/{self.key}/record}}, and its text for AI at "
              f"\\url{{{self.base}/p/{self.key}.txt}}.",
              "paper", "id, version")
        lab = pageview.lab_record_uri(self.doc)
        if lab:
            D.add(f"The research was recorded as it was done, in a lab record: {D.url(lab)}.", "artefacts",
                  "lab_record")
        arts = [a for a in self.P.artefacts if a.get("kind") not in ("figure", "lab_record")]
        if arts:
            D.add("\\begin{itemize}")
            for a in arts:
                desc = f" {self.t(a['description'])}" if isinstance(a.get("description"), str) else ""
                lic = f" Licence: {D.esc(a['licence'])}." if a.get("licence") else ""
                D.add(f"\\item\\label{{art:{_label(a['id'])}}} {self.artefact_ref(a['id'])}.{desc}{lic}", a["id"],
                      "kind, uri, description, licence")
            D.add("\\end{itemize}")
        D.blank()

    def tex(self):
        D = self.D
        bib = self.references()
        self.title()
        D.add("\\begin{document}")
        D.add("\\maketitle")
        self.abstract()
        self.introduction()
        self.terms()
        self.design()
        self.results()
        self.assumptions()
        self.limitations()
        self.discussion()
        self.back_matter()
        D.add("\\bibliographystyle{plainnat}")
        D.add("\\bibliography{references}")
        D.add("\\end{document}")
        head = self.preamble().split("\n")
        # the title, author and date come before \begin{document}: the preamble is put before them
        shift = len(head)
        lines = head + D.lines
        trace = [(a + shift, b + shift, o, f) for a, b, o, f in D.trace]
        gaps = [(n + shift, w) for n, w in D.gaps]
        return "\n".join(lines) + "\n", bib, trace, gaps


def readme(global_id, url, files):
    return f"""# {DRAFT_LABEL}: {global_id}

This is a draft of a paper for people, made by EntryLib from the claimset {global_id} ({url}).
It sets out what the claimset holds as a paper and adds nothing to it. What a paper needs and the claimset
does not hold is marked in the text with `\\gap{{…}}`, printed in red, and listed with its line in `GAPS.md`.
Write each, then delete its marker. Nothing else needs to change for the draft to compile.

## Compiling

    pdflatex paper
    bibtex paper
    pdflatex paper
    pdflatex paper

or `latexmk -pdf paper`. A character outside the Latin script is printed by pdflatex as [U+…];
compile with `lualatex` instead to print it.

## Files

{chr(10).join(f"- `{f}`" for f in files)}

- `paper.tex`: the paper, a plain `article`.
- `references.bib`: the claimset itself, then each work it cites, as EntryLib knows it.
  A reference given only by its identifier has only that: complete it from the publisher's record.
- `tables/`: each result table as the claimset records it, every digit kept (the paper rounds them).
- `traceability.csv`: which lines of `paper.tex` come from which object and field of the claimset.
- `GAPS.md`: what is left for you to write.

## Keep the link to the claimset

The paper names its claimset three times: a footnote on the title, its citation in the introduction
(the first entry of `references.bib`), and the statement on data, materials and provenance. Please keep
them: they let a reader find each claim with its evidence, and the citation is the part a journal's
template keeps. A double-blind journal will ask you to remove all three for review.
"""


def gaps_md(global_id, gaps):
    rows = "\n".join(f"| {n} | {w} |" for n, w in gaps)
    return (f"# What is left to write: {global_id}\n\n"
            "Each line of `paper.tex` below holds a `\\gap{…}`: write what it asks for, then delete the marker.\n\n"
            f"| Line | What |\n|---|---|\n{rows}\n")


def build(doc, base_url, references=None, figure_file=None):
    """(the zip's file name, its bytes): the draft of `doc`, a published claimset. `references`: {reference ID: what
    the portal knows of it}, as known_references gives; `figure_file(artefact)`: the stored file of a figure, a Path,
    or None."""
    from claimset.render import DIGITS
    token = DIGITS.set(site.number)
    try:
        paper = _Paper(doc, base_url, references, figure_file)
        tex, bib, trace, gaps = paper.tex()
    finally:
        DIGITS.reset(token)
    folder = f"entrylib-{paper.key}-v{paper.n}"
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["first_line", "last_line", "object", "field"])
    w.writerows(trace)
    files = {"paper.tex": tex.encode("utf-8"), "references.bib": bib.encode("utf-8"),
             "traceability.csv": out.getvalue().encode("utf-8"),
             "GAPS.md": gaps_md(paper.global_id, gaps).encode("utf-8"), **paper.files}
    names = sorted(files) + ["README.md"]
    files["README.md"] = readme(paper.global_id, paper.url, names).encode("utf-8")
    try:
        y, m, d = (int(x) for x in str(paper.p.get("date"))[:10].split("-"))
        stamp = (max(y, 1980), m, d, 0, 0, 0)
    except ValueError:
        stamp = (1980, 1, 1, 0, 0, 0)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in names:
            info = zipfile.ZipInfo(f"{folder}/{name}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, files[name])
    return f"{folder}-latex.zip", buf.getvalue()


def figure_files(published_dir, base_url):
    """figure_file for build(): the stored file of a figure of the claimset (its uri on this site, site.file_url_for)
    when TeX can include it (PNG, JPEG, PDF) and it is not too large; else None."""
    if not published_dir:
        return None
    root = Path(published_dir).resolve()
    find = site.file_url_for(root, base_url)

    def figure_file(a):
        path = find(a) if isinstance(a, dict) else None
        if not path:
            return None
        f = (root / urllib.parse.unquote(path).lstrip("/")).resolve()
        try:
            ok = root in f.parents and f.suffix.lower() in FIGURE_TYPES and f.stat().st_size <= MAX_FIGURE_BYTES
        except OSError:
            return None
        return f if ok else None
    return figure_file


def known_references(conn, doc, base_url):
    """{reference ID: {authors, year, title, container, volume, issue, page, publisher, url, note}} for the references
    of `doc` the portal knows: a DOI's metadata from Crossref as kept at publication (never asked for here), a
    claimset published here (its guarantor, year and title)."""
    refs = [b for b in doc.get("references") or [] if isinstance(b, dict) and isinstance(b.get("id"), str)]
    dois = {}
    for b in refs:
        if b.get("id_type") == "doi":
            d = crossref.normalise(b.get("target"))
            if d:
                dois[b["id"]] = d
    out = {}
    if dois:
        rows = dict(conn.execute("SELECT doi, summary FROM doi_metadata WHERE doi = ANY(%s) AND summary IS NOT NULL",
                                 (sorted(set(dois.values())),)).fetchall())
        for rid, d in dois.items():
            if isinstance(rows.get(d), dict):
                out[rid] = rows[d]
    for b in refs:
        if b.get("id_type") != "claimset" or not isinstance(b.get("target"), str):
            continue
        m = pageview.GLOBAL_ID.fullmatch(b["target"])
        if not m:
            continue
        concept, version = f"entrylib:{m.group(1)}", int(m.group(2)[2:]) if m.group(2) else None
        row = conn.execute(
            "SELECT file->'paper'->>'title', file->'paper'->>'date', file->'contributors', version FROM versions"
            " WHERE concept_id = %s AND (%s::int IS NULL OR version = %s) ORDER BY version DESC LIMIT 1",
            (concept, version, version)).fetchone()
        if not row or not row[0]:
            continue
        title, date, people, n = row
        names = [c.get("name") for c in people or [] if isinstance(c, dict) and c.get("type") == "human"
                 and "guarantor" in (c.get("positions") or []) and isinstance(c.get("name"), str)]
        authors = [{"family": f, "initials": site._initials(g)} for f, g in (site._split_name(x) for x in names)]
        out[b["id"]] = {"authors": authors, "year": str(date or "")[:4], "title": title,
                        "url": f"{base_url.rstrip('/')}/p/{m.group(1)}@v{n}",
                        "note": f"Claimset {concept}@v{n}, EntryLib"}
    return out

