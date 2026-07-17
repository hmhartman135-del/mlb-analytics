"use client";
import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  playoffsApi,
  type PlayoffLeagueField,
  type PlayoffTeamSeed,
  type PlayoffBubbleTeam,
  type PlayoffOutlook,
  type BracketResponse,
  type BracketSeries,
  type SeriesPrediction,
} from "@/lib/api";
import { Award, Sparkles, Loader2 } from "lucide-react";

const SEASON = 2026;

// ── AI outlook panel (regular season) ───────────────────────────────────────────

function OutlookPanel({
  outlook, isPending, isError, onGenerate,
}: {
  outlook: PlayoffOutlook | null | undefined;
  isPending: boolean;
  isError: boolean;
  onGenerate: () => void;
}) {
  return (
    <div className="stat-card mb-6">
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-gray-200">AI Playoff Outlook</h2>
        <button
          onClick={onGenerate}
          disabled={isPending}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 text-xs font-medium hover:bg-blue-500/20 transition-colors disabled:opacity-40"
        >
          {isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          {outlook ? "Refresh Outlook" : "Generate Outlook"}
        </button>
      </div>
      {isError && <p className="text-xs text-red-400 mb-2">Failed to generate outlook. Try again.</p>}
      {isPending && !outlook && (
        <div className="flex items-center gap-2 text-xs text-gray-500 py-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>Weighing records, streaks, and the bubble…</span>
        </div>
      )}
      {outlook ? (
        <>
          <p className="text-sm text-gray-300 leading-relaxed">{outlook.summary}</p>
          <p className="text-[10px] text-gray-600 mt-2">
            Updated {new Date(outlook.generated_at).toLocaleString()}
          </p>
        </>
      ) : (
        !isPending && (
          <p className="text-xs text-gray-600">
            Generate a grounded read on who&apos;s a lock, who&apos;s vulnerable, and who has the best real shot off the bubble.
          </p>
        )
      )}
    </div>
  );
}

// ── Playoff field (regular season) ──────────────────────────────────────────────

function SeedRow({ team }: { team: PlayoffTeamSeed }) {
  const isDiv = !team.is_wild_card;
  return (
    <div
      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${
        isDiv ? "bg-blue-950/25 border-blue-800/30" : "bg-gray-800/40 border-gray-700/30"
      }`}
    >
      <span
        className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold flex-shrink-0 ${
          isDiv ? "bg-blue-600 text-white" : "bg-gray-700 text-gray-300"
        }`}
      >
        {team.seed}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-bold text-gray-100 text-sm">{team.full_name}</span>
          <span className="text-gray-500 text-xs">{team.division}</span>
          {isDiv ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400 font-medium">DIV</span>
          ) : (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-600/20 text-orange-400 font-medium">WC</span>
          )}
        </div>
        <div className="text-[11px] text-gray-400 mt-0.5">
          {team.win}-{team.loss}
          {team.streak_kind && <> &middot; {team.streak_kind}{team.streak_length}</>}
          {" "}&middot; L10 {team.last10_win}-{team.last10_loss}
        </div>
      </div>
    </div>
  );
}

function BubbleRow({ team, idx }: { team: PlayoffBubbleTeam; idx: number }) {
  return (
    <div className="flex items-center gap-3 px-3 py-1.5 rounded-lg bg-gray-800/25 border border-gray-800/30">
      <span className="text-[10px] text-gray-600 font-medium w-4 text-center">{idx + 1}</span>
      <span className="font-medium text-gray-400 text-xs flex-1">
        {team.full_name} <span className="text-gray-600 font-normal">{team.division}</span>
      </span>
      <span className="text-[11px] text-gray-500">
        {team.win}-{team.loss} &middot; {team.games_back ?? 0} back
      </span>
    </div>
  );
}

function LeagueFieldCard({ league }: { league: PlayoffLeagueField }) {
  const divLeaders = league.seeds.filter((s) => !s.is_wild_card);
  const wildCards = league.seeds.filter((s) => s.is_wild_card);
  return (
    <div className="stat-card">
      <h2 className="text-sm font-bold text-gray-200 mb-4">{league.league_name}</h2>
      <div className="space-y-2 mb-4">
        <p className="text-[10px] text-gray-600 uppercase tracking-widest px-1 mb-1">Division Leaders</p>
        {divLeaders.map((t) => <SeedRow key={t.id} team={t} />)}
      </div>
      <div className="space-y-2 mb-4">
        <p className="text-[10px] text-gray-600 uppercase tracking-widest px-1 mb-1">Wild Card</p>
        {wildCards.map((t) => <SeedRow key={t.id} team={t} />)}
      </div>
      {league.bubble.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 mb-2">On the Bubble</p>
          <div className="space-y-1">
            {league.bubble.map((t, i) => <BubbleRow key={t.id} team={t} idx={i} />)}
          </div>
        </div>
      )}
    </div>
  );
}

