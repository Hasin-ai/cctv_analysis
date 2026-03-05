"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  type FacialExpressionRealtimeResponse,
  getFacialExpressionRealtime,
} from "@/lib/api";
import { StatTile } from "@/components/v2/ui";

const ANALYSIS_POLL_INTERVAL_MS = 1000;

function formatPercent(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "0%";
  return `${value.toFixed(1)}%`;
}

export function FacialExpressionPanel({
  cameraId,
  selectedZoneId = "all",
  start,
}: {
  cameraId: number;
  selectedZoneId?: string;
  start?: string;
}) {
  const [data, setData] = useState<FacialExpressionRealtimeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  void start;

  const analysisRequestRef = useRef(0);
  const inFlightRef = useRef(false);

  const zoneId = useMemo(() => {
    if (selectedZoneId === "all") return null;
    const parsed = Number(selectedZoneId);
    if (!Number.isFinite(parsed) || parsed <= 0) return null;
    return parsed;
  }, [selectedZoneId]);

  const runAnalysis = useCallback(async (requestId: number) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;

    setLoading(true);
    setError(null);

    try {
      const payload = await getFacialExpressionRealtime({
        cameraId,
        zoneId,
      });
      if (analysisRequestRef.current !== requestId) return;
      setData(payload);
    } catch (err) {
      if (analysisRequestRef.current !== requestId) return;
      setData(null);
      setError(err instanceof Error ? err.message : "Facial expression realtime fetch failed");
    } finally {
      inFlightRef.current = false;
      if (analysisRequestRef.current !== requestId) return;
      setLoading(false);
    }
  }, [cameraId, zoneId]);

  useEffect(() => {
    analysisRequestRef.current += 1;
    const requestId = analysisRequestRef.current;
    let timeoutId: number | null = null;
    let active = true;

    const loop = async () => {
      if (!active) return;
      await runAnalysis(requestId);
      if (!active) return;
      timeoutId = window.setTimeout(() => {
        void loop();
      }, ANALYSIS_POLL_INTERVAL_MS);
    };

    void loop();
    return () => {
      active = false;
      analysisRequestRef.current += 1;
      inFlightRef.current = false;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [runAnalysis]);

  const emotionRows = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.emotion_counts)
      .map(([emotion, count]) => ({
        emotion,
        count,
        pct: data.emotion_percentages[emotion] ?? 0,
      }))
      .sort((a, b) => b.count - a.count || a.emotion.localeCompare(b.emotion));
  }, [data]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-emerald-700">Realtime update every 1s</p>
        <p className="text-xs text-muted-foreground">
          {data?.frame_timestamp ? `Frame ${new Date(data.frame_timestamp).toLocaleTimeString()}` : "Waiting for frame"}
        </p>
      </div>

      {loading && !data ? (
        <p className="text-sm text-muted-foreground">Loading realtime facial analytics...</p>
      ) : null}

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {!data && !loading && !error ? (
        <p className="text-sm text-muted-foreground">No facial expression data available yet.</p>
      ) : null}

      {data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Faces Analyzed" value={data.analyzed_faces} hint="Faces inside selected zone" />
            <StatTile label="Dominant Emotion" value={data.dominant_emotion ?? "N/A"} hint={data.zone_name ?? "Selected zone"} />
            <StatTile label="Avg. Age" value={data.avg_age ?? "N/A"} hint="Overall average age" />
            <StatTile
              label="Zone Filter"
              value={data.zone_filter_available ? "Applied" : "Missing"}
              hint={data.zone_name ?? "No zone selected"}
            />
          </div>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="overflow-x-auto items-start rounded-xl border border-border/70 bg-white/80">
              <table className="min-w-full text-left text-xs">
                <thead className="bg-muted/40 text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Emotion</th>
                    <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Count</th>
                    <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {emotionRows.length === 0 ? (
                    <tr>
                      <td className="px-3 py-3 text-muted-foreground" colSpan={3}>
                        No faces detected in the selected zone.
                      </td>
                    </tr>
                  ) : (
                    emotionRows.map((row) => (
                      <tr key={row.emotion} className="border-t border-border/50">
                        <td className="px-3 py-2 text-foreground capitalize">{row.emotion}</td>
                        <td className="px-3 py-2 tabular-nums text-slate-700">{row.count}</td>
                        <td className="px-3 py-2 tabular-nums text-slate-700">{formatPercent(row.pct)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="space-y-3">
              <div className="overflow-x-auto rounded-xl border border-border/70 bg-white/80">
                <table className="min-w-full text-left text-xs">
                  <thead className="bg-muted/40 text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]" colSpan={2}>Gender Breakdown</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(!data.gender_counts || Object.keys(data.gender_counts).length === 0) ? (
                      <tr>
                        <td className="px-3 py-3 text-muted-foreground" colSpan={2}>
                          No gender data available.
                        </td>
                      </tr>
                    ) : (
                       Object.entries(data.gender_counts)
                        .sort((a, b) => b[1] - a[1])
                        .map(([gender, count]) => (
                          <tr key={gender} className="border-t border-border/50">
                            <td className="px-3 py-2 text-foreground capitalize">{gender}</td>
                            <td className="px-3 py-2 tabular-nums text-slate-700">{count}</td>
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
                      <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]" colSpan={2}>Age Distribution</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(!data.age_distribution || Object.keys(data.age_distribution).length === 0) ? (
                      <tr>
                        <td className="px-3 py-3 text-muted-foreground" colSpan={2}>
                          No age data available.
                        </td>
                      </tr>
                    ) : (
                       Object.entries(data.age_distribution)
                         /* simple lexical sort works for "0-12", "13-17", etc., but let's just render the dict as provided assuming backend pre-ordered it */
                         .map(([bracket, count]) => (
                           <tr key={bracket} className="border-t border-border/50">
                             <td className="px-3 py-2 text-foreground">{bracket}</td>
                             <td className="px-3 py-2 tabular-nums text-slate-700">{count}</td>
                           </tr>
                         ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>


          <div className="overflow-x-auto rounded-xl border border-border/70 bg-white/80 mt-1">
            <table className="min-w-full text-left text-xs">
              <thead className="bg-muted/40 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Latest Frame</th>
                  <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Faces</th>
                  <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Detector</th>
                  <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Zone Filter</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-border/50">
                  <td className="px-3 py-2 text-slate-700">
                    {data.frame_timestamp ? new Date(data.frame_timestamp).toLocaleTimeString() : "-"}
                  </td>
                  <td className="px-3 py-2 tabular-nums text-slate-700">{data.analyzed_faces}</td>
                  <td className="px-3 py-2 text-slate-700">{data.detector_available ? "Ready" : "Unavailable"}</td>
                  <td className="px-3 py-2 text-slate-700">{data.zone_filter_available ? "Applied" : "Missing"}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
