# Production runbook: remove Telegram and legacy support chat

This runbook covers Alembic revision `d4e5f6a7b8c9` (predecessor
`b7e1d3a9f4c2`). The application images must be deployed and verified before
the migration is run. Database migration, protected environment cleanup, and
removal of the old bot container are separate approved operations.

## Owners and evidence

- The release owner records the backend and frontend image tags and the commit
  IDs used to build them.
- The database owner creates the pre-migration backup, validates a restore into
  an isolated database, and records the backup identifier, validation time, and
  restore owner in the change ticket.
- The operator records the reviewed database host and database name before any
  write command. Do not proceed when either value is unexpected.
- Query results attached to the ticket must contain counts only. Never capture
  message bodies, attachment data, tokens, webhook secrets, chat IDs, or user
  Telegram identifiers.

## Read-only preflight

Confirm the target first:

```sql
SELECT current_database(), inet_server_addr(), inet_server_port();
SELECT version_num FROM alembic_version;
```

The Alembic version must be `b7e1d3a9f4c2`. Capture counts without values:

```sql
SELECT count(*) AS users_with_telegram_id
FROM "user"
WHERE telegram_id IS NOT NULL;

SELECT count(*) AS legacy_messages FROM message;
SELECT count(*) AS legacy_rooms FROM chat_room;

SELECT type, count(*)
FROM notifications
WHERE type IN ('MESSAGE', 'ORDER_MESSAGE')
GROUP BY type
ORDER BY type;

SELECT event_type, count(*)
FROM chat_outbox_event
WHERE event_type IN (
    'telegram_client_alert',
    'telegram_manager_alert',
    'telegram_projection_error'
)
GROUP BY event_type
ORDER BY event_type;
```

The mapping audit must report zero ambiguous messages:

```sql
WITH legacy_map AS (
    SELECT m.id AS legacy_message_id
    FROM message AS m
    JOIN chat_room AS cr
      ON m.to_chat_room_id = cr.id
      OR m.to_chat_room_id = cr.order_id
    WHERE cr.order_id IS NOT NULL
)
SELECT count(*) AS ambiguous_message_count
FROM (
    SELECT legacy_message_id
    FROM legacy_map
    GROUP BY legacy_message_id
    HAVING count(*) > 1
) AS ambiguous;
```

The missing-client audit must report zero:

```sql
WITH legacy_map AS (
    SELECT m.id AS legacy_message_id, cr.client_id
    FROM message AS m
    JOIN chat_room AS cr
      ON m.to_chat_room_id = cr.id
      OR m.to_chat_room_id = cr.order_id
    WHERE cr.order_id IS NOT NULL
)
SELECT count(*) AS missing_client_count
FROM legacy_map
WHERE client_id IS NULL;
```

The notification mapping audit must also report zero:

```sql
WITH legacy_map AS (
    SELECT DISTINCT m.id AS legacy_message_id
    FROM message AS m
    JOIN chat_room AS cr
      ON m.to_chat_room_id = cr.id
      OR m.to_chat_room_id = cr.order_id
    WHERE cr.order_id IS NOT NULL
)
SELECT count(*) AS unmapped_order_notification_count
FROM notifications AS notification
JOIN message AS legacy
  ON legacy.id = notification.object_id
LEFT JOIN legacy_map AS map
  ON map.legacy_message_id = legacy.id
WHERE notification.type = 'ORDER_MESSAGE'
  AND map.legacy_message_id IS NULL;
```

Audit the retained account without deleting it:

```sql
SELECT count(*) AS matching_bot_accounts
FROM "user"
WHERE email = 'bot@pixlogistic.com';

SELECT count(*) AS legacy_messages_authored_by_bot
FROM message AS legacy
JOIN "user" AS author ON author.id = legacy.from_user_id
WHERE author.email = 'bot@pixlogistic.com';
```

Stop if any zero-required audit is nonzero, the database target is unexpected,
the backup restore has not been validated, or the image tags are not captured.

## Approved migration action

After a separate approval for the reviewed target, run exactly this command in
the deployed backend environment:

```text
alembic upgrade d4e5f6a7b8c9
```

Do not use `upgrade head` in this change. Do not combine the command with
container deletion or environment editing.

## Post-migration checks

```sql
SELECT version_num FROM alembic_version;

SELECT count(*) AS retained_legacy_order_messages
FROM order_chat_message
WHERE source = 'legacy';

SELECT count(*) AS dangling_order_message_notifications
FROM notifications AS notification
LEFT JOIN order_chat_message AS retained
  ON retained.id = notification.object_id
WHERE notification.type = 'ORDER_MESSAGE'
  AND retained.id IS NULL;

SELECT count(*) AS removed_message_notifications
FROM notifications
WHERE type = 'MESSAGE';

SELECT count(*) AS removed_telegram_outbox_events
FROM chat_outbox_event
WHERE event_type IN (
    'telegram_client_alert',
    'telegram_manager_alert',
    'telegram_projection_error'
);

SELECT count(*) AS obsolete_tables
FROM information_schema.tables
WHERE table_schema = current_schema()
  AND table_name IN ('message', 'chat_room');

SELECT count(*) AS obsolete_columns
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name = 'user'
  AND column_name = 'telegram_id';
```

The Alembic version must be `d4e5f6a7b8c9`; dangling notifications, removed
notification/outbox types, obsolete tables, and obsolete columns must all be
zero. Verify email registration, order mutations, website notification counts,
and order-specific chat after the schema checks.

## Rollback boundaries

Before the database migration, roll back by restoring the previously captured
application image tags; no database rollback is needed.

After the database migration, `alembic downgrade b7e1d3a9f4c2` recreates only
empty compatibility tables and a nullable `user.telegram_id` column. It does
not restore deleted support messages, notification rows, outbox events, room
rows, or Telegram identity values. Recovering those values requires the
validated pre-migration backup and the database owner's restore procedure.
Application rollback after migration therefore requires an explicit database
recovery decision; do not run the downgrade as an automatic response.
