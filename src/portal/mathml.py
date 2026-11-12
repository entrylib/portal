"""Inline LaTeX, as claimsets write it in text ($...$), as MathML, which browsers show without a script.

    to_mathml(tex, display=False) -> '<math>...</math>', or None if the expression cannot be read

The subset is what papers write in statements and definitions: letters, numbers and operators; sub- and
superscripts; \\frac, \\sqrt, \\binom; accents (\\hat, \\bar, \\tilde, \\dot, \\vec, \\overline, \\underline);
Greek letters; relations, arrows and big operators with limits; named functions (\\log, \\max, \\operatorname);
font commands (\\mathbf, \\mathbb, \\mathcal, \\mathrm, \\text, \\boldsymbol); \\left ... \\right; spaces; and the
matrix environments (matrix, pmatrix, bmatrix, vmatrix, cases, aligned, array). Every expression keeps its LaTeX in
an annotation, for copying and for models. Text is escaped: nothing from the expression becomes markup.

Standard library only (claimset uses no dependencies).
"""

import html
import re

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν",
    "xi": "ξ", "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ",
    "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ",
    "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
#: Operators, relations, arrows and other symbols: shown as <mo>.
OPERATORS = {
    "times": "×", "cdot": "⋅", "div": "÷", "pm": "±", "mp": "∓", "ast": "∗", "star": "⋆", "circ": "∘",
    "bullet": "∙", "oplus": "⊕", "otimes": "⊗", "odot": "⊙", "setminus": "∖", "wedge": "∧", "land": "∧",
    "vee": "∨", "lor": "∨", "cap": "∩", "cup": "∪",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "ll": "≪", "gg": "≫", "approx": "≈",
    "sim": "∼", "simeq": "≃", "cong": "≅", "equiv": "≡", "propto": "∝", "in": "∈", "notin": "∉", "ni": "∋",
    "subset": "⊂", "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇", "perp": "⊥", "parallel": "∥", "mid": "∣",
    "nmid": "∤", "models": "⊨", "vdash": "⊢", "coloneqq": "≔", "triangleq": "≜", "doteq": "≐", "prec": "≺",
    "succ": "≻", "preceq": "⪯", "succeq": "⪰",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "gets": "←", "leftrightarrow": "↔", "Rightarrow": "⇒",
    "Leftarrow": "⇐", "Leftrightarrow": "⇔", "implies": "⟹", "iff": "⟺", "mapsto": "↦", "uparrow": "↑",
    "downarrow": "↓", "longrightarrow": "⟶", "xrightarrow": "→",
    "forall": "∀", "exists": "∃", "nexists": "∄", "neg": "¬", "lnot": "¬", "partial": "∂", "nabla": "∇",
    "infty": "∞", "emptyset": "∅", "varnothing": "∅", "ldots": "…", "dots": "…", "cdots": "⋯", "vdots": "⋮",
    "ddots": "⋱", "prime": "′", "top": "⊤", "bot": "⊥", "angle": "∠", "triangle": "△", "Box": "□", "dagger": "†",
    "ell": "ℓ", "hbar": "ℏ", "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ", "wp": "℘",
    "lvert": "|", "rvert": "|", "vert": "|", "lVert": "‖", "rVert": "‖", "Vert": "‖", "|": "‖",
    "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "{": "{", "}": "}", "lbrace": "{", "rbrace": "}", "lbrack": "[", "rbrack": "]",
    "%": "%", "$": "$", "_": "_", "&": "&", "#": "#",
}
#: Identifiers that are symbols rather than letters: shown as <mi>.
LETTERLIKE = {"ell", "hbar", "Re", "Im", "aleph", "wp", "infty", "emptyset", "varnothing", "partial", "nabla", "top",
              "bot"}
#: Big operators: their sub- and superscripts are limits.
BIG = {"sum": "∑", "prod": "∏", "coprod": "∐", "bigcup": "⋃", "bigcap": "⋂", "bigoplus": "⨁", "bigotimes": "⨂",
       "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮"}
