"""Split oversized XHTML files and fix every link that points into them."""

from __future__ import annotations

import copy
import posixpath

from lxml import etree

from .epub import NS, OPF_NS, XHTML_NS, XLINK_HREF, Book, localname, parse_xml, relative_href, resolve, serialize_xhtml, serialize_xml

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
WRAPPERS = {"div", "section", "article", "main"}



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


def fix_pre_breaks(book: Book, log: list[str]) -> None:
    """Turn <br> inside <pre> into plain newlines.

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


def _container_path(body) -> list[int]:
    """Index path from <body> down through single wrapper elements."""
    node, path = body, []
    while True:
        kids = [c for c in node if isinstance(c.tag, str)]
        if (
            len(kids) == 1
            and localname(kids[0]) in WRAPPERS
            and not (node.text or "").strip()
            and not (kids[0].tail or "").strip()
        ):
            path.append(list(node).index(kids[0]))
            node = kids[0]
        else:
            return path


def _follow(node, path):
    for i in path:
        node = node[i]
    return node


def _plan_chunks(container, limit: int) -> list[tuple[int, int]]:
    """Group the container's children into [start, end) ranges of ~limit bytes."""
    children = list(container)
    sizes = [len(etree.tostring(c, encoding="utf-8")) for c in children]
    ranges, start, current = [], 0, 0
    for i, (child, size) in enumerate(zip(children, sizes)):
        heading_break = localname(child) in HEADINGS and current > limit // 2
        if i > start and (current + size > limit or heading_break):
            ranges.append((start, i))
            start, current = i, 0
        current += size
    ranges.append((start, len(children)))
    return ranges


def _ids(el) -> set[str]:
    out = set()
    for e in el.iter():
        if not isinstance(e.tag, str):
            continue
        if e.get("id"):
            out.add(e.get("id"))
        if localname(e) == "a" and e.get("name"):
            out.add(e.get("name"))
    return out


def _new_name(book: Book, path: str, n: int) -> str:
    base, ext = posixpath.splitext(path)
    name = f"{base}_split{n:03d}{ext}"
    while name in book.files:
        n += 100
        name = f"{base}_split{n:03d}{ext}"
    return name


def _split_one(book: Book, path: str, limit: int):
    """Split one file. Returns (chunk paths, {id: chunk path}) or None."""
    tree = parse_xml(book.files[path])
    body = tree.getroot().find("h:body", NS)
    if body is None:
        return None
    cpath = _container_path(body)
    container = _follow(body, cpath)
    ranges = _plan_chunks(container, limit)
    if len(ranges) < 2:
        return None

    chunk_paths = [path] + [_new_name(book, path, n) for n in range(1, len(ranges))]
    id_map: dict[str, str] = {}
    outputs = []
    for n, (start, end) in enumerate(ranges):
        doc = copy.deepcopy(tree)
        doc_body = doc.getroot().find("h:body", NS)
        doc_container = _follow(doc_body, cpath)
        children = list(doc_container)
        for child in children[:start] + children[end:]:
            doc_container.remove(child)
        # Wrapper elements are repeated in every chunk: keep their ids/text once.
        for depth in range(len(cpath) + 1):
            wrapper = _follow(doc_body, cpath[:depth])
            if n == 0 and wrapper.get("id"):
                id_map.setdefault(wrapper.get("id"), path)
            elif n > 0:
                wrapper.attrib.pop("id", None)
        if n > 0:
            doc_container.text = None
        for child in doc_container:
            for ident in _ids(child):
                id_map.setdefault(ident, chunk_paths[n])
        outputs.append(doc)

    book.write(path, serialize_xhtml(outputs[0]))
    previous = path
    for chunk_path, doc in zip(chunk_paths[1:], outputs[1:]):
        book.insert_after(previous, chunk_path, serialize_xhtml(doc))
        previous = chunk_path
    _register_chunks(book, path, chunk_paths[1:])
    return chunk_paths, id_map


def _register_chunks(book: Book, original: str, new_paths: list[str]) -> None:
    item = next(i for i in book.items() if book.item_path(i) == original)
    anchor_item = item
    refs = [r for r in book.spine.findall("opf:itemref", NS) if r.get("idref") == item.get("id")]
    anchor_ref = refs[0] if refs else None
    for new_path in new_paths:
        new_item = etree.Element(f"{{{OPF_NS}}}item")
        new_item.set("id", book.unique_id(f"{item.get('id')}_split"))
        new_item.set("href", book.path_to_href(new_path))
        new_item.set("media-type", item.get("media-type"))
        new_item.tail = anchor_item.tail
        anchor_item.addnext(new_item)
        anchor_item = new_item
        if anchor_ref is not None:
            new_ref = etree.Element(f"{{{OPF_NS}}}itemref")
            new_ref.set("idref", new_item.get("id"))
            if anchor_ref.get("linear"):
                new_ref.set("linear", anchor_ref.get("linear"))
            new_ref.tail = anchor_ref.tail
            anchor_ref.addnext(new_ref)
            anchor_ref = new_ref


def split_large_files(book: Book, max_bytes: int, log: list[str]) -> None:
    # original path -> {id: chunk path now containing it}
    moved: dict[str, dict[str, str]] = {}
    origin: dict[str, str] = {}  # chunk path -> original path
    for path in book.xhtml_paths():
        original_size = len(book.files[path])
        if original_size <= max_bytes:
            continue
        try:
            result = _split_one(book, path, max_bytes)
        except etree.XMLSyntaxError as exc:
            log.append(f"could not split {path}: {exc}")
            continue
        if result is None:
            continue
        chunk_paths, id_map = result
        moved[path] = id_map
        for c in chunk_paths:
            origin[c] = path
        log.append(f"split {path} ({original_size // 1024} KB) into {len(chunk_paths)} files")
    if moved:
        _rewrite_links(book, moved, origin)


def _retarget(href: str, doc: str, doc_origin: str, moved: dict[str, dict[str, str]]) -> str | None:
    if "#" not in href:
        return None
    path_part, frag = href.split("#", 1)
    target = resolve(doc_origin, path_part) if path_part else doc_origin
    if target not in moved or frag not in moved[target]:
        return None
    new_target = moved[target][frag]
    new_href = (f"#{frag}" if new_target == doc else f"{relative_href(doc, new_target)}#{frag}")
    return new_href if new_href != href else None


def _rewrite_links(book: Book, moved, origin) -> None:
    for doc in book.xhtml_paths():
        try:
            tree = parse_xml(book.files[doc])
        except etree.XMLSyntaxError:
            continue
        doc_origin = origin.get(doc, doc)
        dirty = False
        for el in tree.getroot().iter():
            if not isinstance(el.tag, str):
                continue
            for attr in ("href", XLINK_HREF):
                value = el.get(attr)
                if value and (new := _retarget(value, doc, doc_origin, moved)):
                    el.set(attr, new)
                    dirty = True
        if dirty:
            book.write(doc, serialize_xhtml(tree))

    ncx = book.ncx_path()
    if ncx and ncx in book.files:
        tree = parse_xml(book.files[ncx])
        dirty = False
        for el in tree.getroot().iter("{*}content"):
            value = el.get("src")
            if value and (new := _retarget(value, ncx, ncx, moved)):
                el.set("src", new)
                dirty = True
        if dirty:
            book.write(ncx, serialize_xml(tree))

    for ref in book.opf.iter(f"{{{OPF_NS}}}reference"):
        value = ref.get("href")
        if value and (new := _retarget(value, book.opf_path, book.opf_path, moved)):
            ref.set("href", new)
            book.changed = True
