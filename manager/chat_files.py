from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    filename: str
    content: bytes
    mime_type: str
    size_bytes: int
    sha256: str


class ChatFileRejected(ValueError):
    pass


_OLE_HEADER = bytes.fromhex("D0CF11E0A1B11AE1")
_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xls": "application/vnd.ms-excel",
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".txt": "text/plain",
    ".zip": "application/zip",
}


def _extension(filename: str) -> str:
    basename = PurePosixPath(filename.replace("\\", "/")).name
    if "." not in basename:
        return ""
    return "." + basename.rsplit(".", 1)[1].lower()


def _safe_zip_members(content: bytes) -> tuple[str, ...]:
    try:
        with ZipFile(BytesIO(content)) as archive:
            names = tuple(item.filename for item in archive.infolist())
    except (BadZipFile, OSError) as error:
        raise ChatFileRejected("invalid ZIP container") from error

    if not names:
        raise ChatFileRejected("empty ZIP container")
    for name in names:
        normalized = name.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
            raise ChatFileRejected("unsafe ZIP member path")
    return names


def _validate_signature(extension: str, content: bytes) -> None:
    if extension in {".jpg", ".jpeg"}:
        valid = content.startswith(b"\xff\xd8\xff")
    elif extension == ".png":
        valid = content.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension == ".webp":
        valid = len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    elif extension == ".pdf":
        valid = content.startswith(b"%PDF-")
    elif extension in {".doc", ".xls"}:
        valid = content.startswith(_OLE_HEADER)
    elif extension in {".docx", ".xlsx", ".zip"}:
        members = _safe_zip_members(content)
        if extension == ".docx":
            valid = any(name.replace("\\", "/").startswith("word/") for name in members)
        elif extension == ".xlsx":
            valid = any(name.replace("\\", "/").startswith("xl/") for name in members)
        else:
            valid = True
    elif extension == ".txt":
        if b"\x00" in content:
            valid = False
        else:
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                valid = False
            else:
                valid = True
    else:
        valid = False

    if not valid:
        raise ChatFileRejected("file content does not match its extension")


def validate_chat_upload(
    filename: str,
    content: bytes,
    max_bytes: int,
) -> ValidatedUpload:
    if not content:
        raise ChatFileRejected("empty files are not allowed")
    if len(content) > max_bytes:
        raise ChatFileRejected("file is too large")
    extension = _extension(filename)
    mime_type = _MIME_TYPES.get(extension)
    if mime_type is None:
        raise ChatFileRejected("file type is not allowed")
    _validate_signature(extension, content)
    return ValidatedUpload(
        filename=PurePosixPath(filename.replace("\\", "/")).name,
        content=content,
        mime_type=mime_type,
        size_bytes=len(content),
        sha256=sha256(content).hexdigest(),
    )


def validate_upload_batch(
    files: list[tuple[str, bytes]],
    max_count: int,
    max_bytes: int,
) -> tuple[ValidatedUpload, ...]:
    if len(files) > max_count:
        raise ChatFileRejected(f"maximum {max_count} files are allowed")
    return tuple(validate_chat_upload(filename, content, max_bytes) for filename, content in files)
