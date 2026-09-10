"""US-1203 wallet (T-S3-7)."""

from tests.test_knowledge_api import _bootstrap_full

WALLET = "/api/v1/wallet"
EX = "/api/v1/executions"


def test_wallet_welcome_credit_and_charge(client):
    ctx = _bootstrap_full(client)
    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["balance"] == 50  # welcome credit (US-1203)
    assert state["blocked"] is False

    charged = client.post(f"{WALLET}/charge", json={"amount": 100}, headers=ctx["headers"])
    assert charged.status_code == 200, charged.text
    assert charged.json()["data"]["balance"] == 150

    invalid = client.post(f"{WALLET}/charge", json={"amount": 0}, headers=ctx["headers"])
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"

    transactions = client.get(WALLET, headers=ctx["headers"]).json()["data"]["transactions"]
    assert transactions[0]["kind"] == "CHARGE"
    assert transactions[0]["balance_after"] == 150


def test_zero_balance_blocks_online_execution(client, monkeypatch):
    """US-1203 AC7: zero credit blocks the run for online providers (402)."""
    from backend.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_provider", "online-mock")

    ctx = _bootstrap_full(client)
    # materialize the wallet first (it is created lazily with the welcome credit)
    assert client.get(WALLET, headers=ctx["headers"]).json()["data"]["balance"] == 50
    # drain the welcome credit via direct wallet mutation (simulation of usage)
    import asyncio

    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from backend.models import Wallet

    async def _zero():
        settings = get_settings()
        engine = create_async_engine(settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            await session.execute(update(Wallet).values(balance=0))
            await session.commit()
        await engine.dispose()

    asyncio.get_event_loop().run_until_complete(_zero())

    blocked = client.post(EX, json={"input": {"text": "سلام"}}, headers=ctx["headers"])
    assert blocked.status_code == 402
    assert blocked.json()["error"]["code"] == "CREDIT_EXHAUSTED"

    # charge -> unblocked
    client.post(f"{WALLET}/charge", json={"amount": 25}, headers=ctx["headers"])
    allowed = client.post(EX, json={"input": {"text": "سلام"}}, headers=ctx["headers"])
    assert allowed.status_code == 200

    # deduction applied on completion (online provider, 1 credit per 1000 tokens)
    run_response = client.post(f"{EX}/{allowed.json()['data']['id']}/run", headers=ctx["headers"])
    assert run_response.status_code == 200, run_response.text
    done = run_response.json()["data"]
    assert done["status"] == "COMPLETED"
    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["balance"] == 24  # 25 - 1 (ceil(tokens_out/1000))
    deduction = state["transactions"][0]
    assert deduction["kind"] == "DEDUCTION"


def test_mock_provider_skips_credit_gate(client, monkeypatch):
    """US-1205 analogue: the local/mock provider is exempt from the gate."""
    from backend.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_provider", "mock")
    ctx = _bootstrap_full(client)
    created = client.post(EX, json={"input": {"text": "سلام"}}, headers=ctx["headers"])
    assert created.status_code == 200
    state = client.get(WALLET, headers=ctx["headers"]).json()["data"]
    assert state["balance"] == 50  # untouched
