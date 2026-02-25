from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import fetcher_enabled
from app.db import crud


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    cleaned = value.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


async def create_zone(session: AsyncSession, camera_id: int, name: str, polygon: dict):
    camera = await crud.get_camera(session, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return await crud.create_zone(session, camera_id, name, polygon)


async def list_zones(session: AsyncSession, camera_id: int | None):
    return await crud.list_zones(session, camera_id=camera_id)


async def delete_zone(session: AsyncSession, zone_id: int):
    zone = await crud.get_zone(session, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    await crud.delete_zone(session, zone)



async def zone_preview(
    session: AsyncSession,
    camera_id: int,
):
    if not fetcher_enabled():
        raise HTTPException(status_code=503, detail="Zone preview available only on fetcher")

    camera = await crud.get_camera(session, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    latest = await crud.get_latest_frame(session, camera_id)
    if not latest:
        raise HTTPException(
            status_code=404,
            detail="No captured frames found for this camera yet. Start capture and wait a few seconds.",
        )

    if Path(latest.path).exists():
        return FileResponse(latest.path, media_type="image/jpeg")

    raise HTTPException(
        status_code=404,
        detail="Latest captured frame file is missing on disk. Re-capture this camera.",
    )


async def get_footfall(
    session: AsyncSession,
    camera_id: int,
    start: str | None,
    end: str | None,
    zone_id: int | None,
):
    camera = await crud.get_camera(session, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    start_dt = _parse_datetime(start)
    end_dt = _parse_datetime(end)

    payload = await crud.query_footfall(
        session=session,
        camera_id=camera_id,
        start=start_dt,
        end=end_dt,
        zone_id=zone_id,
    )

    return {
        "camera_id": camera_id,
        "zone_id": zone_id,
        "total": int(payload.get("total", 0)),
        "total_entries": int(payload.get("total_entries", 0)),
        "total_exits": int(payload.get("total_exits", 0)),
        "net_flow": int(payload.get("net_flow", 0)),
        "series": list(payload.get("series", [])),
        "zone_totals": list(payload.get("zone_totals", [])),
    }
