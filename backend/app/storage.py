"""Bill photo storage.

local:    files on the server disk (self-hosted Docker setup).
supabase: a private Supabase Storage bucket. Only the backend talks to Supabase (service role key);
          the browser fetches photos through /api, so a block on supabase.co in India would not
          affect staff as long as the backend runs outside India.
"""
import os
import uuid

import httpx

from .config import get_settings

ALLOWED = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf")
TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
         ".heic": "image/heic", ".pdf": "application/pdf"}


def _ext(filename: str, content_type: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED:
        ext = ".pdf" if content_type == "application/pdf" else ".jpg"
    return ext


def _sb_headers() -> dict:
    key = get_settings().supabase_service_role_key
    return {"Authorization": f"Bearer {key}", "apikey": key}


def _sb_base() -> str:
    s = get_settings()
    return f"{s.supabase_url.rstrip('/')}/storage/v1/object"


def save_bill_photo(bill_id: int, filename: str, content: bytes, content_type: str) -> str:
    path = f"bills/{bill_id}/{uuid.uuid4().hex}{_ext(filename, content_type)}"
    s = get_settings()
    if s.storage_backend == "supabase":
        r = httpx.post(
            f"{_sb_base()}/{s.storage_bucket}/{path}",
            headers=_sb_headers() | {"Content-Type": content_type or "application/octet-stream", "x-upsert": "true"},
            content=content,
            timeout=30,
        )
        r.raise_for_status()
        return path
    full = os.path.join(s.upload_dir, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(content)
    return path


def load_bill_photo(path: str) -> tuple[bytes, str]:
    """Returns (content, media type). Raises FileNotFoundError if missing."""
    s = get_settings()
    media = TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
    if s.storage_backend == "supabase":
        r = httpx.get(f"{_sb_base()}/authenticated/{s.storage_bucket}/{path}", headers=_sb_headers(), timeout=30)
        if r.status_code in (400, 404):
            raise FileNotFoundError(path)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", media)
    root = os.path.realpath(s.upload_dir)
    full = os.path.realpath(os.path.join(root, path))
    if not full.startswith(root + os.sep) or not os.path.exists(full):
        raise FileNotFoundError(path)
    with open(full, "rb") as f:
        return f.read(), media
