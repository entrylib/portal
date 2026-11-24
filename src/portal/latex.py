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

from . import crossref, ids, mathml, site, source
from . import page as pageview
from . import paper as paperview

DRAFT_LABEL = "Draft for a preprint"
#: The largest figure put in a draft; a larger one is a gap.
MAX_FIGURE_BYTES = 20 * 1024 * 1024
FIGURE_TYPES = {".png", ".jpg", ".jpeg", ".pdf"}
#: Rows over which a table prints only the rows its claims cite (all are in its CSV file), and over which what it
#: prints breaks across pages.
LONG_TABLE = 40

#: A proof longer than this, in steps or in characters, goes to the appendix; a shorter one follows its theorem.
PROOF_STEPS = 6
PROOF_CHARS = 600
#: How the paper names a claim set out as a theorem, proposition or lemma.
ENV_NAME = {"theorem": "Theorem", "proposition": "Proposition", "lemma": "Lemma"}
#: The kinds of definition set out as a numbered `definition` when their text holds a formula.
FORMAL_KINDS = {"concept", "method", "model", "variable"}
#: The lab record's words for an evidence object's runs and plan, which the paper's design paragraph leaves out.
LAB_RUNS = re.compile(r"^Lab runs? [A-Z0-9, and]+ under plans? [A-Z0-9, and]+\.\s*")
#: A parenthesis that names a run or a file of the record, left out where checks of the same kind are said once.
PARENTHESIS = re.compile(r"\s*\((?=[^()]*(?:\brun\b|\bRN\d+|\.md\b|\.py\b))[^()]*\)")

#: A table description's reference to another table of the record ("Summary of T1: ").
SUMMARY_OF = re.compile(r"^Summary of T\d+:\s*")
#: A table description's naming of the hypothesis it decided ("; hypothesis: H18"), the record's.
HYPOTHESIS_IN = re.compile(r"[;,]?\s*\bhypothesis: H\d+\b")
#: Conditions of a table that belong to the record, left out of the paper's captions.
RECORD_CONDITIONS = {"hypothesis", "lab_plan", "lab_run", "plan", "run"}

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
        self.refer = None                                 # how a claim's ID in a text is written, or a link to it

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
                out.append(self.refer(word) if self.refer else f"\\hyperref[claim:{word}]{{{word}}}")
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
    def gap(self, what, material=()):
        """A visible gap for people to fill: what a paper needs that the claimset does not hold; `material`, what the
        claimset gives towards it, listed under it in GAPS.md."""
        self._pending.append((what, [m for m in material if m]))
        return f"\\gap{{{self.esc(what)}}}"

    def add(self, tex="", obj=None, field=None):
        start = len(self.lines) + 1
        for line in str(tex).split("\n"):
            self.lines.append(line)
            n = len(self.lines)
            for _ in range(line.count("\\gap{")):
                if self._pending:
                    self.gaps.append((n, *self._pending.pop(0)))
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


def _sentence_tex(s):
    return s[:1].upper() + s[1:]


