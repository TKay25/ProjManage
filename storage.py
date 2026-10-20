"""Upload handling for receipts and project documents."""

import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "heic": "image/heic",
    "heif": "image/heif",
    "pdf": "application/pdf",
}


class UploadError(ValueError):
    pass


def upload_dir() -> Path:
    directory = Path(current_app.config["UPLOAD_FOLDER"])
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def save_upload(file_storage, prefix: str = "doc") -> dict:
    if not file_storage or not file_storage.filename:
        raise UploadError("Choose a file to upload.")

    safe_name = secure_filename(file_storage.filename)
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""

    if extension not in ALLOWED_EXTENSIONS:
        raise UploadError("Upload a JPG, PNG, WebP or PDF file.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    token = secrets.token_hex(5)
    prefix = "".join(char for char in prefix if char.isalnum() or char == "-")[:20] or "doc"
    filename = f"{prefix}-{stamp}-{token}.{extension}"

    file_storage.save(upload_dir() / filename)
    size = (upload_dir() / filename).stat().st_size

    if size == 0:
        (upload_dir() / filename).unlink(missing_ok=True)
        raise UploadError("That file looks empty. Try another one.")

    return {
        "filename": filename,
        "original_name": file_storage.filename[:200],
        "mime_type": ALLOWED_EXTENSIONS[extension],
        "size": size,
    }


def delete_upload(filename: str):
    if not filename:
        return
    target = (upload_dir() / filename).resolve()
    if target.parent != upload_dir().resolve():
        return
    target.unlink(missing_ok=True)
