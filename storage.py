"""Upload handling for receipts, plans, voice notes, video and everything else.

Bytes go into the database, not the container filesystem. On a hosted plan the
local disk is wiped on every deploy and restart, which would mean a receipt that
existed yesterday and 404s today; a row in Postgres survives. Disk is still read
as a fallback so files saved before this change keep working.
"""

import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

# Extension -> MIME. Anything not listed here is refused, because an extension
# alone is not proof of content and a browser will happily render a .svg.
ALLOWED_EXTENSIONS = {
    # Images
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "heic": "image/heic",
    "heif": "image/heif",
    "avif": "image/avif",
    # Documents
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "csv": "text/csv",
    "txt": "text/plain",
    "rtf": "application/rtf",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    # Audio: WhatsApp voice notes land as .ogg or .m4a
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "opus": "audio/opus",
    "wav": "audio/wav",
    "amr": "audio/amr",
    "weba": "audio/webm",
    # Video
    "mp4": "video/mp4",
    "m4v": "video/mp4",
    "mov": "video/quicktime",
    "webm": "video/webm",
    "ogv": "video/ogg",
    "avi": "video/x-msvideo",
    "mkv": "video/x-matroska",
    "3gp": "video/3gpp",
    # Archives
    "zip": "application/zip",
}

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "heic", "heif", "avif"}
AUDIO_EXTENSIONS = {"mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "amr", "weba"}
VIDEO_EXTENSIONS = {"mp4", "m4v", "mov", "webm", "ogv", "avi", "mkv", "3gp"}

# One sentence a person can act on, listing what actually works.
ALLOWED_HINT = (
    "PDF, Word, Excel, PowerPoint, CSV or text; JPG, PNG, WebP, GIF or HEIC; "
    "MP3, M4A, OGG, WAV or AMR; MP4, MOV, WebM or 3GP; or a ZIP."
)

DEFAULT_MAX_BYTES = 25 * 1024 * 1024


class UploadError(ValueError):
    pass


def max_upload_bytes() -> int:
    return int(current_app.config.get("MAX_UPLOAD_BYTES") or DEFAULT_MAX_BYTES)


def upload_dir() -> Path:
    directory = Path(current_app.config["UPLOAD_FOLDER"])
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def upload_accept() -> str:
    """The `accept` attribute for a file input, built from the real allow-list."""
    return ",".join(f".{extension}" for extension in sorted(ALLOWED_EXTENSIONS))


def category_for(extension: str) -> str:
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    return "file"


def save_upload(file_storage, prefix: str = "doc") -> dict:
    """Read the upload into memory and hand the bytes back for storage.

    Nothing is written to disk: the caller puts the bytes in the database, which
    is the only place that survives a redeploy.
    """
    if not file_storage or not file_storage.filename:
        raise UploadError("Choose a file to upload.")

    safe_name = secure_filename(file_storage.filename)
    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""

    if extension not in ALLOWED_EXTENSIONS:
        raise UploadError(f"That file type is not supported. {ALLOWED_HINT}")

    data = file_storage.read()
    if not data:
        raise UploadError("That file looks empty. Try another one.")

    limit = max_upload_bytes()
    if len(data) > limit:
        raise UploadError(
            f"That file is {len(data) / (1024 * 1024):.1f} MB. The limit is "
            f"{limit / (1024 * 1024):.0f} MB ? split it or compress it first."
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    token = secrets.token_hex(5)
    prefix = "".join(char for char in prefix if char.isalnum() or char == "-")[:20] or "doc"
    filename = f"{prefix}-{stamp}-{token}.{extension}"

    return {
        "filename": filename,
        "original_name": file_storage.filename[:200],
        "mime_type": ALLOWED_EXTENSIONS[extension],
        "size": len(data),
        "extension": extension,
        "category": category_for(extension),
        "data": data,
    }


def read_attachment(attachment) -> bytes | None:
    """The bytes for a stored attachment, from the database or legacy disk."""
    data = attachment["data"] if "data" in attachment.keys() else None
    if data is not None:
        return bytes(data)

    path = upload_dir() / (attachment["filename"] or "")
    if path.is_file():
        return path.read_bytes()
    return None


def delete_upload(filename: str):
    """Removes a legacy on-disk file. Database rows go with the attachment row."""
    if not filename:
        return
    target = (upload_dir() / filename).resolve()
    if target.parent != upload_dir().resolve():
        return
    target.unlink(missing_ok=True)
