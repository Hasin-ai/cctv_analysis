from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AnalysisJob,
    AnalysisJobStatus,
    Camera,
    FootfallEvent,
    Frame,
    FrameStatus,
    PersonDetection,
    PersonTrack,
    ReconstructionJob,
    ReconstructionStatus,
    RuntimeConfig,
    SegmentStatus,
    Stream,
    StreamStatus,
    VideoSegment,
    Zone,
    QueueAnalysisJob,
    QueueJobStatus,
    QueueFrameResult,
)


async def create_camera(session: AsyncSession, name: str, rtsp_url: str | None, location: str | None) -> Camera:
    camera = Camera(name=name, rtsp_url=rtsp_url, location=location)
    session.add(camera)
    await session.commit()
    await session.refresh(camera)
    return camera


async def list_cameras(session: AsyncSession) -> list[Camera]:
    result = await session.execute(select(Camera).order_by(Camera.id))
    return list(result.scalars())


async def get_camera(session: AsyncSession, camera_id: int) -> Camera | None:
    result = await session.execute(select(Camera).where(Camera.id == camera_id))
    return result.scalar_one_or_none()


async def update_camera(session: AsyncSession, camera: Camera, **updates) -> Camera:
    for key, value in updates.items():
        setattr(camera, key, value)
    session.add(camera)
    await session.commit()
    await session.refresh(camera)
    return camera


async def delete_camera(session: AsyncSession, camera: Camera) -> None:
    await session.delete(camera)
    await session.commit()


async def allocate_port(session: AsyncSession, base_port: int = 8554) -> int:
    result = await session.execute(select(func.max(Stream.port)))
    max_port = result.scalar_one_or_none() or (base_port - 1)
    return max(base_port, (max_port + 1))


async def get_stream_by_camera(session: AsyncSession, camera_id: int) -> Stream | None:
    result = await session.execute(select(Stream).where(Stream.camera_id == camera_id))
    return result.scalar_one_or_none()


async def get_stream(session: AsyncSession, stream_id: int) -> Stream | None:
    result = await session.execute(select(Stream).where(Stream.id == stream_id))
    return result.scalar_one_or_none()


async def list_streams(session: AsyncSession) -> list[Stream]:
    result = await session.execute(select(Stream).order_by(Stream.id))
    return list(result.scalars())


async def delete_stream(session: AsyncSession, stream: Stream) -> None:
    # Stream rows are referenced by historical frame/segment/footfall records.
    # Preserve those records while allowing stream deletion.
    await session.execute(update(Frame).where(Frame.stream_id == stream.id).values(stream_id=None))
    await session.execute(update(VideoSegment).where(VideoSegment.stream_id == stream.id).values(stream_id=None))
    await session.execute(update(FootfallEvent).where(FootfallEvent.stream_id == stream.id).values(stream_id=None))
    await session.delete(stream)
    await session.commit()


async def create_stream(session: AsyncSession, camera_id: int, port: int | None) -> Stream:
    stream = Stream(
        camera_id=camera_id,
        port=port,
        status=StreamStatus.starting,
        started_at=datetime.utcnow(),
    )
    session.add(stream)
    await session.commit()
    await session.refresh(stream)
    return stream


async def update_stream_status(session: AsyncSession, stream: Stream, status: StreamStatus) -> Stream:
    stream.status = status
    if status == StreamStatus.running:
        stream.started_at = stream.started_at or datetime.utcnow()
        stream.stopped_at = None
    if status in {StreamStatus.stopped, StreamStatus.error}:
        stream.stopped_at = datetime.utcnow()
    session.add(stream)
    await session.commit()
    await session.refresh(stream)
    return stream


async def update_stream_heartbeat(session: AsyncSession, stream: Stream, timestamp: datetime) -> None:
    stream.last_heartbeat = timestamp
    if stream.status != StreamStatus.running:
        stream.status = StreamStatus.running
    session.add(stream)
    await session.commit()


async def create_zone(session: AsyncSession, camera_id: int, name: str, polygon: dict, capacity: int | None = None, expected_wait_time_sec: int | None = None) -> Zone:
    zone = Zone(camera_id=camera_id, name=name, polygon=polygon, capacity=capacity, expected_wait_time_sec=expected_wait_time_sec)
    session.add(zone)
    await session.commit()
    await session.refresh(zone)
    return zone


