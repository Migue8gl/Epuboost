# epuboost

**Make your EPUBs fast on Kobo and other e-readers.**

Kobo e-readers open plain `.epub` files with Adobe RMSDK, which struggles with embedded fonts, huge
images and giant chapter files. The result is slow page turns, long loading screens and the
occasional crash. `epuboost` fixes the books themselves, so they stay plain `.epub` files that work
on any device.

```
✔ The Nature of Code - Shiffman, Daniel.epub: 9.9 MB → 5.2 MB
```

## What it does

`epuboost` runs a series of steps on each book. The first four run by default:

| Step | What it does |
|---|---|
| `clean` | Removes links to missing files (like Calibre's `page-template.xpgt`) and orphan manifest entries. Also turns `<br>` inside code blocks into plain newlines, which otherwise make Kobo skip or repeat pages. |
| `fonts` | Removes embedded fonts and `font-family` rules, so the book uses your e-reader's fonts. Code blocks stay `monospace`. |
| `images` | Fits images to the screen and recompresses them, fixes CMYK and progressive JPEGs, and converts WebP, AVIF, BMP and TIFF (which Kobo can't display) to JPEG or PNG. |
| `split` | Breaks chapters larger than 80 KB into smaller files, and updates every link and the table of contents to match. |
| `kepub` | **Opt-in with `--kepub`.** Writes a `.kepub.epub` with Kobo's sentence markers, so the book opens in Kobo's faster native reader and shows reading stats. |

Your original files are never modified. Each book is built in a temporary file, validated, and
only then moved into place, so if anything goes wrong nothing is written.

## Installation

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

**Option 1: install it as a command** (recommended). This makes `epuboost` available from any
folder:

```sh
uv tool install --python 3.12 git+https://github.com/Migue8gl/Epuboost
```

`--python 3.12` makes sure uv uses a supported Python even if your system default is older (uv
downloads it if needed).

**Option 2: run it from a clone.** Useful if you want to change the code:

```sh
git clone https://github.com/Migue8gl/Epuboost epuboost
cd epuboost
uv sync
```

If you use this option, put `uv run` in front of every command in this README
(`uv run epuboost --help` instead of `epuboost --help`).

## Quick start

```sh
epuboost ~/"Calibre Library" --analyze   # 1. See which books are slow (changes nothing)
epuboost ~/"Calibre Library"             # 2. Optimize them into ./output
```

Then copy the books from `./output` to your e-reader.

> **Note:** keep `~` outside the quotes (`~/"Calibre Library"`, not `"~/Calibre Library"`),
> otherwise your shell won't expand it to your home folder.

## Usage

### 1. Diagnose your library (optional)

`--analyze` reads your books and reports what makes each one slow, without changing anything:

```sh
epuboost ~/"Calibre Library" --analyze
```

```
  11.0 MB  synthetic.epub
           fonts: 2 embedded (1.0 MB, 2 oversized)
           chapters: 1 over 80 KB (largest 129 KB)
           images: 9.9 MB total, 2 larger than 1264x1680, 1 in formats Kobo can't show

2 books (16.2 MB): 2 need work (2 fonts, 1 chapters, 1 images), 0 look fine.
```

### 2. Optimize

Pass a whole library, an author's folder or a single book. Folders are searched recursively:

```sh
epuboost ~/"Calibre Library"                               # whole library
epuboost ~/"Calibre Library/Shiffman, Daniel"              # one author
epuboost ~/"Calibre Library/Author/Title (31)/book.epub"   # one book
```

To preview every change without writing anything, add `--dry-run --verbose`.

### 3. Collect the results

Optimized books are written to `./output` (change it with `-o`), using the same folder layout as
Calibre:

```
output/
└── Shiffman, Daniel/
    └── The Nature of Code (31)/
        └── The Nature of Code - Shiffman, Daniel.epub
```

Running `epuboost` again overwrites existing files in `./output`, so you never end up with
duplicates.

### 4. Copy them to your e-reader

Connect your Kobo by USB and drag the books onto it.

## Choosing steps

Use `--only` to run just some steps, or `--skip` to run every default step except some:

```sh
epuboost books/ --only images,split   # only resize images and split chapters
epuboost books/ --skip fonts          # keep the book's own typography
epuboost books/ --keep-fonts          # keep fonts, but shrink the big ones
epuboost books/ --kepub               # every default step, plus .kepub.epub output
```

## Options

| Option | Default | Description |
|---|---|---|
| `-a`, `--analyze` | | Only diagnose what makes each book slow |
| `-o`, `--output DIR` | `./output` | Folder for the optimized books |
| `--in-place` | | Overwrite the original files instead (can't be combined with `--kepub`) |
| `-n`, `--dry-run` | | Report what would change, write nothing |
| `-v`, `--verbose` | | Show every change made to each book |
| `-f`, `--force` | | Re-process books that were already optimized |
| `-j`, `--jobs N` | CPU count | Number of books processed in parallel |
| `--kepub` | | Also convert to `.kepub.epub` (changes the file format) |
| `--only STEPS` | | Run only these comma-separated steps (`clean,fonts,images,split,kepub`) |
| `--skip STEPS` | | Run every default step except these |
| `--keep-fonts` | | Subset embedded fonts instead of removing them |
| `--subset-font-kb N` | `150` | With `--keep-fonts`, subset fonts larger than N KB |
| `--image-size WxH` | `1264x1680` | Fit images inside this box |
| `--grayscale` | | Convert images to grayscale (for black-and-white e-readers) |
| `--jpeg-quality N` | `85` | JPEG quality when recompressing |
| `--split-kb N` | `80` | Split chapters larger than N KB |

**Screen sizes for `--image-size`:** Clara and Libra (all models) `1264x1680`, Sage `1440x1920`,
Elipsa `1404x1872`.

## Good to know

- **Highlights and reading position don't carry over.** Splitting chapters renames files inside
  the book, and your Kobo treats a `.kepub.epub` as a different book. Optimize books *before* you
  start reading them.
- With `--kepub`, copy only the `.kepub.epub` file to your Kobo, or the book will show up twice.
- Books whose fonts contain special symbols or non-Latin scripts may display incorrectly without
  them. Use `--skip fonts` or `--keep-fonts` for those.
- Hidden folders (like `.caltrash`), `.kepub.epub` files and Calibre's `.original_epub` backups
  are ignored.
- With `--in-place`, processed books get a `<meta name="epuboost">` marker and are skipped on later
  runs. Use `-f` to process them again.
- DRM-protected books can't be optimized. `--analyze` flags them.
