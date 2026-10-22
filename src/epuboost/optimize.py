"""Optimize a single EPUB."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field

from .epub import Book
from .fonts import clean_font_faces, strip_fonts, subset_fonts
from .images import optimize_images
from .kepub import convert_to_kepub
from .split import fix_pre_breaks, remove_broken_links, split_large_files

STEPS = ("clean", "fonts", "images", "split", "kepub")
DEFAULT_STEPS = frozenset(STEPS) - {"kepub"}  # kepub changes the file format: opt-in


@dataclass
class Settings:
    steps: frozenset[str] = DEFAULT_STEPS
    keep_fonts: bool = False  # subset embedded fonts instead of removing them
    split_kb: int = 80
    subset_font_kb: int = 150
    image_size: tuple[int, int] = (1264, 1680)
    grayscale: bool = False
    jpeg_quality: int = 85
    dry_run: bool = False
    force: bool = False


@dataclass
class Result:
    path: str
    status: str  # "optimized", "unchanged", "skipped", "error"
    size_before: int = 0
    size_after: int = 0
    log: list[str] = field(default_factory=list)


def _copy_atomic(src: str, dest: str) -> None:
    directory = os.path.dirname(os.path.abspath(dest))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".epuboost-", suffix=".tmp", dir=directory)
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def optimize(path: str, dest: str | None, settings: Settings) -> Result:
    """Optimize `path`, writing to `dest` (None = in place).

    With a separate `dest`, books that need no changes are copied as-is so the
    output folder always holds every book.
    """
    result = Result(path, "unchanged", size_before=os.path.getsize(path))
    result.size_after = result.size_before
    try:
        book = Book(path)
        steps = settings.steps
        if book.has_marker() and not settings.force:
            result.status = "skipped"
        else:
            if "clean" in steps:
                remove_broken_links(book, result.log)
                fix_pre_breaks(book, result.log)
            if "fonts" in steps and not settings.keep_fonts:
                strip_fonts(book, result.log)
            elif "fonts" in steps:
                clean_font_faces(book, result.log)
                subset_fonts(book, settings.subset_font_kb * 1024, result.log)
            if "images" in steps:
                optimize_images(book, settings.image_size, settings.grayscale, settings.jpeg_quality, result.log)
            if "split" in steps:
                split_large_files(book, settings.split_kb * 1024, result.log)
            if book.changed:
                result.status = "optimized"
        if "kepub" in steps and dest is not None:
            convert_to_kepub(book, result.log)
            result.status = "optimized"
        if settings.dry_run:
            return result
        if result.status == "optimized":
            if not book.has_marker():
                book.add_marker()
            result.size_after = book.save(dest)
        elif dest is not None:
            _copy_atomic(path, dest)
    except Exception as exc:  # never leave a half-written book behind
        result.status = "error"
        result.log.append(f"{type(exc).__name__}: {exc}")
    return result
