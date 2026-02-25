from __future__ import annotations

from datetime import datetime

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import fetcher_enabled
from app.db import crud
from app.models.queue import QueueAnalysisRequest, QueueJobResponse
from app.services.queue_management import QueueManagementService

_queue_service: QueueManagementService | None = None


def get_queue_service() -> QueueManagementService:
    global _queue_service
    if _queue_service is None:
        _queue_service = QueueManagementService()
    return _queue_service


def _parse_datetime(value: str) -> datetime:
    cleaned = value.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


async def get_queue_status():
    service = get_queue_service()
    return {
        "available": service.is_available(),
        "fetcher_enabled": fetcher_enabled(),
    }


async def list_cameras_for_queue(session: AsyncSession):
    cameras = await crud.list_cameras(session)
    result = []
    for camera in cameras:
        stream = await crud.get_stream_by_camera(session, camera.id)
        zones = await crud.list_zones(session, camera_id=camera.id)
        first_frame = await crud.get_first_frame(session, camera.id)
        latest_frame = await crud.get_latest_frame(session, camera.id)

        result.append(
            {
                "id": camera.id,
                "name": camera.name,
                "location": camera.location,
                "rtsp_url": camera.rtsp_url,
                "stream_status": stream.status.value if stream else None,
                "zone_count": len(zones),
                "first_frame_time": first_frame.timestamp.isoformat() if first_frame else None,
                "latest_frame_time": latest_frame.timestamp.isoformat() if latest_frame else None,
            }
        )
    return result


async def list_zones_for_queue(session: AsyncSession, camera_id: int):
    camera = await crud.get_camera(session, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    zones = await crud.list_zones(session, camera_id=camera_id)
    return [
        {
            "id": zone.id,
            "name": zone.name,
            "polygon": zone.polygon,
            "created_at": zone.created_at.isoformat(),
        }
        for zone in zones
    ]


async def start_queue_analysis(
    session: AsyncSession,
    request: QueueAnalysisRequest,
    background_tasks: BackgroundTasks,
):
    if not fetcher_enabled():
        raise HTTPException(status_code=503, detail="Queue management only available on fetcher service")

    camera = await crud.get_camera(session, request.camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    zones = await crud.list_zones(session, camera_id=request.camera_id)
    zone = next((item for item in zones if item.id == request.zone_id), None)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found for this camera")

    try:
        start_dt = _parse_datetime(request.start)
        end_dt = _parse_datetime(request.end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {exc}") from exc

    frames = await crud.get_frames_for_range(session, request.camera_id, start_dt, end_dt)
    if not frames:
        raise HTTPException(status_code=404, detail="No frames found for the specified time range")

    job = await crud.create_queue_analysis_job(
        session,
        request.camera_id,
        request.zone_id,
        start_dt,
        end_dt,
    )

    service = get_queue_service()
    zone_polygon = zone.polygon

    async def run_job():
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as bg_session:
            bg_frames = await crud.get_frames_for_range(bg_session, request.camera_id, start_dt, end_dt)
            await service.run_queue_analysis(
                bg_session,
                job.id,
                request.camera_id,
                request.zone_id,
                zone_polygon,
                bg_frames,
            )

    background_tasks.add_task(run_job)

    return {
        "job_id": job.id,
        "status": job.status.value,
        "message": f"Queue analysis started for {len(frames)} frames in zone '{zone.name}'",
    }


async def list_queue_jobs(
    session: AsyncSession,
    camera_id: int | None,
    zone_id: int | None,
):
    jobs = await crud.list_queue_analysis_jobs(session, camera_id=camera_id, zone_id=zone_id)
    return [_job_to_response(job) for job in jobs]


async def get_queue_job(session: AsyncSession, job_id: int):
    job = await crud.get_queue_analysis_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


async def get_queue_results(session: AsyncSession, job_id: int):
    job = await crud.get_queue_analysis_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    frame_results = await crud.get_queue_results_for_job(session, job_id)
    zones = await crud.list_zones(session, camera_id=job.camera_id)
    zone_map = {zone.id: zone.name for zone in zones}

    return {
        "job_id": job.id,
        "camera_id": job.camera_id,
        "zone_id": job.zone_id,
        "zone_name": zone_map.get(job.zone_id),
        "status": job.status.value,
        "max_queue_count": job.max_queue_count,
        "avg_queue_count": job.avg_queue_count,
        "frame_results": [
            {
                "timestamp": result.timestamp.isoformat(),
                "queue_count": result.queue_count,
            }
            for result in frame_results
        ],
    }


def _job_to_response(job) -> QueueJobResponse:
    return QueueJobResponse(
        id=job.id,
        camera_id=job.camera_id,
        zone_id=job.zone_id,
        start_time=job.start_time.isoformat(),
        end_time=job.end_time.isoformat(),
        status=job.status.value,
        total_frames=job.total_frames,
        processed_frames=job.processed_frames,
        max_queue_count=job.max_queue_count,
        avg_queue_count=job.avg_queue_count,
        error=job.error,
        created_at=job.created_at.isoformat(),
    )

