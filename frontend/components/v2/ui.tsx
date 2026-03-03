"use client";

import { type ReactNode, useEffect, useMemo, useState } from "react";

import type { RealtimeDetectionBox, Zone } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SourceStatus } from "@/hooks/use-sources-data";


export type AnalyticsMode = "person_count" | "queue" | "entry_exit_count" | "person_reid";

export const ANALYTICS_MODES: Array<{ id: AnalyticsMode; label: string }> = [
  { id: "person_count", label: "Person Count" },
  { id: "queue", label: "Queue Management" },
  { id: "entry_exit_count", label: "Entry/Exit Count" },
  { id: "person_reid", label: "Person ReID" },
];

function readZonePolygons(zone: Zone): Array<Array<{ x: number; y: number }>> {
  const evaluatePoints = (pts: unknown) => {
    if (!Array.isArray(pts)) return [];
    return pts
      .map((point) => {
        if (!point || typeof point !== "object") return null;
        let x = Number((point as { x?: number }).x);
        let y = Number((point as { y?: number }).y);
        if (Number.isNaN(x) || Number.isNaN(y)) return null;
        
        if (x > 2 || y > 2) {
          x = x / 1920;
          y = y / 1080;
        }

        return { x: x * 100, y: y * 100 };
      })
      .filter((point): point is { x: number; y: number } => point !== null);
  };

  const rawPolygons = zone.polygon?.polygons;
  if (Array.isArray(rawPolygons)) {
    return rawPolygons.map(evaluatePoints).filter(poly => poly.length >= 3);
  }

  const legacyPoints = zone.polygon?.points;
  const legacyPoly = evaluatePoints(legacyPoints);
  return legacyPoly.length >= 3 ? [legacyPoly] : [];
}

function readLinePoints(zone: Zone, key: "entry_line" | "exit_line"):
  | {
      x1: number;
      y1: number;
      x2: number;
      y2: number;
    }
  | null {
  const raw = zone.polygon?.[key];
  if (!raw || typeof raw !== "object") return null;

  const points = (raw as { points?: unknown }).points;
  if (!Array.isArray(points) || points.length < 2) return null;

  /* If points are mostly between 0 and 1, they are normalized. Otherwise absolute. */
  const parsed = points
    .slice(0, 2)
    .map((point) => {
      if (!point || typeof point !== "object") return null;
      let x = Number((point as { x?: number }).x);
      let y = Number((point as { y?: number }).y);
      if (Number.isNaN(x) || Number.isNaN(y)) return null;

      // Autodetect if it's not normalized
      if (x > 2 || y > 2) {
        // Fallback for non-normalized lines, though we prefer normalized data from the API
        // This prevents the lines from disappearing if coordinates are saved relatively.
        // We'll scale down assuming a loose max width of 1920 / max height of 1080 for fallback.
        x = x / 1920;
        y = y / 1080;
      }
      return { x: x * 100, y: y * 100 };
    })
    .filter((point): point is { x: number; y: number } => point !== null);

  if (parsed.length < 2) return null;

  return {
    x1: parsed[0].x,
    y1: parsed[0].y,
    x2: parsed[1].x,
    y2: parsed[1].y,
  };
}

export function sourceStatusLabel(status: SourceStatus): string {
  if (status === "live") return "Live";
  if (status === "paused") return "Paused";
  return "Offline";
}

function sourceStatusTone(status: SourceStatus): string {
  if (status === "live") return "border-emerald-600/70 bg-emerald-500/10 text-emerald-700";
  if (status === "paused") return "border-orange-500/70 bg-orange-400/10 text-orange-700";
  return "border-red-500/70 bg-red-500/10 text-red-700";
}

export function PanelCard({
  title,
  subtitle,
  right,
  className,
  children,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn("dashboard-panel rounded-2xl p-4 md:p-5", className)}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">{title}</p>
          {subtitle ? <p className="mt-1 text-xs text-muted-foreground">{subtitle}</p> : null}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

export function StatusPill({ status }: { status: SourceStatus }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold",
        sourceStatusTone(status),
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          status === "live" ? "bg-emerald-600" : status === "paused" ? "bg-orange-600" : "bg-red-600",
        )}
      />
      {sourceStatusLabel(status)}
    </span>
  );
}

