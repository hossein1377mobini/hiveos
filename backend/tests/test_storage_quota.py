"""Per-organization storage quota tests (FR-011, PO request 2026-09-13).

Every tenant shares one volume, so the quota is what stops one organization
from filling the disk and taking the others down. The cap must also be
optional: NULL means unlimited, so an existing organization is never locked
out of its own data by a migration.
"""

import asyncio
import uuid

from backend.api_errors import ApiError
from backend.knowledge.assets import _assert_quota, _org_storage_bytes


def _with_org(quota_mb, assets: list[int], check: int):
    """Run the quota helpers against a real session and a throwaway org."""

    async def _run():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from backend.config import get_settings

        engine = create_async_engine(get_settings().database_url)
        org_id = uuid.uuid4()
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await session.execute(
                    text(
                        "INSERT INTO hiveos.organizations"
                        " (id, tenant_id, name, industry, size, status, storage_quota_mb)"
                        " VALUES (:id, gen_random_uuid(), 'کوتاه', 'tech', 'lt_10',"
                        " 'active', :q)"
                    ),
                    {"id": org_id, "q": quota_mb},
                )
                for size in assets:
                    await session.execute(
                        text(
                            "INSERT INTO hiveos.knowledge_assets"
                            " (id, organization_id, name, storage_path, size_bytes,"
                            "  extension, status)"
                            " VALUES (gen_random_uuid(), :org, 'a.txt', '/tmp/a.txt',"
                            " :s, 'txt', 'ready')"
                        ),
                        {"org": org_id, "s": size},
                    )
                await session.commit()

                class _Org:
                    id = org_id
                    storage_quota_mb = quota_mb

                used = await _org_storage_bytes(session, org_id)
                try:
                    await _assert_quota(session, _Org(), check)
                    return used, None
                except ApiError as exc:
                    return used, exc.code
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_null_quota_means_unlimited(synced_database):
    """An existing organization must keep working after the migration."""
    used, code = _with_org(None, [10_000_000], 500_000_000)
    assert used == 10_000_000
    assert code is None


def test_upload_within_quota_is_allowed(synced_database):
    _used, code = _with_org(100, [50 * 1024 * 1024], 10 * 1024 * 1024)
    assert code is None


def test_upload_past_quota_is_refused(synced_database):
    _used, code = _with_org(100, [95 * 1024 * 1024], 10 * 1024 * 1024)
    assert code == "STORAGE_QUOTA_EXCEEDED"


def test_soft_deleted_assets_stop_counting(synced_database):
    """Deleting a document must return its space to the organization, or the
    quota fills with data the tenant can no longer see."""
    used, _code = _with_org(100, [90 * 1024 * 1024], 1)
    assert used == 90 * 1024 * 1024
