from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import fetcher_enabled
from app.db import crud
from app.db.models import AnalysisJobStatus
from app.db.session import AsyncSessionLocal
from app.models.analyzer import (
    AnalysisJobResponse,
    AnalysisRequest,
    TotalPersonDetectionRequest,
)
from app.services.person_tracking import PersonTrackingService
from app.services.total_person_detection import TotalPersonDetectionService

_tracking_service: PersonTrackingService | None = None
_total_person_service: TotalPersonDetectionService | None = None


def get_tracking_service() -> PersonTrackingService:
    global _tracking_service
    if _tracking_service is None:
        _tracking_service = PersonTrackingService()
    return _tracking_service


def get_total_person_service() -> TotalPersonDetectionService:
    global _total_person_service
    if _total_person_service is None:
        _total_person_service = TotalPersonDetectionService()
    return _total_person_service


def _parse_datetime(value: str) -> datetime:
    cleaned = value.replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def _to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


async def get_analyzer_status():
    service = get_tracking_service()
    return {
        "available": service.is_available(),
        "fetcher_enabled": fetcher_enabled(),
    }


async def list_cameras_for_analysis(session: AsyncSession):
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
                "stream_port": stream.port if stream else None,
                "zone_count": len(zones),
                "first_frame_time": first_frame.timestamp.isoformat() if first_frame else None,
                "latest_frame_time": latest_frame.timestamp.isoformat() if latest_frame else None,
            }
        )
    return result


async def list_zones_for_camera(session: AsyncSession, camera_id: int):
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