export function CameraFeed({
  cameraId,
  title,
  status,
  resolution,
  fps,
  zones = [],
  detectionBoxes = [],
  hasLiveFrame = false,
  compact = false,
  staticFirstFrame = false,
  zoneId,
  analyticsMode,
}: {
  cameraId: number;
  title: string;
  status: SourceStatus;
  resolution: string;
  fps: number;
  zones?: Zone[];
  detectionBoxes?: RealtimeDetectionBox[];
  hasLiveFrame?: boolean;
  compact?: boolean;
  staticFirstFrame?: boolean;
  zoneId?: string;
  analyticsMode?: AnalyticsMode;
}) {
  const [streamErrored, setStreamErrored] = useState(false);
  const [snapshotErrored, setSnapshotErrored] = useState(false);
  const [snapshotTick, setSnapshotTick] = useState(0);
  const [streamNonce, setStreamNonce] = useState(0);

  const analyticsModeParam = analyticsMode ?? "person_count";

  const streamUrlBase = `/api/backend/api/monitoring/cameras/${cameraId}/stream.mjpg`;
  const streamParams = new URLSearchParams({
    v: String(streamNonce),
    analytics_mode: analyticsModeParam,
  });
  if (zoneId && zoneId !== "all") {
    streamParams.set("zone_id", zoneId);
  }
  const streamUrl = `${streamUrlBase}?${streamParams.toString()}`;

  const snapshotUrlBase = staticFirstFrame
    ? `/api/backend/api/monitoring/cameras/${cameraId}/first-frame`
    : `/api/backend/api/monitoring/cameras/${cameraId}/frame`;
  const snapshotParams = new URLSearchParams({
    analytics_mode: analyticsModeParam,
  });
  if (!staticFirstFrame) {
    snapshotParams.set("t", String(snapshotTick));
  }
  if (zoneId && zoneId !== "all") {
    snapshotParams.set("zone_id", zoneId);
  }
  const snapshotUrl = `${snapshotUrlBase}?${snapshotParams.toString()}`;
  const parsedZones = useMemo(
    () => {
      let filteredZones = zones;
      if (zoneId && zoneId !== "all") {
        filteredZones = zones.filter((z) => z.id.toString() === zoneId);
      }
      const results = filteredZones.map((zone) => {
        const polygons = readZonePolygons(zone);
        if (polygons.length === 0) return null;

        return {
          id: zone.id,
          name: zone.name,
          polygons: polygons,
          entryLine: readLinePoints(zone, "entry_line"),
          exitLine: readLinePoints(zone, "exit_line"),
        };
      });
      return results.filter((zone): zone is NonNullable<typeof results[number]> => zone !== null);
    },
    [zones, zoneId],
  );
  const parsedDetectionBoxes = useMemo(
    () =>
      detectionBoxes
        .map((box, index) => {
          const x1 = Number(box.x1);
          const y1 = Number(box.y1);
          const x2 = Number(box.x2);
          const y2 = Number(box.y2);
          if (
            Number.isNaN(x1) ||
            Number.isNaN(y1) ||
            Number.isNaN(x2) ||
            Number.isNaN(y2) ||
            x2 <= x1 ||
            y2 <= y1
          ) {
            return null;
          }
          return {
            key: `${index}-${x1}-${y1}-${x2}-${y2}`,
            x: Math.max(0, Math.min(100, x1 * 100)),
            y: Math.max(0, Math.min(100, y1 * 100)),
            width: Math.max(0, Math.min(100, (x2 - x1) * 100)),
            height: Math.max(0, Math.min(100, (y2 - y1) * 100)),
            inZone: Boolean(box.in_zone),
          };
        })
        .filter(
          (
            box,
          ): box is {
            key: string;
            x: number;
            y: number;
            width: number;
            height: number;
            inZone: boolean;
          } => box !== null,
        ),
    [detectionBoxes],
  );

  const showStream = !staticFirstFrame && status === "live" && hasLiveFrame && !streamErrored;
  const showSnapshot = !showStream && !snapshotErrored;

  useEffect(() => {
    setStreamErrored(false);
    setSnapshotErrored(false);
  }, [analyticsModeParam, cameraId, status, hasLiveFrame, staticFirstFrame]);

  useEffect(() => {
    setSnapshotTick(0);
    setStreamNonce((value) => value + 1);
  }, [analyticsModeParam, cameraId, staticFirstFrame, zoneId]);

  useEffect(() => {
    if (showStream || staticFirstFrame) return undefined;
    const id = window.setInterval(() => {
      setSnapshotTick((value) => value + 1);
    }, 2000);
    return () => window.clearInterval(id);
  }, [showStream, staticFirstFrame]);

  useEffect(() => {
    setSnapshotErrored(false);
  }, [snapshotTick]);

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border border-border/70",
        compact ? "aspect-[16/9]" : "aspect-video",
      )}
    >
      {showStream ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={`stream-${cameraId}-${streamNonce}`}
          src={streamUrl}
          alt={`${title} live feed`}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={() => setStreamErrored(true)}
        />
      ) : (
        <>
          {showSnapshot ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={`snapshot-${cameraId}-${staticFirstFrame ? "first" : "latest"}-${snapshotTick}`}
              src={snapshotUrl}
              alt={`${title} latest frame`}
              className="h-full w-full object-cover"
              loading="lazy"
              onError={() => setSnapshotErrored(true)}
            />
          ) : null}
          {snapshotErrored ? (
            <div className="absolute inset-0 bg-[linear-gradient(160deg,#111a23_0%,#182939_45%,#263d4f_100%)]" />
          ) : null}
        </>
      )}

      {showStream || showSnapshot ? null : (
        <div className="h-full w-full bg-[linear-gradient(160deg,#111a23_0%,#182939_45%,#263d4f_100%)]" />
      )}

      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:22px_22px]" />

      {parsedZones.length > 0 ? (
        <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          {parsedZones.map((zone) => (
            <g key={zone.id}>
              {analyticsMode !== "entry_exit_count" ? (
                <>
                  {zone.polygons.map((poly: {x: number, y: number}[], i: number) => (
                    <polygon
                      key={`${zone.id}-poly-${i}`}
                      points={poly.map((point: {x: number, y: number}) => `${point.x},${point.y}`).join(" ")}
                      fill="rgba(20, 184, 166, 0.2)"
                      stroke="rgba(20, 184, 166, 0.95)"
                      strokeWidth="0.8"
                      strokeDasharray="2.4 1.6"
                    />
                  ))}
                  <text
                    x={zone.polygons[0]?.[0]?.x ?? 2}
                    y={Math.max((zone.polygons[0]?.[0]?.y ?? 3) - 1.2, 2)}
                    fill="rgba(237, 253, 255, 0.95)"
                    fontSize="2.8"
                    fontWeight="700"
                  >
                    {zone.name}
                  </text>
                </>
              ) : null}
              {analyticsMode !== "entry_exit_count" && zone.entryLine ? (
                <line
                  x1={zone.entryLine.x1}
                  y1={zone.entryLine.y1}
                  x2={zone.entryLine.x2}
                  y2={zone.entryLine.y2}
                  stroke="rgba(16, 185, 129, 0.98)"
                  strokeWidth="0.9"
                  strokeDasharray="1.6 1.2"
                />
              ) : null}
              {analyticsMode !== "entry_exit_count" && zone.exitLine ? (
                <line
                  x1={zone.exitLine.x1}
                  y1={zone.exitLine.y1}
                  x2={zone.exitLine.x2}
                  y2={zone.exitLine.y2}
                  stroke="rgba(239, 68, 68, 0.98)"
                  strokeWidth="0.9"
                  strokeDasharray="1.6 1.2"
                />
              ) : null}
            </g>
          ))}
        </svg>
      ) : null}

      {/* RENDER BOXES ONLY IF NOT IN ENTRY/EXIT MODE */}
      {parsedDetectionBoxes.length > 0 && (showStream || showSnapshot) && analyticsMode !== "entry_exit_count" ? (
        <>
          {parsedDetectionBoxes.map((box) => (
            <div
              key={box.key}
              className="absolute border-[1.5px] transition-all duration-300"
              style={{
                left: `${box.x}%`,
                top: `${box.y}%`,
                width: `${box.width}%`,
                height: `${box.height}%`,
                borderColor: box.inZone ? "rgba(20, 184, 166, 0.8)" : "rgba(239, 68, 68, 0.6)",
                backgroundColor: box.inZone ? "rgba(20, 184, 166, 0.15)" : "transparent",
                boxShadow: box.inZone ? "0 0 10px rgba(20, 184, 166, 0.3)" : "none",
              }}
            >
              {box.inZone && (
                <div className="absolute -top-5 left-0 rounded bg-teal-500/90 px-1.5 py-0.5 text-[0.6rem] font-bold tracking-wider text-white shadow-sm backdrop-blur-md">
                  PERSON
                </div>
              )}
            </div>
          ))}
        </>
      ) : null}

      <div className="absolute left-2 top-2 inline-flex items-center gap-2 rounded-md bg-slate-900/70 px-2 py-1 text-[10px] font-semibold text-slate-100">
        <StatusPill status={status} />
        <span className="max-w-[140px] truncate">{title}</span>
      </div>

      <div className="absolute bottom-2 right-2 rounded-md bg-slate-900/70 px-2 py-1 text-[10px] text-slate-200">
        {resolution} • {fps}fps
      </div>

      {!showStream && !showSnapshot ? (
        <div className="absolute inset-0 grid place-items-center text-[11px] text-slate-200/90">
          {status === "live" ? "Waiting for frames..." : "Stream unavailable"}
        </div>
      ) : null}
    </div>
  );
}

