# Security Notes

## Credential rotation required

Credential-bearing values were found in historical working-tree or Git configuration locations for these categories:

- Bitrix webhook authentication in `manager/bitrix.py` history.
- Privoz username/password in `manager/privoz_order.py` history.
- Git credentials embedded in the backend and frontend `origin` URLs.

The current working tree removes credential defaults and the local remotes are sanitized separately. Removal does not invalidate a credential and does not erase it from Git history, logs, clones, CI caches, or hosting-provider records. Rotate/revoke the affected Bitrix, Privoz, and Git credentials manually in their issuing systems, then update only the production secret store.

Do not test old credentials to determine whether they still work. Do not rewrite shared Git history without a separately reviewed incident-response plan.

## Secret boundaries

- Never store secrets in `AGENTS.md`, README files, committed environment files, frontend `NEXT_PUBLIC_*` variables, URLs, screenshots, test fixtures, exception messages, or logs.
- Treat Bitrix webhook URLs, Redis URLs with passwords, external account names, and deployment host/user data as sensitive even when they are not conventional passwords.
- `.env`, `.env.local`, `.venv`, build output, Playwright artifacts, and local logs must remain ignored.
- Browser code is public. `NEXT_PUBLIC_BACKEND_URL` may contain only a public API base, never credentials or private network tokens.
- Missing integration configuration must produce a sanitized `IntegrationNotConfigured` error and HTTP 503.
- `MOYSKLAD_ORDER_CHAT_WEBHOOK_SECRET` is embedded in a URL path. NGINX disables access logging for only that exact prefix, registration output redacts the final segment, and application code must never log the unredacted request target. Rotate it by deploying a new secret, restarting, registering the new exact URL, and deleting only the old webhook after explicit approval.
- MinIO access and secret keys belong only in the backend/container secret store. Never expose them through `NEXT_PUBLIC_*`, browser object URLs, MoySklad comments, filenames, or order-chat messages.

## Runtime trust boundaries

- FastAPI Users bearer tokens are backed by Redis. WebSocket authentication passes a token through a query parameter, which may be captured by proxies unless logging is controlled.
- Integration and webhook endpoints require an explicit authorization review before expansion; some existing endpoints do not declare a current-user dependency.
- Blocking external HTTP calls should gain timeouts, TLS/error handling, retry limits, and redacted structured logging.
- Scheduler enablement permits periodic external reads and mutations. Keep it disabled in local/test environments.
- Spreadsheet uploads are parsed by pandas in-process; enforce file-size/content limits before treating the endpoint as internet-safe.

## Immutable order-chat controls

- PostgreSQL is the source of truth for message history. Database triggers reject `UPDATE` and `DELETE` on canonical message and attachment rows; application APIs expose no edit/delete operation.
- Every history read, attachment download, WebSocket order-room connection, site send, and inbound MoySklad delivery performs or inherits a fresh customer-order owner check. Unauthorized and missing orders deliberately converge on `404`/`4404` behavior.
- Attachments are limited to ten files and 20 MiB each. Filename extensions and byte signatures are checked server-side for the allowlist; browser checks are usability only. Stored object keys do not trust the original filename.
- Only text below the manager reply marker and MoySklad files prefixed `[КЛИЕНТ]` are client-visible. Other manager files remain internal.
- PostgreSQL and the MinIO volume must be backed up and restored as one retention set. A database-only restore can leave attachment metadata without bytes; a volume-only restore loses ownership and immutable-history links.
- Revision `d4e5f6a7b8c9` deletes obsolete messaging rows, tables, and identity values. It must be applied manually only after the backup has been restored successfully in isolation; its downgrade recreates empty compatibility structures and cannot recover deleted values. Follow its production runbook under `docs/operations/`.

## Dependency and deployment observations

- The frontend dependency audit currently reports unresolved findings, including high and critical severities. Upgrade deliberately with compatibility tests; do not use a force fix blindly.
- The deployment workflow validates configuration and updates Compose without
  running migrations, stopping the whole project, pruning Docker data or
  registering webhooks. Protect the deployment branch, CI secrets, database
  backups and the separate manual migration approval process.
- Production `.env` must be readable only by the deployment account and must not be copied into Docker build layers or CI output.
- Backend and frontend Docker build contexts exclude ignored `.env` files,
  local dependency/build caches, Git metadata and test artifacts. The frontend
  public API origin is an explicit build argument and may never contain a
  credential.
- The MinIO server repository is archived and distributed under AGPLv3. The image is built from the pinned `RELEASE.2025-10-15T17-29-55Z` source tag instead of an unreviewed binary/latest tag. Legal/license review, image scanning, upstream-risk ownership, and a replacement plan are production prerequisites.
