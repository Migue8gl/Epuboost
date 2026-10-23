"""Make EPUBs fast on Kobo (Adobe RMSDK) e-readers."""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor

from .analyze import analyze, report as report_analysis
from .optimize import DEFAULT_STEPS, STEPS, Result, Settings, optimize


def library_path(epub: str, kepub: bool = False) -> str:
    """Calibre-style relative path: Author/Title (id)/book.epub (or .kepub.epub)."""
    # Drop the drive first: on Windows, joining "D:" with the rest yields a drive-relative path.
    parts = os.path.splitdrive(os.path.abspath(epub))[1].split(os.sep)
    path = os.path.join(*parts[-3:])
    return os.path.splitext(path)[0] + ".kepub.epub" if kepub else path


def step_list(value: str) -> frozenset[str]:
    steps = frozenset(s.strip() for s in value.split(",") if s.strip())
    if unknown := steps - set(STEPS):
        raise argparse.ArgumentTypeError(f"unknown step(s): {', '.join(sorted(unknown))} (choose from {', '.join(STEPS)})")
    return steps


def size(value: str) -> tuple[int, int]:
    try:
        w, h = (int(n) for n in value.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("expected WIDTHxHEIGHT, e.g. 1264x1680")
    return w, h


def find_epubs(paths: list[str], exclude: str | None = None) -> list[str]:
    found = []
    for path in paths:
        if os.path.isfile(path):
            found.append(path)
            continue
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(
                d for d in dirs
                if not d.startswith(".")  # skips .caltrash
                and os.path.abspath(os.path.join(root, d)) != exclude
            )
            for name in sorted(files):
                lower = name.lower()
                if lower.endswith(".epub") and not lower.endswith(".kepub.epub"):
                    found.append(os.path.join(root, name))
    return found


def _mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB"


def report(r: Result, verbose: bool) -> None:
    name = os.path.basename(r.path)
    if r.status == "optimized":
        print(f"✔ {name}: {_mb(r.size_before)} → {_mb(r.size_after)}")
    elif r.status == "error":
        print(f"✘ {name}: ERROR, file left untouched")
    elif verbose:
        print(f"· {name}: {r.status}")
    if verbose or r.status == "error":
        for line in r.log:
            print(f"    {line}")


def main() -> None:
    # Windows writes redirected output in its legacy code page, which can't encode ✔, → or many titles.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="epuboost",
        description="Make EPUBs fast on Kobo. By default these steps run: "
        "clean (broken links/manifest), fonts (remove embedded fonts so Kobo's are used), "
        "images (fit to screen, recompress, convert WebP/AVIF) and split (break up huge chapters). "
        "With --kepub, books are also converted to .kepub.epub for Kobo's fast engine.",
    )
    parser.add_argument("paths", nargs="+", help="EPUB files or folders (searched recursively)")
    parser.add_argument("-o", "--output", default="output",
                        help="folder for the optimized books, as Author/Title/book.epub (default: ./output)")
    parser.add_argument("--in-place", action="store_true",
                        help="overwrite the original files instead of using --output")
    parser.add_argument("-a", "--analyze", action="store_true", help="only diagnose what makes each book slow")
    parser.add_argument("-n", "--dry-run", action="store_true", help="only report, don't write anything")
    parser.add_argument("-f", "--force", action="store_true", help="re-process books already optimized")
    parser.add_argument("-v", "--verbose", action="store_true", help="show what was done to each book")
    # None lets ProcessPoolExecutor pick the CPU count, capped at Windows' limit of 61 workers.
    parser.add_argument("-j", "--jobs", type=int, default=None, help="parallel workers (default: CPU count)")

    steps = parser.add_argument_group("choosing steps")
    choice = steps.add_mutually_exclusive_group()
    choice.add_argument("--only", type=step_list, metavar="STEPS",
                        help=f"run only these comma-separated steps ({', '.join(STEPS)})")
    choice.add_argument("--skip", type=step_list, metavar="STEPS", default=frozenset(),
                        help="run every default step except these")
    steps.add_argument("--kepub", action="store_true",
                       help="also convert to .kepub.epub for Kobo's fast engine (changes the file format)")

    tuning = parser.add_argument_group("tuning")
    tuning.add_argument("--keep-fonts", action="store_true",
                        help="keep embedded fonts, just subset the big ones and drop unused ones")
    tuning.add_argument("--subset-font-kb", type=int, default=150, help="with --keep-fonts, subset fonts larger than this (default: 150)")
    tuning.add_argument("--image-size", type=size, default=(1264, 1680), metavar="WxH",
                        help="fit images inside this box (default: 1264x1680)")
    tuning.add_argument("--grayscale", action="store_true", help="convert all images to grayscale (black & white Kobos)")
    tuning.add_argument("--jpeg-quality", type=int, default=85, help="JPEG quality when recompressing (default: 85)")
    tuning.add_argument("--split-kb", type=int, default=80, help="split chapters larger than this (default: 80)")
    args = parser.parse_args()

    selected = (args.only or DEFAULT_STEPS - args.skip) | ({"kepub"} if args.kepub else set())
    if args.in_place and "kepub" in selected:
        parser.error("kepub can't be written in place; use --output")
    kepub = "kepub" in selected
    settings = Settings(
        steps=selected,
        keep_fonts=args.keep_fonts,
        split_kb=args.split_kb,
        subset_font_kb=args.subset_font_kb,
        image_size=args.image_size,
        grayscale=args.grayscale,
        jpeg_quality=args.jpeg_quality,
        dry_run=args.dry_run,
        force=args.force,
    )

    output = None if args.in_place else os.path.abspath(args.output)
    epubs = find_epubs(args.paths, exclude=output)
    if not epubs:
        sys.exit("No .epub files found.")

    if args.analyze:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            analyses = list(pool.map(analyze, epubs, [settings] * len(epubs)))
        report_analysis(analyses, args.verbose)
        return

    dests = [None if output is None else os.path.join(output, library_path(e, kepub)) for e in epubs]
    if args.dry_run:
        print("Dry run: nothing will be written.")
    elif output:
        print(f"Writing to {output}")
    print(f"Steps: {', '.join(s for s in STEPS if s in selected)}")

    counts = {"optimized": 0, "unchanged": 0, "skipped": 0, "error": 0}
    saved = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for r in pool.map(optimize, epubs, dests, [settings] * len(epubs)):
            report(r, args.verbose)
            counts[r.status] += 1
            saved += r.size_before - r.size_after
    print(
        f"\n{len(epubs)} books: {counts['optimized']} optimized, {counts['unchanged']} already fine, "
        f"{counts['skipped']} done previously, {counts['error']} errors. Saved {_mb(saved)}."
    )
    sys.exit(1 if counts["error"] else 0)