async def list_zones(session: AsyncSession, camera_id: int | None = None) -> list[Zone]:
    stmt = select(Zone)
    if camera_id is not None:
        stmt = stmt.where(Zone.camera_id == camera_id)
    result = await session.execute(stmt.order_by(Zone.id))
    return list(result.scalars())


async def delete_zone(session: AsyncSession, zone: Zone) -> None:
    await session.delete(zone)
    await session.commit()


async def get_zone(session: AsyncSession, zone_id: int) -> Zone | None:
    result = await session.execute(select(Zone).where(Zone.id == zone_id))
    return result.scalar_one_or_none()


async def get_first_zone(session: AsyncSession, camera_id: int) -> Zone | None:
    result = await session.execute(
        select(Zone).where(Zone.camera_id == camera_id).order_by(Zone.id).limit(1)
    )
    return result.scalar_one_or_none()


async def create_frame(
    session: AsyncSession,
    camera_id: int,
    stream_id: int | None,
    path: str,
    timestamp: datetime,
    width: int | None,
    height: int | None,
    size_bytes: int,
) -> Frame:
    existing = await session.execute(select(Frame).where(Frame.path == path))
    frame = existing.scalar_one_or_none()
    if frame:
        return frame
    frame = Frame(
        camera_id=camera_id,
        stream_id=stream_id,
        path=path,
        timestamp=timestamp,
        width=width,
        height=height,
        size_bytes=size_bytes,
        status=FrameStatus.captured,
    )
    session.add(frame)
    await session.commit()
    await session.refresh(frame)
    return frame


async def get_unprocessed_frames(session: AsyncSession, limit: int = 50) -> list[Frame]:
    stmt = (
        select(Frame)
        .where(Frame.status == FrameStatus.captured)
        .order_by(Frame.timestamp)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def mark_frame_processed(session: AsyncSession, frame: Frame) -> None:
    frame.status = FrameStatus.processed
    frame.processed_at = datetime.utcnow()
    session.add(frame)
    await session.commit()


async def get_first_frame(session: AsyncSession, camera_id: int) -> Frame | None:
    result = await session.execute(
        select(Frame).where(Frame.camera_id == camera_id).order_by(Frame.timestamp).limit(1)
    )
    return result.scalar_one_or_none()


async def list_frames_for_camera(
    session: AsyncSession,
    camera_id: int,
    limit: int | None = 500,
    descending: bool = False,
) -> list[Frame]:
    stmt = select(Frame).where(Frame.camera_id == camera_id)
    stmt = stmt.order_by(Frame.timestamp.desc() if descending else Frame.timestamp)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars())


async def delete_frames_for_camera(session: AsyncSession, camera_id: int) -> list[str]:
    result = await session.execute(select(Frame).where(Frame.camera_id == camera_id))
    frames = list(result.scalars())
    paths = [frame.path for frame in frames]
    frame_ids = [frame.id for frame in frames]

    if frame_ids:
        # Manually cascade deletes for SQLite's sake
        from sqlalchemy import delete
        from app.db.models import PersonDetection, QueueFrameResult
        await session.execute(delete(PersonDetection).where(PersonDetection.frame_id.in_(frame_ids)))
        await session.execute(delete(QueueFrameResult).where(QueueFrameResult.frame_id.in_(frame_ids)))

    for frame in frames:
        await session.delete(frame)
    await session.commit()
    return paths


async def delete_segments_for_camera(session: AsyncSession, camera_id: int) -> list[str]:
    result = await session.execute(select(VideoSegment).where(VideoSegment.camera_id == camera_id))
    segments = list(result.scalars())
    paths = [segment.path for segment in segments]
    for segment in segments:
        await session.delete(segment)
    await session.commit()
    return paths


async def delete_reconstruction_jobs_for_camera(session: AsyncSession, camera_id: int) -> list[str]:
    result = await session.execute(select(ReconstructionJob).where(ReconstructionJob.camera_id == camera_id))
    jobs = list(result.scalars())
    output_paths = [job.output_path for job in jobs if job.output_path]
    for job in jobs:
        await session.delete(job)
    await session.commit()
    return output_paths


