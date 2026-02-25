from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models import ReconstructionStatus, SegmentStatus, StreamStatus


class CameraCreate(BaseModel):
    name: str = Field(..., min_length=1)
    rtsp_url: str | None = None
    location: str | None = None


class CameraUpdate(BaseModel):
    name: str | None = None
    rtsp_url: str | None = None
    location: str | None = None


class CameraRead(BaseModel):
    id: int
    name: str
    rtsp_url: str | None
    location: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MediaUploadResponse(BaseModel):
    camera: CameraRead
    source_type: str
    file_name: str
    size_bytes: int
    source_url: str


class StreamStartRequest(BaseModel):
    camera_id: int


class StreamStopRequest(BaseModel):
    camera_id: int | None = None
    stream_id: int | None = None


class StreamRead(BaseModel):
    id: int
    camera_id: int
    port: int | None
    rtsp_url: str | None = None
    status: StreamStatus
    started_at: datetime | None
    stopped_at: datetime | None
    last_heartbeat: datetime | None

    model_config = {"from_attributes": True}


class StreamStatusRead(BaseModel):
    id: int
    status: StreamStatus
    last_heartbeat: datetime | None
    running: bool
    rtsp_url: str | None = None


class ZoneCreate(BaseModel):
    camera_id: int
    name: str = Field(..., min_length=1)
    polygon: dict


class ZoneRead(BaseModel):
    id: int
    camera_id: int
    name: str
    polygon: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class FootfallSeriesPoint(BaseModel):
    timestamp: str
    zone_id: int | None = None
    event_type: str = "entry"
    count: int
    entry_count: int = 0
    exit_count: int = 0
    net_count: int = 0


class FootfallZoneTotal(BaseModel):
    zone_id: int | None = None
    zone_name: str | None = None
    total_entries: int = 0
    total_exits: int = 0
    net_flow: int = 0


class FootfallResponse(BaseModel):
    camera_id: int
    zone_id: int | None
    total: int
    total_entries: int
    total_exits: int
    net_flow: int
    series: list[FootfallSeriesPoint]
    zone_totals: list[FootfallZoneTotal] = Field(default_factory=list)


class SegmentRead(BaseModel):
    id: int
    camera_id: int
    stream_id: int | None
    path: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    size_bytes: int
    status: SegmentStatus | None = None

    model_config = {"from_attributes": True}


class ReconstructionCreate(BaseModel):
    camera_id: int
    start_time: datetime
    end_time: datetime
    overlay_lines: list[str] = Field(default_factory=list, max_length=8)
    analysis_job_id: int | None = None
    draw_tracking: bool = False


class ReconstructionRead(BaseModel):
    id: int
    camera_id: int
    start_time: datetime
    end_time: datetime
    status: ReconstructionStatus
    output_path: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RuntimeConfigRead(BaseModel):
    config: dict


class RuntimeConfigUpdate(BaseModel):
    key: str
    value: object


class MonitoringResponse(BaseModel):
    timestamp: str
    counts: dict
    disk: dict
    load: tuple | None
    alerts: list[str]


class RealtimeZoneCount(BaseModel):
    zone_id: int
    zone_name: str
    person_count: int


class RealtimeDetectionBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    zone_id: int | None = None
    in_zone: bool = False


class RealtimeCameraSnapshot(BaseModel):
    camera_id: int
    camera_name: str
    stream_status: str
    frame_timestamp: str | None = None
    has_live_frame: bool
    total_person_count: int
    total_detected_person_count: int
    detection_boxes: list[RealtimeDetectionBox] = Field(default_factory=list)
    zones: list[RealtimeZoneCount]


class RealtimeMonitoringResponse(BaseModel):
    timestamp: str
    detector_available: bool
    analytics_running: bool = True
    cameras: list[RealtimeCameraSnapshot]


class AnalyticsRunState(BaseModel):
    running: bool
