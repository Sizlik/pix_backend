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
- Treat Bitrix webhook URLs, Redis URLs with passwords, Telegram chat IDs, account names, and deployment host/user data as sensitive even when they are not conventional passwords.
- `.env`, `.env.local`, `.venv`, build output, Playwright artifacts, and local logs must remain ignored.
- Browser code is public. `NEXT_PUBLIC_BACKEND_URL` may contain only a public API base, never credentials or private network tokens.
- Missing integration configuration must produce a sanitized `IntegrationNotConfigured` error and HTTP 503.

## Runtime trust boundaries

- FastAPI Users bearer tokens are backed by Redis. WebSocket authentication passes a token through a query parameter, which may be captured by proxies unless logging is controlled.
- Integration and webhook endpoints require an explicit authorization review before expansion; some existing endpoints do not declare a current-user dependency.
- Blocking external HTTP calls should gain timeouts, TLS/error handling, retry limits, and redacted structured logging.
- Scheduler enablement permits periodic external reads and mutations. Keep it disabled in local/test environments.
- Spreadsheet uploads are parsed by pandas in-process; enforce file-size/content limits before treating the endpoint as internet-safe.

## Dependency and deployment observations

- The frontend dependency audit currently reports unresolved findings, including high and critical severities. Upgrade deliberately with compatibility tests; do not use a force fix blindly.
- The deployment workflow runs a database migration and Docker prune on the server. Protect the deployment branch, CI secrets, database backups, and recovery process.
- Production `.env` must be readable only by the deployment account and must not be copied into Docker build layers or CI output.