async def count_cameras_by_rtsp_url(
    session: AsyncSession,
    rtsp_url: str,
    exclude_camera_id: int | None = None,
) -> int:
    stmt = select(func.count(Camera.id)).where(Camera.rtsp_url == rtsp_url)
    if exclude_camera_id is not None:
        stmt = stmt.where(Camera.id != exclude_camera_id)
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def get_latest_frame(session: AsyncSession, camera_id: int) -> Frame | None:
    result = await session.execute(
        select(Frame).where(Frame.camera_id == camera_id).order_by(Frame.timestamp.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def get_frames_for_range(
    session: AsyncSession,
    camera_id: int,
    start: datetime,
    end: datetime,
) -> list[Frame]:
    stmt = (
        select(Frame)
        .where(Frame.camera_id == camera_id)
        .where(Frame.timestamp >= start)
        .where(Frame.timestamp <= end)
        .order_by(Frame.timestamp)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def create_segment(
    session: AsyncSession,
    camera_id: int,
    stream_id: int | None,
    path: str,
    start_time: datetime,
    end_time: datetime,
    duration_seconds: float,
    size_bytes: int,
) -> VideoSegment:
    existing = await session.execute(select(VideoSegment).where(VideoSegment.path == path))
    segment = existing.scalar_one_or_none()
    if segment:
        return segment
    segment = VideoSegment(
        camera_id=camera_id,
        stream_id=stream_id,
        path=path,
        start_time=start_time,
        end_time=end_time,
        duration_seconds=duration_seconds,
        size_bytes=size_bytes,
        status=SegmentStatus.recorded,
    )
    session.add(segment)
    await session.commit()
    await session.refresh(segment)
    return segment


async def get_segments_for_range(
    session: AsyncSession,
    camera_id: int,
    start: datetime,
    end: datetime,
) -> list[VideoSegment]:
    stmt = (
        select(VideoSegment)
        .where(VideoSegment.camera_id == camera_id)
        .where(VideoSegment.end_time >= start)
        .where(VideoSegment.start_time <= end)
        .order_by(VideoSegment.start_time)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def get_unprocessed_segments(session: AsyncSession, limit: int = 20) -> list[VideoSegment]:
    stmt = (
        select(VideoSegment)
        .where(VideoSegment.status == SegmentStatus.recorded)
        .order_by(VideoSegment.start_time)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def mark_segment_processed(session: AsyncSession, segment: VideoSegment) -> None:
    segment.status = SegmentStatus.processed
    segment.processed_at = datetime.utcnow()
    session.add(segment)
    await session.commit()


async def create_reconstruction_job(
    session: AsyncSession,
    camera_id: int,
    start_time: datetime,
    end_time: datetime,
) -> ReconstructionJob:
    job = ReconstructionJob(
        camera_id=camera_id,
        start_time=start_time,
        end_time=end_time,
        status=ReconstructionStatus.pending,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def update_reconstruction_job(
    session: AsyncSession,
    job: ReconstructionJob,
    status: ReconstructionStatus,
    output_path: str | None = None,
    error: str | None = None,
) -> ReconstructionJob:
    job.status = status
    job.output_path = output_path
    job.error = error
    job.updated_at = datetime.utcnow()
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def get_reconstruction_job(session: AsyncSession, job_id: int) -> ReconstructionJob | None:
    result = await session.execute(select(ReconstructionJob).where(ReconstructionJob.id == job_id))
    return result.scalar_one_or_none()


async def list_reconstruction_jobs(session: AsyncSession) -> list[ReconstructionJob]:
    result = await session.execute(select(ReconstructionJob).order_by(ReconstructionJob.id.desc()))
    return list(result.scalars())


async def upsert_runtime_config(session: AsyncSession, key: str, value: dict) -> RuntimeConfig:
    existing = await session.execute(select(RuntimeConfig).where(RuntimeConfig.key == key))
    config = existing.scalar_one_or_none()
    if config:
        config.value = value
        config.updated_at = datetime.utcnow()
    else:
        config = RuntimeConfig(key=key, value=value, updated_at=datetime.utcnow())
    session.add(config)
    await session.commit()
    await session.refresh(config)
    return config


async def list_runtime_config(session: AsyncSession) -> list[RuntimeConfig]:
    result = await session.execute(select(RuntimeConfig).order_by(RuntimeConfig.key))
    return list(result.scalars())


async def get_runtime_config(session: AsyncSession, key: str) -> RuntimeConfig | None:
    result = await session.execute(select(RuntimeConfig).where(RuntimeConfig.key == key))
    return result.scalar_one_or_none()


async def delete_old_segments(session: AsyncSession, cutoff: datetime) -> int:
    result = await session.execute(
        select(VideoSegment).where(VideoSegment.end_time < cutoff)
    )
    segments = list(result.scalars())
    deleted = 0
    for segment in segments:
        await session.delete(segment)
        deleted += 1
    await session.commit()
    return deleted


async def list_segments_older_than(session: AsyncSession, cutoff: datetime) -> list[VideoSegment]:
    result = await session.execute(
        select(VideoSegment).where(VideoSegment.end_time < cutoff)
    )
    return list(result.scalars())


async def delete_old_frames(session: AsyncSession, cutoff: datetime) -> int:
    result = await session.execute(select(Frame).where(Frame.timestamp < cutoff))
    frames = list(result.scalars())
    deleted = 0
    for frame in frames:
        await session.delete(frame)
        deleted += 1
    await session.commit()
    return deleted


async def list_frames_older_than(session: AsyncSession, cutoff: datetime) -> list[Frame]:
    result = await session.execute(select(Frame).where(Frame.timestamp < cutoff))
    return list(result.scalars())


async def count_metrics(session: AsyncSession) -> dict:
    cameras = await session.execute(select(func.count(Camera.id)))
    streams = await session.execute(select(func.count(Stream.id)))
    running_streams = await session.execute(
        select(func.count(Stream.id)).where(Stream.status == StreamStatus.running)
    )
    segments = await session.execute(select(func.count(VideoSegment.id)))
    frames = await session.execute(select(func.count(Frame.id)))
    events = await session.execute(select(func.count(FootfallEvent.id)))
    return {
        "cameras": cameras.scalar_one() or 0,
        "streams": streams.scalar_one() or 0,
        "running_streams": running_streams.scalar_one() or 0,
        "segments": segments.scalar_one() or 0,
        "frames": frames.scalar_one() or 0,
        "footfall_events": events.scalar_one() or 0,
    }


async def create_footfall_event(
    session: AsyncSession,
    camera_id: int,
    stream_id: int | None,
    zone_id: int | None,
    timestamp: datetime,
    count: int,
    event_type: str = "entry",
) -> FootfallEvent:
    event = FootfallEvent(
        camera_id=camera_id,
        stream_id=stream_id,
        zone_id=zone_id,
        timestamp=timestamp,
        event_type=event_type,
        count=count,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return event


def _normalize_footfall_event_type(event_type: str | None) -> str:
    if not event_type:
        return "entry"
    normalized = event_type.strip().lower()
    return "exit" if normalized == "exit" else "entry"


async def query_footfall(
    session: AsyncSession,
    camera_id: int,
    start: datetime | None,
    end: datetime | None,
    zone_id: int | None = None,
) -> dict:
    stmt = select(FootfallEvent).where(FootfallEvent.camera_id == camera_id)
    if zone_id is not None:
        stmt = stmt.where(FootfallEvent.zone_id == zone_id)
    if start is not None:
        stmt = stmt.where(FootfallEvent.timestamp >= start)
    if end is not None:
        stmt = stmt.where(FootfallEvent.timestamp <= end)

    result = await session.execute(stmt.order_by(FootfallEvent.timestamp, FootfallEvent.id))
    events = list(result.scalars())

    zone_rows = await list_zones(session, camera_id=camera_id)
    zone_names = {zone.id: zone.name for zone in zone_rows}

    total_entries = 0
    total_exits = 0
    zone_totals_by_id: dict[int | None, dict] = {}
    series_by_time_zone: dict[tuple[datetime, int | None], dict] = {}
    series: list[dict] = []

    # Always include configured zones even when there are no events yet.
    for zone in zone_rows:
        zone_key = int(zone.id)
        if zone_id is not None and zone_key != zone_id:
            continue
        zone_totals_by_id[zone_key] = {
            "zone_id": zone_key,
            "zone_name": zone.name,
            "total_entries": 0,
            "total_exits": 0,
            "net_flow": 0,
        }

    for event in events:
        event_count = int(event.count or 0)
        normalized_type = _normalize_footfall_event_type(getattr(event, "event_type", None))
        entry_count = event_count if normalized_type == "entry" else 0
        exit_count = event_count if normalized_type == "exit" else 0

        total_entries += entry_count
        total_exits += exit_count

        zone_key = int(event.zone_id) if event.zone_id is not None else None
        bucket = zone_totals_by_id.setdefault(
            zone_key,
            {
                "zone_id": zone_key,
                "zone_name": zone_names.get(zone_key) if zone_key is not None else "Unassigned",
                "total_entries": 0,
                "total_exits": 0,
                "net_flow": 0,
            },
        )
        bucket["total_entries"] += entry_count
        bucket["total_exits"] += exit_count
        bucket["net_flow"] = bucket["total_entries"] - bucket["total_exits"]

        # Group by minute for chart smoothing
        bucket_ts = event.timestamp.replace(second=0, microsecond=0)
        time_key = (bucket_ts, zone_key)

        if time_key not in series_by_time_zone:
            series_by_time_zone[time_key] = {
                "timestamp": bucket_ts.isoformat(),
                "zone_id": zone_key,
                "event_type": "aggregated",
                "count": 0,
                "entry_count": 0,
                "exit_count": 0,
                "net_count": 0,
            }

        series_by_time_zone[time_key]["count"] += event_count
        series_by_time_zone[time_key]["entry_count"] += entry_count
        series_by_time_zone[time_key]["exit_count"] += exit_count
        series_by_time_zone[time_key]["net_count"] += entry_count - exit_count

    # Sort the aggregated series chronologically
    sorted_time_keys = sorted(series_by_time_zone.keys(), key=lambda k: (k[0], k[1] or 0))
    for k in sorted_time_keys:
        series.append(series_by_time_zone[k])

    zone_totals = list(zone_totals_by_id.values())
    zone_totals.sort(
        key=lambda item: (
            item["zone_id"] is None,
            item["zone_id"] if item["zone_id"] is not None else 0,
        )
    )

    return {
        "total": total_entries,
        "total_entries": total_entries,
        "total_exits": total_exits,
        "net_flow": total_entries - total_exits,
        "series": series,
        "zone_totals": zone_totals,
    }


# Analysis Job CRUD
async def create_analysis_job(
    session: AsyncSession,
    camera_id: int,
    start_time: datetime,
    end_time: datetime,
) -> AnalysisJob:
    job = AnalysisJob(
        camera_id=camera_id,
        start_time=start_time,
        end_time=end_time,
        status=AnalysisJobStatus.pending,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def get_analysis_job(session: AsyncSession, job_id: int) -> AnalysisJob | None:
    result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
    return result.scalar_one_or_none()


async def list_analysis_jobs(session: AsyncSession, camera_id: int | None = None) -> list[AnalysisJob]:
    stmt = select(AnalysisJob)
    if camera_id is not None:
        stmt = stmt.where(AnalysisJob.camera_id == camera_id)
    result = await session.execute(stmt.order_by(AnalysisJob.id.desc()))
    return list(result.scalars())


async def update_analysis_job(
    session: AsyncSession,
    job: AnalysisJob,
    status: AnalysisJobStatus | None = None,
    total_frames: int | None = None,
    processed_frames: int | None = None,
    unique_persons: int | None = None,
    error: str | None = None,
) -> AnalysisJob:
    if status is not None:
        job.status = status
    if total_frames is not None:
        job.total_frames = total_frames
    if processed_frames is not None:
        job.processed_frames = processed_frames
    if unique_persons is not None:
        job.unique_persons = unique_persons
    if error is not None:
        job.error = error
    job.updated_at = datetime.utcnow()
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


# Person Track CRUD
async def create_person_track(
    session: AsyncSession,
    job_id: int,
    track_id: int,
    camera_id: int,
    zone_id: int | None,
    first_seen: datetime,
    last_seen: datetime,
    appearances: int = 1,
    avg_confidence: float = 0.0,
    dwell_seconds: float = 0.0,
) -> PersonTrack:
    track = PersonTrack(
        job_id=job_id,
        track_id=track_id,
        camera_id=camera_id,
        zone_id=zone_id,
        first_seen=first_seen,
        last_seen=last_seen,
        appearances=appearances,
        avg_confidence=avg_confidence,
        dwell_seconds=dwell_seconds,
    )
    session.add(track)
    await session.commit()
    await session.refresh(track)
    return track


async def get_tracks_for_job(session: AsyncSession, job_id: int) -> list[PersonTrack]:
    result = await session.execute(
        select(PersonTrack).where(PersonTrack.job_id == job_id).order_by(PersonTrack.track_id)
    )
    return list(result.scalars())


async def get_tracks_for_zone(session: AsyncSession, job_id: int, zone_id: int) -> list[PersonTrack]:
    result = await session.execute(
        select(PersonTrack)
        .where(PersonTrack.job_id == job_id)
        .where(PersonTrack.zone_id == zone_id)
        .order_by(PersonTrack.track_id)
    )
    return list(result.scalars())


async def update_person_track(
    session: AsyncSession,
    track: PersonTrack,
    last_seen: datetime | None = None,
    appearances: int | None = None,
    avg_confidence: float | None = None,
    dwell_seconds: float | None = None,
) -> PersonTrack:
    if last_seen is not None:
        track.last_seen = last_seen
    if appearances is not None:
        track.appearances = appearances
    if avg_confidence is not None:
        track.avg_confidence = avg_confidence
    if dwell_seconds is not None:
        track.dwell_seconds = dwell_seconds
    session.add(track)
    await session.commit()
    await session.refresh(track)
    return track


# Person Detection CRUD
async def create_person_detection(
    session: AsyncSession,
    track_id: int,
    frame_id: int,
    bbox_x1: float,
    bbox_y1: float,
    bbox_x2: float,
    bbox_y2: float,
    confidence: float,
    in_zone_id: int | None,
    timestamp: datetime,
) -> PersonDetection:
    detection = PersonDetection(
        track_id=track_id,
        frame_id=frame_id,
        bbox_x1=bbox_x1,
        bbox_y1=bbox_y1,
        bbox_x2=bbox_x2,
        bbox_y2=bbox_y2,
        confidence=confidence,
        in_zone_id=in_zone_id,
        timestamp=timestamp,
    )
    session.add(detection)
    await session.commit()
    await session.refresh(detection)
    return detection


async def get_detections_for_frame(session: AsyncSession, frame_id: int) -> list[PersonDetection]:
    result = await session.execute(
        select(PersonDetection).where(PersonDetection.frame_id == frame_id)
    )
    return list(result.scalars())


async def get_tracking_detections_for_job(session: AsyncSession, job_id: int) -> dict[int, list[dict]]:
    result = await session.execute(
        select(
            PersonDetection.frame_id,
            PersonDetection.bbox_x1,
            PersonDetection.bbox_y1,
            PersonDetection.bbox_x2,
            PersonDetection.bbox_y2,
            PersonDetection.confidence,
            PersonDetection.in_zone_id,
            PersonTrack.track_id,
        )
        .join(PersonTrack, PersonDetection.track_id == PersonTrack.id)
        .where(PersonTrack.job_id == job_id)
        .order_by(PersonDetection.frame_id, PersonTrack.track_id)
    )

    by_frame: dict[int, list[dict]] = {}
    for row in result.all():
        frame_id = int(row.frame_id)
        by_frame.setdefault(frame_id, []).append(
            {
                "track_id": int(row.track_id),
                "bbox_x1": float(row.bbox_x1),
                "bbox_y1": float(row.bbox_y1),
                "bbox_x2": float(row.bbox_x2),
                "bbox_y2": float(row.bbox_y2),
                "confidence": float(row.confidence),
                "zone_id": int(row.in_zone_id) if row.in_zone_id is not None else None,
            }
        )

    return by_frame


async def get_zone_stats_for_job(session: AsyncSession, job_id: int) -> list[dict]:
    """Get aggregate statistics per zone for an analysis job."""
    tracks = await get_tracks_for_job(session, job_id)
    
    zone_stats: dict[int, dict] = {}
    for track in tracks:
        if track.zone_id is None:
            zone_key = 0  # No zone
        else:
            zone_key = track.zone_id
            
        if zone_key not in zone_stats:
            zone_stats[zone_key] = {
                "zone_id": track.zone_id,
                "unique_persons": 0,
                "total_appearances": 0,
                "total_dwell_seconds": 0.0,
            }
        zone_stats[zone_key]["unique_persons"] += 1
        zone_stats[zone_key]["total_appearances"] += track.appearances
        zone_stats[zone_key]["total_dwell_seconds"] += track.dwell_seconds
    
    return list(zone_stats.values())


# Queue Management CRUD
async def create_queue_analysis_job(
    session: AsyncSession,
    camera_id: int,
    zone_id: int,
    start_time: datetime,
    end_time: datetime,
) -> QueueAnalysisJob:
    job = QueueAnalysisJob(
        camera_id=camera_id,
        zone_id=zone_id,
        start_time=start_time,
        end_time=end_time,
        status=QueueJobStatus.pending,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def get_queue_analysis_job(session: AsyncSession, job_id: int) -> QueueAnalysisJob | None:
    result = await session.execute(select(QueueAnalysisJob).where(QueueAnalysisJob.id == job_id))
    return result.scalar_one_or_none()


async def list_queue_analysis_jobs(
    session: AsyncSession,
    camera_id: int | None = None,
    zone_id: int | None = None,
) -> list[QueueAnalysisJob]:
    stmt = select(QueueAnalysisJob)
    if camera_id is not None:
        stmt = stmt.where(QueueAnalysisJob.camera_id == camera_id)
    if zone_id is not None:
        stmt = stmt.where(QueueAnalysisJob.zone_id == zone_id)
    result = await session.execute(stmt.order_by(QueueAnalysisJob.id.desc()))
    return list(result.scalars())


async def update_queue_analysis_job(
    session: AsyncSession,
    job: QueueAnalysisJob,
    status: QueueJobStatus | None = None,
    total_frames: int | None = None,
    processed_frames: int | None = None,
    max_queue_count: int | None = None,
    avg_queue_count: float | None = None,
    avg_wait_time_sec: float | None = None,
    avg_throughput_exits_per_sec: float | None = None,
    error: str | None = None,
) -> QueueAnalysisJob:
    if status is not None:
        job.status = status
    if total_frames is not None:
        job.total_frames = total_frames
    if processed_frames is not None:
        job.processed_frames = processed_frames
    if max_queue_count is not None:
        job.max_queue_count = max_queue_count
    if avg_queue_count is not None:
        job.avg_queue_count = avg_queue_count
    if avg_wait_time_sec is not None:
        job.avg_wait_time_sec = avg_wait_time_sec
    if avg_throughput_exits_per_sec is not None:
        job.avg_throughput_exits_per_sec = avg_throughput_exits_per_sec
    if error is not None:
        job.error = error
    
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def create_queue_frame_result(
    session: AsyncSession,
    job_id: int,
    frame_id: int,
    timestamp: datetime,
    queue_count: int,
    wait_time_sec: float | None = None,
    throughput_exits_per_sec: float | None = None,
) -> QueueFrameResult:
    result = QueueFrameResult(
        job_id=job_id,
        frame_id=frame_id,
        timestamp=timestamp,
        queue_count=queue_count,
        wait_time_sec=wait_time_sec,
        throughput_exits_per_sec=throughput_exits_per_sec,
    )
    session.add(result)
    await session.commit()
    await session.refresh(result)
    return result


async def get_queue_results_for_job(session: AsyncSession, job_id: int) -> list[QueueFrameResult]:
    result = await session.execute(
        select(QueueFrameResult)
        .where(QueueFrameResult.job_id == job_id)
        .order_by(QueueFrameResult.timestamp)
    )
    return list(result.scalars())
