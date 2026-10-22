"""Reading, modifying and writing EPUB containers."""

from __future__ import annotations

import html.entities
import io
import os
import posixpath
import re
import shutil
import tempfile
import zipfile
from urllib.parse import quote, unquote, urlsplit

from lxml import etree

OPF_NS = "http://www.idpf.org/2007/opf"
XHTML_NS = "http://www.w3.org/1999/xhtml"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
ENC_NS = "http://www.w3.org/2001/04/xmlenc#"
NS = {"opf": OPF_NS, "h": XHTML_NS}

MARKER_NAME = "epuboost"
MARKER_VERSION = "1"

XHTML_TYPES = {"application/xhtml+xml", "text/html"}
FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".tif", ".tiff"}
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

_XML_PARSER = etree.XMLParser(resolve_entities=False, huge_tree=True, remove_blank_text=False)
_ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>")
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_CSS_URL_RE = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")
_REF_ATTRS = ("src", "href", "poster", XLINK_HREF)


def _numeric_entity(m: re.Match) -> str:
    name = m.group(1)
    if name in _XML_ENTITIES:
        return m.group(0)
    chars = html.entities.html5.get(name + ";")
    if chars is None:
        return m.group(0)
    return "".join(f"&#{ord(c)};" for c in chars)


def parse_xml(data: bytes) -> etree._ElementTree:
    """Parse XML/XHTML, tolerating HTML named entities like &nbsp;."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return etree.ElementTree(etree.fromstring(data, _XML_PARSER))
    text = _XML_DECL_RE.sub("", text.lstrip("﻿"), count=1)
    text = _ENTITY_RE.sub(_numeric_entity, text)
    return etree.ElementTree(etree.fromstring(text.encode("utf-8"), _XML_PARSER))


def serialize_xhtml(tree: etree._ElementTree) -> bytes:
    # Avoid self-closing non-void tags (<a id="x"/>), which HTML parsers misread.
    for el in tree.getroot().iter():
        if (
            isinstance(el.tag, str)
            and el.text is None
            and len(el) == 0
            and etree.QName(el).localname not in VOID_ELEMENTS
        ):
            el.text = ""
    return etree.tostring(tree, xml_declaration=True, encoding="utf-8")


def serialize_xml(tree: etree._ElementTree) -> bytes:
    return etree.tostring(tree, xml_declaration=True, encoding="utf-8")


def localname(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def resolve(base_path: str, href: str) -> str | None:
    """Resolve an href found in archive file `base_path` to an archive path.

    Returns None for external URLs and pure fragments.
    """
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or not parts.path:
        return None
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_path), unquote(parts.path)))


def relative_href(from_path: str, to_path: str) -> str:
    start = posixpath.dirname(from_path) or "."
    return quote(posixpath.relpath(to_path, start), safe="/")


def _rewrite_css_urls(css: str, base: str, old: str, new: str) -> str:
    def repl(m: re.Match) -> str:
        if resolve(base, m.group(2)) != old:
            return m.group(0)
        return f"url({m.group(1)}{relative_href(base, new)}{m.group(1)})"
    return _CSS_URL_RE.sub(repl, css)


class Book:
    def __init__(self, path: str):
        self.path = path
        with zipfile.ZipFile(path) as zf:
            self.infos: dict[str, zipfile.ZipInfo] = {i.filename: i for i in zf.infolist() if not i.is_dir()}
            self.files: dict[str, bytes] = {name: zf.read(name) for name in self.infos}
        container = parse_xml(self.files["META-INF/container.xml"])
        rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
        self.opf_path = unquote(rootfile.get("full-path"))
        self.opf_dir = posixpath.dirname(self.opf_path)
        self.opf = parse_xml(self.files[self.opf_path])
        self.encrypted = self._encrypted_paths()
        self.changed = False

    # -- OPF helpers -----------------------------------------------------

    def _encrypted_paths(self) -> set[str]:
        data = self.files.get("META-INF/encryption.xml")
        if not data:
            return set()
        tree = parse_xml(data)
        return {
            unquote(ref.get("URI"))
            for ref in tree.iter(f"{{{ENC_NS}}}CipherReference")
            if ref.get("URI")
        }

    @property
    def manifest(self):
        return self.opf.find("opf:manifest", NS)

    @property
    def spine(self):
        return self.opf.find("opf:spine", NS)

    def items(self):
        return self.manifest.findall("opf:item", NS)

    def item_path(self, item) -> str:
        return posixpath.normpath(posixpath.join(self.opf_dir, unquote(item.get("href", ""))))

    def path_to_href(self, path: str) -> str:
        return quote(posixpath.relpath(path, self.opf_dir or "."), safe="/")

    def xhtml_paths(self) -> list[str]:
        return [
            self.item_path(i) for i in self.items()
            if i.get("media-type") in XHTML_TYPES and self.item_path(i) in self.files
        ]

    def css_paths(self) -> list[str]:
        return [
            self.item_path(i) for i in self.items()
            if (i.get("media-type") == "text/css" or i.get("href", "").lower().endswith(".css"))
            and self.item_path(i) in self.files
        ]

    def font_paths(self) -> list[str]:
        return [
            p for p in self.files
            if posixpath.splitext(p)[1].lower() in FONT_EXTS and p not in self.encrypted
        ]

    def image_paths(self) -> list[str]:
        return [
            p for p in self.files
            if posixpath.splitext(p)[1].lower() in IMAGE_EXTS and p not in self.encrypted
        ]

    def ncx_path(self) -> str | None:
        for i in self.items():
            if i.get("media-type") == "application/x-dtbncx+xml":
                return self.item_path(i)
        return None

    def has_marker(self) -> bool:
        return any(
            m.get("name") == MARKER_NAME
            for m in self.opf.iter(f"{{{OPF_NS}}}meta")
        )

    def add_marker(self) -> None:
        metadata = self.opf.find("opf:metadata", NS)
        meta = etree.SubElement(metadata, f"{{{OPF_NS}}}meta")
        meta.set("name", MARKER_NAME)
        meta.set("content", MARKER_VERSION)
        meta.tail = "\n  "

    def unique_id(self, base: str) -> str:
        ids = {el.get("id") for el in self.opf.iter() if el.get("id")}
        candidate, n = base, 1
        while candidate in ids:
            candidate, n = f"{base}_{n}", n + 1
        return candidate

    # -- file operations -------------------------------------------------

    def write(self, path: str, data: bytes) -> None:
        if self.files.get(path) != data:
            self.files[path] = data
            self.changed = True

    def insert_after(self, existing: str, path: str, data: bytes) -> None:
        """Add a new file placed right after `existing` in the zip order."""
        new_files = {}
        for name, content in self.files.items():
            new_files[name] = content
            if name == existing:
                new_files[path] = data
        new_files.setdefault(path, data)
        self.files = new_files
        self.changed = True

    def remove(self, path: str) -> None:
        if path in self.files:
            del self.files[path]
            self.changed = True
        for item in self.items():
            if self.item_path(item) == path:
                for ref in self.spine.findall("opf:itemref", NS):
                    if ref.get("idref") == item.get("id"):
                        self.spine.remove(ref)
                self.manifest.remove(item)

    def rename(self, old: str, new: str, media_type: str | None = None) -> None:
        """Rename a file and rewrite every reference to it (manifest, XHTML, CSS)."""
        self.files = {(new if name == old else name): data for name, data in self.files.items()}
        if old in self.infos:
            self.infos[new] = self.infos[old]
        self.changed = True
        for item in self.items():
            if self.item_path(item) == old:
                item.set("href", self.path_to_href(new))
                if media_type:
                    item.set("media-type", media_type)
        needle = posixpath.basename(old).encode()
        for path in self.xhtml_paths() + self.css_paths():
            data = self.files[path]
            if needle not in data and quote(needle.decode()).encode() not in data:
                continue
            if path in self.css_paths():
                self.write(path, _rewrite_css_urls(data.decode("utf-8", "replace"), path, old, new).encode("utf-8"))
                continue
            try:
                tree = parse_xml(data)
            except etree.XMLSyntaxError:
                continue
            for el in tree.getroot().iter():
                if not isinstance(el.tag, str):
                    continue
                for attr in _REF_ATTRS:
                    value = el.get(attr)
                    if value and resolve(path, value.split("#", 1)[0]) == old:
                        frag = value[len(value.split("#", 1)[0]):]
                        el.set(attr, relative_href(path, new) + frag)
                if el.get("style"):
                    el.set("style", _rewrite_css_urls(el.get("style"), path, old, new))
                if localname(el) == "style" and el.text:
                    el.text = _rewrite_css_urls(el.text, path, old, new)
            self.write(path, serialize_xhtml(tree))

    def save(self, dest: str | None = None) -> int:
        """Atomically write the book to `dest` (default: replace the original).

        Returns the new size.
        """
        dest = dest or self.path
        self.files[self.opf_path] = serialize_xml(self.opf)
        directory = os.path.dirname(os.path.abspath(dest))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".epuboost-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(self._build_zip())
            with zipfile.ZipFile(tmp) as zf:
                if zf.testzip() is not None:
                    raise RuntimeError("generated zip is corrupt")
            shutil.copymode(self.path, tmp)
            os.replace(tmp, dest)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return os.path.getsize(dest)

    def _build_zip(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # The mimetype entry must be first and stored uncompressed.
            if "mimetype" in self.files:
                zf.writestr(zipfile.ZipInfo("mimetype"), self.files["mimetype"], zipfile.ZIP_STORED)
            for name, data in self.files.items():
                if name == "mimetype":
                    continue
                info = zipfile.ZipInfo(name, self.infos[name].date_time if name in self.infos else (2020, 1, 1, 0, 0, 0))
                zf.writestr(info, data, zipfile.ZIP_DEFLATED, compresslevel=9)
        return buf.getvalue()
