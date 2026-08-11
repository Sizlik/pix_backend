# Production Host Services Design

## Goal

Reduce the production Docker footprint without removing infrastructure required
by the application. pgAdmin is removed entirely. NGINX and Redis remain required
production dependencies, but they run as host-managed services instead of Docker
Compose services. Local development keeps its Redis container.

## Scope

- Remove the `pgadmin` service and `pgadmin-data` volume from production Compose.
- Remove the unused pgAdmin settings, production environment-template entries,
  current documentation, and tests that require those entries.
- Remove the stale commented NGINX service from production Compose.
- Keep the tracked NGINX configuration as the reviewed production proxy
  configuration, remove the `/pgadmin/` upstream and route, and point the
  frontend and backend upstreams at their host-published ports.
- Document that production Redis and NGINX are host-managed services.
- Keep the Redis service in `local-docker-compose.yml` and preserve the existing
  local setup commands.
- Preserve historical design and implementation records under
  `docs/superpowers/`; they describe the state accepted at the time.

## Production Topology

NGINX runs on the host and terminates TLS. It proxies browser traffic to the
frontend on `127.0.0.1:3000` and API/WebSocket traffic to the backend on
`127.0.0.1:8000`. The backend connects to the host Redis service through
`REDIS_URL=redis://127.0.0.1:6379/0` or an equivalent authenticated loopback URL.
Docker Compose continues to run PostgreSQL, the frontend, backend, MinIO, and the
existing bot. No pgAdmin process, port, route, credentials, or persistent volume
remains in the current deployment configuration.

The NGINX rules for WebSocket upgrades, the order-chat upload-size exception,
and secret webhook access-log suppression remain unchanged apart from the
host-based upstream addresses.

## Configuration and Failure Behavior

The backend remains dependent on Redis. If the host Redis service is unavailable,
authentication, token/code storage, cache operations, and realtime fan-out may
fail as they do today; removing the Docker service does not introduce a fallback.
Deployment must therefore ensure Redis and NGINX are installed, enabled, and
healthy before updating the Compose application.

Removing pgAdmin does not affect application requests or database migrations.
Database administration is performed with a separate client over an SSH tunnel
or with command-line tools on the server. Existing ignored server `.env` files
may retain old pgAdmin variables temporarily, but the application and Compose no
longer consume them.

## Verification

- Validate production Compose with `docker-compose --env-file .env config --quiet`
  without starting services.
- Run the production-configuration tests after updating their expected inventory.
- Run `scripts/check.ps1` after the final edit, as required for configuration and
  backend changes.
- Inspect the final diff to confirm the local Redis service remains present and
  that no unrelated or generated-file changes were included.

## Success Criteria

- Production Compose contains no pgAdmin or NGINX service definition.
- Current configuration, environment templates, proxy configuration,
  documentation, and tests contain no active pgAdmin dependency.
- NGINX proxies to the frontend and backend through loopback host ports.
- Production documentation identifies Redis and NGINX as host-managed services.
- Local Docker startup still provides PostgreSQL, Redis, and MinIO.
