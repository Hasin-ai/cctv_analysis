from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.container import ServiceContainer
from app.db import crud
from app.db.models import StreamStatus
from app.schemas import CameraCreate, CameraUpdate

_INGESTION_STOP_TIMEOUT_SECONDS = 8.0
_INGESTION_STOP_POLL_SECONDS = 0.1


async def create_camera(session: AsyncSession, payload: CameraCreate):
    return await crud.create_camera(session, payload.name, payload.rtsp_url, payload.location)


async def list_cameras(session: AsyncSession):
    return await crud.list_cameras(session)


async def get_camera(session: AsyncSession, camera_id: int):
    return await _get_camera_or_404(session, camera_id)


async def update_camera(
    session: AsyncSession,
    services: ServiceContainer,
    camera_id: int,
    payload: CameraUpdate,
):
    camera = await _get_camera_or_404(session, camera_id)
    previous_rtsp_url = camera.rtsp_url
    updates = payload.model_dump(exclude_unset=True)
    updated = await crud.update_camera(session, camera, **updates)

    source_changed = "rtsp_url" in updates and updates.get("rtsp_url") != previous_rtsp_url
    if source_changed:
        stream = await crud.get_stream_by_camera(session, camera_id)
        if stream:
            await _wait_for_ingestion_stop(services, stream.id)
            await crud.update_stream_status(session, stream, StreamStatus.stopped)
        frame_paths = await crud.delete_frames_for_camera(session, camera_id)
        _remove_data_files(frame_paths)

    return updated


async def delete_camera(
    session: AsyncSession,
    services: ServiceContainer,
    camera_id: int,
) -> None:
    camera = await _get_camera_or_404(session, camera_id)

    stream = await crud.get_stream_by_camera(session, camera_id)
    if stream:
        await _wait_for_ingestion_stop(services, stream.id)

    uploaded_source_path = await _uploaded_source_path_to_remove(session, camera_id, camera.rtsp_url)
    frame_paths = await crud.delete_frames_for_camera(session, camera_id)
    segment_paths = await crud.delete_segments_for_camera(session, camera_id)
    reconstruction_paths = await crud.delete_reconstruction_jobs_for_camera(session, camera_id)
    await crud.delete_camera(session, camera)
    _remove_data_files(
        [
            *frame_paths,
            *segment_paths,
            *reconstruction_paths,
            *([str(uploaded_source_path)] if uploaded_source_path else []),
        ]
    )
    _remove_camera_data_dirs(camera_id)


async def _get_camera_or_404(session: AsyncSession, camera_id: int):
    camera = await crud.get_camera(session, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera


def _remove_data_files(paths: list[str]) -> None:
    for raw in paths:
        try:
            path = _resolve_data_path(raw)
            if path is None:
                continue
        except Exception:
            continue
        try:
            path.unlink(missing_ok=True)
        except Exception:
            # Best-effort cleanup only.
            pass


def _remove_camera_data_dirs(camera_id: int) -> None:
    for directory in (
        Path(settings.frames_dir).resolve() / f"camera_{camera_id}",
        Path(settings.segments_dir).resolve() / f"camera_{camera_id}",
    ):
        try:
            shutil.rmtree(directory)
        except FileNotFoundError:
            continue
        except Exception:
            # Best-effort cleanup only.
            continue


def _resolve_data_path(raw: str) -> Path | None:
    candidate = Path(raw).resolve()
    roots = (
        Path(settings.frames_dir).resolve(),
        Path(settings.segments_dir).resolve(),
        Path(settings.reconstructions_dir).resolve(),
        Path(settings.uploads_dir).resolve(),
    )
    for root in roots:
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    return None


async def _uploaded_source_path_to_remove(
    session: AsyncSession,
    camera_id: int,
    source_url: str | None,
) -> Path | None:
    if not source_url:
        return None

    parsed = urlparse(source_url)
    if parsed.scheme.lower() != "file":
        return None

    raw_path = unquote(parsed.path or "")
    if parsed.netloc and parsed.netloc not in {"", "localhost"}:
        raw_path = f"//{parsed.netloc}{raw_path}"

    resolved_path = _resolve_data_path(raw_path)
    if resolved_path is None:
        return None

    uploads_root = Path(settings.uploads_dir).resolve()
    try:
        resolved_path.relative_to(uploads_root)
    except ValueError:
        return None

    in_use_count = await crud.count_cameras_by_rtsp_url(
        session,
        source_url,
        exclude_camera_id=camera_id,
    )
    if in_use_count > 0:
        return None

    return resolved_path


async def _wait_for_ingestion_stop(services: ServiceContainer, stream_id: int) -> None:
    ingestion_manager = services.ingestion_manager
    if not ingestion_manager:
        return

    ingestion_manager.stop_ingestion(stream_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _INGESTION_STOP_TIMEOUT_SECONDS
    while ingestion_manager.is_running(stream_id):
        if loop.time() >= deadline:
            raise HTTPException(
                status_code=503,
                detail="Capture worker is still stopping. Retry in a few seconds.",
            )
        await asyncio.sleep(_INGESTION_STOP_POLL_SECONDS)
