from __future__ import annotations

from pydantic import BaseModel


class AnalysisRequest(BaseModel):
    camera_id: int
    start: str
    end: str
    zone_id: int | None = None


class TotalPersonDetectionRequest(BaseModel):
    camera_id: int
    start: str
    end: str


class AnalysisJobResponse(BaseModel):
    id: int
    camera_id: int
    start_time: str
    end_time: str
    status: str
    total_frames: int
    processed_frames: int
    unique_persons: int
    error: str | None
    created_at: str


class ZoneStatsResponse(BaseModel):
    zone_id: int | None
    zone_name: str | None
    unique_persons: int
    total_appearances: int
    total_dwell_seconds: float


class AnalysisStatsResponse(BaseModel):
    job_id: int
    camera_id: int
    unique_persons: int
    zone_stats: list[ZoneStatsResponse]


class TotalPersonFrameCount(BaseModel):
    frame_id: int
    timestamp: str | None
    person_count: int


class TotalPersonDetectionResponse(BaseModel):
    camera_id: int
    start_time: str
    end_time: str
    detector_available: bool
    processed_frames: int
    total_person_detections: int
    max_person_count: int
    avg_person_count: float
    series: list[TotalPersonFrameCount]