async def start_analysis(
    session: AsyncSession,
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
):
    if not fetcher_enabled():
        raise HTTPException(status_code=503, detail="Analyzer only available on fetcher service")

    camera = await crud.get_camera(session, request.camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    try:
        start_dt = _parse_datetime(request.start)
        end_dt = _parse_datetime(request.end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {exc}") from exc
    start_query_dt = _to_utc_naive(start_dt)
    end_query_dt = _to_utc_naive(end_dt)

    if end_query_dt < start_query_dt:
        raise HTTPException(status_code=400, detail="end must be greater than or equal to start")

    fallback_used = False
    frames = await crud.get_frames_for_range(session, request.camera_id, start_query_dt, end_query_dt)
    if not frames:
        latest_frame = await crud.get_latest_frame(session, request.camera_id)
        if latest_frame is not None:
            fallback_end = latest_frame.timestamp
            fallback_start = fallback_end - timedelta(minutes=30)
            fallback_frames = await crud.get_frames_for_range(
                session,
                request.camera_id,
                fallback_start,
                fallback_end,
            )
            if fallback_frames:
                frames = fallback_frames
                start_query_dt = fallback_frames[0].timestamp
                end_query_dt = fallback_frames[-1].timestamp
                fallback_used = True

    if not frames:
        raise HTTPException(status_code=404, detail="No frames found for the specified time range")

    zones = await crud.list_zones(session, camera_id=request.camera_id)
    if request.zone_id is not None:
        zones = [zone for zone in zones if int(zone.id) == int(request.zone_id)]
        if not zones:
            raise HTTPException(status_code=404, detail="Requested zone was not found for this camera")

    service = get_tracking_service()
    if not service.is_available():
        raise HTTPException(status_code=503, detail=service.error_message())

    job = await crud.create_analysis_job(session, request.camera_id, start_query_dt, end_query_dt)

    async def _run_background_job() -> None:
        async with AsyncSessionLocal() as bg_session:
            bg_frames = await crud.get_frames_for_range(
                bg_session,
                request.camera_id,
                start_query_dt,
                end_query_dt,
            )
            bg_zones = await crud.list_zones(bg_session, camera_id=request.camera_id)
            if request.zone_id is not None:
                bg_zones = [zone for zone in bg_zones if int(zone.id) == int(request.zone_id)]

            if not bg_frames:
                bg_job = await crud.get_analysis_job(bg_session, job.id)
                if bg_job is not None:
                    await crud.update_analysis_job(
                        bg_session,
                        bg_job,
                        status=AnalysisJobStatus.failed,
                        total_frames=0,
                        processed_frames=0,
                        unique_persons=0,
                        error="No frames found for the specified time range",
                    )
                return

            await service.run_analysis(
                bg_session,
                job_id=job.id,
                camera_id=request.camera_id,
                frames=bg_frames,
                zones=bg_zones,
            )

    background_tasks.add_task(_run_background_job)
    return {
        "job_id": job.id,
        "status": job.status.value,
        "message": "Analysis job queued using latest available frames" if fallback_used else "Analysis job queued",
    }


async def detect_total_persons(
    session: AsyncSession,
    request: TotalPersonDetectionRequest,
):
    if not fetcher_enabled():
        raise HTTPException(status_code=503, detail="Total person detection available only on fetcher service")

    camera = await crud.get_camera(session, request.camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    try:
        start_dt = _parse_datetime(request.start)
        end_dt = _parse_datetime(request.end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {exc}") from exc

    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="end must be greater than or equal to start")

    frames = await crud.get_frames_for_range(session, request.camera_id, start_dt, end_dt)
    if not frames:
        raise HTTPException(status_code=404, detail="No frames found for the specified time range")

    service = get_total_person_service()
    if not service.is_available():
        raise HTTPException(status_code=503, detail="YOLO detector is unavailable for total person detection")

    result = await asyncio.to_thread(service.analyze_frames, frames)
    return {
        "camera_id": request.camera_id,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "detector_available": bool(result.get("available", False)),
        "processed_frames": int(result.get("processed_frames", 0)),
        "total_person_detections": int(result.get("total_person_detections", 0)),
        "max_person_count": int(result.get("max_person_count", 0)),
        "avg_person_count": float(result.get("avg_person_count", 0.0)),
        "series": result.get("series", []),
    }


async def list_analysis_jobs(session: AsyncSession, camera_id: int | None):
    jobs = await crud.list_analysis_jobs(session, camera_id=camera_id)
    return [_job_to_response(job) for job in jobs]


async def get_analysis_job(session: AsyncSession, job_id: int):
    job = await crud.get_analysis_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


async def get_analysis_stats(session: AsyncSession, job_id: int):
    job = await crud.get_analysis_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    zone_stats = await crud.get_zone_stats_for_job(session, job_id)

    zones = await crud.list_zones(session, camera_id=job.camera_id)
    zone_map = {zone.id: zone.name for zone in zones}

    enhanced_stats = []
    for stat in zone_stats:
        zone_id = stat.get("zone_id")
        enhanced_stats.append(
            {
                "zone_id": zone_id,
                "zone_name": zone_map.get(zone_id) if zone_id else "Outside zones",
                "unique_persons": stat["unique_persons"],
                "total_appearances": stat["total_appearances"],
                "total_dwell_seconds": stat["total_dwell_seconds"],
            }
        )

    return {
        "job_id": job.id,
        "camera_id": job.camera_id,
        "status": job.status.value,
        "unique_persons": job.unique_persons,
        "zone_stats": enhanced_stats,
        "start_time": job.start_time.isoformat(),
        "end_time": job.end_time.isoformat(),
    }


async def get_person_tracks(session: AsyncSession, job_id: int, zone_id: int | None):
    job = await crud.get_analysis_job(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if zone_id is not None:
        tracks = await crud.get_tracks_for_zone(session, job_id, zone_id)
    else:
        tracks = await crud.get_tracks_for_job(session, job_id)

    return [
        {
            "id": track.id,
            "track_id": track.track_id,
            "zone_id": track.zone_id,
            "first_seen": track.first_seen.isoformat(),
            "last_seen": track.last_seen.isoformat(),
            "appearances": track.appearances,
            "avg_confidence": track.avg_confidence,
            "dwell_seconds": track.dwell_seconds,
        }
        for track in tracks
    ]


def _job_to_response(job) -> AnalysisJobResponse:
    return AnalysisJobResponse(
        id=job.id,
        camera_id=job.camera_id,
        start_time=job.start_time.isoformat(),
        end_time=job.end_time.isoformat(),
        status=job.status.value,
        total_frames=job.total_frames,
        processed_frames=job.processed_frames,
        unique_persons=job.unique_persons,
        error=job.error,
        created_at=job.created_at.isoformat(),
    )
