# Project state

## What works

- CLI with the `clean`, `fonts`, `images`, `split` and `kepub` steps, `--analyze` and `--dry-run`
  (see the README).
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
in code blocks, a non-Latin title). `tests/test_cli.py` runs the installed `epuboost` command on
it and checks the result: originals untouched, valid zip, every TOC and chapter link still
resolving, `--kepub`, `--dry-run` and `--in-place`. Output is forced to cp1252, Windows' legacy
code page, so every platform checks that printing ✔, → and non-Latin titles doesn't crash.

## Known limitations

- Tests are end-to-end only; individual steps have no unit tests.
- Not published on PyPI; installing needs `git` and uv.
