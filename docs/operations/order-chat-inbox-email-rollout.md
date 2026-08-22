# Order-chat inbox and email rollout

This runbook covers the additive inbox/email migration, backend and website
deployment, and Chrome extension `0.2.0`. Production backup, migration,
environment changes, deployment, controlled email delivery, and any data
cleanup are separate approval gates. Never paste credentials, the extension
secret, or the SMTP.BZ token into command output, tickets, or this repository.

## Required rollout order

1. Record the backend and frontend commit SHAs and verify the scoped worktrees
   contain no uncommitted release changes.
2. Inspect the active production database target without displaying a password
   or credential-bearing URL. Confirm only the driver, host, port, and database
   name against the approved environment inventory. Do not run Alembic yet.
3. Create a timestamped custom-format PostgreSQL dump outside the application
   volume. Record its absolute path, byte size, and checksum. Verify that it is
   readable with `pg_restore --list`; retain both the dump and listing.
4. Review revision `f4c8a2d6b901` and run `alembic current` and
   `alembic heads`. Production must be on the expected predecessor and the
   checkout must have exactly one head at `f4c8a2d6b901`.
5. Stop. Present the dump path/checksum, current revision, target revision,
   migration SQL review, and rollback plan. Obtain explicit approval for the
   production migration.
6. Apply only `alembic upgrade f4c8a2d6b901`. Do not use an unbounded
   `upgrade head` command in this rollout.
7. Deploy the backend with `ENABLE_ORDER_CHAT_EMAIL_NOTIFICATIONS=false`.
   Verify `/api_v1/health`, existing room history/send/WebSocket behavior, the
   new operator inbox REST/read endpoints and inbox WebSocket, and the website
   `ORDER_MESSAGE` JSON fields. No email should be queued or sent yet.
8. Deploy the website and verify that an order-message notification opens
   `/dashboard/orders/{id}?openChat=1#order-chat`, expands the chat, and leaves
   unrelated query parameters intact.
9. In the approved production secret store or ignored server `.env`, set
   `ORDER_CHAT_MANAGER_EMAIL=Pixtool22@gmail.com`,
   `PIX_PUBLIC_SITE_URL=https://pixlogistic.com`, retain the existing SMTP.BZ
   value in `MAILERSEND_TOKEN`, then set
   `ENABLE_ORDER_CHAT_EMAIL_NOTIFICATIONS=true`. Run the production preflight
   before restarting the backend. Never print the token.
10. Send one controlled client message and one controlled manager message.
    Confirm the manager address receives only the client-message email, the
    intended client receives only the manager-message email, links open the
    correct order, and the matching outbox rows reach `sent` without duplicate
    delivery.
11. Distribute Chrome extension `0.2.0`. Keep backend compatibility with
    extension `0.1.0` during the workstation rollout and confirm the displayed
    extension version after each replacement.

## Backup verification

Use the deployment's approved PostgreSQL/Compose commands and keep secrets in
their existing environment boundary. A representative custom-format backup is:

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "backups/pix-before-order-chat-inbox-$stamp.dump"
docker compose exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > $backup
pg_restore --list $backup > "$backup.list"
Get-Item $backup, "$backup.list" | Select-Object FullName, Length
Get-FileHash -Algorithm SHA256 $backup
```

Adapt service names only after inspecting the active Compose project. A zero
exit code alone is insufficient: the dump must be non-empty and
`pg_restore --list` must contain the expected schemas/tables. Store it outside
volumes that a deployment or cleanup can replace.

## Post-deploy checks

- `GET /api_v1/chat/operator/conversations` returns ordered summaries,
  `next_before`, and `total_unread` with the extension secret in the header.
- `POST /api_v1/chat/operator/orders/{order_id}/read` clears that conversation
  and returns the authoritative global unread total.
- `/api_v1/chat/operator/inbox/ws` authenticates only through the exact first
  frame and publishes `conversation_updated`; the secret never appears in a
  URL.
- Existing `/api_v1/chat/operator/orders/{order_id}/messages`, room WebSocket,
  attachment download, and customer-site chat remain functional.
- Website notification payloads include `order_name`, `message`,
  `attachment_count`, and `to_chat_room_id` for `ORDER_MESSAGE`.

## Email outbox operations

The dispatcher claims at most 20 due rows. Jobs start as `pending`, are briefly
`processing` while leased, become `sent` after SMTP.BZ accepts delivery, or
return to `pending` with a safe error category. Retry delays are 1 minute,
5 minutes, 15 minutes, 1 hour, then 6 hours for subsequent attempts. After
10 attempts the job becomes `dead`. A five-minute lease lets another process
recover abandoned `processing` jobs. Do not edit payloads, retry timestamps, or
attempt counters directly during rollout.

## Rollback

1. Set `ENABLE_ORDER_CHAT_EMAIL_NOTIFICATIONS=false` first and restart/redeploy
   the backend so no new email jobs are delivered.
2. Redeploy the previously recorded backend and website images/commits.
3. Keep the additive inbox columns, state table, outbox table, and all pending,
   processing, sent, or dead jobs intact for diagnosis and forward recovery.
4. Keep PostgreSQL, MinIO, and Redis data. Do not delete old chat records.
5. Do not run `alembic downgrade` unless a separate reviewed recovery plan and
   explicit approval authorize it. Restore the verified dump only for a proven
   database recovery incident, never as a routine application rollback.

If only extension `0.2.0` is affected, reload or temporarily restore extension
`0.1.0`; do not roll back the additive database migration for a workstation UI
issue.
