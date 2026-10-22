"""Embedded fonts: strip them all, or clean broken/unused @font-face rules and subset."""

from __future__ import annotations

import html
import io
import posixpath
import re
import string

from urllib.parse import unquote

import tinycss2
from fontTools import subset
from fontTools.ttLib import TTFont
from lxml import etree

from .epub import ENC_NS, FONT_EXTS, Book, localname, parse_xml, resolve, serialize_xhtml, serialize_xml

_STYLE_ATTR_RE = re.compile(r"""style\s*=\s*("([^"]*)"|'([^']*)')""", re.I)
_STYLE_TAG_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_BLANK_LINES_RE = re.compile(r"\n\s*\n\s*")


def _decode(data: bytes) -> str | None:
    try:
        return data.decode("utf-8").lstrip("﻿")
    except UnicodeDecodeError:
        return None


def _family_names(tokens) -> set[str]:
    """Family names in a font-family/font value, lowercased."""
    names, current = set(), []
    for tok in tokens:
        if tok.type == "literal" and tok.value == ",":
            if current:
                names.add(" ".join(current).lower())
            current = []
        elif tok.type == "string":
            names.add(tok.value.strip().lower())
        elif tok.type == "ident":
            current.append(tok.value)
    if current:
        names.add(" ".join(current).lower())
    return names


def _used_families_in_decls(decls, out: set[str]) -> None:
    for d in decls:
        if d.type == "declaration" and d.lower_name in ("font-family", "font"):
            out |= _family_names(d.value)
            if d.lower_name == "font":
                # Shorthand: be conservative and treat every word as a family.
                out |= {t.value.lower() for t in d.value if t.type in ("ident", "string")}


def _used_families_in_rules(rules, out: set[str]) -> None:
    for rule in rules:
        if rule.type == "qualified-rule":
            _used_families_in_decls(tinycss2.parse_declaration_list(rule.content), out)
        elif rule.type == "at-rule" and rule.content is not None and rule.lower_at_keyword != "font-face":
            _used_families_in_rules(tinycss2.parse_rule_list(rule.content), out)


def _face_info(rule):
    family, urls, has_local = None, [], False
    for d in tinycss2.parse_declaration_list(rule.content):
        if d.type != "declaration":
            continue
        if d.lower_name == "font-family":
            fams = _family_names(d.value)
            family = next(iter(fams), None)
        elif d.lower_name == "src":
            for tok in d.value:
                if tok.type == "url":
                    urls.append(tok.value)
                elif tok.type == "function" and tok.lower_name == "url":
                    urls += [a.value for a in tok.arguments if a.type == "string"]
                elif tok.type == "function" and tok.lower_name == "local":
                    has_local = True
    return family, urls, has_local


def _rule_without_src(rule) -> str | None:
    """Serialize a normal rule without stray `src` declarations, or None if unchanged."""
    decls = [d for d in tinycss2.parse_declaration_list(rule.content) if d.type == "declaration"]
    kept = [d for d in decls if d.lower_name != "src"]
    if len(kept) == len(decls):
        return None
    body = "".join(f"\n  {d.serialize()};" for d in kept)
    return f"{tinycss2.serialize(rule.prelude).strip()} {{{body}\n}}"


def clean_font_faces(book: Book, log: list[str]) -> None:
    """Remove @font-face rules that point to missing files or are never used,
    drop `src` from non-@font-face rules, and delete orphaned font files."""
    sheets = {}
    for path in book.css_paths():
        text = _decode(book.files[path])
        if text is not None:
            sheets[path] = tinycss2.parse_stylesheet(text, skip_comments=False, skip_whitespace=False)

    used: set[str] = set()
    for rules in sheets.values():
        _used_families_in_rules(rules, used)
    for path in book.xhtml_paths():
        text = _decode(book.files[path]) or ""
        for m in _STYLE_ATTR_RE.finditer(text):
            _used_families_in_decls(tinycss2.parse_declaration_list(html.unescape(m.group(2) or m.group(3) or "")), used)
        for m in _STYLE_TAG_RE.finditer(text):
            _used_families_in_rules(tinycss2.parse_stylesheet(m.group(1)), used)

    for path, rules in sheets.items():
        out, changed = [], False
        for rule in rules:
            if rule.type == "at-rule" and rule.lower_at_keyword == "font-face" and rule.content is not None:
                family, urls, has_local = _face_info(rule)
                targets = [resolve(path, u) for u in urls]
                local_targets = [t for t in targets if t is not None]
                if local_targets and not has_local and not any(t in book.files for t in local_targets):
                    log.append(f"removed @font-face '{family}' (missing file)")
                    changed = True
                    continue
                if family and family not in used:
                    log.append(f"removed @font-face '{family}' (never used)")
                    changed = True
                    continue
            elif rule.type == "qualified-rule":
                fixed = _rule_without_src(rule)
                if fixed is not None:
                    out.append(fixed)
                    changed = True
                    continue
            out.append(rule.serialize())
        if changed:
            book.write(path, "".join(out).encode("utf-8"))

    # Delete font files nothing refers to any more.
    text_blobs = [
        book.files[p] for p in book.css_paths() + book.xhtml_paths()
    ]
    for font in book.font_paths():
        name = posixpath.basename(font).encode()
        if not any(name in blob for blob in text_blobs):
            size = len(book.files[font])
            book.remove(font)
            log.append(f"deleted unused font {font} ({size / 1e6:.1f} MB)")


