"""store_db.py — PostgreSQL helpers for Ascent Terminal.

Manages:
  - Async connection pool (SQLAlchemy 2 async)
  - Schema initialisation
  - CRUD helpers used by other modules
  - Privacy export / delete helpers
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://ascent:changeme@localhost:5432/ascent_db")
# SQLAlchemy async requires asyncpg driver
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


class DatabaseManager:
    def __init__(self) -> None:
        self._engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init_schema(self) -> None:
        """Create tables if they don’t exist."""
        async with self._engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS webhook_events (
                    id          SERIAL PRIMARY KEY,
                    api_key     TEXT,
                    symbol      TEXT,
                    action      TEXT,
                    payload     JSONB,
                    received_at TIMESTAMPTZ DEFAULT NOW()
                )
            """))
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id          SERIAL PRIMARY KEY,
                    api_key     TEXT,
                    endpoint    TEXT,
                    status_code INT,
                    ts          TIMESTAMPTZ DEFAULT NOW()
                )
            """))

    async def export_user_data(self, api_key: str) -> dict[str, Any]:
        """Return all records associated with *api_key*."""
        async with self._session_factory() as session:
            webhooks = (
                await session.execute(
                    text("SELECT * FROM webhook_events WHERE api_key = :k"),
                    {"k": api_key},
                )
            ).mappings().all()
            audit = (
                await session.execute(
                    text("SELECT * FROM audit_log WHERE api_key = :k"),
                    {"k": api_key},
                )
            ).mappings().all()
        return {"webhook_events": [dict(r) for r in webhooks], "audit_log": [dict(r) for r in audit]}

    async def delete_user_data(self, api_key: str) -> int:
        """Delete all records for *api_key*. Returns total rows deleted."""
        async with self._session_factory() as session:
            async with session.begin():
                r1 = await session.execute(
                    text("DELETE FROM webhook_events WHERE api_key = :k"), {"k": api_key}
                )
                r2 = await session.execute(
                    text("DELETE FROM audit_log WHERE api_key = :k"), {"k": api_key}
                )
        return (r1.rowcount or 0) + (r2.rowcount or 0)

    async def log_request(self, api_key: str, endpoint: str, status_code: int) -> None:
        """Append an audit log entry."""
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO audit_log (api_key, endpoint, status_code) "
                        "VALUES (:k, :e, :s)"
                    ),
                    {"k": api_key, "e": endpoint, "s": status_code},
                )