export function MiniLineChart({ values, className }: { values: number[]; className?: string }) {
  const width = 420;
  const height = 110;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = Math.max(max - min, 1);

  const points = values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / span) * (height - 10) - 5;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={cn("h-[110px] w-full", className)}>
      <polyline points={points} fill="none" stroke="hsl(var(--primary))" strokeWidth="2.4" />
      <polyline
        points={`${points} ${width},${height} 0,${height}`}
        fill="hsl(var(--primary) / 0.2)"
        stroke="none"
      />
    </svg>
  );
}

export function MultiZoneLineChart({
  series,
  className,
}: {
  series: { id: string | number; name: string; color: string; values: number[] }[];
  className?: string;
}) {
  const width = 420;
  const height = 110;
  
  // Find global max to scale properly across all overlapping graph sets
  const allValues = series.flatMap(s => s.values);
  const max = Math.max(...allValues, 1);
  const min = Math.min(...allValues, 0);
  const span = Math.max(max - min, 1);

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${width} ${height}`} className={cn("h-[110px] w-full", className)}>
        {series.map((line) => {
          if (line.values.length === 0) return null;
          
          const points = line.values
            .map((value, index) => {
              const x = (index / Math.max(line.values.length - 1, 1)) * width;
              const y = height - ((value - min) / span) * (height - 10) - 5;
              return `${x},${y}`;
            })
            .join(" ");

          return (
            <polyline
              key={line.id}
              points={points}
              fill="none"
              stroke={line.color}
              strokeWidth="2.4"
              opacity="0.85"
            />
          );
        })}
      </svg>
    </div>
  );
}

export function MiniBarChart({ values, className }: { values: number[]; className?: string }) {
  const width = 420;
  const height = 110;
  const gap = 4;
  const barWidth = (width - gap * (values.length + 1)) / Math.max(values.length, 1);
  const max = Math.max(...values, 1);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={cn("h-[110px] w-full", className)}>
      {values.map((value, index) => {
        const x = gap + index * (barWidth + gap);
        const barHeight = (value / max) * (height - 10);
        const y = height - barHeight - 2;
        return (
          <rect
            key={`${index}-${value}`}
            x={x}
            y={y}
            width={barWidth}
            height={barHeight}
            rx="4"
            fill="hsl(var(--secondary))"
            opacity="0.85"
          />
        );
      })}
    </svg>
  );
}

export function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-border/70 bg-white/80 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-primary">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}
