"""Screenshot processing: resize, base64 encode, prepare for Gemini vision API."""

import base64
import io
from pathlib import Path

from PIL import Image


def resize_if_needed(image_bytes: bytes, max_size_kb: int = 500) -> bytes:
    """Resize image if it exceeds the max size threshold."""
    if len(image_bytes) <= max_size_kb * 1024:
        return image_bytes

    img = Image.open(io.BytesIO(image_bytes))
    scale = (max_size_kb * 1024 / len(image_bytes)) ** 0.5
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def load_screenshot(path: str | Path, max_size_kb: int = 500) -> dict:
    """Load a screenshot file, resize if needed, return dict for Gemini vision."""
    data = Path(path).read_bytes()
    data = resize_if_needed(data, max_size_kb)
    return {
        "base64": to_base64(data),
        "media_type": "image/png",
    }


def screenshot_bytes_to_vision(
    image_bytes: bytes, max_size_kb: int = 500
) -> dict:
    """Convert raw screenshot bytes to Gemini vision input dict."""
    data = resize_if_needed(image_bytes, max_size_kb)
    return {
        "base64": to_base64(data),
        "media_type": "image/png",
    }


def crop_element(
    image_bytes: bytes, x: int, y: int, w: int, h: int, padding: int = 20
) -> bytes:
    """Crop an element region from a full-page screenshot with optional padding."""
    img = Image.open(io.BytesIO(image_bytes))
    left = max(0, x - padding)
    top = max(0, y - padding)
    right = min(img.width, x + w + padding)
    bottom = min(img.height, y + h + padding)
    cropped = img.crop((left, top, right, bottom))
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()
