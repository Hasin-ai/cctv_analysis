from __future__ import annotations

from typing import Callable

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import models as _models  # noqa: F401  # ensure model tables are registered on Base.metadata
from app.db.base import Base


async def _create_all(conn) -> None:
    await conn.run_sync(Base.metadata.create_all)


async def _create_all_v3(conn) -> None:
    await conn.run_sync(Base.metadata.create_all)


async def _create_all_v4(conn) -> None:
    await conn.run_sync(Base.metadata.create_all)


def _has_column(sync_conn, table_name: str, column_name: str) -> bool:
    inspector = inspect(sync_conn)
    columns = inspector.get_columns(table_name)
    return any(column.get("name") == column_name for column in columns)


async def _ensure_column(conn, table_name: str, column_name: str, definition: str) -> None:
    exists = await conn.run_sync(lambda sync_conn: _has_column(sync_conn, table_name, column_name))
    if exists:
        return
    await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))


async def _create_all_v5(conn) -> None:
    await conn.run_sync(Base.metadata.create_all)
    await _ensure_column(conn, "footfall_events", "event_type", "VARCHAR(20) NOT NULL DEFAULT 'entry'")


async def _create_all_v6(conn) -> None:
    await conn.run_sync(Base.metadata.create_all)
    await _ensure_column(conn, "zones", "capacity", "INTEGER")
    await _ensure_column(conn, "zones", "expected_wait_time_sec", "INTEGER")


MIGRATIONS: list[Callable] = [
    _create_all,
    _create_all,
    _create_all_v3,
    _create_all_v4,
    _create_all_v5,
    _create_all_v6,
]


async def apply_migrations(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id INTEGER PRIMARY KEY,
                    version INTEGER NOT NULL
                )
                """
            )
        )
        result = await conn.execute(
            text("SELECT version FROM schema_migrations ORDER BY id DESC LIMIT 1")
        )
        current = result.scalar_one_or_none() or 0

        for idx, migration in enumerate(MIGRATIONS, start=1):
            if idx <= current:
                continue
            await migration(conn)
            await conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": idx},
            )
