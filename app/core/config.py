from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    service_role: str = "fetcher"
    stream_tick_seconds: float = 1.0
    stream_heartbeat_timeout_seconds: float = 30.0
    max_streams: int = 16

    ffmpeg_path: str = "ffmpeg"
    ffmpeg_log_level: str = "error"
    ffmpeg_rtsp_transport: str = "tcp"
    rtsp_internal_host: str = ""
    rtsp_internal_port: int = 0
    ffmpeg_segment_time_seconds: int = 10

    segments_dir: str = "./data/segments"
    frames_dir: str = "./data/frames"
    uploads_dir: str = "./data/uploads"
    sqlite_journal_mode: str = "DELETE"
    frame_interval_seconds: float = 0.04
    mjpeg_jpeg_quality: int = 80
    reconstructions_dir: str = "./data/reconstructions"
    analytics_poll_seconds: float = 2.0
    segment_scan_seconds: float = 0.04
    retention_days: int = 7
    config_backup_path: str = "./data/config-backup.json"
    analytics_use_yolo: bool = True
    yolo_model_path: str = "/Users/bs00851/Documents/cctv_analysis/data/models/yolo26x.pt"
    yolo_confidence: float = 0.3
    yolo_iou: float = 0.5
    yolo_tracker: str = "botsort.yaml"
    yolo_verbose: bool = False
    boxmot_reid_weights: str = "osnet_x0_25_msmt17.pt"
    boxmot_device: str = "cpu"
    strongsort_min_hits: int = 1
    strongsort_n_init: int = 1
    strongsort_min_conf: float = 0.2
    personvit_use_reid: bool = True
    personvit_reid_weights: str = "./data/models/personvit/checkpoint0260.pth"
    personvit_similarity_threshold: float = 0.6
    personvit_trust_checkpoint: bool = False
    bytetrack_track_thresh: float = 0.25
    bytetrack_match_thresh: float = 0.8
    bytetrack_track_buffer: int = 30
    analytics_track_grace_frames: int = 3
    analytics_frame_stride: int = 15
    analytics_max_frames: int = 200
    facial_expression_model_name: str = "enet_b0_8_va_mtl"
    facial_expression_engine: str = "onnx"
    facial_expression_device: str = "cpu"
    facial_expression_model_path: str = ""
    facial_expression_frame_stride: int = 10
    facial_expression_max_frames: int = 180
    facial_expression_face_scale_factor: float = 1.1
    facial_expression_face_min_neighbors: int = 3
    facial_expression_min_face_size: int = 15
    facial_expression_face_confidence_threshold: float = 0.0
    facial_expression_detector_backend: str = "opencv"
    facial_expression_realtime_interval_seconds: float = 0.04
    facial_expression_realtime_cache_ttl_seconds: float = 2.0
    dashboard_overlay_modes: dict[str, dict[str, list[str]]] = Field(default_factory=dict)

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()


def ensure_data_dir() -> None:
    # Ensure local sqlite storage exists for the MVP default
    if settings.database_url.startswith("sqlite+aiosqlite:///"):
        path = settings.database_url.replace("sqlite+aiosqlite:///", "", 1)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(settings.segments_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.frames_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.reconstructions_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.config_backup_path).parent.mkdir(parents=True, exist_ok=True)


def fetcher_enabled() -> bool:
    return settings.service_role in {"fetcher", "all"}
