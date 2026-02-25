from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import crud
from app.db.models import FrameStatus

logger = logging.getLogger(__name__)


@dataclass
class IngestionEvent:
    kind: str
    camera_id: int
    stream_id: int
    path: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: float | None = None
    size_bytes: int | None = None
    status: FrameStatus | None = None
    message: str | None = None


@dataclass
class IngestionEntry:
    stream_id: int
    camera_id: int
    stop_event: threading.Event
    future: Future


class StreamIngestionManager:
    def __init__(self, session_factory: Callable[[], AsyncSession]):
        self._session_factory = session_factory
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._lock = threading.Lock()
        self._jobs: dict[int, IngestionEntry] = {}
        self._queue: Queue[IngestionEvent | None] = Queue()
        self._running = False

    def start(self) -> None:
        self._running = True

    def shutdown(self) -> None:
        self._running = False
        with self._lock:
            entries = list(self._jobs.values())
        for entry in entries:
            entry.stop_event.set()
        for entry in entries:
            entry.future.cancel()
        self._queue.put(None)
        self._executor.shutdown(wait=False)

    def start_ingestion(
        self,
        stream_id: int,
        camera_id: int,
        source_kind: str,
        source_value: str,
    ) -> bool:
        if shutil.which(settings.ffmpeg_path) is None:
            logger.error("ffmpeg binary not found: %s", settings.ffmpeg_path)
            return False
        with self._lock:
            existing = self._jobs.get(stream_id)
            if existing:
                if existing.future.done():
                    self._jobs.pop(stream_id, None)
                else:
                    return False
            stop_event = threading.Event()
            future = self._executor.submit(
                _run_ingestion,
                stop_event,
                self._queue,
                stream_id,
                camera_id,
                source_kind,
                source_value,
            )
            self._jobs[stream_id] = IngestionEntry(
                stream_id=stream_id,
                camera_id=camera_id,
                stop_event=stop_event,
                future=future,
            )
        return True

    def stop_ingestion(self, stream_id: int) -> bool:
        with self._lock:
            entry = self._jobs.get(stream_id)
            if not entry:
                return False
            entry.stop_event.set()
            if entry.future.done():
                self._jobs.pop(stream_id, None)
            return True

    def is_running(self, stream_id: int) -> bool:
        with self._lock:
            entry = self._jobs.get(stream_id)
            if not entry:
                return False
            return not entry.future.done()

    async def consume_events(self) -> None:
        while self._running:
            event = await asyncio.to_thread(self._queue.get)
            if event is None:
                break
            try:
                async with self._session_factory() as session:
                    try:
                        await _handle_event(session, event)
                    except Exception:  # noqa: BLE001
                        # Keep consumer alive even if a single event is invalid/stale.
                        logger.exception(
                            "Failed to process ingestion event kind=%s stream_id=%s camera_id=%s",
                            event.kind,
                            event.stream_id,
                            event.camera_id,
                        )
            finally:
                self._queue.task_done()

    async def cleanup_finished(self) -> None:
        with self._lock:
            finished = [key for key, entry in self._jobs.items() if entry.future.done()]
            for key in finished:
                self._jobs.pop(key, None)


def _run_ingestion(
    stop_event: threading.Event,
    queue: Queue[IngestionEvent | None],
    stream_id: int,
    camera_id: int,
    source_kind: str,
    source_value: str,
) -> None:
    base_dir = Path(settings.frames_dir) / f"camera_{camera_id}" / f"stream_{stream_id}"
    base_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale frame files from previous runs to avoid redundant files and
    # stale-frame ingestion when stream jobs restart.
    for stale_path in base_dir.glob("*.jpg"):
        try:
            stale_path.unlink()
        except OSError:
            logger.warning("Failed to remove stale frame file: %s", stale_path)

    run_prefix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    output_pattern = str(base_dir / f"{run_prefix}_%06d.jpg")
    fps_value = max(0.1, 1.0 / max(settings.frame_interval_seconds, 1e-6))
    try:
        cmd = _build_ffmpeg_command(source_kind, source_value, fps_value, output_pattern)
    except ValueError as exc:
        queue.put(
            IngestionEvent(
                kind="status",
                camera_id=camera_id,
                stream_id=stream_id,
                status=FrameStatus.error,
                message=str(exc),
            )
        )
        return

    seen: set[str] = set()
    while not stop_event.is_set():
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to start ffmpeg ingestion: %s", exc)
            queue.put(
                IngestionEvent(
                    kind="status",
                    camera_id=camera_id,
                    stream_id=stream_id,
                    status=FrameStatus.error,
                    message=str(exc),
                )
            )
            time.sleep(1.0)
            continue

        while not stop_event.is_set():
            if process.poll() is not None:
                break

            for path in sorted(base_dir.glob(f"{run_prefix}_*.jpg")):
                if path.name in seen:
                    continue
                stat = path.stat()
                timestamp = datetime.utcfromtimestamp(stat.st_mtime)
                size_bytes = stat.st_size
                queue.put(
                    IngestionEvent(
                        kind="frame",
                        camera_id=camera_id,
                        stream_id=stream_id,
                        path=str(path),
                        start_time=timestamp,
                        end_time=timestamp,
                        duration_seconds=0.0,
                        size_bytes=size_bytes,
                        status=FrameStatus.captured,
                    )
                )
                seen.add(path.name)

            time.sleep(settings.segment_scan_seconds)

        if stop_event.is_set():
            _terminate_process(process)
            return

        queue.put(
            IngestionEvent(
                kind="status",
                camera_id=camera_id,
                stream_id=stream_id,
                status=FrameStatus.error,
                message="ffmpeg ingestion stopped; retrying",
            )
        )
        time.sleep(1.0)


def _build_ffmpeg_command(
    source_kind: str,
    source_value: str,
    fps_value: float,
    output_pattern: str,
) -> list[str]:
    cmd = [
        settings.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        settings.ffmpeg_log_level,
    ]

    if source_kind == "rtsp":
        cmd.extend(
            [
                "-rtsp_transport",
                settings.ffmpeg_rtsp_transport,
                "-i",
                source_value,
            ]
        )
    elif source_kind == "file":
        cmd.extend(["-stream_loop", "-1", "-re", "-i", source_value])
    else:
        raise ValueError(f"Unsupported ingestion source kind: {source_kind}")

    cmd.extend(
        [
            "-vcodec",
            "mjpeg",
            "-vf",
            f"fps={fps_value}",
            "-start_number",
            "0",
            "-f",
            "image2",
            output_pattern,
        ]
    )
    return cmd


def _terminate_process(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    except Exception:
        logger.exception("Failed to terminate ffmpeg ingestion process")


async def _handle_event(session: AsyncSession, event: IngestionEvent) -> None:
    if event.kind == "frame" and event.path:
        stream = await crud.get_stream(session, event.stream_id)
        stream_id = stream.id if stream else None
        await crud.create_frame(
            session=session,
            camera_id=event.camera_id,
            stream_id=stream_id,
            path=event.path,
            timestamp=event.start_time or datetime.utcnow(),
            width=None,
            height=None,
            size_bytes=event.size_bytes or 0,
        )
        if stream:
            await crud.update_stream_heartbeat(session, stream, event.end_time or datetime.utcnow())
