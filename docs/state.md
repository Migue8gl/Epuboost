# Project state

## What works

- CLI with the `clean`, `fonts`, `images`, `split` and `kepub` steps, `--analyze` and `--dry-run`
  (see the README).
- `clean` fixes the two line break patterns known to make Kobo repeat or skip pages (`<br>` in
  `<pre>`, and `<br>` styled `display: block`). Findings and discarded approaches are in
  `kobo-pagination.md`.
- Installed with `uv tool install` or run from a clone with `uv sync`.

## Platforms

- Pure Python (3.12+). Every compiled dependency (lxml, Pillow, fonttools) ships wheels for
  Windows (x64, arm64), macOS (Intel, Apple Silicon) and Linux (glibc and musl, x64 and arm64),
  and uv downloads Python itself if needed, so nothing needs to be compiled on install.
- Not dockerized, on purpose: see `backlog.md`.
- CI (`.github/workflows/tests.yml`) runs the tests on Ubuntu, macOS (Apple Silicon) and Windows
  with Python 3.12 and 3.15, and all of them pass.

## Tests

```sh
uv run pytest
```

`tests/conftest.py` builds a synthetic EPUB with every problem the tool fixes (embedded font,
oversized WebP, a 200 KB chapter, a missing manifest entry, an Adobe page template link, `<br>`
in code blocks, a `display: block` `<br>` whose class a `<div>` shares, a non-Latin title). `tests/test_cli.py` runs the installed `epuboost` command on
it and checks the result: originals untouched, valid zip, every TOC and chapter link still
resolving, `--kepub`, `--dry-run` and `--in-place`. Output is forced to cp1252, Windows' legacy
code page, so every platform checks that printing ✔, → and non-Latin titles doesn't crash.

`tests/test_clean.py` unit-tests the block `<br>` fix (selector cases, `<style>`, `@media`, inline
styles, idempotence) and the versioned marker.

## Known limitations

- Only the clean step has unit tests; the other steps are tested end-to-end only.
- The pagination fixes can't be checked automatically: they need a Kobo reading the book with
  RMSDK.
- Not published on PyPI; installing needs `git` and uv.
