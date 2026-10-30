"""Unit tests for the clean step's line break fixes and the processed-book marker."""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree

from epuboost.clean import fix_block_breaks
from epuboost.epub import MARKER_VERSION, Book

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""


def make_book(tmp_path: Path, body: str, css: str = "", head: str = "", meta: str = "") -> Book:
    """A one-chapter book with `body` in chapter.xhtml and `css` in style.css."""
    opf = f"""<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>{meta}</metadata>
  <manifest>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="ch" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch"/></spine>
</package>
"""
    chapter = f"""<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title>{head}</head><body>{body}</body></html>
"""
    path = tmp_path / "book.epub"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("content.opf", opf)
        zf.writestr("style.css", css)
        zf.writestr("chapter.xhtml", chapter)
    return Book(str(path))


def br_styles(book: Book) -> list[str | None]:
    root = etree.fromstring(book.files["chapter.xhtml"])
    return [br.get("style") for br in root.iter("{*}br")]


def test_block_class_is_overridden_inline(tmp_path: Path) -> None:
    book = make_book(tmp_path, '<p><br class="calibre5 x"/></p><p>a<br/>b</p>', ".calibre5 { display: block; line-height: 1.2 }")

    assert fix_block_breaks(book, []) == 1
    assert br_styles(book) == ["display: inline", None]
    assert b".calibre5 { display: block" in book.files["style.css"]  # shared with <div>s: left alone


def test_type_selectors_media_queries_and_style_elements(tmp_path: Path) -> None:
    css = "@media screen { p > br { display: block } }"
    head = "<style>br.a { display: table }</style>"
    book = make_book(tmp_path, '<p>a<br/>b<br class="a"/>c</p>', css, head)

    assert fix_block_breaks(book, []) == 2
    assert br_styles(book) == ["display: inline", "display: inline"]


def test_inline_style_keeps_other_declarations(tmp_path: Path) -> None:
    book = make_book(tmp_path, '<p>a<br style="clear: both; display: block"/>b</p>')

    assert fix_block_breaks(book, []) == 1
    assert br_styles(book) == ["clear: both; display: inline"]


def test_leaves_alone_hidden_inline_and_pseudo_elements(tmp_path: Path) -> None:
    css = """
    .hide { display: none }
    .wide { display: block }
    .after::after, .before:before { display: block }
    """
    body = (
        '<p>a<br class="hide wide"/>b</p>'  # could be hidden on purpose
        '<p>a<br class="after before"/>b</p>'  # styles generated content, not the <br>
        '<p>a<br class="wide" style="display: inline"/>b</p>'  # already fixed
    )
    book = make_book(tmp_path, body, css)

    assert fix_block_breaks(book, []) == 0
    assert not book.changed


def test_fix_is_idempotent(tmp_path: Path) -> None:
    book = make_book(tmp_path, '<p><br class="calibre5"/></p>', ".calibre5 { display: block }")

    assert fix_block_breaks(book, []) == 1
    assert fix_block_breaks(book, []) == 0


def test_older_marker_is_reprocessed_and_updated(tmp_path: Path) -> None:
    book = make_book(tmp_path, "<p>a</p>", meta='<meta name="epuboost" content="1"/>')

    assert not book.has_marker()
    book.add_marker()
    assert book.has_marker()
    markers = [m for m in book.opf.iter("{*}meta") if m.get("name") == "epuboost"]
    assert [m.get("content") for m in markers] == [MARKER_VERSION]
