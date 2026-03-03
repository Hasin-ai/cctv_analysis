from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rtsp import resolve_rtsp_url
from app.db import crud
from app.db.session import AsyncSessionLocal
from app.services.monitoring import collect_metrics
from app.services.realtime_monitoring import get_realtime_monitoring_service
from app.services.zone_crop import crop_image_to_zone
from app.services.zone_geometry import line_points_from_polygon

_analytics_running = False
_SOURCE_FRAME_TIMEOUT_SECONDS = 12


def _is_entry_exit_mode(analytics_mode: str | None) -> bool:
    return (analytics_mode or "").strip().lower() == "entry_exit_count"


def _draw_entry_exit_lines(cv2: Any, frame: Any, zones: list[Any]) -> None:
    if not zones:
        return

    frame_height, frame_width = frame.shape[:2]
    if frame_width <= 0 or frame_height <= 0:
        return

    line_thickness = max(2, int(round(min(frame_width, frame_height) / 540)))
    for zone in zones:
        polygon = getattr(zone, "polygon", None)
        entry_line = line_points_from_polygon(polygon, frame_width, frame_height, line_key="entry_line")
        if entry_line is None:
            entry_line = line_points_from_polygon(polygon, frame_width, frame_height, line_key="entry_exit_line")
        exit_line = line_points_from_polygon(polygon, frame_width, frame_height, line_key="exit_line")

        if entry_line is not None:
            cv2.line(
                frame,
                (int(round(entry_line[0][0])), int(round(entry_line[0][1]))),
                (int(round(entry_line[1][0])), int(round(entry_line[1][1]))),
                (90, 200, 120),
                line_thickness,
                cv2.LINE_AA,
            )
        if exit_line is not None:
            cv2.line(
                frame,
                (int(round(exit_line[0][0])), int(round(exit_line[0][1]))),
                (int(round(exit_line[1][0])), int(round(exit_line[1][1]))),
                (70, 90, 230),
                line_thickness,
                cv2.LINE_AA,
            )


def _render_entry_exit_lines(payload: bytes, zones: list[Any]) -> bytes:
    if not payload or not zones:
        return payload
    try:
        import cv2
        import numpy as np

        arr = np.frombuffer(payload, np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            return payload
        _draw_entry_exit_lines(cv2, image, zones)
        success, encoded = cv2.imencode(".jpg", image)
        if success:
            return encoded.tobytes()
    except Exception:
        return payload
    return payload


async def _resolve_existing_frame(
    session: AsyncSession,
    camera_id: int,
    *,
    prefer_first: bool,
):
    preferred = await (crud.get_first_frame(session, camera_id) if prefer_first else crud.get_latest_frame(session, camera_id))
    if preferred and Path(preferred.path).exists():
        return preferred

    # Fall back to scanning all frame rows when stale DB rows reference deleted files.
    # This avoids false "no frame" responses when early rows are stale but newer files exist.
    frames = await crud.list_frames_for_camera(
        session,
        camera_id,
        limit=None,
        descending=not prefer_first,
    )
    for frame in frames:
        if Path(frame.path).exists():
            return frame
    return None


async def metrics(session: AsyncSession):
    return await collect_metrics(session)


def analytics_state() -> dict[str, bool]:
    return {"running": _analytics_running}


def start_analytics() -> dict[str, bool]:
    global _analytics_running
    _analytics_running = True
    return {"running": _analytics_running}


def stop_analytics() -> dict[str, bool]:
    global _analytics_running
    _analytics_running = False
    return {"running": _analytics_running}


async def realtime(session: AsyncSession, camera_ids: list[int] | None = None):
    all_cameras = await crud.list_cameras(session)
    if camera_ids:
        camera_filter = set(camera_ids)
        cameras = [camera for camera in all_cameras if camera.id in camera_filter]
    else:
        cameras = all_cameras

    service = get_realtime_monitoring_service()
    analytics_running = _analytics_running
    output = []
    for camera in cameras:
        stream = await crud.get_stream_by_camera(session, camera.id)
        zones = await crud.list_zones(session, camera_id=camera.id)
        latest_frame = await crud.get_latest_frame(session, camera.id)

        has_frame = latest_frame is not None and Path(latest_frame.path).exists()
        frame_timestamp = latest_frame.timestamp.isoformat() if latest_frame else None

        if analytics_running and has_frame and latest_frame:
            result = await asyncio.to_thread(service.count_people, latest_frame.path, zones)
            zone_counts = result["zone_counts"]
            detection_boxes = result.get("detection_boxes", [])
            total_people_in_zones = int(result["total_in_zones"])
            # Person counting is zone-constrained by requirement.
            total_detected_people = total_people_in_zones
        else:
            zone_counts = {zone.id: 0 for zone in zones}
            detection_boxes = []
            total_detected_people = 0
            total_people_in_zones = 0

        zone_rows = [
            {
                "zone_id": zone.id,
                "zone_name": zone.name,
                "person_count": int(zone_counts.get(zone.id, 0)),
            }
            for zone in zones
        ]

        output.append(
            {
                "camera_id": camera.id,
                "camera_name": camera.name,
                "stream_status": stream.status.value if stream else "stopped",
                "frame_timestamp": frame_timestamp,
                "has_live_frame": has_frame,
                "total_person_count": total_people_in_zones,
                "total_detected_person_count": total_detected_people,
                "detection_boxes": detection_boxes,
                "zones": zone_rows,
            }
        )

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "detector_available": service.is_available(),
        "analytics_running": analytics_running,
        "cameras": output,
    }