def json_key(x):
    """A value as a key that compares equal for equal values of any kind."""
    return repr(x)


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
    """The draft: the paper (`paper.tex`), set out as a paper with gaps, and its supplement (`supplement.tex`), the
    claimset as a record (design §4.6)."""

    def __init__(self, doc, base_url, references, figure_file):
        self.doc, self.base = doc, base_url.rstrip("/")
        self.p = doc.get("paper") or {}
        self.D = _Draft()
        self.mode = "paper"
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
        # the paper's numbering, as LaTeX gives it: theorems, propositions and lemmas share one counter
        self.env = {cid: self.env_of(c) for cid, c in self.claims.items()
                    if not P.is_assumption(c) and self.is_formal(c)}
        self.number = {}                                  # claim, definition or assumption ID -> "Theorem 3"
        self.counters = {"theorem": 0, "definition": 0, "assumption": 0, "table": 0, "figure": 0}
        self.def_ref = {}                                 # definition ID -> how the paper names it
        self.table_number, self.figure_number = {}, {}    # table or figure -> its number in the paper
        self.figure_name = {}                             # figure artefact -> its file in the zip
        self.designs_placed = set()
        self.deferred = []                                # (claim, proof evidence): proofs in the appendix
        self.checks = self.verification()                 # evidence that only checks proved claims by computation
        self.part_of = {cid: i for i, (_t, cids) in enumerate(self.parts(), 1) for cid in cids}
        self.file_said = set()                            # tables held in a file, named once
        self.held = []                                    # those a claim names, said after it

    # ----- what a claim is -----
    def is_formal(self, c):
        """A formal claim (claimset §3.3.1) or a proved one: set out as a theorem."""
        if c.get("type") == "formal":
            return True
        return any(sp.get("kind") == "formal_proof" for sp in _dicts(c.get("support")))

    def env_of(self, c):
        return {"principal": "theorem", "secondary": "proposition"}.get(c.get("role"), "lemma")

    def proof_of(self, c):
        for sp in _dicts(c.get("support")):
            e = self.evidence.get(sp.get("evidence")) if isinstance(sp.get("evidence"), str) else None
            if sp.get("kind") == "formal_proof" and e is not None:
                return e
        return None

    def long_proof(self, e):
        steps = _dicts(e.get("steps"))
        size = sum(len(st.get("statement") or "") for st in steps if isinstance(st.get("statement"), str))
        return len(steps) > PROOF_STEPS or size > PROOF_CHARS

    def verification(self):
        """The evidence that only checks proved claims by computation: cited by formal claims, never as their
        proof, and by no other claim. The paper says once, in its appendix, what these checks were."""
        by_formal, by_other = set(), set()
        for c in self.claims.values():
            for sp in _dicts(c.get("support")):
                eid = sp.get("evidence")
                if not isinstance(eid, str) or eid not in self.evidence or sp.get("kind") == "formal_proof":
                    continue
                (by_formal if c["id"] in self.env else by_other).add(eid)
        return [e for e in self.evidence if e in by_formal - by_other]

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
        """A claim as the paper names it ("Theorem~3", "Assumption~1", "Section~8"), or as the supplement does
        ("Claim~C5")."""
        if cid not in self.claims:
            return self.D.esc(cid)
        if self.mode == "supplement":
            return f"\\hyperref[claim:{cid}]{{Claim~{cid}}}"
        if cid in self.env:
            return f"{ENV_NAME[self.env[cid]]}~\\ref{{thm:{cid}}}"
        if self.P.is_assumption(self.claims[cid]):
            return f"Assumption~\\ref{{asm:{cid}}}"
        if cid in self.part_of:
            return f"Section~\\ref{{sec:part-{self.part_of[cid]}}}"
        name = self.claim_name(self.claims[cid])
        return f"\\emph{{{self.D.esc(name)}}}" if name else self.D.esc(cid)

    def in_paper(self, cid):
        """How the supplement names a claim's place in the paper."""
        return self.number.get(cid, "")

    def claim_name(self, c):
        n = c.get("name")
        return " ".join(n.split()) if isinstance(n, str) and n.strip() else ""

    def title_arg(self, s):
        """An environment's optional title, in braces so that a bracket in it cannot end it."""
        return f"[{{{s}}}]" if s else ""

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
            "\\newtheorem{theorem}{Theorem}",
            "\\newtheorem{proposition}[theorem]{Proposition}",
            "\\newtheorem{lemma}[theorem]{Lemma}",
            "\\theoremstyle{definition}",
            "\\newtheorem{definition}{Definition}",
            "\\newtheorem{assumption}{Assumption}",
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
        people = self.byline()
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

    def byline(self):
        return [c for c in _dicts(self.doc.get("contributors")) if c.get("type") == "human"
                and set(_strs(c.get("positions"))) & set(BYLINE)]

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

    def parts(self):
        """[(title, claim IDs)]: the paper's sections, or one *Results*."""
        return self.view.parts or [("Results", list(self.view.shown))]

    def introduction(self):
        D, p = self.D, self.p
        D.add("\\section{Introduction}\\label{sec:introduction}")
        contributions = [self.claims[c] for c in _strs(p.get("contributions")) if c in self.claims]
        given = []
        for c in contributions:
            name = self.claim_name(c)
            summary = c.get("summary") if isinstance(c.get("summary"), str) and c["summary"].strip() else ""
            given.append(": ".join(x for x in (name, summary) if x) or str(c.get("statement") or ""))
        # what the paper finds is the results' to state; the introduction says why it matters, so the contributions
        # are what GAPS.md gives towards the motivation, not claims set out here
        D.add(D.gap("the motivation: why the question matters, to whom, and what this paper contributes",
                    [f"A contribution: {g}" for g in given]))
        D.blank()
        parts = self.parts()
        roadmap = [f"Section~\\ref{{sec:part-{i}}} ({D.esc(title)})" for i, (title, _) in enumerate(parts, 1)]
        tail = ("Section~\\ref{sec:discussion} discusses the results and Section~\\ref{sec:conclusion} concludes.")
        if self.has_long_proofs():
            tail += " The longer proofs are in Appendix~\\ref{app:proofs}."
        D.add("The paper is set out as follows: " + "; ".join(roadmap) + ". " + tail, "paper", "sections")
        D.blank()
        D.add(f"The claims of this paper, with the evidence, assumptions and limitations each rests on, are recorded "
              f"in a claimset \\citep{{{self.self_key}}}; Section~\\ref{{sec:provenance}} says where.")
        D.blank()
        self.earlier_work()

    def has_long_proofs(self):
        for cid in self.env:
            e = self.proof_of(self.claims[cid])
            if e is not None and _dicts(e.get("steps")) and self.long_proof(e):
                return True
        return False

    def earlier_work(self):
        """One paragraph per work the claims relate to: the claims, as the paper names them, then each note once."""
        D = self.D
        works, order = {}, []
        for cid in self.view.shown:
            for r in _dicts(self.claims[cid].get("relations")):
                if r.get("id_type") == "local":
                    continue
                key = r.get("reference") if r.get("reference") in self.bib else f"{r.get('id_type')}:{r.get('target')}"
                if key not in works:
                    works[key] = {"r": r, "by": {}, "notes": []}
                    order.append(key)
                verb = paperview.RELATION.get(r.get("type"), _words(r.get("type")))
                works[key]["by"].setdefault(verb, [])
                if cid not in works[key]["by"][verb]:
                    works[key]["by"][verb].append(cid)
                note = r.get("note") if isinstance(r.get("note"), str) and r["note"].strip() else None
                if note and note not in works[key]["notes"]:
                    works[key]["notes"].append(note)
        D.add("\\subsection{Earlier work}")
        material = []
        for key in order:
            w = works[key]
            r = w["r"]
            claims = "; ".join(f"{self.claim_name(self.claims[c]) or c} ({verb.lower()})"
                               for verb, cids in w["by"].items() for c in cids)
            material.append(f"{r.get('reference') or r.get('target')}: {claims}")
        D.add(D.gap("the earlier work this paper builds on, and what it leaves open", material))
        for key in order:
            w = works[key]
            if not w["notes"]:
                continue                                 # a work related without a note is listed in GAPS.md only
            r = w["r"]
            cite = (self.cite(r["reference"], r.get("locator")) if r.get("reference") in self.bib
                    else "(" + D.esc(f"{r.get('id_type', '')}: {r.get('target', '')}") + ")")
            text = " ".join(self.t(n).strip() for n in w["notes"])
            text = (text[:-1] if text.endswith(".") else text) + f" {cite}."
            D.blank()
            D.add(text, ",".join(c for cids in w["by"].values() for c in cids), "relations")
        D.blank()

    def body(self):
        for i, (title, cids) in enumerate(self.parts(), 1):
            D = self.D
            D.add(f"\\section{{{D.esc(title)}}}\\label{{sec:part-{i}}}", "paper", "sections")
            D.add(D.gap(f"a sentence leading into this section ({title})",
                        [self.claim_name(self.claims[c]) or c for c in cids]))
            D.blank()
            plain = [c for c in cids if c not in self.env]
            for cid in cids:
                self.paper_claim(self.claims[cid], runin=len(plain) > 1)

    def before(self, c):
        """What a claim needs set out just before it: its assumptions, the definitions it is the first to use, the
        design of the evidence it is the first to cite."""
        own = [a for a in _strs(c.get("assumptions")) if a in self.claims and a not in self.view.assumes(c)]
        for a in self.view.assumes(c) + own:
            if a not in self.number:
                self.assumption(self.claims[a])
        new = self.view.new_terms(c)
        e = self.proof_of(c)
        for st in _dicts((e or {}).get("steps")):
            for b in _strs(st.get("by")):
                if b in self.defs and b not in self.view.introduced and b not in new:
                    new.append(b)
                    self.view.introduced.append(b)
        for did in new:
            self.definition(self.defs[did])
        for sp in _dicts(c.get("support")):
            eid = sp.get("evidence")
            e = self.evidence.get(eid) if isinstance(eid, str) else None
            if e is None or sp.get("kind") == "formal_proof" or eid in self.checks or eid in self.designs_placed:
                continue
            self.designs_placed.add(eid)
            self.design_paragraph(e)

    def assumption(self, c):
        D = self.D
        self.counters["assumption"] += 1
        self.number[c["id"]] = f"Assumption {self.counters['assumption']}"
        D.add(f"\\begin{{assumption}}\\label{{asm:{c['id']}}}\n{self.t(c.get('statement'))}\n\\end{{assumption}}",
              c["id"], "statement")
        D.blank()

    def definition(self, d):
        D = self.D
        text = d.get("definition") if isinstance(d.get("definition"), str) else ""
        term = self.t(d.get("term") or d["id"])
        sym = f", {self.t(d['symbol'])}" if isinstance(d.get("symbol"), str) and d["symbol"].strip() else ""
        src = self.source(d.get("source")) if d.get("source") else ""
        tail = (f" {src}." if src and not src.startswith("\\cite") else (f" {src}" if src else ""))
        label = f"\\label{{def:{_label(d['id'])}}}"
        if d.get("kind") in FORMAL_KINDS and ("$" in text or "\\(" in text):
            self.counters["definition"] += 1
            self.number[d["id"]] = f"Definition {self.counters['definition']}"
            self.def_ref[d["id"]] = f"Definition~\\ref{{def:{_label(d['id'])}}}"
            D.add(f"\\begin{{definition}}{self.title_arg(term + sym)}{label}\n{self.t(text)}{tail}\n"
                  "\\end{definition}", d["id"], "term, symbol, definition, source")
        else:
            self.def_ref[d["id"]] = f"\\emph{{{term}}}"
            D.add(f"\\paragraph{{{_sentence_tex(term)}{sym}.}}{label} {self.t(text)}{tail}", d["id"],
                  "term, symbol, definition, source")
        D.blank()

    def design_paragraph(self, e):
        desc = e.get("description") if isinstance(e.get("description"), str) else ""
        desc = LAB_RUNS.sub("", desc, count=1)
        desc = re.sub(r"^Design:\s*", "", desc)
        if not desc.strip():
            return
        self.D.add(f"\\paragraph{{Design.}} {self.t(desc)}", e["id"], "description")
        self.D.blank()

    def paper_claim(self, c, runin):
        D, cid = self.D, c["id"]
        self.before(c)
        name = self.claim_name(c)
        if cid in self.env:
            env = self.env[cid]
            self.counters["theorem"] += 1
            self.number[cid] = f"{ENV_NAME[env]} {self.counters['theorem']}"
            D.add(f"\\begin{{{env}}}{self.title_arg(D.text(name))}\\label{{thm:{cid}}}", cid, "name")
            D.add(self.statement(c.get("statement"), emph=False), cid, "statement")
            D.add(f"\\end{{{env}}}")
            for sp in _dicts(c.get("support")):
                self.formal_support(c, sp)
            D.blank()
            return
        head = f"\\paragraph{{{D.esc(name)}.}}" if runin and name else ""
        text = self.statement(c.get("statement"), emph=False)
        D.add(f"{head}\\label{{claim:{cid}}} {text}".strip(), cid, "name, statement" if head else "statement")
        scope = c.get("scope") if isinstance(c.get("scope"), dict) else {}
        conds = _strs(scope.get("conditions"))
        if conds:
            D.add("It holds for " + "; ".join(self.t(x) for x in conds) + ".", cid, "scope")
        for sp in _dicts(c.get("support")):
            self.plain_support(c, sp)
        D.blank()

    def formal_support(self, c, sp):
        D, cid, kind = self.D, c["id"], sp.get("kind")
        e = self.evidence.get(sp.get("evidence")) if isinstance(sp.get("evidence"), str) else None
        if kind == "formal_proof" and e is not None:
            if not _dicts(e.get("steps")):
                where = e.get("proof_artefact")
                a = self.arts.get(where) or {}
                uri = a.get("uri")
                D.add("The proof is given in " + (D.url(uri) if isinstance(uri, str) else "the source") + ".",
                      e["id"], "proof_artefact")
            elif self.long_proof(e):
                D.add("The proof is in Appendix~\\ref{app:proofs}.", e["id"], "steps")
                self.deferred.append((cid, e))
            else:
                self.proof_block(cid, e)
        elif kind == "cited":
            ref = sp.get("reference")
            where = self.cite(ref, sp.get("locator"), text=True) if ref in self.bib else self.source(sp)
            if self.proof_of(c) is not None:
                D.add(f"See also {where}.", cid, "support")
            else:
                D.add(f"This is a result of {where}.", cid, "support")
        elif kind == "argument":
            self.argument(sp)
        # evidence that checks it by computation is in the appendix (verification)

    def argument(self, sp):
        w = self.warrants.get(sp.get("warrant"))
        if w is not None:
            self.D.add(self.t(w.get("text")), w["id"], "text")

    def proof_block(self, cid, e, appendix=False):
        D = self.D
        head = f"[Proof of {self.xref(cid)}]" if appendix else ""
        D.add(f"\\begin{{proof}}{head}", e["id"], "steps")
        for st in _dicts(e.get("steps")):
            s = st.get("statement", "")
            refs = _list([self.xref(b) if b in self.claims else self.def_ref.get(b, self.term(b))
                          for b in _strs(st.get("by")) if b in self.claims or b in self.defs])
            safe = safe_math(s.strip()) if isinstance(s, str) and pageview.bare_formula(s) else None
            if safe is not None:
                tag = f"\\tag*{{by {refs}}}" if refs else ""
                D.add(f"\\[{safe}{tag}\\]", e["id"], f"steps.{st.get('id', '')}")
            else:
                text = self.t(s).rstrip()
                if refs:
                    text = text.rstrip(".") + f" (by {refs})."
                D.add(text, e["id"], f"steps.{st.get('id', '')}")
        D.add("\\end{proof}")

    def plain_support(self, c, sp):
        D, cid, kind = self.D, c["id"], sp.get("kind")
        e = self.evidence.get(sp.get("evidence")) if isinstance(sp.get("evidence"), str) else None
        if kind in ("empirical_quant", "empirical_qual", "empirical_obs", "simulation") and e is not None:
            cited = _strs(sp.get("results"))
            wanted = {x.split(".")[1] for x in cited if x.startswith(e["id"] + ".") and x.count(".") >= 1}
            said = []
            if e.get("estimate") is not None and not cited:
                said.append(f"{D.esc(e.get('estimand') or 'the estimate')} is {D.esc(number(e['estimate']))}"
                            + "".join(f", {D.esc(x)}" for x in (uncertainty(e.get("uncertainty")),
                                                                interval(e.get("interval"))) if x))
            said += [self.result(r) for r in _dicts(e.get("results")) if r.get("id") in wanted]
            if said:
                D.add("The estimates: " + "; ".join(said) + ".", e["id"], "estimate, results")
            refs, self.held = [], []
            for t in _dicts(e.get("tables")):
                if t.get("id") in wanted:
                    ref = self.paper_table(e, t)
                    if ref:
                        refs.append(ref)
            for a in self.figures_of(sp, e):
                refs.append(self.figure(a))
            if refs:
                D.add("See " + _list(list(dict.fromkeys(refs))) + ".", cid, "support")
            if self.held:
                many = len(self.held) > 1
                D.add(f"The full table{'s are' if many else ' is'} at " + _list([D.url(u) for _t, u in self.held])
                      + ".", ",".join(t for t, _u in self.held), "rows_file")
        elif kind == "argument":
            self.argument(sp)
        elif kind == "cited":
            ref = sp.get("reference")
            where = self.cite(ref, sp.get("locator"), text=True) if ref in self.bib else self.source(sp)
            D.add(f"This is a result of {where}.", cid, "support")
        elif kind == "consensus":
            srcs = [self.source(s) for s in sp.get("sources") or []]
            D.add("It is established knowledge" + (f" {', '.join(s for s in srcs if s)}" if srcs else "") + ".",
                  cid, "support")
        elif kind == "expert_judgement":
            D.add("It is the judgement of " + D.esc(sp.get("holder") or "its authors") + ".", cid, "support")
        elif kind == "demonstration":
            arts = [a for a in _strs(sp.get("artefacts")) if a in self.arts]
            uris = [D.url(self.arts[a]["uri"]) for a in arts if isinstance(self.arts[a].get("uri"), str)]
            D.add("It is shown by construction" + (f" in {_list(uris)}" if uris else "") + ".", cid, "support")

    def figures_of(self, sp, e):
        """The figures a support names, and those of its evidence that show what it cites (as the paper view)."""
        figs = [a for a in _strs(sp.get("artefacts")) if (self.arts.get(a) or {}).get("kind") == "figure"]
        cited = _strs(sp.get("results"))
        if e is not None and cited:
            named = set(cited) | {".".join(x.split(".")[:2]) for x in cited if x.count(".") == 2}
            figs += [a for a in _strs(e.get("artefacts")) if (self.arts.get(a) or {}).get("kind") == "figure"
                     and named & set(_strs(self.arts[a].get("shows")))]
        return list(dict.fromkeys(figs))[:paperview.SHOWN_FIGURES]

    def paper_table(self, e, t):
        """A table where a claim first cites it ("Table~\\ref{…}"), or, held in a file, its address once."""
        tid = f"{e['id']}.{t.get('id')}"
        if _dicts(t.get("rows")):
            if tid not in self.tables_placed:
                self.table(e, t)
            return f"Table~\\ref{{tab:{_label(tid)}}}" if self.printed_rows(tid, t) else ""
        src = t.get("rows_file")
        a = self.arts.get(src) or {}
        if tid not in self.file_said and isinstance(a.get("uri"), str):
            self.file_said.add(tid)
            self.held.append((tid, a["uri"]))
        return ""

    def caption(self, s):
        """A table's description as a caption: without the record's words for its runs and other tables."""
        s = s if isinstance(s, str) else ""
        s = HYPOTHESIS_IN.sub("", SUMMARY_OF.sub("", PARENTHESIS.sub("", s)))
        return self.t(s[:1].upper() + s[1:])

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

    def statement(self, s, emph=True):
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
            plain = "$$" not in s and "```" not in s
            return f"\\emph{{{self.t(s)}}}" if emph and plain else self.t(s)
        items = []
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(s)
            part = s[m.end():end].strip().rstrip(";")
            items.append(f"\\item[({m.group(1)})] {self.t(part)}")
        lead = s[:marks[0].start()].strip()
        return (self.t(lead) + "\n" if lead else "") + "\\begin{itemize}\n" + "\n".join(items) + "\n\\end{itemize}"

    def printed_rows(self, tid, t):
        """The rows of a table the paper prints: all, or of a long table those its claims cite."""
        rows = _dicts(t.get("rows"))
        if len(rows) > LONG_TABLE:
            rows = [r for r in rows if f"{tid}.{r.get('id')}" in self.P.cited_rows]
        return rows

    def column(self, c):
        if isinstance(c, dict):
            out = self.term(c.get("variable"))
            if c.get("conditions"):
                out += f" ({self.conditions(c['conditions'])})"
            note = statistic_note(c)
            return out + self.D.esc(note)
        return self.term(c)

    def headers(self, columns):
        """The columns' headers, and what they all share (their variable, the conditions every one of them has), said
        once in the caption instead: a header names what sets its column apart, and a long one wraps."""
        dicts = [c for c in columns if isinstance(c, dict)]
        if len(dicts) < 2 or len(dicts) != len(columns):
            return [self.wrap(self.column(c)) for c in columns], ""
        variables = {json_key(c.get("variable")) for c in dicts}
        same_var = len(variables) == 1
        conds = [c.get("conditions") if isinstance(c.get("conditions"), dict) else {} for c in dicts]
        common = {k: v for k, v in conds[0].items() if all(json_key(x.get(k)) == json_key(v) and k in x for x in conds)}
        out = []
        for c, cd in zip(dicts, conds, strict=True):
            rest = {k: v for k, v in cd.items() if k not in common}
            head = "; ".join(f"{self.term(k)}: {self.term(v)}" for k, v in rest.items())
            if not same_var:
                head = self.term(c.get("variable")) + (f" ({head})" if head else "")
            out.append(self.wrap((head or self.term(c.get("variable"))) + self.D.esc(statistic_note(c))))
        shared = []
        if same_var:
            shared.append(self.term(dicts[0].get("variable")))
        if common:
            shared.append(self.conditions(common))
        return out, "; ".join(shared)

    def wrap(self, head):
        """A long header in a box of its own width, so that a table of many columns is not shrunk to nothing."""
        return f"\\parbox[b]{{2.6cm}}{{\\raggedright {head}}}" if len(head) > 22 else head

    def table(self, e, t):
        """A result table where a claim first cites it, its caption its description, and its values in
        tables/<E>.<T>.csv, exact."""
        D, eid = self.D, e["id"]
        tid = f"{eid}.{t.get('id')}"
        if tid in self.tables_placed:
            return
        self.tables_placed.add(tid)
        rows = _dicts(t.get("rows"))
        cols, shared = self.headers(t.get("columns") or [])
        units = t.get("units") if isinstance(t.get("units"), list) else []
        cols = [f"{c} ({D.esc(u)})" if isinstance(u, str) and u and u != "1" else c
                for c, u in zip(cols, units + [None] * len(cols), strict=False)]
        labels = [self.term(x) for x in t.get("row_labels") or []]
        caption = (self.caption(t.get("description", "")) if self.mode == "paper" else self.t(t.get("description", "")))
        caption = caption or D.esc(tid)
        conds = {k: v for k, v in (t.get("conditions") or {}).items() if k not in RECORD_CONDITIONS} \
            if isinstance(t.get("conditions"), dict) else {}
        if conds:
            caption += f" ({self.conditions(conds)})"
        if shared:
            caption = caption.rstrip(".") + f". Each column: {shared}"
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
            D.add(f"The full table, of {len(rows)} rows, is in \\texttt{{{D.esc(whole)}}}.", tid, "rows")
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

    def figure(self, aid):
        """A figure where a claim first shows it, as figures/figure-<n>; "Figure~\\ref{…}"."""
        D = self.D
        ref = f"Figure~\\ref{{fig:{_label(aid)}}}"
        if aid in self.figure_name:
            return ref
        a = self.arts[aid]
        self.counters["figure"] += 1
        n = self.counters["figure"]
        caption = self.t(a.get("description") or "")
        path = self.figure_file(a) if self.figure_file else None
        if path is not None:
            name = f"figures/figure-{n}{path.suffix.lower()}"
            self.files[name] = path.read_bytes()
            self.figure_name[aid] = name
            D.add(f"\\begin{{figure}}[htbp]\n\\centering\n\\includegraphics[width=\\linewidth]{{{name}}}", aid,
                  "uri")
        else:
            uri = a.get("uri")
            self.figure_name[aid] = ""
            D.add("\\begin{figure}[htbp]\n\\centering")
            D.add(D.gap("this figure" + (f", from {uri}" if isinstance(uri, str) else "")), aid, "uri")
        D.add(f"\\caption{{{caption}}}\\label{{fig:{_label(aid)}}}\n\\end{{figure}}", aid, "description")
        return ref

    def discussion(self):
        D = self.D
        principal = [c for c in self.view.shown if self.claims[c].get("role") == "principal"]
        D.add("\\section{Discussion}\\label{sec:discussion}")
        D.add(D.gap("the discussion: what the results mean, how they compare with earlier work, and what they are "
                    "good for", ["The principal results: " + "; ".join(
                        f"{self.number.get(c, c)}: {self.claim_name(self.claims[c]) or c}" for c in principal)]))
        D.blank()
        lims = [x for x in self.P.limitations if x.get("category") != "deviation"]
        D.add("\\subsection{Limitations}")
        if lims:
            D.add(" ".join(self.t(x.get("statement")).rstrip(".") + "." for x in lims),
                  ",".join(x["id"] for x in lims), "statement")
        else:
            D.add(D.gap("the limitations of the work: the claimset records none"))
        D.blank()
        qs = self.P.questions
        if qs:
            D.add("\\subsection{Open questions}")
            D.add("\\begin{itemize}")
            for q in qs:
                D.add(f"\\item {self.t(q.get('question'))}", q["id"], "question")
            D.add("\\end{itemize}")
            D.blank()
        D.add("\\section{Conclusion}\\label{sec:conclusion}")
        D.add(D.gap("the conclusion", [self.claim_name(self.claims[c]) or c for c in
                                       _strs(self.p.get("contributions")) if c in self.claims]))
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
            if len(self.byline()) == 1:
                D.add(D.gap("check the contributions listed: they are those the claimset records for its one author, "
                            "and the writing it credits to AI"))
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

    def materials(self):
        """The artefacts a reader may want, beyond the figures, the lab record and the files of tables."""
        files = {t.get(k) for e in self.evidence.values() for t in _dicts(e.get("tables"))
                 for k in ("rows_file", "artefact") if _dicts(t.get("rows")) or k == "rows_file"}
        return [a for a in self.P.artefacts if a.get("kind") not in ("figure", "lab_record") and a["id"] not in files]

    def provenance(self):
        D = self.D
        D.add("\\section*{Data, materials and provenance}\\label{sec:provenance}")
        D.add(f"This paper is the human edition of the claimset {D.esc(self.global_id)} \\citep{{{self.self_key}}}: "
              f"the paper at \\url{{{self.url}}}, its record of claims, evidence and limitations at "
              f"\\url{{{self.base}/p/{self.key}/record}}, and its text for AI at "
              f"\\url{{{self.base}/p/{self.key}.txt}}. The supplement sets out that record claim by claim.",
              "paper", "id, version")
        lab = pageview.lab_record_uri(self.doc)
        if lab:
            D.add(f"The research was recorded as it was done, in a lab record: {D.url(lab)}.", "artefacts",
                  "lab_record")
        arts = self.materials()
        if arts:
            D.add("\\begin{itemize}")
            for a in arts:
                desc = (self.t(PARENTHESIS.sub("", a["description"])) if isinstance(a.get("description"), str)
                        else D.esc(_words(a.get("kind"))))
                uri = f" {D.url(a['uri'])}" if isinstance(a.get("uri"), str) else ""
                lic = f" Licence: {D.esc(a['licence'])}." if a.get("licence") else ""
                D.add(f"\\item {desc.rstrip('.')}.{uri}{lic}", a["id"], "description, uri, licence")
            D.add("\\end{itemize}")
        D.blank()

    def appendix(self):
        D = self.D
        if not self.deferred and not self.checks:
            return
        D.add("\\appendix")
        if self.deferred:
            D.add("\\section{Proofs}\\label{app:proofs}")
            for cid, e in self.deferred:
                self.proof_block(cid, e, appendix=True)
                D.blank()
        if self.checks:
            D.add("\\section{Numerical checks}\\label{app:checks}")
            groups, order = {}, []
            for eid in self.checks:
                e = self.evidence[eid]
                desc = e.get("description") if isinstance(e.get("description"), str) else ""
                key = " ".join(PARENTHESIS.sub("", desc).split())
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(e)
            for key in order:
                es = groups[key]
                checked = [c for c in self.view.shown if c in self.env and any(
                    sp.get("evidence") in {e["id"] for e in es} for sp in _dicts(self.claims[c].get("support")))]
                text = self.t(key) if key else ""
                if checked:
                    text += f" These checks were made of {_list([self.xref(c) for c in checked])}."
                values = [r.get("value") for e in es for r in _dicts(e.get("results"))
                          if isinstance(r.get("value"), (int, float)) and not isinstance(r.get("value"), bool)]
                variables = {r.get("variable") for e in es for r in _dicts(e.get("results"))}
                if values and len(variables) == 1:
                    text += (f" Over these checks, {self.term(next(iter(variables)))} is at most "
                             f"{D.esc(f'{max(values):.2g}')}.")
                D.add(text.strip(), ",".join(e["id"] for e in es), "description, results")
                for e in es:
                    for t in _dicts(e.get("tables")):
                        if _dicts(t.get("rows")):
                            self.table(e, t)
                D.blank()

    def tex(self):
        D = self.D
        bib = self.references()
        self.D.refer = self.xref
        self.title()
        D.add("\\begin{document}")
        D.add("\\maketitle")
        self.abstract()
        self.introduction()
        self.body()
        self.discussion()
        self.back_matter()
        D.add("\\bibliographystyle{plainnat}")
        D.add("\\bibliography{references}")
        self.appendix()
        D.add("\\end{document}")
        text, trace, gaps = self.finish(D)
        return text, bib, trace, gaps

    def finish(self, D):
        head = self.preamble().split("\n")
        # the title, author and date come before \begin{document}: the preamble is put before them
        shift = len(head)
        lines = head + D.lines
        trace = [(a + shift, b + shift, o, f) for a, b, o, f in D.trace]
        gaps = [(n + shift, w, m) for n, w, m in D.gaps]
        return "\n".join(lines) + "\n", trace, gaps

    # ----- the supplement: the claimset as a record -----
    def supplement(self):
        self.mode = "supplement"
        D = self.D = _Draft()
        D.refer = self.xref
        D.add(f"\\title{{Supplement to: {D.text(self.p.get('title') or '')}}}", "paper", "title")
        D.add("\\author{" + "\n\\and\n".join(D.esc(c.get("name") or "") for c in self.byline()) + "}",
              "contributors", "name")
        D.add(f"\\date{{{DRAFT_LABEL}\\\\ made from {D.esc(self.global_id)} of {D.esc(_day(self.p.get('date')))}}}",
              "paper", "date")
        D.add("\\begin{document}")
        D.add("\\maketitle")
        D.add(f"This supplement sets out the claimset {D.esc(self.global_id)} \\citep{{{self.self_key}}} as a record, "
              f"for the reader who checks the paper: each claim by its ID, with its place in the paper, everything it "
              f"rests on and what limits it; then every evidence object, limitation and artefact. The claimset is at "
              f"\\url{{{self.url}}}.")
        D.blank()
        D.add("\\section{Claims}")
        for cid in self.view.shown:
            self.record_claim(self.claims[cid])
        D.blank()
        self.record_assumptions()
        self.record_definitions()
        self.record_evidence()
        self.record_limitations()
        self.record_artefacts()
        D.add("\\bibliographystyle{plainnat}")
        D.add("\\bibliography{references}")
        D.add("\\end{document}")
        tex, trace, _ = self.finish(D)
        return tex, trace

    def record_claim(self, c):
        D, cid = self.D, c["id"]
        name = self.claim_name(c)
        where = f" ({self.in_paper(cid)} in the paper)" if cid in self.env and self.in_paper(cid) else ""
        D.blank()
        D.add(f"\\paragraph{{Claim {D.esc(cid)}{where}{': ' + D.esc(name) if name else ''}.}}\\label{{claim:{cid}}}",
              cid, "name")
        D.add(self.statement(c.get("statement")), cid, "statement")
        scope = c.get("scope") if isinstance(c.get("scope"), dict) else {}
        conds = _strs(scope.get("conditions"))
        if conds:
            D.add("It holds for " + "; ".join(self.t(x) for x in conds) + ".", cid, "scope")
        for sp in _dicts(c.get("support")):
            self.record_support(c, sp)
        assumed = [a for a in _strs(c.get("assumptions")) if a in self.claims]
        if assumed:
            D.add(f"It assumes {_list([self.xref(a) for a in assumed])}.", cid, "assumptions")
        lims = _strs(c.get("limitations"))
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

    def record_support(self, c, sp):
        D, cid, kind = self.D, c["id"], sp.get("kind")
        e = self.evidence.get(sp.get("evidence")) if isinstance(sp.get("evidence"), str) else None
        if kind == "formal_proof" and e is not None:
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
        elif kind in ("empirical_quant", "empirical_qual", "empirical_obs", "simulation") and e is not None:
            cited = _strs(sp.get("results"))
            parts = [f"Evidence \\hyperref[ev:{_label(e['id'])}]{{{D.esc(e['id'])}}}"]
            if e.get("estimate") is not None and not cited:
                parts.append(f"{D.esc(e.get('estimand') or 'the estimate')} is {D.esc(number(e['estimate']))}")
            wanted = {x.split(".")[1] for x in cited if x.startswith(e["id"] + ".") and x.count(".") >= 1}
            parts += [self.result(r) for r in _dicts(e.get("results")) if r.get("id") in wanted]
            tables = [t for t in _dicts(e.get("tables")) if t.get("id") in wanted]
            line = parts[0] + (": " + "; ".join(parts[1:]) if len(parts) > 1 else "") + "."
            for t in tables:
                tid = f"{e['id']}.{t.get('id')}"
                rows = [x.split(".")[2] for x in cited if x.startswith(tid + ".") and x.count(".") == 2]
                where = (f"\\texttt{{tables/{D.esc(tid)}.csv}}" if _dicts(t.get("rows"))
                         else self.artefact_ref(t.get("rows_file")) if t.get("rows_file") in self.arts else "a file")
                line += f" Table {D.esc(tid)}" + (f", rows {D.esc(', '.join(rows))}" if rows else "") + f", in {where}."
            D.add(line, e["id"], "estimate, results")
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
        elif kind in ("consensus", "expert_judgement", "demonstration"):
            self.plain_support(c, sp)

    def artefact_ref(self, aid):
        a = self.arts.get(aid) or {}
        kind = _words(a.get("kind") or "artefact")
        uri = a.get("uri")
        return f"{self.D.esc(aid)} ({self.D.esc(kind)}{', ' + self.D.url(uri) if isinstance(uri, str) else ''})"

    def record_assumptions(self):
        D = self.D
        assumed = [self.claims[c] for c in self.view.assumed]
        if not assumed:
            return
        D.add("\\section{Assumptions}")
        D.add("\\begin{itemize}")
        for c in assumed:
            cat = f" ({D.esc(_words(c['assumption_category']))})" if isinstance(c.get("assumption_category"), str) \
                else ""
            where = f", {self.in_paper(c['id'])} in the paper" if self.in_paper(c["id"]) else ""
            D.add(f"\\item\\label{{claim:{c['id']}}}\\textbf{{{D.esc(c['id'])}}}{cat}{where}. "
                  f"{self.t(c.get('statement'))}", c["id"], "statement, assumption_category")
        D.add("\\end{itemize}")
        D.blank()

    def record_definitions(self):
        D = self.D
        if not self.defs:
            return
        D.add("\\section{Definitions}")
        D.add("\\begin{description}[style=unboxed]")
        for d in self.defs.values():
            sym = f" ({self.t(d['symbol'])})" if isinstance(d.get("symbol"), str) and d["symbol"].strip() else ""
            src = self.source(d.get("source")) if d.get("source") else ""
            where = f" {self.number[d['id']]} in the paper." if d["id"] in self.number else ""
            D.add(f"\\item[{{{D.esc(d['id'])}: {self.t(d.get('term') or d['id'])}}}]{sym} {self.t(d.get('definition'))}"
                  + (f" {src}" if src else "") + where, d["id"], "term, symbol, definition, source")
        D.add("\\end{description}")
        D.blank()

    def record_evidence(self):
        D = self.D
        if not self.evidence:
            return
        D.add("\\section{Evidence}")
        for e in self.evidence.values():
            facts = []
            for key in ("profile", "design", "data_origin", "analytic_approach", "sampling"):
                if isinstance(e.get(key), str) and e[key] != "other":
                    facts.append(_words(e[key]))
            if e.get("n") is not None:
                facts.append(f"n = {number(e['n'])}" if isinstance(e["n"], int) else f"n {e['n']}")
            line = (f"\\paragraph{{Evidence {D.esc(e['id'])}.}}\\label{{ev:{_label(e['id'])}}} "
                    f"{self.t(e.get('description'))}")
            if facts:
                line += " (" + D.esc("; ".join(facts)) + ")."
            arts = [a for a in _strs(e.get("artefacts")) if a in self.arts]
            if arts:
                line += f" Its artefacts: {_list([self.artefact_ref(a) for a in arts])}."
            D.add(line, e["id"], "description, design, n, artefacts")
        D.blank()

    def record_limitations(self):
        D = self.D
        D.add("\\section{Limitations}\\label{sec:limitations}")
        lims = self.P.limitations
        if not lims:
            D.add("The claimset records no limitation.")
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

    def record_artefacts(self):
        D = self.D
        arts = [a for a in self.P.artefacts]
        if not arts:
            return
        D.add("\\section{Artefacts}")
        D.add("\\begin{itemize}")
        for a in arts:
            desc = f" {self.t(a['description'])}" if isinstance(a.get("description"), str) else ""
            lic = f" Licence: {D.esc(a['licence'])}." if a.get("licence") else ""
            D.add(f"\\item\\label{{art:{_label(a['id'])}}} {self.artefact_ref(a['id'])}.{desc}{lic}", a["id"],
                  "kind, uri, description, licence")
        D.add("\\end{itemize}")
        D.blank()


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

