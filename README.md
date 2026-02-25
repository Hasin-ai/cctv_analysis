# CCTV RTSP Capture & Analytics

This repository now contains a **capture-focused backend/frontend**:

- RTSP camera CRUD
- RTSP frame capture (ingestion)
- Zone drawing and analytics
- Realtime multi-camera dashboard output (MJPEG stream cards)
- Realtime zone-based person counting and queue counting (count only)
- Queue and video analysis workflows
- Next.js control dashboard

The RTSP **simulator** has been split out of the runtime paths and moved into:

- `simulator/backend/`
- `simulator/frontend/`

## Quickstart (Docker Compose)

```bash
docker compose up -d --build
```

- Frontend: `http://127.0.0.1:3000`
- Backend API: `http://127.0.0.1:8000`

## Quickstart (Local)

1. Create virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Ensure FFmpeg is installed and available:

```bash
ffmpeg -version
```

3. Run backend (capture mode):

```bash
SERVICE_ROLE=fetcher uvicorn app.main:app --reload --port 8000
```

4. Run frontend:

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 npm run dev
```

## Frontend Pages

- `/capture` for RTSP camera capture and local video file loading (Browse Files)
- `/realtime-dashboard` for monitoring-only live multi-camera output
- `/zones` for polygon zone configuration
- `/video-analysis` for analysis and output playback

## Capture Flow

1. Open `/capture`.
2. Add camera with RTSP URL (`rtsp://...`).
3. Start capture for the camera.
4. Go to `/zones` once frames are available.

## Configuration

Main environment variables:

- `DATABASE_URL=sqlite+aiosqlite:///./data/app.db`
- `SERVICE_ROLE=fetcher|all`
- `FFMPEG_PATH=ffmpeg`
- `FFMPEG_LOG_LEVEL=error`
- `FFMPEG_RTSP_TRANSPORT=tcp`
- `FRAMES_DIR=./data/frames`
- `FRAME_INTERVAL_SECONDS=2.0`
- `SEGMENT_SCAN_SECONDS=1.0`
- `RTSP_INTERNAL_HOST=`
- `RTSP_INTERNAL_PORT=0`

## API Overview

- `GET /health`
- `POST /api/cameras`, `GET /api/cameras`, `GET /api/cameras/{id}`, `PUT /api/cameras/{id}`, `DELETE /api/cameras/{id}`
- `POST /api/streams/start`, `POST /api/streams/stop`, `GET /api/streams`, `GET /api/streams/{id}`, `GET /api/streams/{id}/status`, `DELETE /api/streams/{id}`
- `POST /api/analytics/zones`, `GET /api/analytics/zones`
- `GET /api/analytics/footfall`
- `GET /api/monitoring/metrics`
- `GET /api/monitoring/realtime`
- `GET /api/monitoring/cameras/{camera_id}/frame`
- `GET /api/monitoring/cameras/{camera_id}/stream.mjpg`
- `GET /api/analyzer/status`, `GET /api/analyzer/cameras`, `GET /api/analyzer/zones/{camera_id}`
- `POST /api/analyzer/run`, `POST /api/analyzer/total-person-detection`
- `GET /api/analyzer/jobs`, `GET /api/analyzer/jobs/{job_id}`, `GET /api/analyzer/stats/{job_id}`, `GET /api/analyzer/tracks/{job_id}`
- `POST /api/reconstructions`, `GET /api/reconstructions`, `GET /api/reconstructions/{id}`, `GET /api/reconstructions/{id}/download`

## Simulator Split

Simulator code has been separated from the active backend/frontend and placed in:

- `simulator/backend/` (RTSP publishing and simulator controllers/modules)
- `simulator/frontend/` (simulation UI and related frontend helpers)

Run the dedicated simulator stack with:

```bash
docker compose -f docker-compose.simulator.yml up -d --build
```

- Simulator frontend: `http://127.0.0.1:3001`
- Simulator backend: `http://127.0.0.1:8001`
- Simulator RTSP: `rtsp://127.0.0.1:8554/stream_<port>`
