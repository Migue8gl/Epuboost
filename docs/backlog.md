# Backlog

## High priority

- [ ] **Tests + CI matrix.** There are no tests yet. Add a small fixture EPUB and a smoke test
      (`--analyze`, a real optimize, `--kepub`), and run it in GitHub Actions on `ubuntu-latest`,
      `macos-latest` and `windows-latest` with Python 3.12 and 3.13. This is the only way to
      actually prove cross-platform support; so far Windows/macOS behaviour has only been checked
      by simulation on Linux.
- [ ] **Publish to PyPI**, so `uvx epuboost` / `pipx install epuboost` work without git or a clone.

## Medium priority

- [ ] **Standalone binaries** (PyInstaller or similar) for Windows, macOS and Linux, built in CI and
      attached to GitHub Releases, for users who don't want to install Python or uv.
- [ ] **README for Windows users**: PowerShell examples, how to install uv on each OS, and the
      `~` quoting note only applies to POSIX shells.

## Low priority

- [ ] Optional `Dockerfile` for running on a NAS or server. Not a good main distribution channel
      for a desktop CLI (needs Docker Desktop on Windows/macOS, bind mounts, root-owned output on
      Linux), so only as an extra.

## Done

- [x] Windows: books within two folders of a drive root (`D:\Books\book.epub`) were written to a
      drive-relative path instead of `--output`, which could overwrite the original.
- [x] Windows: redirecting output to a file or pipe crashed with `UnicodeEncodeError` (✔, → and
      non-Latin titles). stdout is now UTF-8 with `errors="replace"`.
- [x] Windows: default `--jobs` crashed on machines with more than 61 logical CPUs.
