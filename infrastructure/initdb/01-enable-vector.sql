-- Enable the pgvector extension on first database initialization.
-- Runs automatically via /docker-entrypoint-initdb.d on a fresh volume.
CREATE EXTENSION IF NOT EXISTS vector;
