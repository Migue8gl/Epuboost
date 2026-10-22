"""Read-only diagnosis of what makes a book slow on Kobo."""

from __future__ import annotations

import io
import os
import posixpath
from dataclasses import dataclass, field

from PIL import Image

from .epub import FONT_EXTS, Book
from .images import NATIVE_FORMATS
from .optimize import Settings


@dataclass
class Analysis:
    path: str
    size: int = 0
    issues: dict[str, str] = field(default_factory=dict)  # category -> description
    error: str | None = None


def _mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB"


def analyze(path: str, settings: Settings) -> Analysis:
    a = Analysis(path, os.path.getsize(path))
    try:
        book = Book(path)
    except Exception as exc:
        a.error = f"{type(exc).__name__}: {exc}"
        return a

    xhtml = book.xhtml_paths()
    if any(p in book.encrypted for p in xhtml):
        a.issues["drm"] = "DRM-protected, can't be optimized"
        return a

    fonts = [p for p in book.files if posixpath.splitext(p)[1].lower() in FONT_EXTS]
    if fonts:
        size = sum(len(book.files[p]) for p in fonts)
        big = sum(len(book.files[p]) > settings.subset_font_kb * 1024 for p in fonts)
        detail = f", {big} oversized" if big else ""
        a.issues["fonts"] = f"{len(fonts)} embedded ({_mb(size)}{detail})"

    big_chapters = [len(book.files[p]) for p in xhtml if len(book.files[p]) > settings.split_kb * 1024]
    if big_chapters:
        a.issues["chapters"] = (
            f"{len(big_chapters)} over {settings.split_kb} KB (largest {max(big_chapters) // 1024} KB)"
        )

    oversized = unsupported = slow = 0
    image_bytes = 0
    box = settings.image_size
    for p in book.image_paths():
        image_bytes += len(book.files[p])
        try:
            img = Image.open(io.BytesIO(book.files[p]))  # reads the header only
        except Exception:
            continue
        oversized += img.width > box[0] or img.height > box[1]
        unsupported += img.format not in NATIVE_FORMATS
        slow += img.mode == "CMYK" or bool(img.info.get("progressive"))
    problems = [
        f"{n} {what}" for n, what in (
            (oversized, f"larger than {box[0]}x{box[1]}"),
            (unsupported, "in formats Kobo can't show"),
            (slow, "CMYK/progressive"),
        ) if n
    ]
    if problems:
        a.issues["images"] = f"{_mb(image_bytes)} total, " + ", ".join(problems)

    missing = [i.get("href") for i in book.items() if book.item_path(i) not in book.files]
    if missing:
        a.issues["broken"] = f"{len(missing)} manifest entries point to missing files"
    return a


def report(analyses: list[Analysis], verbose: bool) -> None:
    flagged = [a for a in analyses if a.issues or a.error]
    flagged.sort(key=lambda a: (len(a.issues), a.size), reverse=True)
    for a in flagged:
        print(f"{_mb(a.size):>9}  {os.path.basename(a.path)}")
        if a.error:
            print(f"{'':11}✘ can't read: {a.error}")
        for category, text in a.issues.items():
            print(f"{'':11}{category}: {text}")
    if verbose:
        for a in analyses:
            if not (a.issues or a.error):
                print(f"{_mb(a.size):>9}  {os.path.basename(a.path)}  ✔")

    counts: dict[str, int] = {}
    for a in analyses:
        for category in a.issues:
            counts[category] = counts.get(category, 0) + 1
    breakdown = ", ".join(f"{n} {c}" for c, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    total = sum(a.size for a in analyses)
    print(
        f"\n{len(analyses)} books ({_mb(total)}): {len(flagged)} need work"
        + (f" ({breakdown})" if breakdown else "")
        + f", {len(analyses) - len(flagged)} look fine."
    )