async def latest_frame(
    session: AsyncSession,
    camera_id: int,
    zone_id: int | None = None,
    analytics_mode: str | None = None,
):
    camera = await crud.get_camera(session, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    frame = await _resolve_existing_frame(session, camera_id, prefer_first=False)
    if not frame:
        raise HTTPException(status_code=404, detail="No captured frames found for this camera yet.")

    path = Path(frame.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Captured frame file is missing on disk. Re-capture this camera.")
        
    if zone_id is not None:
        zone = await crud.get_zone(session, zone_id)
        if zone:
            try:
                import cv2
                img = cv2.imread(str(path))
                if img is not None:
                    cropped = crop_image_to_zone(img, zone)
                    success, buffer = cv2.imencode(".jpg", cropped)
                    if success:
                        return Response(content=buffer.tobytes(), media_type="image/jpeg")
            except Exception:
                pass

    if _is_entry_exit_mode(analytics_mode):
        zones = await crud.list_zones(session, camera_id=camera_id)
        payload = _render_entry_exit_lines(path.read_bytes(), zones)
        return Response(content=payload, media_type="image/jpeg")

    return FileResponse(str(path), media_type="image/jpeg")


async def first_frame(
    session: AsyncSession,
    camera_id: int,
    zone_id: int | None = None,
    analytics_mode: str | None = None,
):
    camera = await crud.get_camera(session, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    frame = await _resolve_existing_frame(session, camera_id, prefer_first=True)
    if not frame:
        raise HTTPException(status_code=404, detail="No captured frames found for this camera yet.")

    path = Path(frame.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="First captured frame file is missing on disk. Re-capture this camera.")

    if zone_id is not None:
        zone = await crud.get_zone(session, zone_id)
        if zone:
            try:
                import cv2
                img = cv2.imread(str(path))
                if img is not None:
                    cropped = crop_image_to_zone(img, zone)
                    success, buffer = cv2.imencode(".jpg", cropped)
                    if success:
                        return Response(content=buffer.tobytes(), media_type="image/jpeg")
            except ImportError:
                pass

    if _is_entry_exit_mode(analytics_mode):
        zones = await crud.list_zones(session, camera_id=camera_id)
        payload = _render_entry_exit_lines(path.read_bytes(), zones)
        return Response(content=payload, media_type="image/jpeg")

    return FileResponse(str(path), media_type="image/jpeg")


def _capture_rtsp_source_frame(rtsp_url: str) -> bytes:
    command = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        settings.ffmpeg_log_level,
        "-rtsp_transport",
        settings.ffmpeg_rtsp_transport,
        "-i",
        rtsp_url,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=_SOURCE_FRAME_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"ffmpeg binary not found: {settings.ffmpeg_path}") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail="Timed out while capturing a frame from the RTSP source.",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to capture RTSP frame: {exc}") from exc

    if result.returncode != 0 or not result.stdout:
        detail = (result.stderr or "").strip().splitlines()[-1] if result.stderr else "ffmpeg returned non-zero status"
        raise HTTPException(status_code=502, detail=f"Failed to capture RTSP frame: {detail}")
    return result.stdout


async def source_frame(session: AsyncSession, camera_id: int):
    camera = await crud.get_camera(session, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    source_url = (camera.rtsp_url or "").strip()
    if not source_url:
        raise HTTPException(status_code=400, detail="Camera source URL required")

    scheme = urlparse(source_url).scheme.lower()
    if scheme in {"rtsp", "rtsps"}:
        payload = await asyncio.to_thread(_capture_rtsp_source_frame, resolve_rtsp_url(source_url))
        return Response(
            content=payload,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    if scheme == "file":
        return await first_frame(session, camera_id)

    raise HTTPException(
        status_code=400,
        detail="Unsupported camera source URL. Use rtsp://, rtsps://, or file://",
    )


async def mjpeg_stream(
    camera_id: int,
    request: Request,
    zone_id: int | None = None,
    analytics_mode: str | None = None,
):
    async with AsyncSessionLocal() as session:
        camera = await crud.get_camera(session, camera_id)
        zone = await crud.get_zone(session, zone_id) if zone_id else None
        draw_entry_exit_lines = _is_entry_exit_mode(analytics_mode) and zone is None
        zones = await crud.list_zones(session, camera_id=camera_id) if draw_entry_exit_lines else []

    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    boundary = "frame"

    async def _stream():
        last_token = ""
        while True:
            if await request.is_disconnected():
                break

            async with AsyncSessionLocal() as live_session:
                frame = await crud.get_latest_frame(live_session, camera_id)

            if not frame:
                await asyncio.sleep(0.2)
                continue

            path = Path(frame.path)
            if not path.exists():
                await asyncio.sleep(0.2)
                continue

            token = f"{frame.id}:{path.stat().st_mtime_ns}"
            if token == last_token:
                await asyncio.sleep(0.08)
                continue

            payload = path.read_bytes()
            
            if zone is not None:
                try:
                    import cv2
                    import numpy as np
                    arr = np.frombuffer(payload, np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img is not None:
                        cropped = crop_image_to_zone(img, zone)
                        success, enc_buffer = cv2.imencode(".jpg", cropped)
                        if success:
                            payload = enc_buffer.tobytes()
                except Exception:
                    pass
            elif draw_entry_exit_lines and zones:
                payload = _render_entry_exit_lines(payload, zones)

            headers = (
                f"--{boundary}\r\n"
                "Content-Type: image/jpeg\r\n"
                f"Content-Length: {len(payload)}\r\n\r\n"
            ).encode("utf-8")
            yield headers + payload + b"\r\n"
            last_token = token
            await asyncio.sleep(0.03)

    return StreamingResponse(
        _stream(),
        media_type=f"multipart/x-mixed-replace; boundary={boundary}",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