INTEGRALS = {"int", "iint", "iiint", "oint"}
#: Named functions, set upright; those in LIMITS take limits under them.
FUNCTIONS = {"log", "ln", "lg", "exp", "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
             "sinh", "cosh", "tanh", "max", "min", "sup", "inf", "lim", "liminf", "limsup", "arg", "argmax",
             "argmin", "det", "dim", "ker", "deg", "gcd", "Pr", "mod", "var", "Var", "cov", "Cov", "corr", "tr", "diag",
             "rank", "sgn", "sign", "E", "plim"}
LIMITS = {"max", "min", "sup", "inf", "lim", "liminf", "limsup", "argmax", "argmin", "plim"}
ACCENTS = {"hat": "^", "widehat": "^", "check": "ˇ", "bar": "¯", "overline": "‾", "tilde": "~", "widetilde": "~",
           "dot": "˙", "ddot": "¨", "vec": "→", "overrightarrow": "→", "acute": "´", "grave": "`", "breve": "˘"}
UNDER = {"underline": "_", "underbrace": "⏟"}
STRETCHY_ACCENTS = {"widehat", "widetilde", "overline", "overrightarrow", "underline", "underbrace"}
SPACES = {",": "0.1667em", ":": "0.2222em", ">": "0.2222em", ";": "0.2778em", " ": "0.25em", "quad": "1em",
          "qquad": "2em", "enspace": "0.5em", "thinspace": "0.1667em", "medspace": "0.2222em",
          "thickspace": "0.2778em", "!": "-0.1667em", "negthinspace": "-0.1667em"}
IGNORED = {"displaystyle", "textstyle", "scriptstyle", "limits", "nolimits", "big", "Big", "bigg", "Bigg", "bigl",
           "bigr", "Bigl", "Bigr", "biggl", "biggr", "Biggl", "Biggr", "nonumber", "notag", "label", "tag"}
FENCES = {"(": "(", ")": ")", "[": "[", "]": "]", "|": "|", ".": "", "\\{": "{", "\\}": "}", "\\lbrace": "{",
          "\\rbrace": "}", "\\langle": "⟨", "\\rangle": "⟩", "\\lvert": "|", "\\rvert": "|", "\\|": "‖",
          "\\lVert": "‖", "\\rVert": "‖", "\\vert": "|", "\\Vert": "‖", "\\lfloor": "⌊", "\\rfloor": "⌋",
          "\\lceil": "⌈", "\\rceil": "⌉", "\\lbrack": "[", "\\rbrack": "]"}
MATRICES = {"matrix": ("", ""), "pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "Bmatrix": ("{", "}"),
            "vmatrix": ("|", "|"), "Vmatrix": ("‖", "‖"), "smallmatrix": ("", ""), "cases": ("{", ""),
            "aligned": ("", ""), "align": ("", ""), "align*": ("", ""), "array": ("", ""), "gathered": ("", ""),
            "split": ("", "")}
TOKEN = re.compile(r"\\(?:[A-Za-z]+\*?|.)|\d+(?:\.\d+)?|[A-Za-z]|\s+|.", re.S)
MAX_LENGTH = 2000
MAX_DEPTH = 60


class TexError(ValueError):
    pass


