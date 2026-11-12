"""Text from a claimset shown outside the package's page view (cards, notices, score reasons, tooltips): term markup
removed and mathematics rendered, by the claimset package's own MathML (design §7.4). Everything is escaped.

    plain(text)       -> the text without term markup ([[D1:term]] -> term)
    html(text)        -> escaped HTML, mathematics as MathML in the line
    one_line(text)    -> one line of plain text, mathematics as its LaTeX without dollars (titles, descriptions)
    readable(text)    -> plain text with mathematics as the symbols a reader sees (tooltips, which hold no markup)
"""

import html as _html
import re

from . import page as pageview

TERM_MARKUP = re.compile(r"\[\[D\d+:([^\]]*)\]\]")
INLINE_MATH = re.compile(r"\$\$(.+?)\$\$|\$([^$\s][^$]*?)\$", re.S)
TAG = re.compile(r"<annotation[^>]*>.*?</annotation>|<[^>]+>", re.S)


def esc(x):
    return _html.escape("" if x is None else str(x), quote=True)


def plain(text):
    return TERM_MARKUP.sub(r"\1", text or "")


def html(text):
    out, last, text = [], 0, plain(text)
    for m in INLINE_MATH.finditer(text):
        out.append(esc(text[last:m.start()]))
        out.append(pageview.math(m.group(1) or m.group(2)))
        last = m.end()
    out.append(esc(text[last:]))
    return "".join(out)


def one_line(text):
    return re.sub(r"\s+", " ", INLINE_MATH.sub(lambda m: m.group(1) or m.group(2), plain(text))).strip()


def readable(text):
    def symbols(m):
        shown = _html.unescape(TAG.sub("", pageview.math(m.group(1) or m.group(2))))
        return re.sub(r"\s+", "", shown)
    return re.sub(r"\s+", " ", INLINE_MATH.sub(symbols, plain(text))).strip()
