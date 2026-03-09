"use client";

import { useEffect, useState } from "react";

import {
  type ZoneAnalysisResponse,
  getZoneAnalysis,
} from "@/lib/api";
import { usePageVisibility } from "@/hooks/use-page-visibility";
import { parseSelectedZoneId } from "@/lib/zone-selection";
import { StatTile } from "@/components/v2/ui";

function toPercentText(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${Math.round(value)}%`;
}

function levelTone(level: string): string {
  const lowered = level.toLowerCase();
  if (lowered === "critical") return "text-rose-700";
  if (lowered === "high") return "text-orange-700";
  if (lowered === "medium") return "text-amber-700";
  return "text-emerald-700";
}

function staffRatioPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function ZoneAnalysisPanel({
  cameraId,
  selectedZoneId = "",
  start,
}: {
  cameraId: number;
  selectedZoneId?: string;
  start?: string;
}) {
  const [data, setData] = useState<ZoneAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const isPageVisible = usePageVisibility();

  useEffect(() => {
    if (!isPageVisible) return undefined;
    let active = true;

    async function load() {
      try {
        const zoneId = parseSelectedZoneId(selectedZoneId) ?? undefined;
        const payload = await getZoneAnalysis({
          cameraId,
          zoneId,
          start,
        });
        if (!active) return;
        setData(payload);
      } catch {
        if (!active) return;
        setData(null);
      } finally {
        if (!active) return;
        setLoading(false);
      }
    }

    setLoading(true);
    void load();
    const id = window.setInterval(() => {
      void load();
    }, 8000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, [cameraId, isPageVisible, selectedZoneId, start]);

  if (loading && !data) {
    return <p className="text-sm text-muted-foreground">Loading zone analysis...</p>;
  }

  if (!data) {
    return <p className="text-sm text-muted-foreground">Zone analysis is not available yet for this camera.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Zones Monitored" value={data.summary.total_zones ?? 0} hint="Configured zones" />
        <StatTile label="Tracked Paths" value={data.summary.tracked_paths ?? 0} hint="People + staff trajectories" />
        <StatTile label="Staff Tracks" value={data.summary.estimated_staff_tracks ?? 0} hint="Estimated from service-zone behavior" />
        <StatTile
          label="Peak Congestion Zone"
          value={data.summary.peak_congestion_zone?.zone_name ?? "N/A"}
          hint={data.summary.peak_congestion_zone?.congestion_level ?? "No congestion data"}
        />
      </div>

      <div className="overflow-x-auto rounded-xl border border-border/70 bg-white/80">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-muted/40 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Zone</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Current</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Peak</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Avg</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Capacity</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Utilization</th>
              <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Level</th>
            </tr>
          </thead>
          <tbody>
            {data.congestion_by_zone.length === 0 ? (
              <tr>
                <td className="px-3 py-3 text-muted-foreground" colSpan={7}>
                  No congestion metrics yet.
                </td>
              </tr>
            ) : (
              data.congestion_by_zone.map((zone) => (
                <tr key={zone.zone_id} className="border-t border-border/50">
                  <td className="px-3 py-2 text-foreground">
                    {zone.zone_name}
                    {zone.is_service_zone ? <span className="ml-1 text-[10px] text-indigo-600">(service)</span> : null}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-sky-700">{zone.current_count}</td>
                  <td className="px-3 py-2 tabular-nums text-slate-700">{zone.peak_count}</td>
                  <td className="px-3 py-2 tabular-nums text-slate-700">{zone.avg_count.toFixed(1)}</td>
                  <td className="px-3 py-2 tabular-nums text-slate-700">{zone.capacity ?? "-"}</td>
                  <td className="px-3 py-2 tabular-nums text-slate-700">{toPercentText(zone.current_utilization_pct)}</td>
                  <td className={`px-3 py-2 font-semibold capitalize ${levelTone(zone.congestion_level)}`}>{zone.congestion_level}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="overflow-x-auto rounded-xl border border-border/70 bg-white/80">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Track</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Type</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Dwell</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Path</th>
              </tr>
            </thead>
            <tbody>
              {data.tracked_paths.length === 0 ? (
                <tr>
                  <td className="px-3 py-3 text-muted-foreground" colSpan={4}>
                    No tracked paths available yet.
                  </td>
                </tr>
              ) : (
                data.tracked_paths.slice(0, 12).map((track) => (
                  <tr key={track.track_key} className="border-t border-border/50">
                    <td className="px-3 py-2 text-foreground">#{track.track_id}</td>
                    <td className="px-3 py-2 capitalize text-slate-700">{track.track_type}</td>
                    <td className="px-3 py-2 tabular-nums text-slate-700">{track.estimated_dwell_seconds.toFixed(1)}s</td>
                    <td className="px-3 py-2 text-slate-700">{track.zone_sequence_names.join(" -> ") || "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="overflow-x-auto rounded-xl border border-border/70 bg-white/80">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Zone</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Staff</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">People</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Staff Ratio</th>
              </tr>
            </thead>
            <tbody>
              {data.service_staff_presence.length === 0 ? (
                <tr>
                  <td className="px-3 py-3 text-muted-foreground" colSpan={4}>
                    No staff/service presence metrics yet.
                  </td>
                </tr>
              ) : (
                data.service_staff_presence.map((zone) => (
                  <tr key={zone.zone_id} className="border-t border-border/50">
                    <td className="px-3 py-2 text-foreground">
                      {zone.zone_name}
                      {zone.is_service_zone ? <span className="ml-1 text-[10px] text-indigo-600">(service)</span> : null}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-indigo-700">{zone.staff_tracks}</td>
                    <td className="px-3 py-2 tabular-nums text-slate-700">{zone.person_tracks}</td>
                    <td className="px-3 py-2 tabular-nums text-slate-700">{staffRatioPercent(zone.staff_presence_ratio)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
