"use client";

/**
 * SyncBar — shows when rosters/stats were last refreshed and lets the user
 * trigger a live sync from the MLB Stats API.
 *
 * Usage:
 *   <SyncBar onSyncComplete={() => refetch()} />
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { syncApi } from "@/lib/api";
import { RefreshCw, CheckCircle2, AlertCircle, Clock } from "lucide-react";

interface Props {
  /** Called after a sync finishes so the parent can re-fetch its own data. */
  onSyncComplete?: () => void;
  className?: string;
}

export function SyncBar({ onSyncComplete, className = "" }: Props) {
  const qc = useQueryClient();

  const { data, refetch: refetchStatus } = useQuery({
    queryKey: ["sync-status"],
    queryFn: () => syncApi.status().then(r => r.data),
    refetchInterval: (q) => {
      // Poll every 3 s while a sync is running, every 60 s otherwise
      return q.state.data?.status === "running" ? 3_000 : 60_000;
    },
    staleTime: 0,
  });

  const mutation = useMutation({
    mutationFn: () => syncApi.run(),
    onSuccess: () => {
      // Start polling for completion
      const interval = setInterval(async () => {
        const res = await syncApi.status();
        if (res.data.status !== "running") {
          clearInterval(interval);
          // Invalidate all queries so tabs re-fetch fresh data
          qc.invalidateQueries();
          onSyncComplete?.();
          refetchStatus();
        }
      }, 3_000);
    },
  });

  const status = data?.status ?? "idle";
  const isRunning = status === "running" || mutation.isPending;
  const isError = status === "error";
  const isStale = data?.is_stale ?? false;

  return (
    <div className={`flex items-center gap-3 px-4 py-2 rounded-xl text-xs border ${
      isError
        ? "bg-red-950/30 border-red-800/40 text-red-400"
        : isStale
          ? "bg-amber-950/20 border-amber-800/30 text-amber-500"
          : "bg-gray-900 border-gray-800 text-gray-500"
    } ${className}`}>

      {/* Status icon */}
      {isRunning ? (
        <RefreshCw className="h-3.5 w-3.5 animate-spin text-blue-400 flex-shrink-0" />
      ) : isError ? (
        <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
      ) : (
        <Clock className="h-3.5 w-3.5 flex-shrink-0" />
      )}

      {/* Age / status text */}
      <span className="flex-1">
        {isRunning
          ? "Syncing rosters & stats…"
          : isError
            ? `Sync error: ${data?.last_error ?? "unknown"}`
            : data?.last_run_iso
              ? <>Live data — last synced <span className="font-medium">{data.age_display}</span>
                  {data.teams_synced > 0 && (
                    <span className="ml-1 text-gray-600">
                      ({data.teams_synced} teams · {data.roster_updates + data.stat_updates} updates)
                    </span>
                  )}
                </>
              : "Rosters not yet synced"
        }
      </span>

      {/* Stale warning chip */}
      {isStale && !isRunning && (
        <span className="px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 font-medium">
          stale
        </span>
      )}

      {/* Sync now button */}
      <button
        onClick={() => mutation.mutate()}
        disabled={isRunning}
        title="Pull fresh rosters & stats from MLB"
        className={`flex items-center gap-1 px-2 py-1 rounded-lg border transition-colors disabled:opacity-40 flex-shrink-0 ${
          isStale
            ? "border-amber-500/50 text-amber-400 hover:bg-amber-500/10"
            : "border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-500"
        }`}
      >
        <RefreshCw className={`h-3 w-3 ${isRunning ? "animate-spin" : ""}`} />
        {isRunning ? "Syncing…" : "Sync now"}
      </button>
    </div>
  );
}
