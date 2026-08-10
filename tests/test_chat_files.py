from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from manager.chat_files import (
    ChatFileRejected,
    validate_chat_upload,
    validate_upload_batch,
)


def zip_bytes(member: str) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(member, "content")
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "content", "mime_type"),
    [
        ("photo.jpg", b"\xff\xd8\xff\xe0image", "image/jpeg"),
        ("photo.png", b"\x89PNG\r\n\x1a\nimage", "image/png"),
        ("photo.webp", b"RIFF\x10\x00\x00\x00WEBPimage", "image/webp"),
        ("doc.pdf", b"%PDF-1.7\nbody", "application/pdf"),
        ("note.txt", "текст".encode(), "text/plain"),
        (
            "legacy.doc",
            bytes.fromhex("D0CF11E0A1B11AE1") + b"document",
            "application/msword",
        ),
        (
            "legacy.xls",
            bytes.fromhex("D0CF11E0A1B11AE1") + b"sheet",
            "application/vnd.ms-excel",
        ),
        (
            "doc.docx",
            zip_bytes("word/document.xml"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "sheet.xlsx",
            zip_bytes("xl/workbook.xml"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        ("archive.zip", zip_bytes("file.txt"), "application/zip"),
    ],
)
def test_allowed_uploads_require_matching_content(filename, content, mime_type):
    validated = validate_chat_upload(filename, content, 20 * 1024 * 1024)

    assert validated.filename == filename
    assert validated.mime_type == mime_type
    assert validated.size_bytes == len(content)
    assert len(validated.sha256) == 64


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("program.exe", b"MZ"),
        ("fake.pdf", b"not a pdf"),
        ("fake.docx", zip_bytes("xl/workbook.xml")),
        ("bad.txt", b"hello\x00world"),
        ("empty.txt", b""),
        ("unsafe.zip", zip_bytes("../escape.txt")),
    ],
)
def test_dangerous_or_mismatched_files_are_rejected(filename, content):
    with pytest.raises(ChatFileRejected):
        validate_chat_upload(filename, content, 20 * 1024 * 1024)


def test_batch_limit_and_file_size_are_enforced():
    with pytest.raises(ChatFileRejected, match="maximum 10"):
        validate_upload_batch([("a.txt", b"a")] * 11, 10, 20 * 1024 * 1024)
    with pytest.raises(ChatFileRejected, match="too large"):
        validate_chat_upload("a.txt", b"a" * 11, 10)
