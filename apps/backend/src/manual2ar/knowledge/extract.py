"""Deterministic evidence extraction, without an LLM or website credentials."""
from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
HIDDEN = {"script", "style", "noscript", "nav", "header", "footer", "button", "form", "template"}
BLOCK = {"p", "li", "table", "pre", "blockquote", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6"}
SAFE = BLOCK | {"div", "section", "article", "span", "strong", "em", "b", "i", "u", "s", "sub", "sup", "br", "hr", "ul", "ol", "dl", "dt", "dd", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "figure", "a", "img", "code"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: str, base: str = "", *, page: bool = False) -> str | None:
    value = html.unescape(value).strip()
    if not value or value.startswith(("#", "data:", "blob:", "javascript:", "mailto:", "tel:")):
        return None
    try:
        p = urlsplit(urljoin(base, value))
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
            return None
        path = quote(p.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = "" if page else quote(p.query, safe="/%?:@!$&'()*+,;=-._~")
        # Preserve escaped reserved characters, normalize UTF-8 and percent-escape case.
        path = re.sub(r"%[0-9a-fA-F]{2}", lambda m:m.group().upper(), path)
        query = re.sub(r"%[0-9a-fA-F]{2}", lambda m:m.group().upper(), query)
        return urlunsplit(("https", p.hostname.lower(), path, query, ""))
    except ValueError:
        return None


class Node:
    def __init__(self, tag="root", attrs=(), parent=None, pos=(0, 0)):
        self.tag, self.attrs, self.parent, self.pos = tag, dict(attrs), parent, pos
        self.children: list[Node | str] = []

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Node):
                yield from c.walk()

    def text(self, skip_blocks=False):
        if self.tag in HIDDEN or "toc-anchor" in self.attrs.get("class", "").split():
            return ""
        chunks = []
        for c in self.children:
            if isinstance(c, str):
                chunks.append(c)
            elif not (skip_blocks and c.tag in BLOCK):
                separator = " " if c.tag in BLOCK | {"div", "section", "br", "hr", "tr", "td", "th", "dt", "dd"} else ""
                chunks.append(separator + c.text(skip_blocks) + separator)
        # Keep CJK inline text intact; block boundaries and line breaks get spaces.
        return re.sub(r"\s+", " ", "".join(chunks)).strip()

    def selector(self):
        parts, n = [], self
        while n.parent:
            siblings = [c for c in n.parent.children if isinstance(c, Node) and c.tag == n.tag]
            parts.append(f"{n.tag}:nth-of-type({siblings.index(n) + 1})")
            n = n.parent
        return " > ".join(reversed(parts))

    def serialize(self):
        if self.tag == "root":
            return "".join(c.serialize() if isinstance(c, Node) else html.escape(c) for c in self.children)
        attrs = "".join(f' {k}="{html.escape(v or "", quote=True)}"' for k, v in self.attrs.items())
        start = f"<{self.tag}{attrs}>"
        return start if self.tag in VOID else start + "".join(c.serialize() if isinstance(c, Node) else html.escape(c) for c in self.children) + f"</{self.tag}>"


class Parser(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.stack[-1], self.getpos())
        self.stack[-1].children.append(n)
        if tag not in VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def article(root):
    nodes = list(root.walk())
    for n in nodes:
        if "contents" in n.attrs.get("class", "").split() and len(n.text()) >= 30:
            return n, "wikijs:.contents"
    for tag in ("article", "main"):
        candidates = [n for n in nodes if n.tag == tag and len(n.text()) >= 30]
        if candidates:
            return max(candidates, key=lambda n: len(n.text())), tag
    # Do not treat a login page / JS shell / navigation as a valid article.
    return None, None


def extract(source: str, url: str):
    root = Parser(source).root
    content, method = article(root)
    titles = [n.text() for n in root.walk() if n.tag == "title"]
    metadata = {n.attrs.get("property", n.attrs.get("name", "")): n.attrs.get("content")
                for n in root.walk() if n.tag == "meta" and n.attrs.get("content")}
    result = {"title": titles[0] if titles else url, "article_selector": method,
              "metadata": metadata, "blocks": [], "links": [], "assets": [], "language_links": []}
    for n in root.walk():
        if n.tag == "link" and n.attrs.get("rel") == "alternate":
            u = canonical(n.attrs.get("href", ""), url, page=True)
            if u:
                result["language_links"].append({"url": u, "language": n.attrs.get("hreflang")})
    if not content:
        return result, None
    headings = []
    for n in content.walk():
        if any(p.tag in HIDDEN for p in ancestors(n)):
            continue
        # Table content is represented once, with rows/cells preserved below.
        in_table = any(p.tag == "table" for p in ancestors(n))
        if n.tag in BLOCK and not in_table:
            text = n.text(skip_blocks=n.tag not in {"table", "pre", "blockquote"})
            if n.tag.startswith("h") and len(n.tag) == 2 and n.tag[1].isdigit():
                level = int(n.tag[1])
                headings = [h for h in headings if h[0] < level]
                headings.append((level, text, n.attrs.get("id")))
            if text:
                b = {"ordinal": len(result["blocks"]) + 1, "kind": n.tag,
                     "text": text, "text_sha256": digest(text.encode()),
                     "heading_path": [h[1] for h in headings],
                     "anchor": n.attrs.get("id") or (headings[-1][2] if headings else None),
                     "dom_path": n.selector(), "html_line": n.pos[0],
                     "html": n.serialize()}
                if n.tag == "table":
                    b["rows"] = [[c.text() for c in row.children if isinstance(c, Node) and c.tag in {"td", "th"}]
                                 for row in n.walk() if row.tag == "tr"]
                result["blocks"].append(b)
        if n.tag == "a":
            u = canonical(n.attrs.get("href", ""), url)
            if u:
                result["links"].append({"url": u, "label": n.text(),
                    "href": n.attrs["href"], "dom_path": n.selector(),
                    "heading_path": [h[1] for h in headings]})
        if n.tag in {"img", "source", "video", "iframe", "oembed", "embed", "object"}:
            candidates = []
            for key in ("src", "data-src", "poster", "url", "data"):
                if n.attrs.get(key):
                    candidates.append((key, n.attrs[key]))
            for key in ("srcset", "data-srcset"):
                for part in n.attrs.get(key, "").split(","):
                    if part.strip():
                        candidates.append((key, part.strip().split()[0]))
            for key, value in candidates:
                u = canonical(value, url)
                if u:
                    kind = "image" if n.tag == "img" or key == "poster" else "embedded_media"
                    result["assets"].append({"url": u, "kind": kind, "attribute": key,
                        "alt": n.attrs.get("alt", ""), "raw_reference": value,
                        "dom_path": n.selector(), "heading_path": [h[1] for h in headings],
                        "nearby_text": n.parent.text()[:1500] if n.parent else ""})
    return result, content


def ancestors(n):
    while n.parent:
        n = n.parent
        yield n


def offline_html(content, url, asset_paths, page_paths=None, attachment_paths=None):
    """Safe derivative: no scripts, embedded frames, remote CSS or remote images."""
    page_paths, attachment_paths = page_paths or {}, attachment_paths or {}
    def render(n):
        if isinstance(n, str):
            return html.escape(n)
        if n.tag in HIDDEN:
            return ""
        children = "".join(render(c) for c in n.children)
        if n.tag not in SAFE:
            return children
        attrs = ""
        for key in ("id", "colspan", "rowspan", "alt", "title", "start", "value"):
            if n.attrs.get(key):
                attrs += f' {key}="{html.escape(n.attrs[key], quote=True)}"'
        if n.tag == "a":
            href = n.attrs.get("href", "")
            u = href if href.startswith("#") else canonical(href, url)
            if u:
                if not href.startswith("#"):
                    local = attachment_paths.get(u) or page_paths.get(canonical(u, page=True))
                    fragment = urlsplit(urljoin(url, href)).fragment
                    original = u + ("#" + fragment if fragment else "")
                    attrs += f' data-source-url="{html.escape(original, quote=True)}"'
                    u = local + ("#" + fragment if fragment else "") if local else original
                attrs += f' href="{html.escape(u, quote=True)}" rel="noreferrer"'
        if n.tag == "img":
            u = canonical(n.attrs.get("src") or n.attrs.get("data-src", ""), url)
            local = asset_paths.get(u)
            if not local:
                # A hyperlink explicitly marks an image that was not archived.
                return f'<p>[未归档图片：{html.escape(n.attrs.get("alt", ""))}]</p>'
            attrs += f' src="{html.escape(local, quote=True)}"'
        return f"<{n.tag}{attrs}>" + ("" if n.tag in VOID else children + f"</{n.tag}>")
    csp = "default-src 'none'; img-src 'self' data: file:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    return '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + html.escape(csp, quote=True) + '"><style>body{max-width:1000px;margin:2em auto;font:17px/1.7 sans-serif;padding:1em}img{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #999;padding:6px}a{overflow-wrap:anywhere}</style><p><a href="../../index.html">资料目录</a> · <a href="' + html.escape(url,quote=True) + '">官方原文</a></p><p>离线阅读派生件；原始响应与渲染 DOM 请见本目录证据记录。</p>' + render(content)
