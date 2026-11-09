"""Download, validate, resize, and hash cover images."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) prosopon-coverfetch/0.1"

MAGIC = {
    b"\xff\xd8\xff": ".jpg",
    b"\x89PNG\r\n\x1a\n": ".png",
    b"RIFF": ".webp",
    b"GIF8": ".gif",
}


def _opener(proxy: str | None):
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)


def download(url: str, dest: str, referer: str | None = None, proxy: str | None = None, timeout: int = 40) -> str:
    """Download an image and return its path. Raises on non-image/too-small."""
    if not url:
        raise ValueError("empty cover url")
    headers = {"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with _opener(proxy).open(req, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < 3000:
        raise ValueError(f"image too small ({len(data)} bytes): {url}")
    head = data[:12]
    if not any(head.startswith(m) for m in MAGIC):
        raise ValueError(f"not an image (magic={head[:8]!r}): {url}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def dimensions(path: str) -> tuple[int | None, int | None]:
    try:
        out = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
            capture_output=True, text=True, timeout=20,
        ).stdout
        w = h = None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("pixelWidth:"):
                w = int(line.split(":")[1])
            elif line.startswith("pixelHeight:"):
                h = int(line.split(":")[1])
        return w, h
    except Exception:
        return None, None


def to_webp(src: str, dest: str, max_width: int = 480) -> str:
    """Resize to max_width and encode WebP. Falls back to JPEG if cwebp is absent."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cwebp = shutil.which("cwebp")
    if cwebp:
        try:
            subprocess.run(
                [cwebp, "-quiet", "-q", "82", "-resize", str(max_width), "0", src, "-o", dest],
                check=True, capture_output=True, timeout=60,
            )
            if os.path.getsize(dest) > 1000:
                return dest
        except Exception:
            pass
    # macOS fallback: sips can resize/convert to jpeg
    jpg = os.path.splitext(dest)[0] + ".jpg"
    sips = shutil.which("sips")
    if sips:
        try:
            subprocess.run(
                [sips, "-Z", str(max_width), "-s", "format", "jpeg", src, "--out", jpg],
                check=True, capture_output=True, timeout=60,
            )
            return jpg
        except Exception:
            pass
    # Last resort: copy the raw file; the caller records the actual path.
    ext = os.path.splitext(src)[1] or ".jpg"
    out = os.path.splitext(dest)[0] + ext
    shutil.copyfile(src, out)
    return out
