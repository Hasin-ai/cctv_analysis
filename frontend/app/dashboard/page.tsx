"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Pencil, Pause, Play, Plus, Search, Trash2, Filter } from "lucide-react";

import type { RealtimeZoneCount } from "@/lib/api";
import { type FootfallResponse, type Zone, getFootfall, listZones } from "@/lib/api";
import { useSourcesData } from "@/hooks/use-sources-data";
import {
  CameraFeed,
  MiniLineChart,
  MultiZoneLineChart,
  PanelCard,
  StatTile,
  StatusPill
} from "@/components/v2/ui";
import { PersonReidAnalyticsPanel } from "@/components/v2/person-reid-analytics-panel";
import { ZoneQuickEditor } from "@/components/v2/zone-quick-editor";
import { QueueAnalyticsPanel } from "@/components/v2/queue-analytics-panel";
import { ZoneAnalysisPanel } from "@/components/v2/zone-analysis-panel";

type AnalyticsMode = "person_count" | "person_reid" | "entry_exit_count" | "queue";

const ANALYTICS_MODES: { id: AnalyticsMode; label: string; desc: string }[] = [
  { id: "person_count", label: "Person Count", desc: "Standard detection and unique IDs" },
  { id: "queue", label: "Queue Management", desc: "Waiting times & line length" },
  { id: "entry_exit_count", label: "Entry/Exit Count", desc: "Track line-crossing per zone" },
  { id: "person_reid", label: "Person ReID", desc: "Track identities across frames" },
];

const ANALYTICS_SEARCH_TERMS: Record<AnalyticsMode, string[]> = {
  person_count: ["person count", "person", "count", "crowd"],
  queue: ["queue", "queue management", "line", "wait", "waiting"],
  entry_exit_count: ["entry", "exit", "entry exit", "entry/exit", "extry", "extry exit"],
  person_reid: ["person reid", "reid", "re-id", "identity", "track id"],
};

const ZONE_ANALYSIS_SEARCH_TERMS = ["zone analysis", "zone", "congestion", "path", "heatmap", "staff", "service"];

type TimelinePoint = {
  ts: number;
  person: number;
};

