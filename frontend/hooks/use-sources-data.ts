"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  type Camera,
  type RealtimeCameraSnapshot,
  type Stream,
  createCamera,
  deleteCamera,
  getAnalyticsRunState,
  getRealtimeMonitoring,
  listCameras,
  listStreams,
  startAnalyticsRun,
  startStream,
  stopAnalyticsRun,
  stopStream,
  uploadVideoSource,
  updateCamera,
} from "@/lib/api";

export type SourceStatus = "live" | "paused" | "offline";

export type SourceRow = {
  camera: Camera;
  stream: Stream | null;
  realtime: RealtimeCameraSnapshot | null;
  hasLiveFrame: boolean;
  status: SourceStatus;
  type: "RTSP" | "Video File" | "Webcam";
  endpoint: string;
  resolution: string;
  fps: number;
  uptime: string;
};

export type SaveSourceInput = {
  cameraId?: number;
  name: string;
  sourceType: "rtsp" | "file" | "webcam";
  rtspUrl: string;
  webcamId?: string;
  file?: File | null;
  fileName: string;
  scheduleLabel: string;
  autoStartStream?: boolean;
};

type Options = {
  pollCoreMs?: number;
  pollRealtimeMs?: number;
  enableRealtime?: boolean;
};

const DEFAULT_RESOLUTION = "1920x1080";
const DEFAULT_FPS = 25;

function statusFromStream(
  streamStatus: string | null | undefined,
  hasSource: boolean,
): SourceStatus {
  if (streamStatus === "running") return "live";
  if (streamStatus === "starting" || streamStatus === "stopped") return "paused";
  if (streamStatus === "error") return "offline";
  return hasSource ? "paused" : "offline";
}

