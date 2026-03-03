from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    service_role: str = "fetcher"
    stream_tick_seconds: float = 1.0
    stream_heartbeat_timeout_seconds: float = 5.0
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
    frame_interval_seconds: float = 0.3333333333
    reconstructions_dir: str = "./data/reconstructions"
    analytics_poll_seconds: float = 2.0
    segment_scan_seconds: float = 1.0
    retention_days: int = 7
    config_backup_path: str = "./data/config-backup.json"
    analytics_use_yolo: bool = True
    yolo_model_path: str = "./data/models/best.pt"
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
