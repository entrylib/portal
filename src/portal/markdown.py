"""A small Markdown to HTML converter for the specifications (portal issue #46).

Only for our own text, the specifications shipped with the claimset package; submitted content is never converted.
It still escapes everything and keeps only http(s), relative and fragment links. It knows what the specifications use:
headings, paragraphs, nested lists, tables, fenced code, block quotes, rules, inline code, bold, italic, links
and autolinks (<https://…>).
Numbered headings ("### 2.6 Specification versions") get their number as anchor (`#2.6`), and "§2.6" in the text links
to it.

    convert(text) -> (html, [(level, anchor, title)])     the headings, for a contents list
"""

import html
import re

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
SECTION_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)\.?\s")
SECTION_REF = re.compile(r"§\s?(\d+(?:\.\d+)*)")


def esc(s):
    return html.escape(s, quote=True)


def slug(text):
    m = SECTION_NUMBER.match(text)
    if m:
        return m.group(1)
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[\s_]+", "-", s) or "section"


def _href(url):
    url = url.strip()
    if url.startswith(("https://", "http://", "#", "/")) or not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
        return url
    return None


def inline(text, anchors=frozenset()):
    """One line or paragraph of inline Markdown as HTML."""
    out, pos = [], 0
    for m in re.finditer(r"(`+)(.+?)\1", text):                 # code spans first: nothing inside them is markup
        out.append(_inline_markup(text[pos:m.start()], anchors))
        out.append(f"<code>{esc(m.group(2).strip())}</code>")
        pos = m.end()
    out.append(_inline_markup(text[pos:], anchors))
    return "".join(out)


def _inline_markup(text, anchors):
    links = []

    def keep_link(m):
        href = _href(m.group(2))
        label = _inline_markup(m.group(1), anchors)
        links.append(f'<a href="{esc(href)}">{label}</a>' if href else label)
        return f"\x00{len(links) - 1}\x00"

    def keep_autolink(m):
        links.append(f'<a href="{esc(m.group(1))}">{esc(m.group(1))}</a>')
        return f"\x00{len(links) - 1}\x00"

    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", keep_link, text)
    text = re.sub(r"<(https?://[^\s<>]+)>", keep_autolink, text)     # an autolink, <https://…>
    s = esc(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w])_(?!\s)([^_]+?)(?<!\s)_(?![\w])", r"<em>\1</em>", s)
    if anchors:
        s = SECTION_REF.sub(lambda m: f'<a href="#{m.group(1)}">{m.group(0)}</a>' if m.group(1) in anchors
                            else m.group(0), s)
    return re.sub("\x00(\\d+)\x00", lambda m: links[int(m.group(1))], s)


def _cells(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    cells, cur, code = [], "", False
    i = 0
    while i < len(row):
        ch = row[i]
        if ch == "\\" and i + 1 < len(row) and row[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if ch == "`":
            code = not code
        if ch == "|" and not code:
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


def convert(text):
    lines = text.replace("\r\n", "\n").split("\n")
    headings, used = [], set()
    for line in lines:                                          # anchors first, so §refs can link forward
        m = HEADING.match(line)
        if m:
            anchor = slug(m.group(2))
            base, n = anchor, 2
            while anchor in used:
                anchor, n = f"{base}-{n}", n + 1
            used.add(anchor)
            headings.append((len(m.group(1)), anchor, m.group(2)))
    anchors = {a for _, a, _ in headings if re.fullmatch(r"\d+(\.\d+)*", a)}
    out, i, h = [], 0, 0
    para = []

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(x.strip() for x in para), anchors)}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if FENCE.match(line):
            flush()
            fence = FENCE.match(line).group(1)
            lang = line.strip()[3:].strip()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                body.append(lines[i])
                i += 1
            cls = f' class="language-{esc(lang)}"' if re.fullmatch(r"[\w-]+", lang or "-") and lang else ""
            out.append(f"<pre><code{cls}>{esc(chr(10).join(body))}</code></pre>")
            i += 1
            continue
        m = HEADING.match(line)
        if m:
            flush()
            level, anchor, title = headings[h]
            h += 1
            out.append(f'<h{level} id="{esc(anchor)}">{inline(title, anchors)}</h{level}>')
            i += 1
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        if RULE.match(line) and not para:
            out.append("<hr>")
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
            flush()
            head = _cells(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            th = "".join(f'<th scope="col">{inline(c, anchors)}</th>' for c in head)
            body = "".join("<tr>" + "".join(f"<td>{inline(c, anchors)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'
                       "</div>")
            continue
        if line.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i][1:].lstrip())
                i += 1
            inner, _ = convert("\n".join(quote))
            out.append(f"<blockquote>{inner}</blockquote>")
            continue
        if LIST_ITEM.match(line) and not para:
            html_, i = _list(lines, i, anchors)
            out.append(html_)
            continue
        if line.startswith("    ") and not para:                 # an indented code block
            body = []
            while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                body.append(lines[i][4:])
                i += 1
            while body and not body[-1].strip():
                body.pop()
            out.append(f"<pre><code>{esc(chr(10).join(body))}</code></pre>")
            continue
        para.append(line)
        i += 1
    flush()
    return "\n".join(out), headings


def _list(lines, i, anchors):
    """A list starting at line i, with the lists nested in it. Returns (html, next line)."""
    first = LIST_ITEM.match(lines[i])
    indent = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    tag = "ol" if ordered else "ul"
    start = ""
    if ordered and int(first.group(2)[:-1]) != 1:
        start = f' start="{int(first.group(2)[:-1])}"'
    items = []
    while i < len(lines):
        m = LIST_ITEM.match(lines[i])
        if not m or len(m.group(1)) != indent:
            if m and len(m.group(1)) > indent and items:
                sub, i = _list(lines, i, anchors)
                items[-1][1].append(sub)
                continue
            if not m and lines[i].strip() and items and (len(lines[i]) - len(lines[i].lstrip())) > indent:
                items[-1][0].append(lines[i].strip())       # a continuation line of the item
                i += 1
                continue
            if not lines[i].strip() and i + 1 < len(lines):
                nxt = LIST_ITEM.match(lines[i + 1])
                if nxt and len(nxt.group(1)) >= indent:
                    i += 1
                    continue
            break
        items.append(([m.group(3)], []))
        i += 1
    body = "".join(f"<li>{inline(' '.join(text), anchors)}{''.join(subs)}</li>" for text, subs in items)
    return f"<{tag}{start}>{body}</{tag}>", i