function formatUptime(startedAt: string | null | undefined, status: SourceStatus): string {
  if (!startedAt || status !== "live") return "-";
  const startedMs = new Date(startedAt).getTime();
  if (Number.isNaN(startedMs)) return "-";

  const elapsedMs = Date.now() - startedMs;
  if (elapsedMs <= 0) return "0m";

  const totalMinutes = Math.floor(elapsedMs / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m`;
}

function sourceEndpoint(camera: Camera, sourceType: "RTSP" | "Video File" | "Webcam"): string {
  if (sourceType === "RTSP") {
    return camera.rtsp_url || "-";
  }
  if (sourceType === "Webcam") {
    return camera.rtsp_url ? camera.rtsp_url.replace("webcam://", "Device: ") : "Unknown Device";
  }
  const location = camera.location?.trim() || "";
  const fileFromLocation = location.includes("File:")
    ? location.split("File:")[1]?.split("|")[0]?.trim() || ""
    : "";
  if (fileFromLocation) {
    return fileFromLocation;
  }
  const fileUrl = camera.rtsp_url || "";
  if (fileUrl.toLowerCase().startsWith("file://")) {
    const encodedName = fileUrl.split("/").pop() || "";
    if (encodedName) {
      try {
        return decodeURIComponent(encodedName);
      } catch {
        return encodedName;
      }
    }
  }
  if (camera.location?.trim()) {
    return camera.location;
  }
  return "Uploaded video";
}

function sourceTypeForCamera(camera: Camera): "RTSP" | "Video File" | "Webcam" {
  const source = (camera.rtsp_url || "").trim().toLowerCase();
  if (source.startsWith("webcam://")) return "Webcam";
  if (source.startsWith("rtsp://") || source.startsWith("rtsps://")) return "RTSP";
  if (source.startsWith("file://")) return "Video File";
  return source ? "RTSP" : "Video File";
}

function buildCameraLocation(input: SaveSourceInput): string | undefined {
  const parts: string[] = [];
  const selectedFileName = input.file?.name?.trim() || input.fileName.trim();
  if (input.sourceType === "file" && selectedFileName) {
    parts.push(`File: ${selectedFileName}`);
  }
  if (input.scheduleLabel.trim()) {
    parts.push(`Schedule: ${input.scheduleLabel.trim()}`);
  }
  return parts.length ? parts.join(" | ") : undefined;
}

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function useSourcesData(options: Options = {}) {
  const {
    pollCoreMs = 12000,
    pollRealtimeMs = 1500,
    enableRealtime = true,
  } = options;

  const [cameras, setCameras] = useState<Camera[]>([]);
  const [streams, setStreams] = useState<Stream[]>([]);
  const [realtime, setRealtime] = useState<RealtimeCameraSnapshot[]>([]);
  const [detectorAvailable, setDetectorAvailable] = useState(false);
  const [analyticsRunning, setAnalyticsRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const refreshCore = useCallback(async () => {
    try {
      const [cameraRows, streamRows] = await Promise.all([listCameras(), listStreams()]);
      setCameras(cameraRows);
      setStreams(streamRows);
    } catch (err) {
      setError(toErrorMessage(err, "Failed to refresh camera sources"));
    }
  }, []);

  const refreshRealtime = useCallback(async () => {
    if (!enableRealtime) return;
    try {
      const payload = await getRealtimeMonitoring();
      setRealtime(payload.cameras);
      setDetectorAvailable(payload.detector_available);
      setAnalyticsRunning(payload.analytics_running);
    } catch {
      // Keep last successful realtime payload to avoid noisy UI on transient errors.
    }
  }, [enableRealtime]);

  useEffect(() => {
    if (enableRealtime) return;
    let cancelled = false;
    void (async () => {
      try {
        const state = await getAnalyticsRunState();
        if (!cancelled) {
          setAnalyticsRunning(state.running);
        }
      } catch {
        // Ignore transient failures; realtime response will include this when enabled.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enableRealtime]);

  const refreshAll = useCallback(async () => {
    setBusy(true);
    setError("");
    await Promise.all([refreshCore(), refreshRealtime()]);
    setBusy(false);
  }, [refreshCore, refreshRealtime]);

  useEffect(() => {
    void refreshAll();
    const id = window.setInterval(() => {
      void refreshCore();
    }, pollCoreMs);
    return () => window.clearInterval(id);
  }, [pollCoreMs, refreshAll, refreshCore]);

  useEffect(() => {
    if (!enableRealtime) return undefined;
    const id = window.setInterval(() => {
      void refreshRealtime();
    }, pollRealtimeMs);
    return () => window.clearInterval(id);
  }, [enableRealtime, pollRealtimeMs, refreshRealtime]);

  const streamByCamera = useMemo(() => {
    const map = new Map<number, Stream>();
    for (const stream of streams) {
      map.set(stream.camera_id, stream);
    }
    return map;
  }, [streams]);

  const realtimeByCamera = useMemo(() => {
    const map = new Map<number, RealtimeCameraSnapshot>();
    for (const snapshot of realtime) {
      map.set(snapshot.camera_id, snapshot);
    }
    return map;
  }, [realtime]);

  const sources = useMemo<SourceRow[]>(() => {
    return cameras
      .map((camera) => {
        const stream = streamByCamera.get(camera.id) ?? null;
        const snapshot = realtimeByCamera.get(camera.id) ?? null;
        const streamStatus = snapshot?.stream_status ?? stream?.status;
        const type = sourceTypeForCamera(camera);
        const hasLiveFrame = Boolean(snapshot?.has_live_frame);
        const inferredStatus = statusFromStream(streamStatus, Boolean(camera.rtsp_url?.trim()));
        const status: SourceStatus = hasLiveFrame ? "live" : inferredStatus;

        return {
          camera,
          stream,
          realtime: snapshot,
          hasLiveFrame,
          status,
          type,
          endpoint: sourceEndpoint(camera, type),
          resolution: DEFAULT_RESOLUTION,
          fps: status === "live" ? DEFAULT_FPS : 0,
          uptime: formatUptime(stream?.started_at, status),
        };
      })
      .sort((a, b) => a.camera.id - b.camera.id);
  }, [cameras, realtimeByCamera, streamByCamera]);

  const sourceById = useMemo(() => {
    const map = new Map<number, SourceRow>();
    for (const source of sources) {
      map.set(source.camera.id, source);
    }
    return map;
  }, [sources]);

  const counts = useMemo(() => {
    const live = sources.filter((source) => source.status === "live").length;
    const paused = sources.filter((source) => source.status === "paused").length;
    const offline = sources.filter((source) => source.status === "offline").length;
    return {
      total: sources.length,
      live,
      paused,
      offline,
    };
  }, [sources]);

  const toggleStreamForCamera = useCallback(
    async (cameraId: number) => {
      const source = sourceById.get(cameraId);
      if (!source) return;

      setBusy(true);
      setError("");
      setNotice("");
      try {
        if (source.status === "live") {
          await stopStream({ camera_id: cameraId });
          setNotice(`Paused stream for #${cameraId}`);
        } else {
          await startStream(cameraId);
          setNotice(`Started stream for #${cameraId}`);
        }
      } catch (err) {
        setError(toErrorMessage(err, "Failed to toggle stream"));
      } finally {
        await Promise.all([refreshCore(), refreshRealtime()]);
        setBusy(false);
      }
    },
    [refreshCore, refreshRealtime, sourceById],
  );

  const deleteSourceByCamera = useCallback(
    async (cameraId: number) => {
      setBusy(true);
      setError("");
      setNotice("");
      try {
        await deleteCamera(cameraId);
        setNotice(`Deleted camera #${cameraId}`);
      } catch (err) {
        setError(toErrorMessage(err, "Failed to delete source"));
      } finally {
        await Promise.all([refreshCore(), refreshRealtime()]);
        setBusy(false);
      }
    },
    [refreshCore, refreshRealtime],
  );

  const saveSource = useCallback(
    async (input: SaveSourceInput) => {
      setBusy(true);
      setError("");
      setNotice("");
      const name = input.name.trim();
      const location = buildCameraLocation(input);

      try {
        let camera: Camera;
        if (input.sourceType === "file") {
          if (input.file) {
            const uploaded = await uploadVideoSource({
              file: input.file,
              name,
              location,
              cameraId: input.cameraId,
            });
            camera = uploaded.camera;
            setNotice(
              input.cameraId
                ? `Updated source #${camera.id} with uploaded video`
                : `Created source #${camera.id} from uploaded video`,
            );
          } else if (input.cameraId) {
            camera = await updateCamera(input.cameraId, {
              name,
              location,
            });
            setNotice(`Updated source #${camera.id}`);
          } else {
            throw new Error("Select a video file to upload");
          }
        } else if (input.sourceType === "webcam") {
          const deviceUrl = `webcam://${input.webcamId?.trim() || "0"}`;
          if (input.cameraId) {
            camera = await updateCamera(input.cameraId, {
              name,
              rtsp_url: deviceUrl,
              location,
            });
            setNotice(`Updated source #${camera.id}`);
          } else {
            camera = await createCamera({
              name,
              rtsp_url: deviceUrl,
              location,
            });
            setNotice(`Created source #${camera.id}`);
          }
        } else {
          const trimmedRtspUrl = input.rtspUrl.trim();
          if (input.cameraId) {
            camera = await updateCamera(input.cameraId, {
              name,
              rtsp_url: trimmedRtspUrl || null,
              location,
            });
            setNotice(`Updated source #${camera.id}`);
          } else {
            camera = await createCamera({
              name,
              rtsp_url: trimmedRtspUrl || undefined,
              location,
            });
            setNotice(`Created source #${camera.id}`);
          }
        }

        if (input.autoStartStream) {
          await startStream(camera.id);
          setNotice(`Source #${camera.id} saved and stream started`);
        }

        await Promise.all([refreshCore(), refreshRealtime()]);
        return camera;
      } catch (err) {
        setError(toErrorMessage(err, "Failed to save source"));
        throw err;
      } finally {
        setBusy(false);
      }
    },
    [refreshCore, refreshRealtime],
  );

  const startAnalyticsProcessing = useCallback(async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const state = await startAnalyticsRun();
      setAnalyticsRunning(state.running);
      setNotice("Analytics started");
      await refreshRealtime();
    } catch (err) {
      setError(toErrorMessage(err, "Failed to start analytics"));
    } finally {
      setBusy(false);
    }
  }, [refreshRealtime]);

  const stopAnalyticsProcessing = useCallback(async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const state = await stopAnalyticsRun();
      setAnalyticsRunning(state.running);
      setNotice("Analytics stopped");
      await refreshRealtime();
    } catch (err) {
      setError(toErrorMessage(err, "Failed to stop analytics"));
    } finally {
      setBusy(false);
    }
  }, [refreshRealtime]);

  return {
    busy,
    error,
    notice,
    setError,
    setNotice,
    detectorAvailable,
    analyticsRunning,
    cameras,
    streams,
    realtime,
    sources,
    sourceById,
    counts,
    refreshCore,
    refreshRealtime,
    refreshAll,
    toggleStreamForCamera,
    deleteSourceByCamera,
    saveSource,
    startAnalyticsProcessing,
    stopAnalyticsProcessing,
  };
}