and the same for `supplement`, or `latexmk -pdf paper supplement`. A character outside the Latin script is
printed by pdflatex as [U+…]; compile with `lualatex` instead to print it.

## Files

{chr(10).join(f"- `{f}`" for f in files)}

- `paper.tex`: the paper, a plain `article`: the claims as theorems and results in the paper's sections, the
  longer proofs and the numerical checks in its appendix. It names no ID of the claimset's record.
- `supplement.tex`: the claimset as a record, claim by claim, with each claim's place in the paper.
- `references.bib`: the claimset itself, then each work it cites, as EntryLib knows it.
  A reference given only by its identifier has only that: complete it from the publisher's record.
- `tables/`: each result table as the claimset records it, every digit kept (the paper rounds them).
- `figures/`: the figures, numbered in the order the paper shows them.
- `traceability.csv`: which lines of `paper.tex` and `supplement.tex` come from which object and field of the
  claimset.
- `GAPS.md`: what is left for you to write, each with what the claimset gives towards it.

## Keep the link to the claimset

The paper names its claimset three times: a footnote on the title, its citation in the introduction
(the first entry of `references.bib`), and the statement on data, materials and provenance. Please keep
them: they let a reader find each claim with its evidence, and the citation is the part a journal's
template keeps. A double-blind journal will ask you to remove all three for review.
"""


def gaps_md(global_id, gaps):
    rows = "\n".join(f"| {n} | {w} |" for n, w, _m in gaps)
    given = [f"### Line {n}: {w}\n\n" + "\n".join(f"- {x}" for x in m) + "\n" for n, w, m in gaps if m]
    return (f"# What is left to write: {global_id}\n\n"
            "Each line of `paper.tex` below holds a `\\gap{…}`: write what it asks for, then delete the marker.\n\n"
            f"| Line | What |\n|---|---|\n{rows}\n"
            + ("\n## What the claimset gives towards them\n\n" + "\n".join(given) if given else ""))


#: Why a published claimset has no LaTeX draft (design §4.6): {reason: (in a few words, in full)}.
NO_DRAFT = {
    "restates": ("it restates a published paper",
                 "This claimset restates a paper that is already published, which is its paper for people. The LaTeX "
                 "draft is for research that has no paper yet: made with claimset-lab or written directly as a "
                 "claimset."),
}
#: What Your submissions says once about the drafts, when a paper has none.
DRAFT_RULE = ("A LaTeX draft is offered for research that has no paper yet: made with claimset-lab or written "
              "directly as a claimset. A claimset that restates a paper already published has its paper, and gets "
              "none.")


def refusal(doc):
    """Why no LaTeX draft is made of `doc` (a key of NO_DRAFT), or None when one is: a draft is made of research that
    has no paper yet (made with claimset-lab, or written directly), never of a claimset that restates a published
    paper, converted by its authors (`published_as`, a `manuscript` with a DOI) or by others (`converted`)."""
    p = doc.get("paper") if isinstance(doc, dict) and isinstance(doc.get("paper"), dict) else {}
    if p.get("origin") == "converted" or isinstance(p.get("converted_from"), dict) \
            or isinstance(p.get("published_as"), dict) or source.doi(doc):
        return "restates"
    return None


def build(doc, base_url, references=None, figure_file=None):
    """(the zip's file name, its bytes): the draft of `doc`, a published claimset. `references`: {reference ID: what
    the portal knows of it}, as known_references gives; `figure_file(artefact)`: the stored file of a figure, a Path,
    or None."""
    from claimset.render import DIGITS
    token = DIGITS.set(site.number)
    try:
        paper = _Paper(doc, base_url, references, figure_file)
        tex, bib, trace, gaps = paper.tex()
        supplement, supplement_trace = paper.supplement()
    finally:
        DIGITS.reset(token)
    folder = f"entrylib-{paper.key}-v{paper.n}"
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["file", "first_line", "last_line", "object", "field"])
    w.writerows(("paper.tex", *row) for row in trace)
    w.writerows(("supplement.tex", *row) for row in supplement_trace)
    files = {"paper.tex": tex.encode("utf-8"), "supplement.tex": supplement.encode("utf-8"),
             "references.bib": bib.encode("utf-8"),
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

