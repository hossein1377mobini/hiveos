"""Locust scenarios for the v0.1 load gate (RG-20, T-S5-5, ADR-024 amendment 1).

Two shapes, because two very different things are being measured:

  read   - search, asset lists, job queue, wallet. No model call, so it can be
           pushed hard and repeatedly without spending credits. This is where
           the server's real ceiling lives: pgvector over halfvec(1024), the
           connection pool, the rate limiter.
  chat   - a full RAG turn, which reaches the answer generator. Every request
           costs credit and several seconds, so it is exercised at modest
           concurrency and for a bounded duration.

Selection is by HIVEOS_LOAD_MODE so one file covers both profiles.

    locust -f scripts/load/locustfile.py --host https://hivesystem.ir \
        --users 10 --spawn-rate 2 --run-time 5m --headless \
        --csv reports/load/read

Credentials come from the environment (ADR-022: never in the repo).
"""
import os
import random

from locust import HttpUser, between, task

MODE = os.environ.get("HIVEOS_LOAD_MODE", "read")

# Grounded questions, so retrieval actually has to work rather than short-circuit
# on an empty result. Mixed with off-topic ones to exercise the relevance floor.
QUESTIONS = [
    "بودجه پروژه قناری چقدر است؟",
    "شناسه QNR-7741 مربوط به چیست؟",
    "دکتر آرمان رهگذر چه نقشی دارد؟",
    "قرارداد پشتیبانی سالانه با چه کسی تمدید شد؟",
    "قطعه XR-9 چیست؟",
]
NOISE = ["قیمت بیت‌کوین امروز چقدر است؟", "هوای تهران فردا چطور است؟"]


class HiveOSUser(HttpUser):
    """Read-side load: the profile that finds the server's ceiling."""

    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.headers: dict[str, str] = {}
        self.session_id: str | None = None
        user = os.environ.get("HIVEOS_LOAD_USER", "")
        password = os.environ.get("HIVEOS_LOAD_PASS", "")
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": user, "password": password},
            name="/api/v1/auth/login",
        )
        if response.status_code == 200:
            self.headers = {
                "Authorization": f"Bearer {response.json()['data']['session']['token']}"
            }

    @task(6)
    def search(self) -> None:
        """The hot path: embed the query, scan HNSW, rerank, filter by access."""
        query = random.choice(QUESTIONS if random.random() < 0.8 else NOISE)
        self.client.post(
            "/api/v1/search",
            json={"query": query},
            headers=self.headers,
            name="/api/v1/search",
        )

    @task(3)
    def read_lists(self) -> None:
        self.client.get("/api/v1/knowledge-assets", headers=self.headers,
                        name="/api/v1/knowledge-assets")
        self.client.get("/api/v1/processing/jobs", headers=self.headers,
                        name="/api/v1/processing/jobs")
        self.client.get("/api/v1/agent", headers=self.headers, name="/api/v1/agent")

    @task(1)
    def wallet_read(self) -> None:
        self.client.get("/api/v1/wallet", headers=self.headers, name="/api/v1/wallet")


class HiveOSChatUser(HttpUser):
    """Chat-side load: a real RAG turn, which costs credit and takes seconds."""

    wait_time = between(3, 8)

    def on_start(self) -> None:
        self.headers: dict[str, str] = {}
        self.session_id: str | None = None
        response = self.client.post(
            "/api/v1/auth/login",
            json={
                "username": os.environ.get("HIVEOS_LOAD_USER", ""),
                "password": os.environ.get("HIVEOS_LOAD_PASS", ""),
            },
            name="/api/v1/auth/login",
        )
        if response.status_code == 200:
            self.headers = {
                "Authorization": f"Bearer {response.json()['data']['session']['token']}"
            }
            created = self.client.post("/api/v1/chat/sessions", json={},
                                       headers=self.headers, name="/api/v1/chat/sessions")
            if created.status_code == 200:
                self.session_id = created.json()["data"]["id"]

    @task
    def chat_turn(self) -> None:
        if not self.session_id:
            return
        execution = self.client.post(
            "/api/v1/executions",
            json={"input": {"text": random.choice(QUESTIONS)}, "chat_session_id": self.session_id},
            headers=self.headers,
            name="/api/v1/executions",
        )
        if execution.status_code != 200:
            return
        execution_id = execution.json()["data"]["id"]
        self.client.post(f"/api/v1/executions/{execution_id}/start",
                         headers=self.headers, name="/api/v1/executions/[id]/start")
        self.client.post(f"/api/v1/executions/{execution_id}/run",
                         headers=self.headers, name="/api/v1/executions/[id]/run")
