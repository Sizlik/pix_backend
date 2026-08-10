import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from uuid import UUID
from zoneinfo import ZoneInfo

CHAT_HEADER = "ПЕРЕПИСКА С КЛИЕНТОМ — НЕ РЕДАКТИРОВАТЬ"
REPLY_MARKER = "ОТВЕТ МЕНЕДЖЕРА:"
REPLY_PROMPT = "ОТВЕТ МЕНЕДЖЕРА:\nНапишите ответ ниже этой строки и сохраните заказ."
HISTORY_FILENAME = "[PIX] История переписки.txt"
PRIOR_COMMENT_FILENAME = "[PIX] Комментарий до подключения чата.txt"
MAX_COMMENT_CHARS = 4096

_DISPLAY_TIMEZONE = ZoneInfo("Europe/Kaliningrad")
_TRUNCATION_NOTICE = f"Показаны последние сообщения. Полная история — в файле «{HISTORY_FILENAME}»."


class FileDisposition(StrEnum):
    SYSTEM = "system"
    CLIENT_MIRROR = "client_mirror"
    MANAGER_PUBLIC = "manager_public"
    INTERNAL = "internal"


class MalformedOrderChatComment(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    sender_kind: str
    created_at: datetime
    body: str
    filenames: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RenderedOrderComment:
    text: str
    full_history: str
    truncated: bool
    history_filename: str | None


def _display_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_DISPLAY_TIMEZONE)


def _entry_block(entry: TranscriptEntry) -> str:
    label = "Менеджер Pix Logistic" if entry.sender_kind == "manager" else "Клиент"
    timestamp = _display_datetime(entry.created_at).strftime("%d.%m.%Y %H:%M")
    lines = [f"[{timestamp}] {label}: {entry.body}"]
    if entry.filenames:
        lines.append("Файлы: " + ", ".join(entry.filenames))
    return "\n".join(lines)


def render_full_history(entries: list[TranscriptEntry]) -> str:
    blocks = [_entry_block(entry) for entry in entries]
    return "\n\n".join([CHAT_HEADER, *blocks]).rstrip()


def _compose_comment(blocks: list[str], notice: str | None = None) -> str:
    parts = [CHAT_HEADER]
    if notice:
        parts.append(notice)
    parts.extend(blocks)
    parts.append(REPLY_PROMPT)
    return "\n\n".join(parts)


def render_order_comment(
    entries: list[TranscriptEntry],
) -> RenderedOrderComment:
    blocks = [_entry_block(entry) for entry in entries]
    full_history = render_full_history(entries)
    complete = _compose_comment(blocks)
    if len(complete) <= MAX_COMMENT_CHARS:
        return RenderedOrderComment(
            text=complete,
            full_history=full_history,
            truncated=False,
            history_filename=None,
        )

    recent: list[str] = []
    for block in reversed(blocks):
        candidate = [block, *recent]
        if len(_compose_comment(candidate, _TRUNCATION_NOTICE)) > MAX_COMMENT_CHARS:
            break
        recent = candidate

    return RenderedOrderComment(
        text=_compose_comment(recent, _TRUNCATION_NOTICE),
        full_history=full_history,
        truncated=True,
        history_filename=HISTORY_FILENAME,
    )


def extract_manager_reply(description: str) -> str:
    if not description.startswith(CHAT_HEADER):
        raise MalformedOrderChatComment("order chat header is missing")
    before, separator, after = description.rpartition(REPLY_PROMPT)
    if not separator or not before.rstrip():
        raise MalformedOrderChatComment("manager reply prompt is missing")
    return after.strip()


def description_hash(description: str) -> str:
    return sha256(description.encode("utf-8")).hexdigest()


def _sanitize_visible_filename(filename: str) -> str:
    basename = PurePosixPath(filename.replace("\\", "/")).name
    basename = "".join(character for character in basename if unicodedata.category(character)[0] != "C").strip()
    basename = re.sub(r"\s+", " ", basename)
    return basename or "file"


def _split_extension(filename: str) -> tuple[str, str]:
    if "." not in filename or filename.startswith("."):
        return filename, ""
    stem, suffix = filename.rsplit(".", 1)
    return stem, f".{suffix}"


def _limit_filename(filename: str, max_chars: int = 255) -> str:
    if len(filename) <= max_chars:
        return filename
    stem, extension = _split_extension(filename)
    available = max(max_chars - len(extension), 1)
    return stem[:available].rstrip() + extension


def classify_moysklad_filename(filename: str) -> FileDisposition:
    if filename.startswith("[PIX]"):
        return FileDisposition.SYSTEM
    if filename.startswith("[ЧАТ-КЛИЕНТ]"):
        return FileDisposition.CLIENT_MIRROR
    if filename.startswith("[КЛИЕНТ]"):
        return FileDisposition.MANAGER_PUBLIC
    return FileDisposition.INTERNAL


def client_copy_filename(
    message_id: UUID,
    original_filename: str,
    ordinal: int,
) -> str:
    if ordinal < 1:
        raise ValueError("ordinal must be positive")
    safe_name = _sanitize_visible_filename(original_filename)
    stem, extension = _split_extension(safe_name)
    ordinal_suffix = f" ({ordinal})" if ordinal > 1 else ""
    prefix = f"[ЧАТ-КЛИЕНТ][{message_id}] "
    available = max(255 - len(prefix) - len(ordinal_suffix) - len(extension), 1)
    visible = f"{stem[:available].rstrip()}{ordinal_suffix}{extension}"
    return _limit_filename(prefix + visible)


def manager_public_filename(filename: str) -> str:
    prefix = "[КЛИЕНТ]"
    visible = filename[len(prefix) :] if filename.startswith(prefix) else filename
    return _limit_filename(_sanitize_visible_filename(visible))
