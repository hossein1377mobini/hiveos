# infrastructure/

- `docker-compose.yml` - dev: db (pgvector/pg16, port 5434) + api (port 8100)
- `docker-compose.prod.yml` - prod overlay: nginx in front of api
- `docker-compose.staging.yml` - server stack (api only; joins external db network `hiveos_default`; T-S0-4)
- `nginx/staging.default.conf` - HOST nginx default site (:80 proxy -> 127.0.0.1:8100; installed once)
- `db/init/01-extensions.sql` - CREATE EXTENSION vector on first boot
- `api.Dockerfile` - backend image (uv + Python 3.11)
- `.env.example` - env contract for the server-side `/opt/hiveos/app/.env` (never committed)

Run (dev):
```
docker compose -f infrastructure/docker-compose.yml up -d
```

## Staging deploy (T-S0-4)

CI builds the api image, ships it via `docker save`/scp/`docker load` (no registry auth
on servers - ADR-023 closed topology), then runs `deploy/remote-deploy.sh <tag>` on the
server: regenerate `.env` (DATABASE_URL from `/opt/hiveos/secrets/pg_password`, host = `db`
via external network `hiveos_default`), compose up, `alembic upgrade head` (one-off api
container), healthcheck direct :8100 + host nginx :80, record tag. Failed healthcheck ->
automatic rollback to the previous tag via `deploy/rollback.sh` (requires sudo - .env is
root-owned chmod 600).

Server layout (staging, one-time setup already done for db):

```
/opt/hiveos/app/                  # app deploy dir (project name hiveos-app)
├── docker-compose.staging.yml    # copied by CI
├── nginx/nginx.conf              # copied by CI (unused while host nginx serves; kept for parity)
├── deploy/remote-deploy.sh       # copied by CI
├── deploy/rollback.sh            # copied by CI
├── .env                          # chmod 600 root-owned, regenerated each deploy
├── .previous-tag                 # current healthy tag
└── .rollback-tag                 # rollback target

Also one-time on each server (already done on staging):
- `/etc/nginx/sites-available/default` <- `nginx/staging.default.conf` (proxy :80 -> 127.0.0.1:8100)
- CI deploy key public half appended to `/home/ubuntu/.ssh/authorized_keys`
```

Manual rollback:
```
ssh hiveos-staging 'sudo bash /opt/hiveos/app/deploy/rollback.sh [tag]'
```

Secrets (ADR-022): `pg_password` already on both servers in `/opt/hiveos/secrets/`.
GitHub repo secrets required before enabling the deploy job: `STAGING_SSH_KEY`
(private half of the generated CI deploy key, held by PO) and `STAGING_HOST`
(193.93.169.136). Secrets API needs admin scope - set via web UI or a workflow-scoped PAT.
