"use client";

import { useEffect, useState, useMemo } from "react";
import { 
  type QueueResult,
  type Zone,
  listQueueJobs,
  getQueueResult
} from "@/lib/api";
import { MiniLineChart, StatTile } from "@/components/v2/ui";

export function QueueAnalyticsPanel({ cameraId, zones = [] }: { cameraId: number; zones?: Zone[] }) {
  const [queueData, setQueueData] = useState<QueueResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    async function fetchData() {
      try {
        // Fetch the most recent job for the specific camera to visualize
        const jobs = await listQueueJobs(cameraId);
        if (jobs.length > 0) {
          const latestJob = jobs[0];
          const result = await getQueueResult(latestJob.id);
          if (active) {
            setQueueData(result);
          }
        } else if (active) {
          setQueueData(null);
        }
      } catch (err) {
        console.error("Failed to load queue analytics", err);
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void fetchData();
    const id = setInterval(fetchData, 10000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [cameraId]);

  const zone = useMemo(() => {
    if (!queueData) return null;
    return zones.find((z) => z.id === queueData.zone_id) || null;
  }, [queueData, zones]);

  const series = useMemo(() => {
    if (!queueData) return [];
    return queueData.frame_results.map(f => f.queue_count);
  }, [queueData]);

  if (loading && !queueData) {
    return <p className="text-sm text-muted-foreground animate-pulse">Loading queue data...</p>;
  }

  if (!queueData) {
    return <p className="text-sm text-muted-foreground">Queue analytics not available yet for this camera.</p>;
  }

  const formatWaitTime = (sec: number | null) => {
    if (sec == null) return "Estimating...";
    if (sec < 60) return `${Math.round(sec)}s`;
    return `${(sec / 60).toFixed(1)}m`;
  };

  const waitTimeStr = formatWaitTime(queueData.avg_wait_time_sec);
  const expectedWaitTimeStr = zone?.expected_wait_time_sec != null ? formatWaitTime(zone.expected_wait_time_sec) : null;

  const waitTimeLabel = expectedWaitTimeStr
    ? `${waitTimeStr} / ${expectedWaitTimeStr}`
    : waitTimeStr;

  const isOverWaitTime = queueData.avg_wait_time_sec != null && zone?.expected_wait_time_sec != null
     ? queueData.avg_wait_time_sec > zone.expected_wait_time_sec
     : false;

  const throughputStr = queueData.avg_throughput_exits_per_sec !== null 
    ? `${queueData.avg_throughput_exits_per_sec.toFixed(2)}/s` 
    : "Estimating...";

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className={isOverWaitTime ? "text-rose-600 font-bold" : ""}>
          <StatTile 
            label="Avg Wait Time" 
            value={waitTimeLabel} 
            hint={expectedWaitTimeStr ? "Curr / Target" : "Estimated delay"} 
          />
        </div>
        <StatTile 
          label="Throughput" 
          value={throughputStr} 
          hint="Exits per sec" 
        />
        <StatTile 
          label="Max Queue" 
          value={queueData.max_queue_count} 
          hint="Peak waiting" 
        />
        <StatTile 
          label="Avg Queue" 
          value={Math.round(queueData.avg_queue_count * 10) / 10} 
          hint="In rolling window" 
        />
      </div>

      <div className="mt-3 rounded-xl border border-border/70 bg-white/80 p-3">
        <p className="mb-2 text-xs font-semibold text-muted-foreground">Queue Count History</p>
        <MiniLineChart values={series} />
      </div>
    </div>
  );
}
