from uuid import UUID

from db.moysklad_order_chat_repository import MoySkladUpload
from db.order_chat_repository import (
    NewMoySkladOrderFile,
    NewOutboxEvent,
)
from manager.order_chat_format import (
    CHAT_HEADER,
    HISTORY_FILENAME,
    PRIOR_COMMENT_FILENAME,
    TranscriptEntry,
    client_copy_filename,
    description_hash,
    render_order_comment,
)


class MoySkladOrderChatSynchronizer:
    def __init__(self, *, repository, moysklad, storage):
        self._repository = repository
        self._moysklad = moysklad
        self._storage = storage

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

    async def _projection_error(self, order_id, code: str) -> None:
        if not hasattr(self._repository, "enqueue_events"):
            return
        await self._repository.enqueue_events(
            (
                NewOutboxEvent(
                    event_type="telegram_projection_error",
                    order_id=order_id,
                    dedup_key=f"projection_error:{order_id}:{code}",
                    payload={"code": code},
                ),
            )
        )