function FieldView() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["playoffs", "field", SEASON],
    queryFn: () => playoffsApi.getField(SEASON).then((r) => r.data),
  });

  const outlookMutation = useMutation({
    mutationFn: () => playoffsApi.generateOutlook(SEASON).then((r) => r.data),
  });
  const outlook = outlookMutation.data ?? data?.outlook;

  return (
    <>
      <OutlookPanel
        outlook={outlook}
        isPending={outlookMutation.isPending}
        isError={outlookMutation.isError}
        onGenerate={() => outlookMutation.mutate()}
      />

      {isLoading && (
        <div className="flex flex-col items-center justify-center py-24 gap-3">
          <Loader2 className="h-6 w-6 text-gray-600 animate-spin" />
          <p className="text-sm text-gray-500">Loading playoff picture…</p>
        </div>
      )}
      {isError && !isLoading && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/40 p-8 text-center">
          <p className="text-red-400 text-sm font-medium">Failed to load the playoff picture</p>
        </div>
      )}
      {data && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {data.leagues.map((lg) => <LeagueFieldCard key={lg.league} league={lg} />)}
        </div>
      )}
    </>
  );
}

// ── Bracket (postseason) ─────────────────────────────────────────────────────────

function SeriesPredictionBlock({
  prediction, isPending, isError, onGenerate,
}: {
  prediction: SeriesPrediction | null | undefined;
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
          Predict the series
        </button>
      )}
      {isPending && (
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>Weighing rosters and regular-season records…</span>
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

function SeriesCard({ series }: { series: BracketSeries }) {
  const [expanded, setExpanded] = useState(false);
  const predictMutation = useMutation({
    mutationFn: () => playoffsApi.predictSeries(series.series_key, SEASON).then((r) => r.data),
  });
  const prediction = predictMutation.data ?? series.prediction;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 overflow-hidden">
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full text-left px-4 py-3.5 hover:bg-gray-800/40 transition-colors"
      >
        <div className="flex items-center justify-between mb-1">
          <span className="font-semibold text-sm text-gray-100">
            {series.team_a_abbr} vs {series.team_b_abbr}
          </span>
          {series.games_in_series && (
            <span className="text-[10px] text-gray-500">Best of {series.games_in_series}</span>
          )}
        </div>
        {series.started ? (
          <p className={`text-xs ${series.is_over ? "text-gray-300 font-medium" : "text-gray-400"}`}>
            {series.result_text}
          </p>
        ) : (
          <p className="text-xs text-gray-500">Series hasn&apos;t started</p>
        )}
      </button>

      {expanded && series.started && (
        <div className="px-4 py-3 bg-gray-950/60 border-t border-gray-800 space-y-1.5">
          {series.games.map((g) => (
            <div key={g.game_pk} className="flex items-center justify-between text-xs">
              <span className="text-gray-400">{g.away_abbr} @ {g.home_abbr}</span>
              <span className="font-mono text-gray-300">
                {g.away_score ?? "—"} - {g.home_score ?? "—"}
              </span>
            </div>
          ))}
        </div>
      )}

      {expanded && !series.started && (
        <SeriesPredictionBlock
          prediction={prediction}
          isPending={predictMutation.isPending}
          isError={predictMutation.isError}
          onGenerate={() => predictMutation.mutate()}
        />
      )}
    </div>
  );
}

function BracketView({ bracket }: { bracket: BracketResponse }) {
  return (
    <div className="space-y-8">
      {bracket.rounds.map((round) => (
        <div key={round.round_label}>
          <h2 className="text-sm font-bold text-gray-200 mb-3">{round.round_label}</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {round.series.map((s) => <SeriesCard key={s.series_key} series={s} />)}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function PlayoffsPage() {
  const { data: bracket, isLoading: bracketLoading } = useQuery({
    queryKey: ["playoffs", "bracket", SEASON],
    queryFn: () => playoffsApi.getBracket(SEASON).then((r) => r.data),
  });

  return (
    <div className="p-6 max-w-screen-xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 bg-purple-600/20 rounded-lg">
          <Award className="h-5 w-5 text-purple-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-100">Playoffs</h1>
          <p className="text-xs text-gray-500">
            {bracket?.has_bracket ? `${SEASON} Postseason Bracket` : `${SEASON} Playoff Picture`}
          </p>
        </div>
      </div>

      {bracketLoading && (
        <div className="flex flex-col items-center justify-center py-24 gap-3">
          <Loader2 className="h-6 w-6 text-gray-600 animate-spin" />
          <p className="text-sm text-gray-500">Checking for the postseason bracket…</p>
        </div>
      )}

      {!bracketLoading && bracket?.has_bracket && <BracketView bracket={bracket} />}
      {!bracketLoading && !bracket?.has_bracket && <FieldView />}
    </div>
  );
}
