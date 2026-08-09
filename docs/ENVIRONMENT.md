# Environment Variables

`config.Settings` is the backend source of truth. Backend values are read from process environment or an ignored `.env`. The frontend public base URL is embedded into browser assets at build time; changing it after the image is built does not update the client bundle.

Never copy production values into this document, `.env.example`, source code, logs, or `AGENTS.md`.

## Production inventory

| Variable | Scope | Required in production | Secret | Format | Purpose |
| --- | --- | --- | --- | --- | --- |
| `APP_ENV` | Backend | Yes | No | Environment enum | Enables production safety validation |
| `POSTGRES_DRIVER` | Backend | Yes | No | SQLAlchemy async driver name | Database URL scheme |
| `POSTGRES_USER` | Backend/Compose | Yes | No | PostgreSQL role | Database authentication |
| `POSTGRES_PASSWORD` | Backend/Compose | Yes | Yes | Strong password | Database authentication; local default is rejected in production |
| `POSTGRES_DB` | Backend/Compose | Yes | No | Database name | Application database |
| `POSTGRES_HOST` | Backend | Yes | No | Hostname or IP | PostgreSQL network location |
| `DB_PORT` | Backend | Yes | No | Integer TCP port | PostgreSQL network port |
| `REDIS_URL` | Backend | Yes | Conditional | Redis URL | JWT, codes, cache, and rate storage; secret if credentials are embedded |
| `TOKEN_LIFETIME` | Backend | Yes | No | Positive seconds | JWT token lifetime |
| `VERIFICATION_TOKEN_SECRET` | Backend | Yes | Yes | Long random string | Email-verification token signing |
| `RESET_PASSWORD_TOKEN_SECRET` | Backend | Yes | Yes | Long random string | Password-reset token signing |
| `CORS_ORIGINS` | Backend | Yes | No | JSON array of origins | Allowed browser origins |
| `ENABLE_SCHEDULER` | Backend | Yes | No | Boolean | Enables hourly external order-state synchronization |
| `BOT_TOKEN` | Telegram | If Telegram flows are enabled | Yes | Bot API token | Constructs the Telegram bot client |
| `CHAT_ID` | Telegram | If group notifications are enabled | Sensitive | Integer chat ID | Destination for group/order messages |
| `HELP_CHAT_ID` | Telegram | If support notifications are enabled | Sensitive | Integer chat ID | Destination for support messages |
| `BITRIX_LINK` | Bitrix | If Bitrix endpoints are enabled | Yes | HTTPS webhook base URL | Authenticated Bitrix REST base |
| `MOYSKLAD_LOGIN` | MoySklad | Yes for full product behavior | Sensitive | Account login | MoySklad Basic authentication |
| `MOYSKLAD_PASSWORD` | MoySklad | Yes for full product behavior | Yes | Account password/token | MoySklad Basic authentication |
| `PRIVOZ_USERNAME` | Privoz | If Privoz/scheduler flows are enabled | Sensitive | Account login | Privoz web login |
| `PRIVOZ_PASSWORD` | Privoz | If Privoz/scheduler flows are enabled | Yes | Account password | Privoz web login |
| `MAILERSEND_TOKEN` | Email | Yes for verify/reset flows | Yes | API token | SMTP.BZ authorization header |
| `NEXT_PUBLIC_BACKEND_URL` | Frontend build | Yes | No | Absolute public HTTPS URL ending in `/api_v1` | Browser API base; build-time public value |
| `PGADMIN_DEFAULT_EMAIL` | Production Compose | If pgAdmin is enabled | Sensitive | Email address | Initial pgAdmin account |
| `PGADMIN_DEFAULT_PASSWORD` | Production Compose | If pgAdmin is enabled | Yes | Strong password | Initial pgAdmin account |

`MOYSKLAD_PASWORD` is accepted only as a deprecated compatibility alias. New environments must use `MOYSKLAD_PASSWORD`.

## Copy-ready production key list

Fill this block directly in the production secret store or `.env`; values are deliberately absent:

```dotenv
APP_ENV=
POSTGRES_DRIVER=
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=
POSTGRES_HOST=
DB_PORT=
REDIS_URL=
TOKEN_LIFETIME=
VERIFICATION_TOKEN_SECRET=
RESET_PASSWORD_TOKEN_SECRET=
CORS_ORIGINS=
ENABLE_SCHEDULER=
BOT_TOKEN=
CHAT_ID=
HELP_CHAT_ID=
BITRIX_LINK=
MOYSKLAD_LOGIN=
MOYSKLAD_PASSWORD=
PRIVOZ_USERNAME=
PRIVOZ_PASSWORD=
MAILERSEND_TOKEN=
NEXT_PUBLIC_BACKEND_URL=
PGADMIN_DEFAULT_EMAIL=
PGADMIN_DEFAULT_PASSWORD=
```

The GitHub deployment workflow separately consumes repository/action secrets named `HOST`, `USERNAME`, `PASSWORD`, and `PORT`. They are not application `.env` variables.

## Local defaults

`.env.example` contains only local-safe PostgreSQL, Redis, CORS, and authentication defaults. All production integrations are blank. `APP_ENV=production` rejects the shipped local database and authentication secrets.
