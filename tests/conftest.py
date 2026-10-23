"""A small synthetic EPUB with every problem epuboost fixes."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

AUTHOR = "Author Name"
# Non-Latin on purpose: the title must survive consoles and pipes in legacy code pages.
TITLE = "Libro 東京"
BOOK_DIR = f"{TITLE} (1)"
BOOK_FILE = f"{TITLE} - {AUTHOR}.epub"

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:00000000-0000-0000-0000-000000000000</dc:identifier>
    <dc:title>Libro 東京</dc:title>
    <dc:creator>Author Name</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="font" href="fonts/fancy.ttf" media-type="font/ttf"/>
    <item id="cover" href="images/cover.webp" media-type="image/webp"/>
    <item id="ch1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="text/chapter2.xhtml" media-type="application/xhtml+xml"/>
    <item id="gone" href="text/missing.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="ch1"/>
    <itemref idref="ch2"/>
    <itemref idref="gone"/>
  </spine>
</package>
"""

NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body>
  <nav epub:type="toc"><ol>
    <li><a href="text/chapter1.xhtml#s1">One</a></li>
    <li><a href="text/chapter1.xhtml#s2">Two</a></li>
    <li><a href="text/chapter1.xhtml#s3">Three</a></li>
    <li><a href="text/chapter2.xhtml">Four</a></li>
  </ol></nav>
</body>
</html>
"""

NCX = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="urn:uuid:00000000-0000-0000-0000-000000000000"/></head>
  <docTitle><text>Libro 東京</text></docTitle>
  <navMap>
    <navPoint id="p1" playOrder="1"><navLabel><text>One</text></navLabel><content src="text/chapter1.xhtml#s1"/></navPoint>
    <navPoint id="p2" playOrder="2"><navLabel><text>Two</text></navLabel><content src="text/chapter1.xhtml#s2"/></navPoint>
    <navPoint id="p3" playOrder="3"><navLabel><text>Three</text></navLabel><content src="text/chapter1.xhtml#s3"/></navPoint>
    <navPoint id="p4" playOrder="4"><navLabel><text>Four</text></navLabel><content src="text/chapter2.xhtml"/></navPoint>
  </navMap>
</ncx>
"""

CSS = """@font-face { font-family: "Fancy"; src: url(fonts/fancy.ttf); }
body { font-family: "Fancy", serif; margin: 0 }
pre { font-family: "Fancy Mono", monospace }
"""

PARAGRAPH = "<p>" + "This sentence pads the chapter so that it has to be split. " * 15 + "</p>\n"


def _chapter1() -> str:
    # ~210 KB in three sections: well over the default 80 KB split limit.
    sections = "".join(
        f'<h2 id="s{n}">Section {n}</h2>\n' + PARAGRAPH * 80 for n in (1, 2, 3)
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>Chapter 1</title>
  <link rel="stylesheet" type="text/css" href="../style.css"/>
  <link rel="stylesheet" type="application/vnd.adobe-page-template+xml" href="../page-template.xpgt"/>
</head>
<body>
<div><img src="../images/cover.webp" alt="Cover"/></div>
<p style="font-family: Fancy; text-indent: 1em">Opening line&nbsp;with an HTML entity.</p>
{sections}</body>
</html>
"""


CHAPTER2 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter 2</title><link rel="stylesheet" type="text/css" href="../style.css"/></head>
<body>
<p>Back to <a href="chapter1.xhtml#s3">section three</a>.</p>
<pre>
first line<br/>
second line<br/>
third line</pre>
</body>
</html>
"""


def _cover() -> bytes:
    # Bigger than the default 1264x1680 box, and WebP, which Kobo can't display.
    img = Image.linear_gradient("L").resize((2000, 3000)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=80)
    return buf.getvalue()


def write_epub(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        files = {
            "META-INF/container.xml": CONTAINER,
            "OEBPS/content.opf": OPF,
            "OEBPS/nav.xhtml": NAV,
            "OEBPS/toc.ncx": NCX,
            "OEBPS/style.css": CSS,
            "OEBPS/fonts/fancy.ttf": b"\x00\x01\x00\x00" + bytes(200_000),
            "OEBPS/images/cover.webp": _cover(),
            "OEBPS/text/chapter1.xhtml": _chapter1(),
            "OEBPS/text/chapter2.xhtml": CHAPTER2,
        }
        for name, data in files.items():
            zf.writestr(name, data, zipfile.ZIP_DEFLATED)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A Calibre-style library holding one problematic book."""
    root = tmp_path / "Calibre Library"
    write_epub(root / AUTHOR / BOOK_DIR / BOOK_FILE)
    return root
