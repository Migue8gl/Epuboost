"""Kobo kepub conversion: wrap every sentence in a koboSpan (like kepubify), so
the book opens in Kobo's fast native engine instead of Adobe RMSDK."""

from __future__ import annotations

import re

from lxml import etree

from .epub import XHTML_NS, Book, localname, parse_xml, serialize_xhtml

SKIP = {"script", "style", "pre", "audio", "video", "svg", "math", "head", "textarea"}
NEW_PARAGRAPH = {"p", "ol", "ul", "li", "table", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
STYLE_HACKS = "div#book-inner { margin-top: 0; margin-bottom: 0; }"

_SENTENCE_RE = re.compile(r"""\S.*?(?:[.!?…]+['"”’»)\]]*(?:\s+|$)|$)|\s+$""", re.S)


class _Spanner:
    def __init__(self, ns: str | None):
        self.tag = f"{{{ns}}}span" if ns else "span"
        self.para = self.seg = 0
        self.new_para = True

    def span(self) -> etree._Element:
        if self.new_para:
            self.para, self.seg, self.new_para = self.para + 1, 0, False
        self.seg += 1
        el = etree.Element(self.tag)
        el.set("class", "koboSpan")
        el.set("id", f"kobo.{self.para}.{self.seg}")
        return el

    def text_spans(self, text: str) -> tuple[str, list[etree._Element]]:
        """Split text into (leading whitespace, sentence spans)."""
        stripped = text.lstrip()
        lead = text[: len(text) - len(stripped)]
        spans = []
        for m in _SENTENCE_RE.finditer(stripped):
            if not m.group(0):
                continue
            if not m.group(0).strip():
                if spans:
                    spans[-1].text += m.group(0)
                continue
            span = self.span()
            span.text = m.group(0)
            spans.append(span)
        return lead, spans

    def walk(self, el: etree._Element) -> None:
        if localname(el) in NEW_PARAGRAPH:
            self.new_para = True
        children = [c for c in el if isinstance(c.tag, str)]  # before adding our own spans
        if el.text and el.text.strip():
            lead, spans = self.text_spans(el.text)
            el.text = lead or None
            for i, span in enumerate(spans):
                el.insert(i, span)
        for child in children:
            ns = etree.QName(child).namespace
            name = localname(child)
            if name == "img":
                self.new_para = True
                wrapper = self.span()
                child.addprevious(wrapper)
                tail, child.tail = child.tail, None
                wrapper.append(child)
                wrapper.tail = tail
                child = wrapper
            elif name not in SKIP and ns in (XHTML_NS, None):
                self.walk(child)
            if child.tail and child.tail.strip():
                lead, spans = self.text_spans(child.tail)
                child.tail = lead or None
                anchor = child
                for span in spans:
                    anchor.addnext(span)
                    anchor = span


def _convert_file(data: bytes) -> bytes | None:
    if b"koboSpan" in data:
        return None
    tree = parse_xml(data)
    root = tree.getroot()
    ns = etree.QName(root).namespace
    q = (lambda name: f"{{{ns}}}{name}") if ns else (lambda name: name)
    body = root.find(q("body"))
    if body is None:
        return None
    _Spanner(ns).walk(body)

    # Kobo's own wrappers, used by its pagination/column engine.
    columns = etree.Element(q("div"), id="book-columns")
    inner = etree.SubElement(columns, q("div"), id="book-inner")
    inner.text, body.text = body.text, None
    for child in list(body):
        inner.append(child)
    body.append(columns)

    head = root.find(q("head"))
    if head is not None:
        style = etree.SubElement(head, q("style"), type="text/css")
        style.set("class", "kobostylehacks")
        style.text = STYLE_HACKS
    return serialize_xhtml(tree)


def convert_to_kepub(book: Book, log: list[str]) -> None:
    converted = 0
    for path in book.xhtml_paths():
        try:
            out = _convert_file(book.files[path])
        except etree.XMLSyntaxError as exc:
            log.append(f"could not kepubify {path}: {exc}")
            continue
        if out is not None:
            book.write(path, out)
            converted += 1
    book.changed = True  # the .kepub.epub output is new even if nothing needed spans
    log.append(f"converted to kepub ({converted} files)")
