from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from app.core.config import ensure_data_dir, fetcher_enabled
from app.core.container import ServiceContainer, build_service_container
from app.core.logging import configure_logging
from app.db import crud
from app.db.session import AsyncSessionLocal, init_db
from app.services import runtime_config


async def _cleanup_loop(services: ServiceContainer) -> None:
    while True:
        await asyncio.sleep(2.0)
        ingestion_manager = services.ingestion_manager
        if ingestion_manager:
            await ingestion_manager.cleanup_finished()


async def _retention_loop() -> None:
    while True:
        await asyncio.sleep(60.0)
        async with AsyncSessionLocal() as session:
            config_values = await runtime_config.get_runtime_config(session)
            retention_days = config_values.get("retention_days", 7)
            cutoff = datetime.utcnow() - timedelta(days=retention_days)
            frames = await crud.list_frames_older_than(session, cutoff)
            for frame in frames:
                try:
                    Path(frame.path).unlink(missing_ok=True)
                except Exception:
                    pass
            if frames:
                await crud.delete_old_frames(session, cutoff)


def create_lifespan():
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        ensure_data_dir()
        await init_db()

        services = build_service_container(AsyncSessionLocal)
        app.state.services = services

        if services.ingestion_manager:
            services.ingestion_manager.start()
        if services.analytics_engine:
            services.analytics_engine.start()

        tasks = []
        if services.ingestion_manager:
            tasks.append(asyncio.create_task(_cleanup_loop(services)))
            tasks.append(asyncio.create_task(services.ingestion_manager.consume_events()))
        if services.analytics_engine:
            tasks.append(asyncio.create_task(services.analytics_engine.run()))
        if fetcher_enabled():
            tasks.append(asyncio.create_task(_retention_loop()))

        try:
            yield
        finally:
            if services.ingestion_manager:
                services.ingestion_manager.shutdown()
            if services.analytics_engine:
                services.analytics_engine.stop()
            for task in tasks:
                task.cancel()

    return lifespan
