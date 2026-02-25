from __future__ import annotations

from pydantic import BaseModel


class QueueAnalysisRequest(BaseModel):
    camera_id: int
    zone_id: int
    start: str
    end: str


class QueueJobResponse(BaseModel):
    id: int
    camera_id: int
    zone_id: int
    start_time: str
    end_time: str
    status: str
    total_frames: int
    processed_frames: int
    max_queue_count: int
    avg_queue_count: float
    error: str | None
    created_at: str


class QueueFrameResultResponse(BaseModel):
    timestamp: str
    queue_count: int


class QueueResultsResponse(BaseModel):
    job_id: int
    camera_id: int
    zone_id: int
    zone_name: str | None
    status: str
    max_queue_count: int
    avg_queue_count: float
    frame_results: list[QueueFrameResultResponse]

