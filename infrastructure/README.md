# infrastructure/

- `docker-compose.yml` - dev: db (pgvector/pg16, port 5432) + api (port 8100)
- `docker-compose.prod.yml` - prod overlay: nginx in front of api
- `db/init/01-extensions.sql` - CREATE EXTENSION vector on first boot
- `api.Dockerfile` - backend image (uv + Python 3.11)

Run (dev):
```
docker compose -f infrastructure/docker-compose.yml up -d
```

Run (staging/prod):
```
docker compose -f infrastructure/docker-compose.yml -f infrastructure/docker-compose.prod.yml up -d
```