function ModeAnalyticsPanel({
  timeline,
  zones = [],
  liveZones = [],
  footfall = null,
  isPersonCountMode = false,
  sourceType = "RTSP",
}: {
  timeline: TimelinePoint[];
  zones?: Zone[];
  liveZones?: RealtimeZoneCount[];
  footfall?: FootfallResponse | null;
  isPersonCountMode?: boolean;
  sourceType?: "RTSP" | "Video File";
}) {
  const current = timeline[timeline.length - 1] ?? {
    ts: Date.now(),
    person: 0,
  };

  const avgPerson =
    timeline.length > 0
      ? Math.round(timeline.reduce((sum, point) => sum + point.person, 0) / timeline.length)
      : 0;

  const availableVideoHours = footfall?.video_available_hours ?? 0;
  const peakHourPayload = footfall?.peak_person_count_hour ?? null;
  const mostCrowdedQuarter = footfall?.most_crowded_quarter ?? null;
  const isVideoSource = sourceType === "Video File";
  const peakWindowLabel = formatTimeOnlyRange(peakHourPayload?.hour_start, peakHourPayload?.hour_end);
  const peakWindowDate = formatDateLabel(peakHourPayload?.hour_start);
  const peakHint =
    peakWindowLabel === "N/A"
      ? "No hourly person-count history"
      : `${peakHourPayload?.zone_name ?? "Selected scope"} | ${peakWindowDate} | Max persons: ${peakHourPayload?.person_count ?? 0}`;
  const crowdedQuarterRange = formatDateTimeRange(
    mostCrowdedQuarter?.start_time,
    mostCrowdedQuarter?.end_time,
  );
  const crowdedQuarterHint =
    crowdedQuarterRange === "N/A"
      ? "No quarter crowding history"
      : `${mostCrowdedQuarter?.zone_name ?? "Selected scope"} | ${crowdedQuarterRange}`;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile label="People Now" value={current.person} hint="Detected in frame" />
        <StatTile label="Peak" value={Math.max(...timeline.map((point) => point.person), 0)} hint="Current window" />
        <StatTile label="Average" value={avgPerson} hint="Rolling average" />
        <StatTile
          label="Video Available"
          value={`${availableVideoHours.toFixed(2)}h`}
          hint="Captured in selected window"
        />
        {isPersonCountMode ? (
          isVideoSource ? (
            <StatTile
              label="Most Crowded Quarter"
              value={mostCrowdedQuarter?.quarter_label ?? "N/A"}
              hint={crowdedQuarterHint}
            />
          ) : (
            <StatTile
              label="Peak Hour Window"
              value={peakWindowLabel}
              hint={peakHint}
            />
          )
        ) : null}
      </div>
      <div className="rounded-xl border border-border/70 bg-white/80 p-3">
        <MiniLineChart values={timeline.map((point) => point.person)} />
      </div>
      
      {zones.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border/70 bg-white/80 mt-3">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Zone</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Live Count</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Capacity / Status</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((zone) => {
                const liveCount = liveZones.find((lz) => lz.zone_id === zone.id)?.person_count ?? 0;
                const capacity = zone.capacity;
                const statusStr = capacity 
                  ? (liveCount > capacity ? `+${liveCount - capacity} Extra Persons` : `${liveCount} / ${capacity} Capacity`) 
                  : "-";
                  
                return (
                  <tr key={zone.id} className="border-t border-border/50">
                    <td className="px-3 py-2 text-foreground">{zone.name}</td>
                    <td className="px-3 py-2 tabular-nums text-sky-700">{liveCount}</td>
                    <td className="px-3 py-2 tabular-nums font-semibold">
                      <span className={capacity && liveCount > capacity ? "text-rose-600" : "text-emerald-600"}>{statusStr}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function toTimelinePoint(currentPerson: number): TimelinePoint {
  return {
    ts: Date.now(),
    person: currentPerson,
  };
}

function EntryExitAnalyticsPanel({
  footfall,
  liveZones = [],
  searchQuery = "",
  selectedZoneId = "all",
}: {
  footfall: FootfallResponse | null;
  liveZones?: RealtimeZoneCount[];
  searchQuery?: string;
  selectedZoneId?: string;
}) {
  const hasRealEvents = useMemo(() => {
    if (!footfall) return false;
    if (footfall.total_entries > 0 || footfall.total_exits > 0) return true;
    return footfall.series?.some((point) => point.entry_count > 0 || point.exit_count > 0 || point.count > 0) ?? false;
  }, [footfall]);

  const filteredZoneTotals = useMemo(() => {
    if (!footfall) return [];

    // First apply explicit Zone ID filter if set
    let activeTotals = footfall.zone_totals || [];
    if (selectedZoneId && selectedZoneId !== "all") {
      const zoneIdNum = Number(selectedZoneId);
      if (!Number.isNaN(zoneIdNum)) {
        activeTotals = activeTotals.filter((t) => t.zone_id === zoneIdNum);
      }
    }

    // Hide placeholder all-zero rows (configured zones without real transitions AND zero live presence).
    activeTotals = activeTotals.filter((z) => {
      const hasTransitions = z.total_entries > 0 || z.total_exits > 0;
      const liveCount = liveZones?.find((lz) => lz.zone_id === z.zone_id)?.person_count ?? 0;
      return hasTransitions || liveCount > 0;
    });

    // Then apply exact search formatting
    if (!searchQuery.trim()) return activeTotals;
    const lower = searchQuery.toLowerCase();
    return activeTotals.filter((z) => {
      const name = z.zone_name ?? `Zone ${z.zone_id ?? "-"}`;
      return name.toLowerCase().includes(lower);
    });
  }, [footfall, searchQuery, selectedZoneId, liveZones]);

  const seriesByZone = useMemo(() => {
    if (!footfall) return [];
    
    // Group series by zone
    const map = new Map<number | null, typeof footfall.series>();
    for (const pt of footfall.series) {
      if (!map.has(pt.zone_id)) map.set(pt.zone_id, []);
      map.get(pt.zone_id)!.push(pt);
    }
    
    // Convert to target format
    const results = Array.from(map.entries()).map(([zId, pts]) => {
      const recent = pts.slice(-36);
      
      const netSeries = recent.reduce<number[]>((acc, p) => {
        const prev = acc[acc.length - 1] ?? 0;
        acc.push(prev + p.net_count);
        return acc;
      }, []);

      const zName = footfall.zone_totals?.find(t => t.zone_id === zId)?.zone_name ?? (zId === null ? "Global Tracking" : `Zone ${zId}`);
      
      const colors = ["#0f766e", "#ea580c", "#1d4ed8", "#dc2626", "#7c3aed", "#15803d"];
      const cIdx = zId ? zId % colors.length : 0;
      
      return {
        id: zId ?? "global",
        name: zName,
        color: colors[cIdx],
        entryValues: recent.map(p => p.entry_count),
        exitValues: recent.map(p => p.exit_count),
        netValues: netSeries,
      };
    });
    
    // Apply filters
    if (selectedZoneId && selectedZoneId !== "all") {
        const zNum = Number(selectedZoneId);
        return results.filter(r => r.id === zNum);
    }
    return results;
  }, [footfall, selectedZoneId]);

  const peakTrafficWindow = useMemo(
    () => formatTimeOnlyRange(footfall?.peak_traffic_hour?.hour_start, footfall?.peak_traffic_hour?.hour_end),
    [footfall],
  );
  const peakTrafficDate = useMemo(
    () => formatDateLabel(footfall?.peak_traffic_hour?.hour_start),
    [footfall],
  );

  if (!footfall) {
    return <p className="text-sm text-muted-foreground">No entry/exit analytics available yet for this camera.</p>;
  }
  if (!hasRealEvents && (!liveZones || liveZones.length === 0)) {
    return <p className="text-sm text-muted-foreground">No real entry/exit events recorded yet for this camera.</p>;
  }

  const liveByZoneId = new Map<number, number>();
  for (const zone of liveZones) {
    liveByZoneId.set(zone.zone_id, zone.person_count);
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile label="Total Entries" value={footfall.total_entries} hint="Tracked with ByteTrack IDs" />
        <StatTile label="Total Exits" value={footfall.total_exits} hint="Tracked with ByteTrack IDs" />
        <StatTile label="Net Flow" value={footfall.net_flow} hint="Entries minus exits" />
        <StatTile
          label="Peak Hour Window"
          value={peakTrafficWindow}
          hint={
            peakTrafficWindow === "N/A"
              ? "Highest traffic window"
              : `${peakTrafficDate} | Traffic: ${footfall.peak_traffic_hour?.traffic_count ?? 0}`
          }
        />
        <StatTile label="Estimated Occupancy" value={Math.max(footfall.net_flow, 0)} hint="Derived occupancy trend" />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <div className="rounded-xl border border-border/70 bg-white/80 p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Entry Trend (Multi-Zone)</p>
          {seriesByZone.length > 0 ? (
            <div className="mb-2 space-y-2">
              <MultiZoneLineChart series={seriesByZone.map(s => ({ id: s.id, name: s.name, color: s.color, values: s.entryValues }))} />
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold">
                {seriesByZone.map(s => (
                  <div key={s.id} className="flex items-center gap-1">
                    <div className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                    <span className="text-muted-foreground">{s.name}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No trend points yet.</p>
          )}
        </div>
        <div className="rounded-xl border border-border/70 bg-white/80 p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Exit Trend (Multi-Zone)</p>
          {seriesByZone.length > 0 ? (
            <div className="mb-2 space-y-2">
              <MultiZoneLineChart series={seriesByZone.map(s => ({ id: s.id, name: s.name, color: s.color, values: s.exitValues }))} />
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold">
                {seriesByZone.map(s => (
                  <div key={s.id} className="flex items-center gap-1">
                    <div className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                    <span className="text-muted-foreground">{s.name}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No trend points yet.</p>
          )}
        </div>
        <div className="rounded-xl border border-border/70 bg-white/80 p-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Net Trend / Occupancy</p>
          {seriesByZone.length > 0 ? (
            <div className="mb-2 space-y-2">
              <MultiZoneLineChart series={seriesByZone.map(s => ({ id: s.id, name: s.name, color: s.color, values: s.netValues }))} />
              <div className="flex flex-wrap gap-2 text-[10px] font-semibold">
                {seriesByZone.map(s => (
                  <div key={s.id} className="flex items-center gap-1">
                    <div className="h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                    <span className="text-muted-foreground">{s.name}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No trend points yet.</p>
          )}
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border/70 bg-white/80">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-muted/40 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Zone</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Live</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Entries</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Exits</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Net</th>
            </tr>
          </thead>
          <tbody>
            {filteredZoneTotals.length === 0 ? (
              <tr>
                <td className="px-3 py-3 text-muted-foreground" colSpan={5}>
                  {searchQuery.trim() ? "No zones match your search." : "No zone transitions recorded in the selected window."}
                </td>
              </tr>
            ) : (
              filteredZoneTotals.map((zone) => (
                <tr key={`${zone.zone_id ?? "none"}-${zone.zone_name ?? "zone"}`} className="border-t border-border/50">
                  <td className="px-3 py-2 text-foreground">{zone.zone_name ?? `Zone ${zone.zone_id ?? "-"}`}</td>
                  <td className="px-3 py-2 tabular-nums text-sky-700">
                    {zone.zone_id !== null ? (liveByZoneId.get(zone.zone_id) ?? 0) : "-"}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-emerald-700">{zone.total_entries}</td>
                  <td className="px-3 py-2 tabular-nums text-rose-700">{zone.total_exits}</td>
                  <td className="px-3 py-2 tabular-nums font-semibold text-foreground">{zone.net_flow}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function hoursAgoIso(hours: number): string {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
}

function formatDateTimeRange(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return "N/A";
  const parsedStart = new Date(start);
  const parsedEnd = new Date(end);
  if (Number.isNaN(parsedStart.getTime()) || Number.isNaN(parsedEnd.getTime())) return "N/A";
  const s = parsedStart.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: true });
  const e = parsedEnd.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: true });
  return `${s} to ${e}`;
}

function formatTimeOnlyRange(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return "N/A";
  const parsedStart = new Date(start);
  const parsedEnd = new Date(end);
  if (Number.isNaN(parsedStart.getTime()) || Number.isNaN(parsedEnd.getTime())) return "N/A";
  const s = parsedStart.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true }).toLowerCase();
  const e = parsedEnd.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true }).toLowerCase();

  const sMatch = /^(\d{1,2}:\d{2})\s*([ap]m)$/.exec(s);
  const eMatch = /^(\d{1,2}:\d{2})\s*([ap]m)$/.exec(e);
  if (!sMatch || !eMatch) return `${s}-${e}`;

  const sTime = sMatch[1];
  const sPeriod = sMatch[2];
  const eTime = eMatch[1];
  const ePeriod = eMatch[2];

  if (sPeriod === ePeriod) {
    return `${sTime}-${eTime} ${ePeriod}`;
  }
  return `${sTime} ${sPeriod}-${eTime} ${ePeriod}`;
}

function formatDateLabel(value: string | null | undefined): string {
  if (!value) return "N/A";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "N/A";
  return parsed.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

export default function DashboardPage() {
  const router = useRouter();
  const {
    busy,
    error,
    notice,


    analyticsRunning,
    sources,
    sourceById,
    toggleStreamForCamera,
    deleteSourceByCamera,

  } = useSourcesData();

  const [selectedCameraId, setSelectedCameraId] = useState<number | null>(null);
  const [queryCameraId, setQueryCameraId] = useState<number | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string>("all");
  const [overlayMode, setOverlayMode] = useState<AnalyticsMode>("person_count");
  const [historyByCamera, setHistoryByCamera] = useState<Record<string, TimelinePoint[]>>({});
  const [zonesByCamera, setZonesByCamera] = useState<Record<number, Zone[]>>({});
  const [footfallByCamera, setFootfallByCamera] = useState<Record<number, FootfallResponse>>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [analyticsSearchQuery, setAnalyticsSearchQuery] = useState("");
  const [timeRange, setTimeRange] = useState<"12h" | "today" | "24h">("today");
  const [showZoneEditor, setShowZoneEditor] = useState(false);

  const getStartTimestamp = useCallback(() => {
    if (timeRange === "12h") return hoursAgoIso(12);
    if (timeRange === "24h") return hoursAgoIso(24);
    if (timeRange === "today") {
       const d = new Date();
       d.setHours(0, 0, 0, 0);
       return d.toISOString();
    }
    return hoursAgoIso(12);
  }, [timeRange]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const fromQuery = Number(new URLSearchParams(window.location.search).get("camera_id"));
    if (Number.isNaN(fromQuery) || fromQuery <= 0) return;
    setQueryCameraId(fromQuery);
  }, []);

  useEffect(() => {
    if (!queryCameraId) return;
    setSelectedCameraId(queryCameraId);
  }, [queryCameraId]);

  useEffect(() => {
    if (sources.length === 0) {
      setSelectedCameraId(null);
      return;
    }

    if (!selectedCameraId || !sourceById.has(selectedCameraId)) {
      setSelectedCameraId(sources[0].camera.id);
    }
  }, [selectedCameraId, sourceById, sources]);

  useEffect(() => {
    if (!analyticsRunning) return;
    setHistoryByCamera((previous) => {
      const next = { ...previous };

      for (const source of sources) {
        if (!source.realtime) continue;
        // If a specific zone is selected, use that zone's live counts for the timeline
        let currentPerson = source.realtime.total_person_count;

        if (selectedZoneId !== "all") {
          const zoneId = Number(selectedZoneId);
          const activeZone = source.realtime.zones?.find((z) => z.zone_id === zoneId);
          if (activeZone) {
            currentPerson = activeZone.person_count;
          } else {
            currentPerson = 0;
          }
        }

        const historyKey = `${source.camera.id}-${selectedZoneId}`;
        const list = next[historyKey] ?? [];
        const point = toTimelinePoint(currentPerson);
        next[historyKey] = [...list.slice(-23), point];
      }

      return next;
    });
  }, [analyticsRunning, sources, selectedZoneId]);

  const loadZones = useCallback(async (cameraId: number) => {
    try {
      const rows = await listZones(cameraId);
      setZonesByCamera((previous) => ({ ...previous, [cameraId]: rows }));
    } catch {
      // Keep previous zones to avoid interrupting dashboard view on transient issues.
    }
  }, []);

  useEffect(() => {
    if (!selectedCameraId) return;
    void loadZones(selectedCameraId);
    const id = window.setInterval(() => {
      void loadZones(selectedCameraId);
    }, 5000);
    return () => window.clearInterval(id);
  }, [loadZones, selectedCameraId]);

  const loadFootfall = useCallback(async (cameraId: number, zoneId: string) => {
    try {
      const payload = await getFootfall({
        cameraId,
        zoneId: zoneId !== "all" ? Number(zoneId) : undefined,
        start: getStartTimestamp(),
      });
      setFootfallByCamera((previous) => ({
        ...previous,
        [cameraId]: payload,
      }));
    } catch {
      // Keep latest successful analytics payload in the dashboard.
    }
  }, [getStartTimestamp]);

  useEffect(() => {
    if (!selectedCameraId) return;
    void loadFootfall(selectedCameraId, selectedZoneId);
    const id = window.setInterval(() => {
      void loadFootfall(selectedCameraId, selectedZoneId);
    }, 5000);
    return () => window.clearInterval(id);
  }, [loadFootfall, selectedCameraId, selectedZoneId]);

  const selected = selectedCameraId ? sourceById.get(selectedCameraId) ?? null : null;
  const selectedTimeline = useMemo(() => {
    if (!selected) return [];
    const historyKey = `${selected.camera.id}-${selectedZoneId}`;
    const series = historyByCamera[historyKey] ?? [];
    if (series.length === 0) {
      return [toTimelinePoint(0)];
    }
    return series;
  }, [historyByCamera, selected, selectedZoneId]);
  const selectedFootfall = useMemo(() => {
    if (!selected) return null;
    return footfallByCamera[selected.camera.id] ?? null;
  }, [footfallByCamera, selected]);

  const analyticsQuery = analyticsSearchQuery.trim().toLowerCase();
  const hasAnalyticsQuery = analyticsQuery.length > 0;
  const matchesAnalyticsPanel = useCallback(
    (mode: AnalyticsMode): boolean => {
      if (!hasAnalyticsQuery) return true;
      const terms = ANALYTICS_SEARCH_TERMS[mode];
      return terms.some((term) => term.includes(analyticsQuery) || analyticsQuery.includes(term));
    },
    [analyticsQuery, hasAnalyticsQuery],
  );
  const showPersonCountPanel = matchesAnalyticsPanel("person_count");
  const showEntryExitPanel = matchesAnalyticsPanel("entry_exit_count");
  const showPersonReidPanel = matchesAnalyticsPanel("person_reid");
  const queueMatchedBySearch = matchesAnalyticsPanel("queue");
  const showZoneAnalysisPanel =
    !hasAnalyticsQuery ||
    ZONE_ANALYSIS_SEARCH_TERMS.some((term) => term.includes(analyticsQuery) || analyticsQuery.includes(term));
  const showQueuePanel = queueMatchedBySearch && overlayMode === "queue";
  const showQueueOverlayHint = hasAnalyticsQuery && queueMatchedBySearch && overlayMode !== "queue";
  const hasMatchedAnalyticsPanel =
    showPersonCountPanel || showEntryExitPanel || showPersonReidPanel || showQueuePanel || showZoneAnalysisPanel || showQueueOverlayHint;
  const entryExitZoneSearchQuery = "";



  const filteredSources = useMemo(() => {
    if (!searchQuery.trim()) return sources;
    const lower = searchQuery.toLowerCase();
    return sources.filter((s) => s.camera.name.toLowerCase().includes(lower) || s.endpoint.toLowerCase().includes(lower));
  }, [searchQuery, sources]);

  async function handleDelete(cameraId: number) {
    const confirmed = window.confirm(`Delete camera #${cameraId}?`);
    if (!confirmed) return;
    await deleteSourceByCamera(cameraId);
  }

  return (
    <div className="space-y-3">



      {error ? (
        <div className="rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700">
          {notice}
        </div>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-[290px_1fr]">
        <PanelCard
          title="Camera Sources"
          subtitle="Live preview and controls"
          right={
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => router.push("/configurations?tab=source")}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-3 text-xs font-semibold text-primary transition hover:bg-primary/20 whitespace-nowrap"
              >
                <Plus className="h-3.5 w-3.5" /> Add Source
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!selected) return;
                  void handleDelete(selected.camera.id);
                }}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-destructive/40 bg-destructive/10 px-3 text-xs font-semibold text-destructive transition hover:bg-destructive/20 disabled:cursor-not-allowed disabled:opacity-60 whitespace-nowrap"
                disabled={!selected || busy}
              >
                <Trash2 className="h-3.5 w-3.5" /> Remove
              </button>
            </div>
          }
        >
          <div className="mb-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search cameras..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="h-9 w-full rounded-lg border border-input bg-white pl-9 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          </div>
          <div className="grid max-h-[calc(100vh-320px)] gap-3 overflow-y-auto pr-1">
            {filteredSources.length === 0 ? (
              <p className="text-sm text-muted-foreground">No cameras found.</p>
            ) : (
              filteredSources.map((source) => {
                const active = source.camera.id === selected?.camera.id;
                return (
                  <div
                    key={source.camera.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedCameraId(source.camera.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedCameraId(source.camera.id);
                      }
                    }}
                    className={cn(
                      "rounded-xl border p-3 cursor-pointer transition",
                      active
                        ? "border-primary bg-primary/10"
                        : "border-border/70 bg-white/75 hover:bg-accent/60",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="truncate text-left text-sm font-semibold text-foreground" title={source.camera.name}>
                        {source.camera.name}
                      </p>
                      <StatusPill status={source.status} />
                    </div>
                    <p className="mt-2 truncate text-[11px] text-muted-foreground">
                      Last frame: {formatFrameTimestamp(source.realtime?.frame_timestamp)}
                    </p>
                    <div className="mt-2.5 flex items-center justify-between gap-2">
                      <span className="truncate text-[11px] tabular-nums text-muted-foreground" title={`Uptime: ${source.uptime}`}>
                        Uptime: {source.uptime}
                      </span>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-primary/40 bg-primary/10 text-primary transition hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-60"
                          title={source.status === "live" ? "Pause stream" : "Start stream"}
                          onClick={(e) => {
                            e.stopPropagation();
                            void toggleStreamForCamera(source.camera.id);
                          }}
                          disabled={busy}
                        >
                          {source.status === "live" ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                        </button>
                        <button
                          type="button"
                          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-primary/40 bg-primary/10 text-primary transition hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-60"
                          title="Edit source"
                          onClick={(e) => {
                            e.stopPropagation();
                            router.push(`/configurations?tab=source&edit=${source.camera.id}`);
                          }}
                          disabled={busy}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-destructive/40 bg-destructive/10 text-destructive transition hover:bg-destructive/20 disabled:cursor-not-allowed disabled:opacity-60"
                          title="Delete source"
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleDelete(source.camera.id);
                          }}
                          disabled={busy}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </PanelCard>

        <div className="space-y-3">
          <PanelCard
            title="Primary Feed"
            subtitle="Live feed and detection overlay while analytics is running"
            right={
              <div className="flex items-center gap-2">
                {selected ? (
                  <button
                    type="button"
                    onClick={() => setShowZoneEditor(true)}
                    className="flex items-center rounded-lg border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary transition hover:bg-primary/20 whitespace-nowrap"
                  >
                    <Pencil className="mr-1.5 h-3.5 w-3.5" />
                    Quick-Edit Zones
                  </button>
                ) : null}
                <select
                  value={overlayMode}
                  onChange={(e) => setOverlayMode(e.target.value as AnalyticsMode)}
                  className="h-9 rounded-lg border border-input bg-white px-3 text-sm text-foreground shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {ANALYTICS_MODES.map((mode) => (
                    <option key={mode.id} value={mode.id}>
                      Overlay: {mode.label}
                    </option>
                  ))}
                </select>
                <select
                  value={selectedZoneId}
                  onChange={(e) => setSelectedZoneId(e.target.value)}
                  className="h-9 rounded-lg border border-input bg-white px-3 text-sm text-foreground shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="all">Compare All Zones</option>
                  {selected && zonesByCamera[selected.camera.id]?.map((z) => (
                    <option key={z.id} value={z.id.toString()}>
                      {z.name}
                    </option>
                  ))}
                </select>
              </div>
            }
          >
            {selected ? (
              <>
                <CameraFeed
                  key={`primary-${selected.camera.id}-${analyticsRunning ? "live" : "static"}`}
                  cameraId={selected.camera.id}
                  title={selected.camera.name}
                  status={selected.status}
                  resolution={selected.resolution}
                  fps={selected.fps}
                  zones={zonesByCamera[selected.camera.id] ?? []}
                  detectionBoxes={selected.realtime?.detection_boxes ?? []}
                  hasLiveFrame={selected.hasLiveFrame}
                  staticFirstFrame={!analyticsRunning}
                  analyticsMode={overlayMode}
                  zoneId={selectedZoneId !== "all" ? selectedZoneId : undefined}
                />

                <div className="mt-3 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                  {(zonesByCamera[selected.camera.id] ?? [])
                    .filter((zone) => selectedZoneId === "all" || zone.id.toString() === selectedZoneId)
                    .map((zone) => {
                    const activeRealtime = selected.realtime?.zones?.find(z => z.zone_id === zone.id);
                    const personCount = activeRealtime?.person_count ?? 0;
                    
                    const zoneStats = selectedFootfall?.zone_totals?.find(z => z.zone_id === zone.id);
                    const entries = zoneStats?.total_entries ?? 0;
                    const exits = zoneStats?.total_exits ?? 0;

                    return (
                      <div key={zone.id} className="relative overflow-hidden flex flex-col rounded-xl border border-border/70 bg-white shadow-sm transition hover:shadow-md">
                        <div className="absolute left-2 top-2 z-10 rounded bg-slate-900/80 px-2 py-1 text-xs font-semibold text-white backdrop-blur">
                          {zone.name}
                        </div>
                        <div className="aspect-video bg-slate-100 shrink-0">
                          <CameraFeed
                            cameraId={selected.camera.id}
                            title={zone.name}
                            status={selected.status}
                            resolution={selected.resolution}
                            fps={selected.fps}
                            detectionBoxes={selected.realtime?.detection_boxes ?? []}
                            hasLiveFrame={selected.hasLiveFrame}
                            compact
                            staticFirstFrame={!analyticsRunning}
                            analyticsMode={overlayMode}
                            zoneId={zone.id.toString()}
                          />
                        </div>
                        <div className="bg-muted/30 p-2 border-t border-border/50 text-[11px] grid grid-cols-4 gap-2 text-center select-none">
                          <div className="flex flex-col"><span className="text-muted-foreground uppercase tracking-widest text-[9px] font-bold">Live</span><span className="font-semibold text-sky-700 text-sm">{personCount}</span></div>
                          <div className="flex flex-col"><span className="text-muted-foreground uppercase tracking-widest text-[9px] font-bold">In</span><span className="font-semibold text-emerald-700 text-sm">{entries}</span></div>
                          <div className="flex flex-col"><span className="text-muted-foreground uppercase tracking-widest text-[9px] font-bold">Out</span><span className="font-semibold text-rose-700 text-sm">{exits}</span></div>
                          <div className="flex flex-col"><span className="text-muted-foreground uppercase tracking-widest text-[9px] font-bold">Status</span><span className="font-semibold text-muted-foreground">{personCount > 0 ? "Active" : "Clear"}</span></div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No source selected.</p>
            )}
          </PanelCard>
        </div>
      </div>

      {selected ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between rounded-xl border border-border/70 bg-white p-3">
            <div className="flex items-center gap-2">
              <Filter className="h-5 w-5 text-primary" />
              <h3 className="font-semibold text-foreground">Analytics Data</h3>
            </div>
            <div className="flex items-center gap-3">
              <select
                value={timeRange}
                onChange={(e) => setTimeRange(e.target.value as "12h" | "today" | "24h")}
                className="h-9 rounded-lg border border-input bg-white px-3 text-xs text-foreground shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="12h">Last 12 Hours</option>
                <option value="24h">Last 24 Hours</option>
                <option value="today">Today</option>
              </select>
              <div className="relative w-48 sm:w-64">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Search analytics: person, queue, reid, entry/exit, zone..."
                  value={analyticsSearchQuery}
                  onChange={(e) => setAnalyticsSearchQuery(e.target.value)}
                  className="h-9 w-full rounded-lg border border-input bg-white pl-9 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>
          </div>

          <div className="grid gap-3">
            {hasAnalyticsQuery && !hasMatchedAnalyticsPanel ? (
              <div className="rounded-xl border border-border/70 bg-white px-4 py-3 text-sm text-muted-foreground">
                No analytics section matches {analyticsSearchQuery.trim()}. Try: person count, queue management, person reid, entry exit, zone analysis.
              </div>
            ) : null}

            {showPersonCountPanel ? (
              <PanelCard title="Zone Analytics" subtitle="Person Count">
                <ModeAnalyticsPanel
                  timeline={selectedTimeline}
                  zones={zonesByCamera[selected.camera.id] ?? []}
                  liveZones={selected?.realtime?.zones ?? []}
                  footfall={selectedFootfall}
                  isPersonCountMode={overlayMode === "person_count"}
                  sourceType={selected.type}
                />
              </PanelCard>
            ) : null}

            {showZoneAnalysisPanel ? (
              <PanelCard
                title="Zone Analysis"
                subtitle="Monitor congestion, people/staff paths, heatmaps, and service presence"
              >
                <ZoneAnalysisPanel
                  cameraId={selected.camera.id}
                  selectedZoneId={selectedZoneId}
                  start={getStartTimestamp()}
                />
              </PanelCard>
            ) : null}

            {showEntryExitPanel ? (
              <PanelCard
                title="Entry / Exit Analytics"
                subtitle="YOLO + ByteTrack zone transitions"
              >
                <EntryExitAnalyticsPanel
                  footfall={selectedFootfall}
                  liveZones={selected?.realtime?.zones ?? []}
                  searchQuery={entryExitZoneSearchQuery}
                  selectedZoneId={selectedZoneId}
                />
              </PanelCard>
            ) : null}

            {showPersonReidPanel ? (
              <PanelCard title="Person ReID Analytics" subtitle="Track occurrences and dwell times across views">
                <PersonReidAnalyticsPanel cameraId={selected.camera.id} />
              </PanelCard>
            ) : null}

            {showQueuePanel ? (
              <PanelCard title="Queue Management" subtitle="Waiting times & line length">
                <QueueAnalyticsPanel
                  cameraId={selected.camera.id}
                  zones={zonesByCamera[selected.camera.id] ?? []}
                  selectedZoneId={selectedZoneId}
                />
              </PanelCard>
            ) : null}
            {showQueueOverlayHint ? (
              <div className="rounded-xl border border-border/70 bg-white px-4 py-3 text-xs text-muted-foreground">
                Queue Management analytics appears when overlay mode is set to Queue Management.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {showZoneEditor && selected ? (
        <ZoneQuickEditor
          cameraId={selected.camera.id}
          cameraName={selected.camera.name}
          frameUrl={`/api/backend/api/monitoring/cameras/${selected.camera.id}/${selected.type === "Video File" ? "first-frame" : "source-frame"}`}
          onClose={() => setShowZoneEditor(false)}
          onZonesUpdated={() => void loadZones(selected.camera.id)}
        />
      ) : null}
    </div>
  );
}

function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

function formatFrameTimestamp(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString();
}
