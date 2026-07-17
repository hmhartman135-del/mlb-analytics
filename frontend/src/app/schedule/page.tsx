"use client";
import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  scheduleApi,
  type ScheduleGame,
  type BoxScoreTeam,
  type GamePrediction,
} from "@/lib/api";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Loader2,
  ChevronDown,
} from "lucide-react";

// ── Date helpers ───────────────────────────────────────────────────────────────

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function shiftDate(dateStr: string, days: number): string {
  const d = new Date(`${dateStr}T12:00:00`);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatDateHeading(dateStr: string): string {
  const d = new Date(`${dateStr}T12:00:00`);
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

// ── Status badge ───────────────────────────────────────────────────────────────

function StatusBadge({ game }: { game: ScheduleGame }) {
  if (game.status === "live") {
    return (
      <span className="flex items-center gap-1.5 text-[10px] font-bold px-2 py-0.5 rounded bg-red-600/20 text-red-400">
        <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
        LIVE
      </span>
    );
  }
  if (game.status === "final") {
    return (
      <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-gray-700 text-gray-300">
        FINAL
      </span>
    );
  }
  return (
    <span className="text-xs font-medium text-gray-400">{formatTime(game.game_date)}</span>
  );
}

// ── AI prediction panel ─────────────────────────────────────────────────────────

function PredictionPanel({
  game, prediction, isPending, isError, onGenerate,
}: {
  game: ScheduleGame;
  prediction: GamePrediction | null | undefined;
  isPending: boolean;
  isError: boolean;
  onGenerate: () => void;
}) {
  return (
    <div className="px-4 py-4 bg-gray-950/60 border-t border-gray-800">
      {!prediction && !isPending && (
        <button
          onClick={onGenerate}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 text-xs font-medium hover:bg-blue-500/20 transition-colors"
        >
          <Sparkles className="h-3.5 w-3.5" />
          Predict the winner
        </button>
      )}
      {isPending && (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>Weighing records and the pitching matchup…</span>
        </div>
      )}
      {isError && <p className="text-xs text-red-400">Failed to generate a prediction. Try again.</p>}
      {prediction && (
        <div className="flex items-start gap-4">
          <div className="shrink-0">
            <p className="text-[10px] uppercase tracking-widest text-gray-500 mb-1">AI Predicts</p>
            <span className="inline-block px-3 py-1.5 rounded-lg bg-blue-500/15 border border-blue-500/30 text-blue-300 font-semibold text-sm whitespace-nowrap">
              {prediction.predicted_winner}
            </span>
            <p className="text-[10px] text-gray-500 mt-1">{prediction.confidence} confidence</p>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-widest text-gray-500 mb-1">Reasoning</p>
            <p className="text-sm text-gray-300 leading-relaxed">{prediction.reasoning}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Box score panel ──────────────────────────────────────────────────────────────

function TeamBox({ team, name, abbr }: { team: BoxScoreTeam; name: string; abbr: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <p className="text-xs font-semibold text-gray-200">{name}</p>
        <p className="text-[11px] text-gray-500 font-mono">
          R {team.runs} &middot; H {team.hits} &middot; E {team.errors} &middot; LOB {team.left_on_base}
        </p>
      </div>
      <div className="overflow-x-auto mb-3">
        <table className="w-full text-[11px] min-w-[320px]">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-left pb-1 font-medium">{abbr} Batting</th>
              <th className="pb-1 font-medium w-8">AB</th>
              <th className="pb-1 font-medium w-8">R</th>
              <th className="pb-1 font-medium w-8">H</th>
              <th className="pb-1 font-medium w-10">RBI</th>
              <th className="pb-1 font-medium w-8">BB</th>
              <th className="pb-1 font-medium w-8">SO</th>
            </tr>
          </thead>
          <tbody>
            {team.batters.map((b, i) => (
              <tr key={i} className="border-b border-gray-800/40">
                <td className="py-1 text-gray-300">
                  {b.name}
                  {b.position && <span className="text-gray-600 ml-1">{b.position}</span>}
                </td>
                <td className="text-center text-gray-400">{b.ab}</td>
                <td className="text-center text-gray-400">{b.r}</td>
                <td className="text-center text-gray-400">{b.h}</td>
                <td className="text-center text-gray-400">{b.rbi}</td>
                <td className="text-center text-gray-400">{b.bb}</td>
                <td className="text-center text-gray-400">{b.so}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] min-w-[320px]">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-left pb-1 font-medium">{abbr} Pitching</th>
              <th className="pb-1 font-medium w-10">IP</th>
              <th className="pb-1 font-medium w-8">H</th>
              <th className="pb-1 font-medium w-8">R</th>
              <th className="pb-1 font-medium w-8">ER</th>
              <th className="pb-1 font-medium w-8">BB</th>
              <th className="pb-1 font-medium w-8">SO</th>
            </tr>
          </thead>
          <tbody>
            {team.pitchers.map((p, i) => (
              <tr key={i} className="border-b border-gray-800/40">
                <td className="py-1 text-gray-300">
                  {p.name}
                  {p.decision && <span className="text-gray-600 ml-1">{p.decision}</span>}
                </td>
                <td className="text-center text-gray-400">{p.ip}</td>
                <td className="text-center text-gray-400">{p.h}</td>
                <td className="text-center text-gray-400">{p.r}</td>
                <td className="text-center text-gray-400">{p.er}</td>
                <td className="text-center text-gray-400">{p.bb}</td>
                <td className="text-center text-gray-400">{p.so}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function BoxScorePanel({ game }: { game: ScheduleGame }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["boxscore", game.game_pk],
    queryFn: () => scheduleApi.boxscore(game.game_pk).then((r) => r.data),
  });

  return (
    <div className="px-4 py-4 bg-gray-950/60 border-t border-gray-800">
      {isLoading && (
        <div className="flex items-center gap-2 text-xs text-gray-500 py-4">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>Loading box score…</span>
        </div>
      )}
      {isError && <p className="text-xs text-red-400 py-4">Failed to load box score.</p>}
      {data && (
        <>
          <div className="overflow-x-auto mb-4">
            <table className="text-[11px] min-w-full">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left pb-1 pr-3 font-medium"></th>
                  {data.innings.map((inn) => (
                    <th key={inn.num} className="pb-1 px-1.5 font-medium text-center w-6">{inn.num}</th>
                  ))}
                  <th className="pb-1 px-2 font-medium text-center">R</th>
                  <th className="pb-1 px-2 font-medium text-center">H</th>
                  <th className="pb-1 px-2 font-medium text-center">E</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-gray-800/40">
                  <td className="py-1 pr-3 text-gray-300 font-medium">{game.away_abbr}</td>
                  {data.innings.map((inn) => (
                    <td key={inn.num} className="text-center text-gray-400 px-1.5">{inn.away ?? "—"}</td>
                  ))}
                  <td className="text-center text-gray-200 font-semibold px-2">{data.away.runs}</td>
                  <td className="text-center text-gray-400 px-2">{data.away.hits}</td>
                  <td className="text-center text-gray-400 px-2">{data.away.errors}</td>
                </tr>
                <tr>
                  <td className="py-1 pr-3 text-gray-300 font-medium">{game.home_abbr}</td>
                  {data.innings.map((inn) => (
                    <td key={inn.num} className="text-center text-gray-400 px-1.5">{inn.home ?? "—"}</td>
                  ))}
                  <td className="text-center text-gray-200 font-semibold px-2">{data.home.runs}</td>
                  <td className="text-center text-gray-400 px-2">{data.home.hits}</td>
                  <td className="text-center text-gray-400 px-2">{data.home.errors}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <TeamBox team={data.away} name={game.away_team} abbr={game.away_abbr} />
            <TeamBox team={data.home} name={game.home_team} abbr={game.home_abbr} />
          </div>
        </>
      )}
    </div>
  );
}

// ── Game card ──────────────────────────────────────────────────────────────────

function TeamLine({
  name, record, score, pitcher, showScore, isWinner,
}: {
  name: string;
  record: string | null;
  score: number | null;
  pitcher: string | null;
  showScore: boolean;
  isWinner: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="min-w-0">
        <span className={`font-semibold text-sm ${isWinner ? "text-gray-100" : "text-gray-300"}`}>{name}</span>
        {record && <span className="text-[11px] text-gray-500 ml-2">{record}</span>}
        {pitcher && <div className="text-[11px] text-gray-500 mt-0.5">{pitcher}</div>}
      </div>
      {showScore && (
        <span className={`font-mono text-lg font-bold ml-3 ${isWinner ? "text-gray-100" : "text-gray-500"}`}>
          {score ?? "—"}
        </span>
      )}
    </div>
  );
}

function GameCard({ game }: { game: ScheduleGame }) {
  const [expanded, setExpanded] = useState(false);
  const isScheduled = game.status === "scheduled";
  const isFinal = game.status === "final";
  const isLive = game.status === "live";
  const showScore = isFinal || isLive;

  const predictMutation = useMutation({
    mutationFn: () => scheduleApi.predict(game.game_pk).then((r) => r.data),
  });
  const prediction = predictMutation.data ?? game.prediction;

  const awayWon = isFinal && game.away_score != null && game.home_score != null && game.away_score > game.home_score;
  const homeWon = isFinal && game.away_score != null && game.home_score != null && game.home_score > game.away_score;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 overflow-hidden">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full text-left px-4 py-3.5 hover:bg-gray-800/40 transition-colors flex items-center gap-4"
      >
        <div className="flex-1 min-w-0 space-y-1.5">
          <TeamLine
            name={game.away_team}
            record={game.away_record}
            score={game.away_score}
            pitcher={isScheduled ? (game.away_probable_pitcher ? `${game.away_probable_pitcher} (P)` : "Probable pitcher TBD") : null}
            showScore={showScore}
            isWinner={awayWon}
          />
          <TeamLine
            name={game.home_team}
            record={game.home_record}
            score={game.home_score}
            pitcher={isScheduled ? (game.home_probable_pitcher ? `${game.home_probable_pitcher} (P)` : "Probable pitcher TBD") : null}
            showScore={showScore}
            isWinner={homeWon}
          />
          {isFinal && game.winning_pitcher && (
            <p className="text-[11px] text-gray-600 pt-1">
              W: {game.winning_pitcher} &middot; L: {game.losing_pitcher}
              {game.save_pitcher && <> &middot; SV: {game.save_pitcher}</>}
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-1.5 shrink-0">
          <StatusBadge game={game} />
          {game.venue && <span className="text-[10px] text-gray-600">{game.venue}</span>}
          <ChevronDown className={`h-3.5 w-3.5 text-gray-600 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </div>
      </button>
      {expanded && isScheduled && (
        <PredictionPanel
          game={game}
          prediction={prediction}
          isPending={predictMutation.isPending}
          isError={predictMutation.isError}
          onGenerate={() => predictMutation.mutate()}
        />
      )}
      {expanded && (isFinal || isLive) && <BoxScorePanel game={game} />}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function SchedulePage() {
  const [date, setDate] = useState(todayStr());

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["schedule", date],
    queryFn: () => scheduleApi.get(date).then((r) => r.data),
    staleTime: 60 * 1000,
  });

  const games = data?.games ?? [];

  return (
    <div className="p-6 max-w-screen-lg mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-blue-600/20 rounded-lg">
            <CalendarDays className="h-5 w-5 text-blue-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-100">Schedule</h1>
            <p className="text-xs text-gray-500">{formatDateHeading(date)}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setDate((d) => shiftDate(d, -1))}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800 transition-colors"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <input
            type="date"
            value={date}
            onChange={(e) => e.target.value && setDate(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          />
          <button
            onClick={() => setDate((d) => shiftDate(d, 1))}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-gray-800 transition-colors"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          <button
            onClick={() => setDate(todayStr())}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-blue-400 hover:bg-blue-600/10 transition-colors"
          >
            Today
          </button>
        </div>
      </div>

      {isLoading && (
        <div className="flex flex-col items-center justify-center py-32 gap-3">
          <Loader2 className="h-6 w-6 text-gray-600 animate-spin" />
          <p className="text-sm text-gray-500">Loading schedule…</p>
        </div>
      )}

      {isError && !isLoading && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/40 p-8 text-center">
          <p className="text-red-400 text-sm font-medium mb-3">Failed to load schedule</p>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="px-4 py-1.5 rounded-lg bg-red-900/40 text-red-300 text-sm hover:bg-red-900/60 transition-colors"
          >
            Try again
          </button>
        </div>
      )}

      {!isLoading && !isError && games.length === 0 && (
        <div className="rounded-xl bg-gray-900 border border-gray-800 p-12 text-center">
          <CalendarDays className="h-8 w-8 text-gray-700 mx-auto mb-3" />
          <p className="text-sm text-gray-400 font-medium">No games scheduled this day</p>
        </div>
      )}

      {games.length > 0 && (
        <div className="space-y-3">
          {games.map((g) => (
            <GameCard key={g.game_pk} game={g} />
          ))}
        </div>
      )}
    </div>
  );
}
