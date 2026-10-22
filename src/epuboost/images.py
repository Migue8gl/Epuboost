"""Image optimization: fit images to the screen, recompress them and convert
formats Adobe RMSDK can't render (WebP, AVIF, BMP, TIFF)."""

from __future__ import annotations

import io
import posixpath

from PIL import Image, ImageChops

from .epub import Book

NATIVE_FORMATS = {"JPEG", "PNG", "GIF"}
PNG_TO_JPEG_MIN = 200_000  # only consider turning PNGs this big into JPEGs
PNG_TO_JPEG_RATIO = 0.4  # ...and only if the JPEG is this much smaller (photos, not line art)

Image.MAX_IMAGE_PIXELS = None  # book images are trusted enough; avoid DecompressionBombError


def _has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA"):
        return img.getchannel("A").getextrema()[0] < 255
    return img.mode == "P" and "transparency" in img.info


def _is_gray(img: Image.Image) -> bool:
    if img.mode not in ("RGB", "RGBA"):
        return img.mode in ("L", "LA")
    r, g, b = img.split()[:3]
    return ImageChops.difference(r, g).getbbox() is None and ImageChops.difference(g, b).getbbox() is None


def _encode(img: Image.Image, fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        img = img.convert("L" if img.mode in ("L", "LA") else "RGB")
        img.save(buf, "JPEG", quality=quality, optimize=True, progressive=False)
    else:
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _optimize_image(data: bytes, box: tuple[int, int], grayscale: bool, quality: int) -> tuple[bytes, str] | None:
    """Returns (new data, "JPEG"|"PNG") or None to keep the original."""
    img = Image.open(io.BytesIO(data))
    fmt = img.format
    if fmt == "GIF":
        return None  # often animated or tiny; RMSDK handles them
    # Format conversions, CMYK and progressive JPEGs are worth fixing even if the file grows.
    must = fmt not in NATIVE_FORMATS or img.mode == "CMYK" or bool(img.info.get("progressive"))
    img.load()
    alpha = _has_alpha(img)
    palette = img.mode == "P"
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if alpha else "RGB")
    if img.width > box[0] or img.height > box[1]:
        img.thumbnail(box, Image.Resampling.LANCZOS)
        must = True
    if not alpha and img.mode == "RGBA":
        img = img.convert("RGB")
    if grayscale or _is_gray(img):
        img = img.convert("LA" if alpha else "L")

    if fmt == "JPEG" or (fmt not in NATIVE_FORMATS and not alpha):
        out, out_fmt = _encode(img, "JPEG", quality), "JPEG"
    else:
        if palette and img.mode in ("RGB", "RGBA"):
            img = img.quantize(256, method=Image.Quantize.FASTOCTREE)
        out, out_fmt = _encode(img, "PNG", quality), "PNG"
        if not alpha and len(out) >= PNG_TO_JPEG_MIN:
            jpeg = _encode(img, "JPEG", quality)
            if len(jpeg) < len(out) * PNG_TO_JPEG_RATIO:
                out, out_fmt = jpeg, "JPEG"
    if must or out_fmt != fmt or len(out) <= len(data) * 0.9:
        return out, out_fmt
    return None


def _new_path(book: Book, path: str, fmt: str) -> str:
    base, ext = posixpath.splitext(path)
    wanted = {"JPEG": (".jpg", ".jpeg"), "PNG": (".png",)}[fmt]
    if ext.lower() in wanted:
        return path
    candidate, n = base + wanted[0], 1
    while candidate in book.files:
        candidate, n = f"{base}_{n}{wanted[0]}", n + 1
    return candidate


def optimize_images(
    book: Book, box: tuple[int, int], grayscale: bool, quality: int, log: list[str]
) -> None:
    before = after = count = converted = 0
    for path in book.image_paths():
        data = book.files[path]
        try:
            result = _optimize_image(data, box, grayscale, quality)
        except Exception as exc:  # unreadable image: leave it alone
            log.append(f"could not optimize {path}: {exc}")
            continue
        if result is None:
            continue
        out, fmt = result
        new_path = _new_path(book, path, fmt)
        if new_path != path:
            book.rename(path, new_path, "image/jpeg" if fmt == "JPEG" else "image/png")
            converted += 1
        book.write(new_path, out)
        before, after, count = before + len(data), after + len(out), count + 1
    if count:
        extra = f", {converted} converted to JPEG/PNG" if converted else ""
        log.append(f"optimized {count} images{extra}: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB")