def _alphabet(ch, style):
    """A letter or digit in a mathematical alphabet (bold, double-struck, script, fraktur, sans-serif, monospace):
    MathML Core shows styles only through these Unicode characters."""
    bases = {"bold": (0x1D400, 0x1D41A, 0x1D7CE), "bb": (0x1D538, 0x1D552, 0x1D7D8), "cal": (0x1D49C, 0x1D4B6, None),
             "frak": (0x1D504, 0x1D51E, None), "sf": (0x1D5A0, 0x1D5BA, 0x1D7E2), "tt": (0x1D670, 0x1D68A, 0x1D7F6),
             "bfit": (0x1D468, 0x1D482, 0x1D7CE)}
    holes = {"bb": {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"},
             "cal": {"B": "ℬ", "E": "ℰ", "F": "ℱ", "H": "ℋ", "I": "ℐ", "L": "ℒ", "M": "ℳ", "R": "ℛ", "e": "ℯ",
                     "g": "ℊ", "o": "ℴ"},
             "frak": {"C": "ℭ", "H": "ℌ", "I": "ℑ", "R": "ℜ", "Z": "ℨ"}}
    if style not in bases:
        return ch
    if ch in holes.get(style, {}):
        return holes[style][ch]
    upper, lower, digit = bases[style]
    if "A" <= ch <= "Z":
        return chr(upper + ord(ch) - ord("A"))
    if "a" <= ch <= "z":
        return chr(lower + ord(ch) - ord("a"))
    if "0" <= ch <= "9" and digit:
        return chr(digit + ord(ch) - ord("0"))
    if style in ("bold", "bfit") and "\u0391" <= ch <= "\u03a9":
        return chr((0x1D6A8 if style == "bold" else 0x1D71C) + ord(ch) - 0x391)
    if style in ("bold", "bfit") and "\u03b1" <= ch <= "\u03c9":
        return chr((0x1D6C2 if style == "bold" else 0x1D736) + ord(ch) - 0x3B1)
    return ch


FONT_COMMANDS = {"mathbf": "bold", "textbf": "bold", "bm": "bfit", "boldsymbol": "bfit", "mathbb": "bb",
                 "mathcal": "cal", "mathscr": "cal", "mathfrak": "frak", "mathsf": "sf", "mathtt": "tt"}
TEXT_COMMANDS = {"text", "textrm", "textit", "textnormal", "mbox", "mathrm", "operatorname", "mathit"}


def esc(s):
    return html.escape(s, quote=False)


def mi(s, normal=False):
    return f'<mi mathvariant="normal">{esc(s)}</mi>' if normal else f"<mi>{esc(s)}</mi>"


def mo(s, **attrs):
    a = "".join(f' {k.replace("_", "")}="{v}"' for k, v in attrs.items())
    return f"<mo{a}>{esc(s)}</mo>"


def row(items):
    items = [x for x in items if x]
    return items[0] if len(items) == 1 else f"<mrow>{''.join(items)}</mrow>"


class _Parser:
    def __init__(self, tex):
        self.toks = [t for t in TOKEN.findall(tex)]
        self.pos = 0
        self.depth = 0

    def peek(self, skip_space=True):
        while skip_space and self.pos < len(self.toks) and self.toks[self.pos].isspace():
            self.pos += 1
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def take(self, skip_space=True):
        t = self.peek(skip_space)
        if t is None:
            raise TexError("unexpected end")
        self.pos += 1
        return t

    def raw_group(self):
        """The text of a {group} as written (for \\text and environment names)."""
        if self.peek() != "{":
            return self.take()
        self.pos += 1
        depth, out = 1, []
        while True:
            t = self.take(skip_space=False)
            if t == "{":
                depth += 1
            elif t == "}":
                depth -= 1
                if depth == 0:
                    return "".join(out)
            out.append(t)

    def group(self):
        """One argument: a {group} or a single atom."""
        if self.peek() == "{":
            self.pos += 1
            inner = self.expression(stop={"}"})
            self.take()
            return row(inner)
        return self.atom()

    def optional(self):
        if self.peek() != "[":
            return None
        self.pos += 1
        inner = self.expression(stop={"]"})
        self.take()
        return row(inner)

    def expression(self, stop=frozenset()):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise TexError("too deeply nested")
        out = []
        while True:
            t = self.peek()
            if t is None or t in stop:
                break
            if t in ("^", "_"):
                base = out.pop() if out else "<mrow></mrow>"
                out.append(self.scripts(base))
                continue
            if t == "'":
                self.pos += 1
                primes = "′"
                while self.peek(False) == "'":
                    self.pos += 1
                    primes += "′"
                base = out.pop() if out else "<mrow></mrow>"
                out.append(f"<msup>{base}{mo(primes)}</msup>")
                continue
            atom = self.atom()
            if atom is not None:
                out.append(atom)
        self.depth -= 1
        return out

    def scripts(self, base, big=False):
        sub = sup = None
        while self.peek() in ("^", "_"):
            t = self.take()
            arg = self.group()
            if t == "_":
                sub = arg
            else:
                sup = arg
        if big:
            tag = "munderover" if sub and sup else "munder" if sub else "mover"
        else:
            tag = "msubsup" if sub and sup else "msub" if sub else "msup"
        parts = [base] + [x for x in (sub, sup) if x]
        return f"<{tag}>{''.join(parts)}</{tag}>"

    def atom(self):
        t = self.take()
        if t == "{":
            inner = self.expression(stop={"}"})
            self.take()
            return row(inner)
        if t == "}":
            raise TexError("unbalanced }")
        if t == "~":
            return '<mspace width="0.25em"></mspace>'
        if t[0] == "\\":
            return self.command(t[1:])
        if t[0].isdigit():
            return f"<mn>{esc(t)}</mn>"
        if t.isalpha():
            return mi(t)
        if t == "-":
            return mo("−")
        if t in "()[]":
            return mo(t, stretchy="false")
        if t == "|":
            return mo("|", stretchy="false")
        if t == "&":
            raise TexError("& outside an environment")
        return mo(t)

    def command(self, name):
        if name in IGNORED:
            if name in ("label", "tag"):
                self.raw_group()
            return None
        if name in SPACES:
            return f'<mspace width="{SPACES[name]}"></mspace>'
        if name in GREEK:
            ch = GREEK[name]
            return mi(ch, normal=ch.isupper())
        if name in BIG:
            op = mo(BIG[name], largeop="true", movablelimits="true") if name not in INTEGRALS \
                else mo(BIG[name], largeop="true")
            if self.peek() in ("^", "_"):
                return self.scripts(op, big=name not in INTEGRALS)
            return op
        if name in FUNCTIONS:
            fn = mi(name) if len(name) > 1 else mi(name, normal=True)
            if self.peek() in ("^", "_"):
                fn = self.scripts(fn, big=name in LIMITS)
            return row([fn, mo("\u2061")])
        if name in LETTERLIKE:
            return mi(OPERATORS[name], normal=True)
        if name in OPERATORS:
            ch = OPERATORS[name]
            if ch in "{}[]()|‖⟨⟩⌊⌋⌈⌉":
                return mo(ch, stretchy="false")
            return mo(ch)
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            return f"<mfrac>{self.group()}{self.group()}</mfrac>"
        if name in ("binom", "dbinom", "tbinom"):
            a, b = self.group(), self.group()
            return row([mo("("), f'<mfrac linethickness="0">{a}{b}</mfrac>', mo(")")])
        if name == "sqrt":
            index = self.optional()
            body = self.group()
            return f"<mroot>{body}{index}</mroot>" if index else f"<msqrt>{body}</msqrt>"
        if name in ACCENTS:
            body = self.group()
            stretchy = "true" if name in STRETCHY_ACCENTS else "false"
            return f'<mover accent="true">{body}{mo(ACCENTS[name], stretchy=stretchy)}</mover>'
        if name in UNDER:
            body = self.group()
            return f'<munder accentunder="true">{body}{mo(UNDER[name], stretchy="true")}</munder>'
        if name in ("overset", "stackrel"):
            over, body = self.group(), self.group()
            return f"<mover>{body}{over}</mover>"
        if name == "underset":
            under, body = self.group(), self.group()
            return f"<munder>{body}{under}</munder>"
        if name in FONT_COMMANDS:
            return self.styled(FONT_COMMANDS[name])
        if name in TEXT_COMMANDS:
            text = self.raw_group()
            if name in ("operatorname", "mathrm"):
                return row([mi(text, normal=True), mo("\u2061")]) if name == "operatorname" else mi(text, normal=True)
            if name == "mathit":
                return mi(text)
            return f"<mtext>{esc(text)}</mtext>"
        if name == "left":
            return self.fenced()
        if name in ("right", "middle"):
            raise TexError(f"\\{name} without \\left")
        if name == "begin":
            return self.environment(self.raw_group())
        if name == "\\":
            raise TexError("\\\\ outside an environment")
        if name in ("not",):
            nxt = self.atom()
            return row([nxt, mo("\u0338")])
        if name in ("pmod",):
            return row([mo("("), mi("mod"), self.group(), mo(")")])
        raise TexError(f"unknown command \\{name}")

    def styled(self, style):
        """A font command over a group: its letters and digits in that mathematical alphabet."""
        start = self.pos
        body = self.group()
        del start

        def restyle(m):
            tag, attrs, text = m.group(1), m.group(2), m.group(3)
            text = "".join(_alphabet(c, style) for c in html.unescape(text))
            attrs = attrs.replace(' mathvariant="normal"', "")
            return f"<{tag}{attrs}>{esc(text)}</{tag}>"
        return re.sub(r"<(mi|mn)([^>]*)>([^<]*)</\1>", restyle, body)

    def fence_token(self):
        t = self.take()
        if t in FENCES:
            return FENCES[t]
        raise TexError(f"not a delimiter: {t}")

    def fenced(self):
        left = self.fence_token()
        inner = []
        while True:
            inner += self.expression(stop={"\\right", "\\middle"})
            t = self.take()
            if t == "\\middle":
                inner.append(mo(self.fence_token(), stretchy="true"))
                continue
            break
        right = self.fence_token()
        items = ([mo(left, fence="true", stretchy="true")] if left else []) + [row(inner)] + \
                ([mo(right, fence="true", stretchy="true")] if right else [])
        return f"<mrow>{''.join(x for x in items if x)}</mrow>"

    def environment(self, name):
        if name not in MATRICES:
            raise TexError(f"unknown environment {name}")
        if name == "array" and self.peek() == "{":
            self.raw_group()                                 # column spec: alignment is not kept
        rows, cells, current = [], [], []
        while True:
            current += self.expression(stop={"&", "\\\\", "\\end"})
            t = self.take()
            if t == "&":
                cells.append(row(current))
                current = []
            elif t == "\\\\":
                cells.append(row(current))
                rows.append(cells)
                cells, current = [], []
            else:
                end = self.raw_group()
                if end != name:
                    raise TexError(f"\\begin{{{name}}} ended by \\end{{{end}}}")
                if current or cells:
                    cells.append(row(current))
                    rows.append(cells)
                break
        align = (' columnalign="left"' if name == "cases" else
                 ' columnalign="right left" columnspacing="0"' if name in ("aligned", "align", "align*", "split")
                 else "")
        table = "<mtable" + align + ">" + "".join(
            "<mtr>" + "".join(f"<mtd>{c or ''}</mtd>" for c in r) + "</mtr>" for r in rows) + "</mtable>"
        left, right = MATRICES[name]
        items = ([mo(left, fence="true", stretchy="true")] if left else []) + [table] + \
                ([mo(right, fence="true", stretchy="true")] if right else [])
        return f"<mrow>{''.join(items)}</mrow>"


def to_mathml(tex, display=False):
    """The expression as a <math> element, or None if it cannot be read (unknown command, unbalanced braces): the
    caller then shows it as written."""
    if not isinstance(tex, str) or not tex.strip() or len(tex) > MAX_LENGTH:
        return None
    p = _Parser(tex)
    try:
        body = p.expression()
        if p.peek() is not None:
            raise TexError(f"unexpected {p.peek()}")
    except (TexError, RecursionError, IndexError):
        return None
    block = ' display="block"' if display else ""
    return (f"<math{block}><semantics>{row(body) or '<mrow></mrow>'}"
            f'<annotation encoding="application/x-tex">{esc(tex)}</annotation></semantics></math>')
