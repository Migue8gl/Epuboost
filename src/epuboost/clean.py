"""Markup that breaks RMSDK: links to missing files and line breaks it paginates wrong."""

from __future__ import annotations

import re

import tinycss2
from lxml import etree

from .epub import XHTML_NS, Book, parse_xml, resolve, serialize_xhtml

_COMBINATOR_RE = re.compile(r"\s*[>+~]\s*|\s+")
_PSEUDO_RE = re.compile(r":[\w-]+(\([^)]*\))?")
_PSEUDO_ELEMENT_RE = re.compile(r"::|:(before|after|first-line|first-letter)\b", re.I)


def remove_broken_links(book: Book, log: list[str]) -> None:
    """Drop <link> elements (e.g. Adobe page templates) pointing to missing files."""
    removed = 0
    for path in book.xhtml_paths():
        try:
            tree = parse_xml(book.files[path])
        except etree.XMLSyntaxError:
            continue
        dirty = False
        for link in tree.getroot().iter(f"{{{XHTML_NS}}}link"):
            target = resolve(path, link.get("href", ""))
            if target is not None and target not in book.files:
                _drop(link)
                dirty = True
                removed += 1
        if dirty:
            book.write(path, serialize_xhtml(tree))
    for item in book.items():
        if book.item_path(item) not in book.files:
            book.remove(book.item_path(item))
            log.append(f"removed manifest entry for missing {item.get('href')}")
    if removed:
        log.append(f"removed {removed} links to missing files")


def fix_pre_breaks(book: Book, log: list[str]) -> int:
    """Turn <br> inside <pre> into plain newlines. Returns how many were fixed.

    Converters like Calibre emit `line<br/>\\n` in code blocks, often with a
    `display: block` rule on the <br>. RMSDK measures those lines differently
    when laying out and when rendering, which makes it skip or repeat pages.
    """
    fixed = 0
    for path in book.xhtml_paths():
        try:
            tree = parse_xml(book.files[path])
        except etree.XMLSyntaxError:
            continue
        dirty = False
        for pre in tree.getroot().iter(f"{{{XHTML_NS}}}pre"):
            # XML parsers keep the newline right after <pre> that HTML drops.
            if pre.text and pre.text.startswith("\n"):
                pre.text = pre.text[1:]
                dirty = True
            for br in list(pre.iter(f"{{{XHTML_NS}}}br")):
                if not (br.tail or "").startswith("\n"):
                    br.tail = "\n" + (br.tail or "")
                _drop(br)
                dirty = True
                fixed += 1
        if dirty:
            book.write(path, serialize_xhtml(tree))
    if fixed:
        log.append(f"replaced {fixed} line breaks in code blocks")
    return fixed


def _drop(el) -> None:
    """Remove an element while keeping its tail text."""
    parent = el.getparent()
    if el.tail:
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def _display(decls) -> str | None:
    """The last `display` value in a declaration list, lowercased."""
    value = None
    for d in decls:
        if d.type == "declaration" and d.lower_name == "display":
            value = tinycss2.serialize(d.value).strip().lower()
    return value


def _subject(selector: str) -> tuple[str, set[str]] | None:
    """(element name, classes) of the element a selector styles, or None for pseudo-elements."""
    compound = _COMBINATOR_RE.split(selector.strip())[-1]
    if _PSEUDO_ELEMENT_RE.search(compound):
        return None
    compound = _PSEUDO_RE.sub("", compound)
    name = re.match(r"[\w-]*", compound).group(0).lower()
    return name, set(re.findall(r"\.([\w-]+)", compound))


def _collect_display_rules(rules, block: set[str], hidden: set[str]) -> None:
    """Add to `block`/`hidden` the selectors (".class", or "br" for the element
    itself) given a block-like display or `display: none`."""
    for rule in rules:
        if rule.type == "at-rule" and rule.content is not None and rule.lower_at_keyword in ("media", "supports"):
            _collect_display_rules(tinycss2.parse_rule_list(rule.content), block, hidden)
            continue
        if rule.type != "qualified-rule":
            continue
        display = _display(tinycss2.parse_declaration_list(rule.content))
        if display is None or display == "inline":
            continue
        target = hidden if display == "none" else block
        for selector in tinycss2.serialize(rule.prelude).split(","):
            subject = _subject(selector)
            if subject is None:
                continue
            name, classes = subject
            target |= {f".{c}" for c in classes}
            if name == "br":
                target.add("br")


def fix_block_breaks(book: Book, log: list[str]) -> int:
    """Make <br> elements styled `display: block` inline again. Returns how many were fixed.

    Calibre gives <br> a class like `.calibre5 { display: block }`, also around
    blank-line paragraphs (`<p><br class="calibre5"/></p>`). RMSDK measures a block
    <br> differently when laying out and when rendering, so pages after it repeat
    or lose lines. An inline `display: inline` wins over the class and keeps its
    other properties; the class itself is often shared with <div>s, so the CSS
    rule is left alone.
    """
    block: set[str] = set()
    hidden: set[str] = set()  # `display: none` could be what hides a <br>: don't touch those
    for path in book.css_paths():
        rules, _ = tinycss2.parse_stylesheet_bytes(book.files[path], skip_comments=True, skip_whitespace=True)
        _collect_display_rules(rules, block, hidden)

    fixed = 0
    for path in book.xhtml_paths():
        if b"<br" not in book.files[path]:
            continue
        try:
            tree = parse_xml(book.files[path])
        except etree.XMLSyntaxError:
            continue
        doc_block, doc_hidden = set(block), set(hidden)  # <style> only applies to its own document
        for style in tree.getroot().iter(f"{{{XHTML_NS}}}style"):
            rules = tinycss2.parse_stylesheet(style.text or "", skip_comments=True, skip_whitespace=True)
            _collect_display_rules(rules, doc_block, doc_hidden)
        dirty = False
        for br in tree.getroot().iter(f"{{{XHTML_NS}}}br"):
            selectors = {f".{c}" for c in br.get("class", "").split()} | {"br"}
            decls = [d for d in tinycss2.parse_declaration_list(br.get("style", "")) if d.type == "declaration"]
            inline = _display(decls)
            if inline is None and (selectors & doc_hidden or not selectors & doc_block):
                continue
            if inline in ("inline", "none"):
                continue
            kept = [d.serialize() for d in decls if d.lower_name != "display"]
            br.set("style", "; ".join(kept + ["display: inline"]))
            dirty = True
            fixed += 1
        if dirty:
            book.write(path, serialize_xhtml(tree))
    if fixed:
        log.append(f"made {fixed} block line breaks inline")
    return fixed