def _book_characters(book: Book) -> set[int]:
    chars = set(string.printable) | set(" ‘’“”–—…­")
    for path in book.xhtml_paths() + book.css_paths():
        text = _decode(book.files[path])
        if text is None:
            continue
        if path in book.css_paths():
            chars |= set(text)
        else:
            chars |= set(html.unescape(_TAG_RE.sub("", text)))
    # text-transform may change case at render time.
    chars |= {c.upper() for c in chars} | {c.lower() for c in chars}
    return {ord(c) for c in "".join(chars)}


def subset_fonts(book: Book, min_size: int, log: list[str]) -> None:
    """Shrink big embedded fonts to the glyphs actually used by the book."""
    candidates = [p for p in book.font_paths() if len(book.files[p]) > min_size]
    if not candidates:
        return
    unicodes = _book_characters(book)
    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.name_legacy = True
    options.notdef_outline = True
    options.glyph_names = True
    options.legacy_kern = True
    options.symbol_cmap = True
    options.hinting = True
    for path in candidates:
        original = book.files[path]
        try:
            font = TTFont(io.BytesIO(original))
            subsetter = subset.Subsetter(options)
            subsetter.populate(unicodes=unicodes)
            subsetter.subset(font)
            buf = io.BytesIO()
            font.save(buf)
        except Exception as exc:  # malformed/unsupported font: leave it alone
            log.append(f"could not subset {path}: {exc}")
            continue
        data = buf.getvalue()
        if len(data) < len(original):
            book.write(path, data)
            log.append(f"subset font {path}: {len(original) / 1e6:.1f} MB -> {len(data) / 1e3:.0f} KB")


def _strip_decls(content) -> str | None:
    """Declarations without non-monospace font-family, or None if unchanged."""
    decls = [d for d in tinycss2.parse_declaration_list(content) if d.type == "declaration"]
    kept, changed = [], False
    for d in decls:
        if d.lower_name != "font-family":
            kept.append(d.serialize())
        elif "monospace" in _family_names(d.value):
            kept.append("font-family: monospace")  # keep code blocks monospaced
            changed |= tinycss2.serialize(d.value).strip().lower() != "monospace"
        else:
            changed = True
    return "; ".join(kept) if changed else None


def _strip_rules(rules) -> tuple[str, bool]:
    out, changed = [], False
    for rule in rules:
        if rule.type == "at-rule" and rule.lower_at_keyword == "font-face":
            changed = True
            continue
        if rule.type == "qualified-rule":
            body = _strip_decls(rule.content)
            if body is not None:
                out.append(f"{tinycss2.serialize(rule.prelude).strip()} {{ {body} }}")
                changed = True
                continue
        elif rule.type == "at-rule" and rule.content is not None and rule.lower_at_keyword in ("media", "supports"):
            inner, inner_changed = _strip_rules(tinycss2.parse_rule_list(rule.content))
            if inner_changed:
                out.append(f"@{rule.at_keyword}{tinycss2.serialize(rule.prelude)}{{{inner}\n}}")
                changed = True
                continue
        out.append(rule.serialize())
    return "".join(out), changed


def _remove_encryption_entries(book: Book, paths: set[str]) -> None:
    data = book.files.get("META-INF/encryption.xml")
    if not data or not paths:
        return
    tree = parse_xml(data)
    root = tree.getroot()
    for enc in list(root):
        ref = enc.find(f".//{{{ENC_NS}}}CipherReference")
        if ref is not None and unquote(ref.get("URI", "")) in paths:
            root.remove(enc)
    if len(root):
        book.write("META-INF/encryption.xml", serialize_xml(tree))
    else:
        del book.files["META-INF/encryption.xml"]
        book.changed = True
    book.encrypted -= paths


def strip_fonts(book: Book, log: list[str]) -> None:
    """Remove every embedded font and font-family declaration so the reader's own
    fonts are used (monospace is kept for code)."""
    for path in book.css_paths():
        text = _decode(book.files[path])
        if text is None:
            continue
        out, changed = _strip_rules(tinycss2.parse_stylesheet(text, skip_comments=False, skip_whitespace=False))
        if changed:
            book.write(path, _BLANK_LINES_RE.sub("\n\n", out).strip().encode("utf-8") + b"\n")

    for path in book.xhtml_paths():
        data = book.files[path]
        if b"font-family" not in data and b"font-face" not in data:
            continue
        try:
            tree = parse_xml(data)
        except etree.XMLSyntaxError:
            continue
        dirty = False
        for el in tree.getroot().iter():
            if not isinstance(el.tag, str):
                continue
            if el.get("style") and (body := _strip_decls(el.get("style"))) is not None:
                if body:
                    el.set("style", body)
                else:
                    del el.attrib["style"]
                dirty = True
            if localname(el) == "style" and el.text:
                out, changed = _strip_rules(tinycss2.parse_stylesheet(el.text))
                if changed:
                    el.text = out
                    dirty = True
        if dirty:
            book.write(path, serialize_xhtml(tree))

    fonts = [p for p in book.files if posixpath.splitext(p)[1].lower() in FONT_EXTS]
    fonts += [
        book.item_path(i) for i in book.items()
        if "font" in i.get("media-type", "") and book.item_path(i) in book.files and book.item_path(i) not in fonts
    ]
    if not fonts:
        return
    size = sum(len(book.files[p]) for p in fonts)
    for path in fonts:
        book.remove(path)
    _remove_encryption_entries(book, set(fonts) & book.encrypted)
    log.append(f"removed {len(fonts)} embedded fonts ({size / 1e6:.1f} MB), the reader's fonts will be used")
