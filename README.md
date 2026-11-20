# VisionLab — Multi-Camera Video Analytics

VisionLab is a computer-vision application for ingesting RTSP camera streams, capturing frames, and running person-detection, tracking, and zone-based analytics. It includes a FastAPI backend and a Next.js dashboard for camera management, live monitoring, and reviewing analysis jobs.

The repository also contains a separate RTSP simulator under `simulator/` for development and testing.

## What it does

- **Camera and stream management** — register cameras, start and stop RTSP capture, and inspect stream status.
- **Frame ingestion** — use FFmpeg to capture frames and video segments from RTSP sources.
- **Person detection** — run YOLO-based person detection on captured frames.
- **Tracking and re-identification** — maintain person tracks across frames, with configurable tracker and appearance/ReID components.
- **Zone analytics** — configure polygon zones and calculate entries, exits, appearances, unique-person counts, and dwell time.
- **Queue workflows** — run queue-oriented analysis on recorded camera footage.
- **Live monitoring** — view multiple camera feeds and monitoring overlays through the dashboard and MJPEG endpoints.
- **Optional face analysis** — a separate, time-windowed workflow can analyze detected faces for model-estimated expression and demographic attributes. This feature depends on its model/runtime being available; it is not required for basic capture and person analytics.

## System overview

```text
RTSP cameras
    |
    v
FFmpeg ingestion
    |
    +----> captured frames / video segments
                    |
                    v
             YOLO person detection
                    |
                    v
           tracking and ReID modules
                    |
                    v
           zone and queue analytics
                    |
                    v
             FastAPI backend
                    |
          +---------+----------+
          |                    |
          v                    v
    Next.js dashboard     Analysis results
    live camera feeds     jobs, tracks, stats
```

The backend is organized into controllers, services, database models, and shared runtime configuration under `app/`. The dashboard lives under `frontend/`. The simulator has its own backend and frontend under `simulator/`.

## Technology

| Area | Technologies |
|---|---|
| API | Python, FastAPI, SQLAlchemy, SQLite (default local database) |
| Video ingestion | FFmpeg, RTSP |
| Computer vision | Ultralytics YOLO, OpenCV |
| Tracking / ReID | BoxMOT, ByteTrack configuration, PersonViT integration |
| Optional face analysis | DeepFace and configured face-analysis model/runtime |
| Dashboard | Next.js 14, React 18, TypeScript, Tailwind CSS |
| Local deployment | Docker Compose |

## Run with Docker Compose

### Prerequisites

- Docker Engine
- Docker Compose plugin
- Network access from the backend container to your RTSP camera sources

### Start the application

From the repository root:

```bash
cp .env.example .env
docker compose up -d --build
```

Open:

- Dashboard: http://127.0.0.1:3000
- Backend API: http://127.0.0.1:8000
- Health check: http://127.0.0.1:8000/health

The Compose configuration uses `host.docker.internal` as the default RTSP host bridge. Check `RTSP_INTERNAL_HOST` and your network/firewall configuration if the container cannot reach a camera.

## Run locally

### Backend

Python 3.11 and FFmpeg are required.

```bash
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp .env.example .env
ffmpeg -version
SERVICE_ROLE=fetcher uvicorn app.main:app --reload --port 8000
```

### Frontend

Node.js 20 or newer:

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 npm run dev
```

On Windows PowerShell, set the environment variable for the current session before running `npm run dev`:

```powershell
$env:NEXT_PUBLIC_API_BASE="http://127.0.0.1:8000"
npm run dev
```

## Model files and configuration

The application code references model files by path. **The required model weights are not bundled with this repository.** Obtain the appropriate weights and place them at the configured paths before enabling the corresponding inference workflows.

| Setting | Purpose |
|---|---|
| `YOLO_MODEL_PATH` | YOLO detection model (default: `./data/models/yolo26x.pt`) |
| `BOXMOT_REID_WEIGHTS` | BoxMOT appearance/ReID weights |
| `PERSONVIT_REID_WEIGHTS` | PersonViT checkpoint |
| `PERSONVIT_USE_REID` | Enable or disable the PersonViT ReID integration |
| `ANALYTICS_USE_YOLO` | Enable or disable YOLO-based analytics |
| `FFMPEG_PATH` | FFmpeg executable path |
| `FFMPEG_RTSP_TRANSPORT` | RTSP transport mode (default: TCP) |
| `DATABASE_URL` | Database URL (defaults to local SQLite) |
| `FRAMES_DIR`, `SEGMENTS_DIR` | Storage locations for captured media |

See [`.env.example`](.env.example) and `app/core/config.py` for the full configuration surface. Do not commit model weights, camera credentials, or private footage.

## Main dashboard pages

- `/capture` — register cameras, start capture, and load local video files.
- `/realtime-dashboard` — monitor live multi-camera output.
- `/zones` — draw and manage polygon zones.
- `/video-analysis` — submit recorded footage for analysis and inspect results.

## API surface

The backend exposes the following main route groups:

| Area | Representative endpoints |
|---|---|
| Health | `GET /health` |
| Cameras | `/api/cameras` |
| Streams | `/api/streams` |
| Zones and footfall | `/api/analytics/zones`, `GET /api/analytics/footfall` |
| Live monitoring | `/api/monitoring/realtime`, `/api/monitoring/cameras/{camera_id}/stream.mjpg` |
| Analysis jobs | `/api/analyzer/run`, `/api/analyzer/jobs`, `/api/analyzer/stats/{job_id}` |
| Person tracks | `/api/analyzer/tracks/{job_id}` |
| Optional face analysis | `/api/analyzer/facial-expression-recognition` |
| Reconstructions | `/api/reconstructions` |

For the complete route definitions and request schemas, inspect the FastAPI application and its controller modules under `app/controllers/`.

## RTSP simulator

The simulator is maintained separately from the main capture application:

- `simulator/backend/`
- `simulator/frontend/`

Start it with:

```bash
docker compose -f docker-compose.simulator.yml up -d --build
```

Default simulator endpoints:

- Simulator dashboard: http://127.0.0.1:3001
- Simulator backend: http://127.0.0.1:8001
- Example RTSP stream: `rtsp://127.0.0.1:8554/stream_<port>`

## Important deployment notes

- RTSP sources must be reachable from the backend process/container.
- Inference availability depends on the model files, their compatible runtime dependencies, and available compute.
- The default BoxMOT device setting is CPU; adjust configuration and validate the installed runtime before relying on GPU inference.
- The optional face-analysis endpoint is a separate workflow and may be unavailable if its model/runtime cannot initialize. Model-estimated attributes should not be treated as ground truth about a person.
- Use appropriate consent, access controls, retention policies, and legal review before processing identifiable camera footage.

## License and contributions

Add the applicable license and contribution instructions here before inviting external contributions. Until then, check the repository owner for reuse permissions.
