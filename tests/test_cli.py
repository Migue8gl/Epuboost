"""End-to-end tests through the installed `epuboost` command, as users run it."""

from __future__ import annotations

import hashlib
import io
import ntpath
import os
import posixpath
import shutil
import subprocess
import types
import zipfile
from pathlib import Path
from urllib.parse import unquote

from lxml import etree
from PIL import Image

import epuboost
from conftest import AUTHOR, BOOK_DIR, BOOK_FILE, TITLE

OPF_NS = "{http://www.idpf.org/2007/opf}"


def run(*args: str | Path, cwd: Path) -> str:
    exe = shutil.which("epuboost")
    assert exe, "the epuboost command is not installed; run the tests with `uv run pytest`"
    # Pipes use the legacy code page on Windows (cp1252 on most western systems): force it
    # everywhere, so every platform checks that ✔, → and non-Latin titles don't crash.
    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    proc = subprocess.run([exe, *map(str, args)], cwd=cwd, env=env, capture_output=True, timeout=300)
    out = proc.stdout.decode("utf-8")
    assert proc.returncode == 0, out + proc.stderr.decode("utf-8", "replace")
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target(doc: str, href: str) -> tuple[str, str]:
    """Archive path and fragment an href in archive file `doc` points to."""
    path, _, frag = href.partition("#")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(doc), unquote(path))) if path else doc
    return resolved, frag


def test_analyze_reports_every_problem(library: Path, tmp_path: Path) -> None:
    out = run(library, "--analyze", cwd=tmp_path)

    assert f"{TITLE} - {AUTHOR}.epub" in out
    assert "fonts: 1 embedded" in out
    assert "chapters: 1 over 80 KB" in out
    assert "larger than 1264x1680" in out and "in formats Kobo can't show" in out
    assert "broken: 1 manifest entries point to missing files" in out
    assert "1 need work" in out
    assert not (tmp_path / "output").exists()


def test_optimize_fixes_book(library: Path, tmp_path: Path) -> None:
    original = library / AUTHOR / BOOK_DIR / BOOK_FILE
    checksum = sha256(original)

    out = run(library, "-o", tmp_path / "out", cwd=tmp_path)

    assert f"✔ {BOOK_FILE}:" in out and "→" in out
    assert "1 optimized" in out and "0 errors" in out
    assert sha256(original) == checksum, "the original book was modified"

    dest = tmp_path / "out" / AUTHOR / BOOK_DIR / BOOK_FILE
    with zipfile.ZipFile(dest) as zf:
        assert zf.testzip() is None
        first = zf.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        files = {name: zf.read(name) for name in zf.namelist()}

    opf = etree.fromstring(files["OEBPS/content.opf"])
    assert any(m.get("name") == "epuboost" for m in opf.iter(f"{OPF_NS}meta"))
    items = {i.get("id"): i for i in opf.iter(f"{OPF_NS}item")}
    for item in items.values():
        assert f"OEBPS/{unquote(item.get('href'))}" in files, f"manifest points to missing {item.get('href')}"
    spine = [ref.get("idref") for ref in opf.iter(f"{OPF_NS}itemref")]
    assert all(idref in items for idref in spine)

    # clean: missing manifest entry, Adobe page template link and <br> in code blocks are gone
    assert "gone" not in items
    assert b"page-template.xpgt" not in files["OEBPS/text/chapter1.xhtml"]
    pre = etree.fromstring(files["OEBPS/text/chapter2.xhtml"]).find(".//{*}pre")
    assert pre.find("{*}br") is None and pre.text == "first line\nsecond line\nthird line"

    # fonts: font files and families removed, code stays monospace
    assert not any(name.endswith(".ttf") for name in files)
    css = files["OEBPS/style.css"].decode("utf-8")
    assert "@font-face" not in css and "Fancy" not in css
    assert "font-family: monospace" in css
    assert b"Fancy" not in files["OEBPS/text/chapter1.xhtml"]

    # images: WebP converted to a JPEG that fits the screen, and references updated
    assert "OEBPS/images/cover.webp" not in files
    cover = Image.open(io.BytesIO(files["OEBPS/images/cover.jpg"]))
    assert cover.format == "JPEG" and cover.width <= 1264 and cover.height <= 1680
    assert items["cover"].get("media-type") == "image/jpeg"
    assert b'src="../images/cover.jpg"' in files["OEBPS/text/chapter1.xhtml"]

    # split: chapter 1 is now several files, all in the spine, all small
    chunks = sorted(n for n in files if n.startswith("OEBPS/text/chapter1"))
    assert len(chunks) > 1
    hrefs = {f"OEBPS/{unquote(items[idref].get('href'))}" for idref in spine}
    assert set(chunks) <= hrefs
    assert all(len(files[c]) <= 100 * 1024 for c in chunks)

    # every link in the TOC and the chapters still lands on an existing file and id
    ids = {
        name: {el.get("id") for el in etree.fromstring(data).iter() if el.get("id")}
        for name, data in files.items() if name.endswith((".xhtml", ".ncx"))
    }
    links = [("OEBPS/toc.ncx", el.get("src")) for el in etree.fromstring(files["OEBPS/toc.ncx"]).iter("{*}content")]
    for doc in (n for n in files if n.endswith(".xhtml")):
        links += [(doc, a.get("href")) for a in etree.fromstring(files[doc]).iter("{*}a") if a.get("href")]
    assert len(links) >= 9
    for doc, href in links:
        path, frag = target(doc, href)
        assert path in files, f"{doc}: {href} points to a missing file"
        assert not frag or frag in ids[path], f"{doc}: {href} points to a missing id"


def test_kepub_writes_kepub_only(library: Path, tmp_path: Path) -> None:
    run(library, "-o", tmp_path / "out", "--kepub", cwd=tmp_path)

    folder = tmp_path / "out" / AUTHOR / BOOK_DIR
    assert [p.name for p in folder.iterdir()] == [f"{TITLE} - {AUTHOR}.kepub.epub"]
    with zipfile.ZipFile(next(folder.iterdir())) as zf:
        assert b'class="koboSpan"' in zf.read("OEBPS/text/chapter2.xhtml")


def test_dry_run_writes_nothing(library: Path, tmp_path: Path) -> None:
    original = library / AUTHOR / BOOK_DIR / BOOK_FILE
    checksum = sha256(original)

    out = run(library, "--dry-run", "-o", tmp_path / "out", cwd=tmp_path)

    assert "Dry run" in out and "1 optimized" in out
    assert not (tmp_path / "out").exists()
    assert sha256(original) == checksum


def test_in_place_marks_books_done(library: Path, tmp_path: Path) -> None:
    original = library / AUTHOR / BOOK_DIR / BOOK_FILE
    checksum = sha256(original)

    assert "1 optimized" in run(library, "--in-place", cwd=tmp_path)
    assert sha256(original) != checksum
    assert "1 done previously" in run(library, "--in-place", cwd=tmp_path)


def test_library_path_drops_windows_drive(monkeypatch) -> None:
    # Joining "D:" with the rest made a drive-relative path that escaped --output.
    monkeypatch.setattr(epuboost, "os", types.SimpleNamespace(path=ntpath, sep=ntpath.sep))

    assert epuboost.library_path(r"D:\Books\book.epub") == r"Books\book.epub"
    assert epuboost.library_path(r"D:\book.epub") == "book.epub"
    assert epuboost.library_path(r"\\nas\share\Author\Title (1)\book.epub") == r"Author\Title (1)\book.epub"
    assert epuboost.library_path(r"C:\Library\Author\Title (1)\book.epub", kepub=True) == r"Author\Title (1)\book.kepub.epub"
