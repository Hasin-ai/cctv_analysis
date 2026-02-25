"use client";

import { useEffect, useState } from "react";
import { type AnalyzerJob, type AnalyzerStats, type AnalyzerTrack, getAnalyzerStats, getAnalyzerTracks, listAnalyzerJobs } from "@/lib/api";
import { Loader2, RefreshCcw, User } from "lucide-react";

export function PersonReidAnalyticsPanel({ cameraId }: { cameraId: number }) {
  const [jobs, setJobs] = useState<AnalyzerJob[]>([]);
  const [selectedJob, setSelectedJob] = useState<AnalyzerJob | null>(null);
  const [stats, setStats] = useState<AnalyzerStats | null>(null);
  const [tracks, setTracks] = useState<AnalyzerTrack[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function fetchJobs() {
      try {
        setLoading(true);
        const allJobs = await listAnalyzerJobs(cameraId);
        if (!active) return;
        
        // Filter jobs strictly matching person_reid logic (usually denoted by unique_persons > 0 or status checking)
        // Currently the backend stores them all as AnalysisJobs. We'll show the most recent completed ones.
        const completed = allJobs.filter(j => j.status === "completed" || j.status === "running").sort((a,b) => b.id - a.id);
        setJobs(completed);
        
        if (completed.length > 0 && !selectedJob) {
          setSelectedJob(completed[0]);
        }
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Failed to load ReID jobs");
      } finally {
        if (active) setLoading(false);
      }
    }
    void fetchJobs();
    return () => { active = false; };
  }, [cameraId, selectedJob]);

  useEffect(() => {
    if (!selectedJob) return;
    let active = true;

    async function fetchDetails() {
      try {
        setLoading(true);
        const [jobStats, jobTracks] = await Promise.all([
          getAnalyzerStats(selectedJob!.id),
          getAnalyzerTracks(selectedJob!.id)
        ]);
        if (!active) return;
        setStats(jobStats);
        setTracks(jobTracks);
        setError(null);
      } catch (err) {
        if (active) setError(err instanceof Error ? err.message : "Failed to load ReID details");
      } finally {
        if (active) setLoading(false);
      }
    }

    void fetchDetails();
    return () => { active = false; };
  }, [selectedJob]);

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center p-8 text-muted-foreground">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  if (error) {
    return <div className="p-4 text-sm text-destructive">{error}</div>;
  }

  if (jobs.length === 0) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-muted-foreground">No Person ReID analytics jobs found for this camera.</p>
        <p className="mt-1 text-xs text-muted-foreground opacity-70">
          Run a new analysis from the Zone Configurations queue to see tracking statistics.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <select
          title="Select Job"
          value={selectedJob?.id ?? ""}
          onChange={(e) => {
             const job = jobs.find(j => j.id === Number(e.target.value));
             if (job) setSelectedJob(job);
          }}
          className="h-9 rounded-lg border border-input bg-white px-3 text-xs font-semibold text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        >
          {jobs.map(j => (
            <option key={j.id} value={j.id}>
              Job #{j.id} ({new Date(j.start_time).toLocaleTimeString()} - {new Date(j.end_time).toLocaleTimeString()})
            </option>
          ))}
        </select>
        <button
           type="button"
           onClick={() => setSelectedJob(selectedJob ? { ...selectedJob } : null)}
           className="p-2 border rounded-md hover:bg-accent text-muted-foreground transition"
           title="Refresh current job stats"
        >
          <RefreshCcw className="w-4 h-4" />
        </button>
      </div>
      
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="rounded-xl border border-primary/20 bg-primary/5 p-3">
             <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Unique Persons</p>
             <p className="text-xl font-bold text-primary mt-1">{stats.unique_persons}</p>
          </div>
          <div className="rounded-xl border border-border/60 bg-white p-3">
             <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Status</p>
             <p className="text-sm font-semibold mt-1 uppercase text-slate-700">{stats.status}</p>
          </div>
        </div>
      )}

      {tracks.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-border/70 bg-white/80">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Track ID</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Appearances</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Dwell (Sec)</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">Confidence</th>
                <th className="px-3 py-2 font-semibold uppercase tracking-[0.1em]">First Seen</th>
              </tr>
            </thead>
            <tbody>
              {tracks.map((track) => (
                <tr key={track.id} className="border-t border-border/50">
                  <td className="px-3 py-2 text-foreground font-semibold flex items-center gap-1.5">
                    <User className="w-3.5 h-3.5 text-indigo-500" /> #{track.track_id}
                  </td>
                  <td className="px-3 py-2 text-slate-700">{track.appearances}</td>
                  <td className="px-3 py-2 text-sky-700">{track.dwell_seconds.toFixed(1)}s</td>
                  <td className="px-3 py-2 text-emerald-700">{Math.round(track.avg_confidence * 100)}%</td>
                  <td className="px-3 py-2 text-muted-foreground">{new Date(track.first_seen).toLocaleTimeString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="p-4 border rounded-xl text-sm text-muted-foreground text-center">No track records isolated for this analysis job yet.</div>
      )}
    </div>
  );
}
