"use client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { powerRankingsApi, type PowerRankingEntry } from "@/lib/api";
import { Flame, RefreshCw, Sparkles } from "lucide-react";

const SEASON = 2026;

function RankBadge({ rank }: { rank: number }) {
  const styles =
    rank === 1
      ? "bg-yellow-500 text-yellow-950"
      : rank === 2
      ? "bg-gray-300 text-gray-900"
      : rank === 3
      ? "bg-amber-700 text-amber-100"
      : rank <= 10
      ? "bg-blue-600/30 text-blue-300"
      : rank <= 20
      ? "bg-gray-700 text-gray-300"
      : "bg-red-900/40 text-red-300";

  return (
    <span
      className={`flex items-center justify-center w-9 h-9 rounded-full text-sm font-bold flex-shrink-0 ${styles}`}
    >
      {rank}
    </span>
  );
}

function RankRow({ entry }: { entry: PowerRankingEntry }) {
  const isTop = entry.rank <= 3;
  return (
    <div
      className={`flex items-start gap-4 px-4 py-3.5 rounded-xl border transition-colors ${
        isTop
          ? "bg-yellow-950/10 border-yellow-800/30"
          : "bg-gray-900 border-gray-800 hover:border-gray-700"
      }`}
    >
      <RankBadge rank={entry.rank} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-bold text-gray-100 text-sm">{entry.team_name}</span>
          {entry.division && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500 font-medium">
              {entry.division}
            </span>
          )}
          {entry.record && (
            <span className="text-xs text-gray-400 font-medium">{entry.record}</span>
          )}
        </div>
        <p className="text-xs text-gray-400 mt-1 leading-relaxed">{entry.blurb}</p>
      </div>
    </div>
  );
}

export default function PowerRankingsPage() {
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["power-rankings", SEASON],
    queryFn: () => powerRankingsApi.get(SEASON).then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  const generate = useMutation({
    mutationFn: () => powerRankingsApi.generate(SEASON).then((r) => r.data),
    onSuccess: (result) => {
      queryClient.setQueryData(["power-rankings", SEASON], result);
    },
  });

  const rankings = data?.rankings ?? [];
  const hasRankings = rankings.length > 0;

  return (
    <div className="p-6 max-w-screen-lg mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-orange-600/20 rounded-lg">
            <Flame className="h-5 w-5 text-orange-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-100">Power Rankings</h1>
            <p className="text-xs text-gray-500">
              All 30 teams, ranked by AI &middot; {SEASON} season
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {data?.generated_at && (
            <p className="text-xs text-gray-600 hidden sm:block">
              Generated {new Date(data.generated_at).toLocaleString()}
            </p>
          )}
          <button
            onClick={() => generate.mutate()}
            disabled={generate.isPending}
            className="flex items-center gap-2 px-4 py-1.5 rounded-lg bg-orange-600/20 text-orange-300 text-sm font-medium hover:bg-orange-600/30 transition-colors disabled:opacity-40"
          >
            {generate.isPending ? (
              <RefreshCw className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {hasRankings ? "Refresh Rankings" : "Generate Rankings"}
          </button>
        </div>
      </div>

      {generate.isError && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/40 p-4 text-center mb-6">
          <p className="text-red-400 text-sm font-medium">
            Failed to generate power rankings. Try again.
          </p>
        </div>
      )}

      {isLoading && (
        <div className="flex flex-col items-center justify-center py-32 gap-3">
          <RefreshCw className="h-6 w-6 text-gray-600 animate-spin" />
          <p className="text-sm text-gray-500">Loading power rankings…</p>
        </div>
      )}

      {isError && !isLoading && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/40 p-8 text-center">
          <p className="text-red-400 text-sm font-medium">Failed to load power rankings</p>
        </div>
      )}

      {!isLoading && !isError && !hasRankings && !generate.isPending && (
        <div className="rounded-xl bg-gray-900 border border-gray-800 p-12 text-center">
          <Flame className="h-8 w-8 text-gray-700 mx-auto mb-3" />
          <p className="text-sm text-gray-400 font-medium mb-1">No power rankings yet</p>
          <p className="text-xs text-gray-600">
            Generate this week&apos;s rankings — grounded in real standings, recent form, and streaks.
          </p>
        </div>
      )}

      {generate.isPending && !hasRankings && (
        <div className="flex flex-col items-center justify-center py-32 gap-3">
          <RefreshCw className="h-6 w-6 text-orange-500 animate-spin" />
          <p className="text-sm text-gray-500">Ranking all 30 teams…</p>
        </div>
      )}

      {hasRankings && (
        <div className="space-y-2">
          {rankings.map((entry) => (
            <RankRow key={entry.rank} entry={entry} />
          ))}
        </div>
      )}
    </div>
  );
}
