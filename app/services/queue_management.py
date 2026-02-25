"""Queue management service for in-zone queue occupancy counting with YOLO."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.db import crud
from app.db.models import QueueJobStatus
from app.services.yolo_person_classes import resolve_person_class_ids
from app.services.zone_geometry import region_points_from_polygon

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class QueueManagementService:
    """Service for running queue analysis inside configured zone regions."""

    def __init__(self) -> None:
        self._use_yolo = settings.analytics_use_yolo
        self._cv2 = None
        self._np = None
        self._yolo = None
        self._person_class_ids: list[int] = [0]

        if not self._use_yolo:
            return

        model_path = Path(settings.yolo_model_path).expanduser()
        if not model_path.is_absolute():
            model_path = (Path.cwd() / model_path).resolve()
        if not model_path.exists():
            logger.warning("Queue model file does not exist: %s", model_path)
            self._use_yolo = False
            return

        try:
            from ultralytics import YOLO  # type: ignore
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            self._yolo = YOLO(str(model_path))
            self._cv2 = cv2
            self._np = np
            self._person_class_ids = resolve_person_class_ids(self._yolo)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to initialize queue detector: %s", exc)
            self._use_yolo = False

    def is_available(self) -> bool:
        """Check if queue detector dependencies are available."""
        return self._use_yolo and self._yolo is not None and self._cv2 is not None and self._np is not None

    async def run_queue_analysis(
        self,
        session: "AsyncSession",
        job_id: int,
        camera_id: int,
        zone_id: int,
        zone_polygon: Any,
        frames: list,
    ) -> dict:
        """Run queue analysis and persist per-frame queue counts."""
        job = await crud.get_queue_analysis_job(session, job_id)
        if not job:
            return {"error": "Job not found"}

        await crud.update_queue_analysis_job(
            session,
            job,
            status=QueueJobStatus.running,
            total_frames=len(frames),
        )

        if not self.is_available():
            error = "Queue detector dependencies are unavailable"
            await crud.update_queue_analysis_job(
                session,
                job,
                status=QueueJobStatus.failed,
                error=error,
            )
            return {"error": error}

        try:
            result = await self._queue_analysis(session, job_id, zone_id, zone_polygon, frames)
            await crud.update_queue_analysis_job(
                session,
                job,
                status=QueueJobStatus.completed,
                processed_frames=result["processed_frames"],
                max_queue_count=result["max_queue_count"],
                avg_queue_count=result["avg_queue_count"],
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("Queue analysis failed: %s", exc)
            await crud.update_queue_analysis_job(
                session,
                job,
                status=QueueJobStatus.failed,
                error=str(exc),
            )
            return {"error": str(exc)}

    async def _queue_analysis(
        self,
        session: "AsyncSession",
        job_id: int,
        zone_id: int,
        zone_polygon: Any,
        frames: list,
    ) -> dict:
        """Run per-frame queue occupancy counting over each frame."""
        width, height = self._detect_frame_size(frames)
        region_points = region_points_from_polygon(
            zone_polygon,
            width,
            height,
            use_default_on_invalid=False,
        )
        if len(region_points) < 3:
            raise RuntimeError("Zone polygon is invalid for queue analysis")

        frame_counts: list[dict[str, Any]] = []
        processed_frames = 0

        for frame in frames:
            if not Path(frame.path).exists():
                continue

            image = self._cv2.imread(frame.path)
            if image is None:
                continue

            queue_count = self._count_people_in_region(image, region_points)

            await crud.create_queue_frame_result(
                session=session,
                job_id=job_id,
                frame_id=frame.id,
                timestamp=frame.timestamp,
                queue_count=queue_count,
            )

            frame_counts.append({"timestamp": frame.timestamp.isoformat(), "queue_count": queue_count})
            processed_frames += 1

        counts = [entry["queue_count"] for entry in frame_counts]
        max_count = max(counts) if counts else 0
        avg_count = round(sum(counts) / len(counts), 2) if counts else 0.0

        return {
            "zone_id": zone_id,
            "max_queue_count": max_count,
            "avg_queue_count": avg_count,
            "processed_frames": processed_frames,
            "frame_counts": frame_counts,
        }

    def _count_people_in_region(self, image: Any, region_points: list[tuple[int, int]]) -> int:
        try:
            predict_kwargs: dict[str, Any] = {
                "conf": settings.yolo_confidence,
                "iou": settings.yolo_iou,
                "verbose": settings.yolo_verbose,
            }
            if self._person_class_ids:
                predict_kwargs["classes"] = self._person_class_ids
            results = self._yolo.predict(image, **predict_kwargs)
            boxes = results[0].boxes if results and results[0].boxes is not None else None
            if boxes is None:
                return 0

            xyxy = boxes.xyxy.cpu().numpy().astype(self._np.float32)
            if len(xyxy) == 0:
                return 0

            cls_data = getattr(boxes, "cls", None)
            if self._person_class_ids and cls_data is not None:
                cls = cls_data.cpu().numpy().astype(self._np.int32)
                mask = self._np.isin(cls, self._person_class_ids)
                xyxy = xyxy[mask]

            count = 0
            for row in xyxy:
                if len(row) < 4:
                    continue
                x1, y1, x2, y2 = float(row[0]), float(row[1]), float(row[2]), float(row[3])
                if x2 <= x1 or y2 <= y1:
                    continue
                foot_x = (x1 + x2) / 2.0
                foot_y = y2
                if self._point_in_polygon(foot_x, foot_y, region_points):
                    count += 1
            return int(count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Queue analysis inference failed: %s", exc)
            return 0

    def _point_in_polygon(self, x: float, y: float, polygon: list[tuple[int, int]]) -> bool:
        if len(polygon) < 3:
            return False

        inside = False
        j = len(polygon) - 1
        for i in range(len(polygon)):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            )
            if intersects:
                inside = not inside
            j = i
        return inside

    def _detect_frame_size(self, frames: list) -> tuple[int, int]:
        for frame in frames:
            if not Path(frame.path).exists():
                continue
            image = self._cv2.imread(frame.path)
            if image is None:
                continue
            height, width = image.shape[:2]
            return width, height
        return 1920, 1080
