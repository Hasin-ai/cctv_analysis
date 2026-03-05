from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from app.services.zone_geometry import region_points_from_polygon
from app.core.config import settings

logger = logging.getLogger(__name__)


def _stable_emotion_dict(
    counts: dict[str, int],
    labels: list[str],
) -> dict[str, int]:
    result: dict[str, int] = {label: 0 for label in labels}
    result.update({k: v for k, v in counts.items() if k in result})
    return result


def _stable_pct_dict(counts: dict[str, int], labels: list[str]) -> dict[str, float]:
    total = sum(counts.values()) or 1
    result: dict[str, float] = {}
    for label in labels:
        result[label] = round(counts.get(label, 0) / total * 100, 2)
    return result


DEEPFACE_EMOTION_LABELS = ["angry", "disgust", "fear", "happy", "sad", "surprise", "neutral"]


class FacialExpressionRecognitionService:
    """Facial expression + demographic analysis service backed by DeepFace."""

    def __init__(self) -> None:
        self._available = False
        self._init_error: str | None = None
        self._cv2 = None
        self._deepface = None
        self._emotion_labels = list(DEEPFACE_EMOTION_LABELS)

        try:
            import cv2  # type: ignore
            from deepface import DeepFace  # type: ignore

            # Warm the model on first import to catch missing weights early
            self._cv2 = cv2
            self._deepface = DeepFace
            self._available = True
        except Exception as exc:  # noqa: BLE001
            self._init_error = str(exc)
            logger.warning("Failed to initialize DeepFace service: %s", exc)

    def is_available(self) -> bool:
        return self._available and self._cv2 is not None and self._deepface is not None

    def error_message(self) -> str:
        return self._init_error or "DeepFace service is unavailable"

    def analyze_frames(
        self,
        frames: list[Any],
        zone: Any,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._empty_result()

        stride = max(1, int(settings.facial_expression_frame_stride))
        max_frames = max(1, int(settings.facial_expression_max_frames))
        selected_frames = [f for idx, f in enumerate(frames) if idx % stride == 0][:max_frames]

        processed_frames = 0
        total_analyzed = 0
        all_emotion_counts: Counter[str] = Counter()
        all_ages: list[float] = []
        all_genders: Counter[str] = Counter()
        series: list[dict[str, Any]] = []

        for frame_obj in selected_frames:
            frame_path = getattr(frame_obj, "path", None)
            frame_id = getattr(frame_obj, "id", 0)
            timestamp = getattr(frame_obj, "timestamp", None)
            ts_iso = timestamp.isoformat() if timestamp else None

            if not frame_path:
                continue

            try:
                image = self._cv2.imread(frame_path)
                if image is None:
                    continue

                processed_frames += 1
                detections = self.detect_faces_with_demographics(image=image, zone=zone)

                frame_emotions: Counter[str] = Counter()
                frame_ages: list[float] = []
                frame_genders: Counter[str] = Counter()

                for det in detections:
                    emotion = det.get("emotion")
                    age = det.get("age")
                    gender = det.get("gender")
                    if emotion:
                        frame_emotions[emotion] += 1
                        all_emotion_counts[emotion] += 1
                    if age is not None:
                        frame_ages.append(float(age))
                        all_ages.append(float(age))
                    if gender:
                        frame_genders[gender] += 1
                        all_genders[gender] += 1

                num_faces = len(detections)
                total_analyzed += num_faces
                dom_emotion = frame_emotions.most_common(1)[0][0] if frame_emotions else None
                dom_gender = frame_genders.most_common(1)[0][0] if frame_genders else None
                avg_age_frame = round(sum(frame_ages) / len(frame_ages), 1) if frame_ages else None

                series.append({
                    "frame_id": frame_id,
                    "timestamp": ts_iso,
                    "analyzed_faces": num_faces,
                    "dominant_emotion": dom_emotion,
                    "emotion_counts": dict(frame_emotions),
                    "avg_age": avg_age_frame,
                    "dominant_gender": dom_gender,
                })
            except Exception as exc:  # noqa: BLE001
                logger.debug("DeepFace frame analysis failed: %s", exc)
                continue

        dom_emotion_global = all_emotion_counts.most_common(1)[0][0] if all_emotion_counts else None
        avg_age_global = round(sum(all_ages) / len(all_ages), 1) if all_ages else None

        # Build age distribution buckets
        age_distribution = _build_age_distribution(all_ages)

        emotion_counts_stable = _stable_emotion_dict(dict(all_emotion_counts), self._emotion_labels)
        emotion_pct_stable = _stable_pct_dict(dict(all_emotion_counts), self._emotion_labels)

        return {
            "processed_frames": processed_frames,
            "analyzed_faces": total_analyzed,
            "dominant_emotion": dom_emotion_global,
            "emotion_counts": emotion_counts_stable,
            "emotion_percentages": emotion_pct_stable,
            "avg_age": avg_age_global,
            "gender_counts": dict(all_genders),
            "age_distribution": age_distribution,
            "series": series,
        }

    def detect_faces_with_demographics(
        self,
        image: Any,
        zone: Any | None = None,
        precomputed_polygons: list[list[tuple[int, int]]] | None = None,
    ) -> list[dict[str, Any]]:
        """Run DeepFace.analyze and return zone-filtered face detections."""
        if not self.is_available() or image is None:
            return []

        frame_h, frame_w = image.shape[:2]
        if frame_h <= 0 or frame_w <= 0:
            return []

        polygons = precomputed_polygons
        if polygons is None and zone is not None:
            polygons = region_points_from_polygon(
                getattr(zone, "polygon", None),
                frame_w,
                frame_h,
                use_default_on_invalid=False,
            )
        polygons = polygons or []

        analysis_image = image
        offset_x = 0
        offset_y = 0
        if polygons:
            bounds = _polygon_bounds(polygons, frame_w, frame_h)
            if bounds is None:
                return []
            x1, y1, x2, y2 = bounds
            analysis_image = image[y1:y2, x1:x2]
            if analysis_image is None or getattr(analysis_image, "size", 0) == 0:
                return []
            offset_x = x1
            offset_y = y1

        try:
            results = self._deepface.analyze(
                img_path=analysis_image,
                actions=["emotion", "age", "gender"],
                enforce_detection=False,
                silent=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("DeepFace.analyze failed: %s", exc)
            return []

        if not isinstance(results, list):
            results = [results]

        detections: list[dict[str, Any]] = []
        min_face_confidence = max(0.0, float(getattr(settings, "facial_expression_face_confidence_threshold", 0.01)))
        for face in results:
            try:
                region = face.get("region", {})
                x = int(region.get("x", 0))
                y = int(region.get("y", 0))
                w = int(region.get("w", 0))
                h = int(region.get("h", 0))

                if w <= 0 or h <= 0:
                    continue

                face_confidence_raw = face.get("face_confidence", face.get("confidence"))
                if face_confidence_raw is None:
                    face_confidence = 1.0
                else:
                    face_confidence = float(face_confidence_raw)
                    if face_confidence != face_confidence:  # NaN guard
                        face_confidence = 0.0
                if face_confidence < min_face_confidence:
                    continue

                x1 = max(0, offset_x + x)
                y1 = max(0, offset_y + y)
                x2 = min(frame_w, offset_x + x + w)
                y2 = min(frame_h, offset_y + y + h)

                # Zone filtering
                if polygons and not _face_in_any_polygon(
                    float(x1), float(y1), float(x2), float(y2), polygons
                ):
                    continue

                dominant_emotion = face.get("dominant_emotion")
                age = face.get("age")
                dominant_gender = face.get("dominant_gender")
                gender_confidence = None
                if dominant_gender and isinstance(face.get("gender"), dict):
                    gender_confidence = face["gender"].get(dominant_gender)

                detections.append({
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "emotion": dominant_emotion,
                    "age": age,
                    "gender": dominant_gender,
                    "gender_confidence": gender_confidence,
                    "face_confidence": round(float(face_confidence), 4),
                })
            except Exception as exc:  # noqa: BLE001
                logger.debug("DeepFace face result parse failed: %s", exc)
                continue

        return detections

    def filter_detections_by_zone(
        self,
        detections: list[dict[str, Any]],
        zone: Any | None,
        frame_width: int,
        frame_height: int,
    ) -> list[dict[str, Any]]:
        if zone is None:
            return list(detections)
        if frame_width <= 0 or frame_height <= 0:
            return []

        polygons = region_points_from_polygon(
            getattr(zone, "polygon", None),
            frame_width,
            frame_height,
            use_default_on_invalid=False,
        )
        if not polygons:
            return []

        filtered: list[dict[str, Any]] = []
        for row in detections:
            try:
                x1 = float(row.get("x1", 0))
                y1 = float(row.get("y1", 0))
                x2 = float(row.get("x2", 0))
                y2 = float(row.get("y2", 0))
            except Exception:  # noqa: BLE001
                continue
            if x2 <= x1 or y2 <= y1:
                continue
            if _face_in_any_polygon(x1, y1, x2, y2, polygons):
                filtered.append(row)
        return filtered

    def summarize_detections(self, detections: list[dict[str, Any]]) -> dict[str, Any]:
        emotion_counts: Counter[str] = Counter()
        gender_counts: Counter[str] = Counter()
        ages: list[float] = []

        for row in detections:
            emotion = row.get("emotion")
            if isinstance(emotion, str) and emotion:
                emotion_counts[emotion] += 1

            gender = row.get("gender")
            if isinstance(gender, str) and gender:
                gender_counts[gender] += 1

            age = row.get("age")
            if age is not None:
                try:
                    ages.append(float(age))
                except (TypeError, ValueError):
                    pass

        dominant_emotion = emotion_counts.most_common(1)[0][0] if emotion_counts else None
        return {
            "analyzed_faces": len(detections),
            "dominant_emotion": dominant_emotion,
            "emotion_counts": _stable_emotion_dict(dict(emotion_counts), self._emotion_labels),
            "emotion_percentages": _stable_pct_dict(dict(emotion_counts), self._emotion_labels),
            "avg_age": round(sum(ages) / len(ages), 1) if ages else None,
            "gender_counts": dict(gender_counts),
            "age_distribution": _build_age_distribution(ages),
        }

    def _empty_result(self) -> dict[str, Any]:
        return {
            "processed_frames": 0,
            "analyzed_faces": 0,
            "dominant_emotion": None,
            "emotion_counts": _stable_emotion_dict({}, self._emotion_labels),
            "emotion_percentages": _stable_pct_dict({}, self._emotion_labels),
            "avg_age": None,
            "gender_counts": {},
            "age_distribution": {},
            "series": [],
            "error": self.error_message(),
        }


def _build_age_distribution(ages: list[float]) -> dict[str, int]:
    """Bucket ages into readable ranges."""
    buckets: dict[str, int] = {
        "0-12": 0,
        "13-17": 0,
        "18-24": 0,
        "25-34": 0,
        "35-44": 0,
        "45-54": 0,
        "55-64": 0,
        "65+": 0,
    }
    for age in ages:
        if age <= 12:
            buckets["0-12"] += 1
        elif age <= 17:
            buckets["13-17"] += 1
        elif age <= 24:
            buckets["18-24"] += 1
        elif age <= 34:
            buckets["25-34"] += 1
        elif age <= 44:
            buckets["35-44"] += 1
        elif age <= 54:
            buckets["45-54"] += 1
        elif age <= 64:
            buckets["55-64"] += 1
        else:
            buckets["65+"] += 1
    return {k: v for k, v in buckets.items() if v > 0}


def _polygon_bounds(
    polygons: list[list[tuple[int, int]]],
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int] | None:
    xs: list[int] = []
    ys: list[int] = []
    for polygon in polygons:
        for point in polygon:
            if not isinstance(point, tuple) or len(point) != 2:
                continue
            xs.append(int(point[0]))
            ys.append(int(point[1]))

    if not xs or not ys:
        return None

    x1 = max(0, min(xs))
    y1 = max(0, min(ys))
    x2 = min(frame_width, max(xs) + 1)
    y2 = min(frame_height, max(ys) + 1)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _face_in_any_polygon(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    polygons: list[list[tuple[int, int]]],
) -> bool:
    center_x = (x1 + x2) / 2.0
    center_y = (y1 + y2) / 2.0
    for px, py in [(center_x, center_y), (center_x, y2), (x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
        for polygon in polygons:
            if _point_in_polygon(px, py, polygon):
                return True
    return False


def _point_in_polygon(x: float, y: float, polygon: list[tuple[int, int]]) -> bool:
    inside = False
    count = len(polygon)
    if count < 3:
        return False
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside
