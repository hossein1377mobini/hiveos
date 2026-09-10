"""Locust scenarios for v0.1 load gate (RG-20, T-S5-5, ADR-024 amendment 1).

Profile (PO 2026-09-14 decision): 10 virtual users doing chat/RAG plus
100-document ingestion per organization. Run against staging:

    locust -f scripts/load/locustfile.py --host http://<staging> \
        --users 10 --spawn-rate 2 --run-time 10m --csv reports/load/v01

Exit criteria (RG-20): p95 < SLO, zero error rate on auth/chat/read,
no connection/asset leaks (rows in agent_executions/chat_sessions
before vs. after must reconcile).
"""

import random

from locust import HttpUser, between, task


class HiveOSUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        self.headers = {}
        # staging bootstrap: env-provisioned org owner (ADR-022: creds via env)
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": self.environment.username, "password": self.environment.password},
        )
        if response.status_code == 200:
            self.headers = {
                "Authorization": f"Bearer {response.json()['data']['session']['token']}"
            }

    @task(3)
    def chat_rag_cycle(self):
        """Create a chat session, run a RAG execution, read messages."""
        created = self.client.post(
            "/api/v1/chat/sessions", json={}, headers=self.headers
        )
        if created.status_code != 200:
            return
        session_id = created.json()["data"]["id"]
        self.client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"text": f"سوال آزمایشی {random.randint(1, 10_000)}"},
            headers=self.headers,
        )
        execution = self.client.post(
            "/api/v1/executions",
            json={"input": {"text": "رویه نصب سرور چیست؟"}, "chat_session_id": session_id},
            headers=self.headers,
        )
        if execution.status_code == 200:
            execution_id = execution.json()["data"]["id"]
            self.client.post(
                f"/api/v1/executions/{execution_id}/run", headers=self.headers
            )
        self.client.get(
            f"/api/v1/chat/sessions/{session_id}/messages", headers=self.headers
        )

    @task(1)
    def knowledge_read(self):
        """Read-side load: assets list + semantic search."""
        self.client.get("/api/v1/knowledge-assets", headers=self.headers)
        self.client.post(
            "/api/v1/search",
            json={"query": f"پرس‌وجوی معنایی {random.randint(1, 10_000)}"},
            headers=self.headers,
        )
