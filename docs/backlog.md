# Backlog

## High priority

- [ ] **Publish to PyPI**, so `uvx epuboost` / `pipx install epuboost` work without git or a clone.
- [ ] **Unit tests per step** (`--keep-fonts` subsetting with a real font, CMYK/progressive JPEGs,
      PNG with alpha, `--grayscale`, nested wrapper `<div>`s when splitting, DRM detection). The
      current suite is end-to-end only.

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

- [x] End-to-end tests (`tests/`) on a synthetic EPUB with every problem the tool fixes, run in
      GitHub Actions on Linux, macOS and Windows with Python 3.12 and 3.15. First run all green.
- [x] Windows: books within two folders of a drive root (`D:\Books\book.epub`) were written to a
      drive-relative path instead of `--output`, which could overwrite the original.
- [x] Windows: redirecting output to a file or pipe crashed with `UnicodeEncodeError` (✔, → and
      non-Latin titles). stdout is now UTF-8 with `errors="replace"`.
- [x] Windows: default `--jobs` crashed on machines with more than 61 logical CPUs.
