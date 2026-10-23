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
- Tested only on Linux. Windows-specific path and console issues were fixed and checked by
  simulation (`ntpath`, non-UTF-8 stdout), not on a real Windows or macOS machine.

## Known limitations

- No automated tests or CI.
- Not published on PyPI; installing needs `git` and uv.
