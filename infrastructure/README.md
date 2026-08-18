# infrastructure

HiveOS v0.1 Docker stack (ADR-019 Python-first backend): Postgres+pgvector and Redis.

## Bring up the stack

```bash
docker compose -f infrastructure/docker-compose.yml up -d
```

Stop it with:

```bash
docker compose -f infrastructure/docker-compose.yml down
```

Add `-v` to `down` only if you also want to wipe the database volume.

## Separate from Kaneo

This stack is intentionally independent from the Kaneo sample app:

| Service | Container      | Host port | Notes                          |
|---------|----------------|-----------|--------------------------------|
| db      | `hiveos-db`    | 5434      | Kaneo Postgres uses 5433       |
| redis   | `hiveos-redis` | 6380      | avoids a possibly-busy 6379    |

Do not run this alongside containers claiming host ports 5434 or 6380.

## Database init

`initdb/01-enable-vector.sql` enables the `pgvector` extension automatically on a
fresh volume (via `/docker-entrypoint-initdb.d`). It only runs the first time the
named volume is created.
