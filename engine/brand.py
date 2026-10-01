"""App name and logo, editable by the owner after deployment (issue #133).

The name comes from `app_settings.app_name`, else the APP_NAME env var, else "Theta Desk". The
logo is uploaded as PNG or WebP and always re-encoded to PNG here, so nothing the browser could run
(SVG, scripts, odd metadata) is ever served back. The favicon and touch icon are made from it.
With no logo uploaded, the app shows its built-in dial mark and /favicon.svg.
"""

import hashlib
import io
import json
import os

from PIL import Image

from . import db

DEFAULT_NAME = "Theta Desk"
MAX_NAME = 40
MAX_UPLOAD = 1024 * 1024
MAX_PIXELS = 4096 * 4096  # refuse decompression bombs before decoding
SIZES = {"logo": 512, "touch": 180, "favicon": 32}


class BrandError(ValueError):
    pass


def name() -> str:
    with db.tx() as c:
        v = c.value("SELECT value FROM app_settings WHERE key='app_name'")
    return v or os.environ.get("APP_NAME", "").strip() or DEFAULT_NAME


def info() -> dict:
    """What every page needs: the name and the current logo version (None = built-in mark)."""
    with db.tx() as c:
        sha = c.value("SELECT sha FROM brand_assets WHERE kind='logo'")
    return {"name": name(), "logo": sha}


def set_name(owner_id: int, value: str) -> str:
    value = " ".join(value.split())
    if not 1 <= len(value) <= MAX_NAME:
        raise BrandError(f"The name must be 1 to {MAX_NAME} characters")
    with db.tx() as c:
        c.run("INSERT INTO app_settings (key, value, updated_at, updated_by) VALUES ('app_name', CAST(:v AS jsonb), now(), :o) "
              "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now(), updated_by=:o",
              v=json.dumps(value), o=owner_id)
    return value


def _square_png(img: Image.Image, size: int) -> bytes:
    im = img.copy()
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    out = io.BytesIO()
    canvas.save(out, "PNG", optimize=True)
    return out.getvalue()


def set_logo(owner_id: int, data: bytes) -> str:
    """Stores a new logo plus its favicon and touch icon. Returns the logo's version."""
    if not data:
        raise BrandError("Choose an image to upload")
    if len(data) > MAX_UPLOAD:
        raise BrandError("The image must be 1 MB or smaller")
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")):
        raise BrandError("Upload a PNG or WebP image")
    try:
        with Image.open(io.BytesIO(data), formats=["PNG", "WEBP"]) as src:
            if src.width * src.height > MAX_PIXELS:
                raise BrandError("The image is too large; keep it under 4096×4096")
            img = src.convert("RGBA")  # first frame of an animated image
    except BrandError:
        raise
    except Exception as e:
        raise BrandError("That file isn't a readable PNG or WebP image") from e
    files = {kind: _square_png(img, size) for kind, size in SIZES.items()}
    with db.tx() as c:
        for kind, png in files.items():
            c.run("INSERT INTO brand_assets (kind, data, sha, updated_by) VALUES (:k, :d, :s, :o) "
                  "ON CONFLICT (kind) DO UPDATE SET data=EXCLUDED.data, sha=EXCLUDED.sha, updated_at=now(), updated_by=:o",
                  k=kind, d=png, s=hashlib.sha256(png).hexdigest()[:16], o=owner_id)
    return hashlib.sha256(files["logo"]).hexdigest()[:16]


def reset_logo() -> None:
    with db.tx() as c:
        c.run("DELETE FROM brand_assets")


def asset(kind: str) -> tuple[bytes, str] | None:
    with db.tx() as c:
        row = c.one("SELECT data, sha FROM brand_assets WHERE kind=:k", k=kind)
    return (bytes(row["data"]), row["sha"]) if row else None
