import logging
from hashlib import sha256
from uuid import UUID, uuid4

from db.moysklad_order_chat_repository import MoySkladUpload
from db.order_chat_repository import (
    NewAttachment,
    NewMoySkladOrderFile,
)
from manager.chat_files import ChatFileRejected, validate_upload_batch
from manager.order_chat_format import (
    CHAT_HEADER,
    HISTORY_FILENAME,
    PRIOR_COMMENT_FILENAME,
    FileDisposition,
    MalformedOrderChatComment,
    TranscriptEntry,
    classify_moysklad_filename,
    client_copy_filename,
    description_hash,
    extract_manager_reply,
    manager_public_filename,
    render_order_comment,
)

logger = logging.getLogger(__name__)


class MoySkladOrderChatSynchronizer:
    def __init__(
        self,
        *,
        repository,
        moysklad,
        storage,
        attachment_max_count: int = 10,
        attachment_max_bytes: int = 20 * 1024 * 1024,
        realtime=None,
        notification_manager=None,
    ):
        self._repository = repository
        self._moysklad = moysklad
        self._storage = storage
        self._attachment_max_count = attachment_max_count
        self._attachment_max_bytes = attachment_max_bytes
        self._realtime = realtime
        self._notification_manager = notification_manager

    async def process_moysklad_update(self, event) -> None:
        order_id = event.order_id
        state = await self._repository.get_state(order_id)
        if state is None or not state.initialized:
            return
        order = await self._moysklad.get_order(order_id)
        client = await self._repository.get_state_client(order_id)
        if client is None or not self._owned_by_client(order, client):
            return

        description = order.get("description") or ""
        identity = str(event.payload.get("audit_href") or event.payload.get("request_id") or event.id)
        try:
            reply = extract_manager_reply(description)
        except MalformedOrderChatComment:
            await self._projection_error(order_id, "malformed_comment", identity)
            await self.sync_order(order_id)
            return

        current_files = await self._moysklad.list_files(order_id)
        known = await self._repository.list_moysklad_files(order_id)
        known_ids = {item.moysklad_file_id for item in known}
        unseen = [item for item in current_files if item.id not in known_ids]
        public_files = [
            item for item in unseen if classify_moysklad_filename(item.filename) is FileDisposition.MANAGER_PUBLIC
        ]
        nonpublic_records = tuple(
            NewMoySkladOrderFile(
                order_id=order_id,
                moysklad_file_id=item.id,
                filename=item.filename,
                disposition=classify_moysklad_filename(item.filename).value,
            )
            for item in unseen
            if classify_moysklad_filename(item.filename) is not FileDisposition.MANAGER_PUBLIC
        )
        await self._repository.record_moysklad_files(nonpublic_records)

        if len(public_files) > self._attachment_max_count:
            await self._projection_error(order_id, "manager_file_count", identity)
            return

        public_ids = sorted(str(item.id) for item in public_files)
        external_key = sha256("|".join([str(order_id), identity, reply, *public_ids]).encode("utf-8")).hexdigest()
        if await self._repository.get_message_by_external_key(external_key):
            await self.sync_order(order_id)
            return

        if not reply and not public_files:
            await self.sync_order(order_id)
            return

        downloaded = []
        for item in public_files:
            downloaded.append(
                (
                    manager_public_filename(item.filename),
                    await self._moysklad.download_file(item.download_href),
                )
            )
        try:
            validated = validate_upload_batch(
                downloaded,
                self._attachment_max_count,
                self._attachment_max_bytes,
            )
        except (ChatFileRejected, ValueError):
            await self._projection_error(order_id, "manager_file_invalid", identity)
            return

        message_id = uuid4()
        attachments: list[NewAttachment] = []
        stored_keys: list[str] = []
        try:
            for upload, source in zip(validated, public_files, strict=True):
                attachment_id = uuid4()
                key = f"orders/{order_id}/messages/{message_id}/attachments/{attachment_id}"
                await self._storage.put(key, upload.content, upload.mime_type)
                stored_keys.append(key)
                attachments.append(
                    NewAttachment(
                        id=attachment_id,
                        object_key=key,
                        original_filename=upload.filename,
                        mime_type=upload.mime_type,
                        size_bytes=upload.size_bytes,
                        sha256=upload.sha256,
                        origin="moysklad",
                        origin_external_file_id=source.id,
                    )
                )
            message = await self._repository.create_manager_message_with_notification(
                message_id=message_id,
                order_id=order_id,
                client_id=client.id,
                body=reply,
                external_key=external_key,
                attachments=tuple(attachments),
                outbox_events=(),
                moysklad_files=tuple(
                    NewMoySkladOrderFile(
                        order_id=order_id,
                        moysklad_file_id=source.id,
                        filename=source.filename,
                        disposition="manager_public",
                        message_id=message_id,
                    )
                    for source in public_files
                ),
            )
        except Exception:
            for key in stored_keys:
                await self._storage.delete(key)
            raise
        if self._notification_manager is not None:
            await self._notification_manager.notify_count_changed(client.id)
        if self._realtime is not None:
            try:
                await self._realtime.publish(str(order_id), self._message_payload(message))
            except Exception:
                pass
        await self.sync_order(order_id)

    @staticmethod
    def _message_payload(message) -> dict:
        return {
            "id": str(message.id),
            "order_id": str(message.order_id),
            "sender_kind": "manager",
            "sender_label": "Менеджер Pix Logistic",
            "message": message.body,
            "created_at": message.created_at.isoformat(),
            "attachments": [
                {
                    "id": str(item.id),
                    "filename": item.original_filename,
                    "mime_type": item.mime_type,
                    "size_bytes": item.size_bytes,
                }
                for item in message.attachments
            ],
            "delivery_state": "synced",
        }

    @staticmethod
    def _owned_by_client(order, client) -> bool:
        try:
            external_id = order["agent"]["meta"]["href"].rstrip("/").rsplit("/", 1)[-1]
        except (AttributeError, KeyError, TypeError):
            return False
        return external_id.lower() == str(client.moysklad_counterparty_id).lower()

    async def sync_order(self, order_id: UUID) -> None:
        state = await self._repository.get_state(order_id)
        if state is None:
            return
        order = await self._moysklad.get_order(order_id)
        current_files = await self._moysklad.list_files(order_id)
        known_files = await self._repository.list_moysklad_files(order_id)

        if not state.initialized:
            await self._record_baseline(order_id, current_files, known_files)
            description = (order.get("description") or "").strip()
            if description and not description.startswith(CHAT_HEADER):
                uploaded = await self._moysklad.upload_files(
                    order_id,
                    [
                        MoySkladUpload(
                            filename=PRIOR_COMMENT_FILENAME,
                            content=description.encode("utf-8"),
                        )
                    ],
                )
                backup = uploaded[0]
                current_files.append(backup)
                await self._repository.record_moysklad_files(
                    (
                        NewMoySkladOrderFile(
                            order_id=order_id,
                            moysklad_file_id=backup.id,
                            filename=backup.filename,
                            disposition="system",
                        ),
                    )
                )
                await self._repository.update_state(order_id, prior_comment_file_id=backup.id)

        await self._mirror_site_attachments(order_id, current_files, known_files)
        transcript = await self._repository.list_transcript(order_id)
        rendered = render_order_comment(
            [
                TranscriptEntry(
                    sender_kind=message.sender_kind,
                    created_at=message.created_at,
                    body=message.body,
                    filenames=tuple(attachment.original_filename for attachment in message.attachments),
                )
                for message in transcript
            ]
        )
        history_file_id = state.history_file_id
        if rendered.truncated:
            history_file_id = await self._replace_history_file(
                order_id,
                rendered.full_history.encode("utf-8"),
                current_files,
                history_file_id,
            )

        await self._moysklad.update_description(order_id, rendered.text)
        values = {
            "initialized": True,
            "rendered_description_hash": description_hash(rendered.text),
        }
        if rendered.truncated:
            values["history_file_id"] = history_file_id
        await self._repository.update_state(order_id, **values)

    async def _record_baseline(self, order_id, current_files, known_files) -> None:
        known_ids = {item.moysklad_file_id for item in known_files}
        baseline = tuple(
            NewMoySkladOrderFile(
                order_id=order_id,
                moysklad_file_id=item.id,
                filename=item.filename,
                disposition="baseline",
            )
            for item in current_files
            if item.id not in known_ids
        )
        await self._repository.record_moysklad_files(baseline)

    async def _mirror_site_attachments(self, order_id, current_files, known_files) -> None:
        records = await self._repository.list_unmirrored_site_attachments(order_id)
        current_names = {item.filename for item in current_files}
        ordinal_by_message: dict[UUID, int] = {}
        for attachment, message in records:
            ordinal = ordinal_by_message.get(message.id, 0) + 1
            ordinal_by_message[message.id] = ordinal
            filename = client_copy_filename(message.id, attachment.original_filename, ordinal)
            if filename in current_names:
                continue
            if len(current_files) >= 100:
                removed = await self._remove_oldest_client_mirror(order_id, current_files, known_files)
                if not removed:
                    await self._projection_error(order_id, "moysklad_file_limit")
                    continue
            content = await self._storage.read(attachment.object_key)
            uploaded = (
                await self._moysklad.upload_files(
                    order_id,
                    [MoySkladUpload(filename=filename, content=content)],
                )
            )[0]
            current_files.append(uploaded)
            current_names.add(uploaded.filename)
            new_record = NewMoySkladOrderFile(
                order_id=order_id,
                moysklad_file_id=uploaded.id,
                filename=uploaded.filename,
                disposition="client_mirror",
                message_id=message.id,
            )
            known_files.append(new_record)
            await self._repository.record_moysklad_files((new_record,))

    async def _remove_oldest_client_mirror(self, order_id, current_files, known_files) -> bool:
        current_ids = {item.id for item in current_files}
        candidate = next(
            (
                item
                for item in known_files
                if item.disposition == "client_mirror" and item.moysklad_file_id in current_ids
            ),
            None,
        )
        if candidate is None:
            return False
        await self._moysklad.delete_file(order_id, candidate.moysklad_file_id)
        await self._repository.forget_moysklad_file(order_id, candidate.moysklad_file_id)
        current_files[:] = [item for item in current_files if item.id != candidate.moysklad_file_id]
        known_files.remove(candidate)
        return True

    async def _replace_history_file(
        self,
        order_id,
        content,
        current_files,
        old_file_id,
    ):
        if old_file_id is not None and len(current_files) >= 100:
            await self._moysklad.delete_file(order_id, old_file_id)
            await self._repository.forget_moysklad_file(order_id, old_file_id)
            current_files[:] = [item for item in current_files if item.id != old_file_id]
            old_file_id = None
        uploaded = (
            await self._moysklad.upload_files(
                order_id,
                [MoySkladUpload(filename=HISTORY_FILENAME, content=content)],
            )
        )[0]
        await self._repository.record_moysklad_files(
            (
                NewMoySkladOrderFile(
                    order_id=order_id,
                    moysklad_file_id=uploaded.id,
                    filename=uploaded.filename,
                    disposition="system",
                ),
            )
        )
        if old_file_id is not None:
            await self._moysklad.delete_file(order_id, old_file_id)
            await self._repository.forget_moysklad_file(order_id, old_file_id)
        return uploaded.id

    async def _projection_error(self, order_id, code: str, identity: str = "") -> None:
        logger.warning(
            "order_chat_projection_rejected order_id=%s code=%s event_identity=%s",
            order_id,
            code,
            identity[:128],
        )
