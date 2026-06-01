"use client";
import { useState, useMemo, Fragment } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  standingsApi,
  type StandingsTeam,
  type StandingsConference,
  type StandingsDivision,
} from "@/lib/api";
import { Trophy, RefreshCw } from "lucide-react";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtPct(v: number) {
  if (v === 0) return ".000";
  return v.toFixed(3).replace(/^0\./, ".");
}

function fmtGB(v: number | null) {
  if (v === null) return "—";
  return v === Math.floor(v) ? String(v) : String(v);
}

function StreakBadge({ kind, length }: { kind: string; length: number }) {
  if (!kind || !length) return <span className="text-gray-600">—</span>;
  return (
    <span className={`font-semibold ${kind === "W" ? "text-green-400" : "text-red-400"}`}>
      {kind}{length}
    </span>
  );
}

function WCBack({ v }: { v: string }) {
  if (!v || v === "0.0") return <span className="text-gray-600">—</span>;
  const sign = v.startsWith("+") ? "+" : "";
  return (
    <span className={sign ? "text-red-400" : "text-emerald-400"}>
      {v.replace("+", "")}
    </span>
  );
}

function LeagueBadge({ alias }: { alias: string }) {
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-bold ${
        alias === "AL"
          ? "bg-blue-600/30 text-blue-300"
          : "bg-red-600/30 text-red-300"
      }`}
    >
      {alias}
    </span>
  );
}

// ── Tab navigation ─────────────────────────────────────────────────────────────

type Tab = "division" | "conference" | "playoff";

const TABS: { id: Tab; label: string }[] = [
  { id: "division",   label: "Division" },
  { id: "conference", label: "Conference" },
  { id: "playoff",    label: "Playoff Picture" },
];

// ── Division tab ───────────────────────────────────────────────────────────────

function DivisionCard({ div }: { div: StandingsDivision }) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
      <div className="px-4 py-2.5 bg-gray-800/60 border-b border-gray-700">
        <h3 className="text-sm font-semibold text-gray-200">{div.name}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs min-w-[480px]">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-left px-4 py-2 font-medium w-32">Team</th>
              <th className="text-center px-2 py-2 font-medium">W</th>
              <th className="text-center px-2 py-2 font-medium">L</th>
              <th className="text-center px-2 py-2 font-medium">PCT</th>
              <th className="text-center px-2 py-2 font-medium">GB</th>
              <th className="text-center px-2 py-2 font-medium">Home</th>
              <th className="text-center px-2 py-2 font-medium">Away</th>
              <th className="text-center px-2 py-2 font-medium">L10</th>
              <th className="text-center px-2 py-2 font-medium">Str</th>
            </tr>
          </thead>
          <tbody>
            {div.teams.map((t, i) => (
              <tr
                key={t.id}
                className={`border-b border-gray-800/50 transition-colors ${
                  i === 0
                    ? "bg-blue-950/20"
                    : "hover:bg-gray-800/30"
                }`}
              >
                <td className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    {i === 0 ? (
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
                    ) : (
                      <span className="w-1.5 h-1.5 flex-shrink-0" />
                    )}
                    <span
                      className={`font-semibold ${
                        i === 0 ? "text-gray-100" : "text-gray-300"
                      }`}
                    >
                      {t.alias}
                    </span>
                  </div>
                </td>
                <td className="text-center px-2 py-2 text-gray-100 font-medium">
                  {t.win}
                </td>
                <td className="text-center px-2 py-2 text-gray-400">
                  {t.loss}
                </td>
                <td className="text-center px-2 py-2 text-gray-300">
                  {fmtPct(t.pct)}
                </td>
                <td className="text-center px-2 py-2 text-gray-400">
                  {fmtGB(t.games_back)}
                </td>
                <td className="text-center px-2 py-2 text-gray-400">
                  {t.home_win}-{t.home_loss}
                </td>
                <td className="text-center px-2 py-2 text-gray-400">
                  {t.away_win}-{t.away_loss}
                </td>
                <td className="text-center px-2 py-2 text-gray-400">
                  {t.last10_win}-{t.last10_loss}
                </td>
                <td className="text-center px-2 py-2">
                  <StreakBadge kind={t.streak_kind} length={t.streak_length} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DivisionView({ conferences }: { conferences: StandingsConference[] }) {
  return (
    <div className="space-y-8">
      {conferences.map((conf) => (
        <div key={conf.alias}>
          <h2 className="text-sm font-bold text-gray-200 mb-3 flex items-center gap-2">
            <LeagueBadge alias={conf.alias} />
            {conf.name}
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {conf.divisions.map((div) => (
              <DivisionCard key={div.alias} div={div} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Conference tab ─────────────────────────────────────────────────────────────

function ConferenceTable({ conf }: { conf: StandingsConference }) {
  const allTeams = useMemo(() => {
    const flat: (StandingsTeam & { division: string })[] = [];
    for (const div of conf.divisions) {
      for (const t of div.teams) {
        flat.push({ ...t, division: div.alias });
      }
    }
    return flat.sort((a, b) => a.league_rank - b.league_rank || b.pct - a.pct);
  }, [conf]);

  const isAL = conf.alias === "AL";

  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
      <div
        className={`px-4 py-3 border-b border-gray-700 flex items-center gap-2 ${
          isAL ? "bg-blue-950/30" : "bg-red-950/20"
        }`}
      >
        <LeagueBadge alias={conf.alias} />
        <h3 className="text-sm font-semibold text-gray-200">{conf.name}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs min-w-[480px]">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-center px-3 py-2 font-medium w-8">#</th>
              <th className="text-left px-2 py-2 font-medium">Team</th>
              <th className="text-left px-2 py-2 font-medium text-gray-600">Div</th>
              <th className="text-center px-2 py-2 font-medium">W</th>
              <th className="text-center px-2 py-2 font-medium">L</th>
              <th className="text-center px-2 py-2 font-medium">PCT</th>
              <th className="text-center px-2 py-2 font-medium">GB</th>
              <th className="text-center px-2 py-2 font-medium">WC Back</th>
              <th className="text-center px-2 py-2 font-medium">Home</th>
              <th className="text-center px-2 py-2 font-medium">Away</th>
              <th className="text-center px-2 py-2 font-medium">L10</th>
              <th className="text-center px-2 py-2 font-medium">Str</th>
            </tr>
          </thead>
          <tbody>
            {allTeams.map((t, i) => (
              <Fragment key={t.id}>
                {i === 6 && (
                  <tr>
                    <td colSpan={12} className="px-4 py-1">
                      <div className="flex items-center gap-3">
                        <div className="flex-1 border-t border-dashed border-gray-700" />
                        <span className="text-[10px] text-gray-600 whitespace-nowrap tracking-wide">
                          ── playoff cutline ──
                        </span>
                        <div className="flex-1 border-t border-dashed border-gray-700" />
                      </div>
                    </td>
                  </tr>
                )}
                <tr
                  className={`border-b border-gray-800/40 transition-colors ${
                    i < 6
                      ? i === 0
                        ? "bg-blue-950/20 hover:bg-blue-950/30"
                        : "hover:bg-gray-800/30"
                      : "opacity-55 hover:opacity-75 hover:bg-gray-800/20"
                  }`}
                >
                  <td className="text-center px-3 py-2 text-gray-500 font-medium">
                    {i + 1}
                  </td>
                  <td className="px-2 py-2">
                    <span
                      className={`font-semibold ${
                        i < 3 ? "text-gray-100" : i < 6 ? "text-gray-200" : "text-gray-400"
                      }`}
                    >
                      {t.alias}
                    </span>
                    <span className="text-gray-500 ml-1.5 text-[11px]">{t.city}</span>
                  </td>
                  <td className="px-2 py-2 text-gray-600 text-[10px] font-medium">
                    {t.division}
                  </td>
                  <td className="text-center px-2 py-2 text-gray-100 font-medium">
                    {t.win}
                  </td>
                  <td className="text-center px-2 py-2 text-gray-400">{t.loss}</td>
                  <td className="text-center px-2 py-2 text-gray-300">
                    {fmtPct(t.pct)}
                  </td>
                  <td className="text-center px-2 py-2 text-gray-400">
                    {fmtGB(t.games_back)}
                  </td>
                  <td className="text-center px-2 py-2">
                    <WCBack v={t.wild_card_back} />
                  </td>
                  <td className="text-center px-2 py-2 text-gray-400">
                    {t.home_win}-{t.home_loss}
                  </td>
                  <td className="text-center px-2 py-2 text-gray-400">
                    {t.away_win}-{t.away_loss}
                  </td>
                  <td className="text-center px-2 py-2 text-gray-400">
                    {t.last10_win}-{t.last10_loss}
                  </td>
                  <td className="text-center px-2 py-2">
                    <StreakBadge kind={t.streak_kind} length={t.streak_length} />
                  </td>
                </tr>
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ConferenceView({ conferences }: { conferences: StandingsConference[] }) {
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
      {conferences.map((conf) => (
        <ConferenceTable key={conf.alias} conf={conf} />
      ))}
    </div>
  );
}

// ── Playoff Picture tab ────────────────────────────────────────────────────────

interface PlayoffTeam extends StandingsTeam {
  seed: number;
  divAlias: string;
  isWildCard: boolean;
}

function computePlayoff(conferences: StandingsConference[]) {
  const out: Record<
    string,
    { seeds: PlayoffTeam[]; bubble: (StandingsTeam & { divAlias: string })[] }
  > = {};

  for (const conf of conferences) {
    // Track which teams are division leaders (division_rank === 1)
    const divLeaderIds = new Set<string>();
    const allTeams: (StandingsTeam & { divAlias: string })[] = [];

    for (const div of conf.divisions) {
      for (const t of div.teams) {
        allTeams.push({ ...t, divAlias: div.alias });
        if (t.division_rank === 1) divLeaderIds.add(t.id);
      }
    }

    // Sort by league_rank (Sportradar's official seeding order)
    allTeams.sort((a, b) => a.league_rank - b.league_rank || b.pct - a.pct);

    const seeded: PlayoffTeam[] = allTeams.slice(0, 6).map((t, i) => ({
      ...t,
      seed: i + 1,
      isWildCard: !divLeaderIds.has(t.id),
    }));
    const bubble = allTeams.slice(6, 11);

    out[conf.alias] = { seeds: seeded, bubble };
  }
  return out;
}

function SeedCard({ team }: { team: PlayoffTeam }) {
  const isDiv = !team.isWildCard;
  const isTopSeed = team.seed <= 2;
  return (
    <div
      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${
        isDiv
          ? "bg-blue-950/25 border-blue-800/30"
          : "bg-gray-800/40 border-gray-700/30"
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
          <span className="font-bold text-gray-100 text-sm">{team.alias}</span>
          <span className="text-gray-400 text-xs">{team.city}</span>
          {isDiv ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400 font-medium">
              DIV
            </span>
          ) : (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-600/20 text-orange-400 font-medium">
              WC
            </span>
          )}
          {isTopSeed && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-600/20 text-emerald-400 font-medium">
              BYE
            </span>
          )}
        </div>
        <div className="text-[11px] text-gray-400 mt-0.5">
          {team.win}-{team.loss} &middot; {fmtPct(team.pct)}
        </div>
      </div>
    </div>
  );
}

function MatchupCard({
  hi,
  lo,
  label,
}: {
  hi: PlayoffTeam;
  lo: PlayoffTeam;
  label: string;
}) {
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-700/50 overflow-hidden">
      <div className="px-3 py-1 bg-gray-800/60 text-[10px] text-gray-500 font-medium uppercase tracking-wide">
        {label}
      </div>
      <div className="p-2 space-y-1">
        {[hi, lo].map((t, idx) => (
          <div
            key={t.id}
            className={`flex items-center gap-2 px-2 py-1.5 rounded ${
              idx === 0 ? "bg-gray-800/70" : "bg-gray-800/30"
            }`}
          >
            <span
              className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 ${
                !t.isWildCard ? "bg-blue-600 text-white" : "bg-gray-700 text-gray-300"
              }`}
            >
              {t.seed}
            </span>
            <span className="font-semibold text-gray-200 text-xs flex-1">{t.alias}</span>
            <span className="text-[11px] text-gray-500">
              {t.win}-{t.loss}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PlayoffColumn({
  conf,
  picture,
}: {
  conf: StandingsConference;
  picture: { seeds: PlayoffTeam[]; bubble: (StandingsTeam & { divAlias: string })[] };
}) {
  const { seeds, bubble } = picture;
  const isAL = conf.alias === "AL";

  const byeed = (n: number) => seeds.find((t) => t.seed === n);
  const s1 = byeed(1), s2 = byeed(2), s3 = byeed(3);
  const s4 = byeed(4), s5 = byeed(5), s6 = byeed(6);

  return (
    <div>
      {/* League header */}
      <h2 className="text-sm font-bold text-gray-200 mb-4 flex items-center gap-2">
        <LeagueBadge alias={conf.alias} />
        {conf.name}
      </h2>

      <div className="space-y-5">
        {/* Seeds list */}
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <div className="px-4 py-2.5 bg-gray-800/60 border-b border-gray-700">
            <p className="text-xs font-semibold text-gray-400">Projected Playoff Seeds</p>
          </div>
          <div className="p-3 space-y-2">
            <p className="text-[10px] text-gray-600 uppercase tracking-widest px-1 mb-1">
              Division Leaders
            </p>
            {[s1, s2, s3].filter(Boolean).map((t) => (
              <SeedCard key={t!.id} team={t!} />
            ))}

            <div className="border-t border-gray-800 pt-2 mt-1">
              <p className="text-[10px] text-gray-600 uppercase tracking-widest px-1 mb-1">
                Wild Card
              </p>
              {[s4, s5, s6].filter(Boolean).map((t) => (
                <SeedCard key={t!.id} team={t!} />
              ))}
            </div>
          </div>
        </div>

        {/* Wild Card bracket */}
        <div>
          <p className="text-xs font-semibold text-gray-400 mb-2">
            Wild Card Round (Best of 3)
          </p>
          <div className="space-y-2">
            {/* Seeds 1 & 2 get byes */}
            {[s1, s2].filter(Boolean).map((t) => (
              <div
                key={t!.id}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${
                  isAL ? "border-blue-700/40 bg-blue-950/20" : "border-red-700/30 bg-red-950/15"
                }`}
              >
                <span className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold bg-blue-600 text-white flex-shrink-0">
                  {t!.seed}
                </span>
                <div className="flex-1">
                  <span className="font-bold text-gray-100 text-sm">{t!.alias}</span>
                  <span className="text-gray-400 text-xs ml-2">
                    {t!.win}-{t!.loss}
                  </span>
                </div>
                <span className="text-[11px] font-semibold text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded">
                  BYE
                </span>
              </div>
            ))}
            {/* WC matchups */}
            {s3 && s6 && (
              <MatchupCard hi={s3} lo={s6} label="Wild Card Series" />
            )}
            {s4 && s5 && (
              <MatchupCard hi={s4} lo={s5} label="Wild Card Series" />
            )}
          </div>
        </div>

        {/* Division Series note */}
        <div className="rounded-lg border border-gray-800 bg-gray-900/60 px-4 py-3">
          <p className="text-[11px] text-gray-500 font-medium mb-1">
            Division Series (Best of 5)
          </p>
          <p className="text-[10px] text-gray-600">
            #1 seed vs lowest remaining seed &middot; #2 seed vs other winner
          </p>
        </div>

        {/* Bubble */}
        {bubble.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-gray-500 mb-2">On the Bubble</p>
            <div className="space-y-1">
              {bubble.map((t, i) => (
                <div
                  key={t.id}
                  className="flex items-center gap-3 px-3 py-1.5 rounded-lg bg-gray-800/25 border border-gray-800/30"
                >
                  <span className="text-[10px] text-gray-600 font-medium w-4 text-center">
                    {i + 1}
                  </span>
                  <span className="font-medium text-gray-400 text-xs flex-1">
                    {t.alias}{" "}
                    <span className="text-gray-600 font-normal">{t.city}</span>
                  </span>
                  <span className="text-[11px] text-gray-500">
                    {t.win}-{t.loss} &middot; {fmtPct(t.pct)}
                  </span>
                  <span className="text-[10px] text-gray-600">{t.divAlias}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function PlayoffView({ conferences }: { conferences: StandingsConference[] }) {
  const picture = useMemo(() => computePlayoff(conferences), [conferences]);
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-10">
      {conferences.map((conf) => (
        <PlayoffColumn
          key={conf.alias}
          conf={conf}
          picture={picture[conf.alias] ?? { seeds: [], bubble: [] }}
        />
      ))}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function StandingsPage() {
  const [tab, setTab] = useState<Tab>("division");
  const season = 2026;

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["standings", season],
    queryFn: () => standingsApi.get(season).then((r) => r.data),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  });

  return (
    <div className="p-6 max-w-screen-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-yellow-600/20 rounded-lg">
            <Trophy className="h-5 w-5 text-yellow-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-100">Standings</h1>
            <p className="text-xs text-gray-500">{season} MLB Regular Season</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {data?.as_of && (
            <p className="text-xs text-gray-600 hidden sm:block">
              Updated {new Date(data.as_of).toLocaleTimeString()}
            </p>
          )}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-800 transition-colors disabled:opacity-40"
            title="Refresh standings"
          >
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-900 rounded-lg p-1 border border-gray-800 w-fit">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              tab === t.id
                ? "bg-gray-700 text-gray-100 shadow-sm"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Body */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center py-32 gap-3">
          <RefreshCw className="h-6 w-6 text-gray-600 animate-spin" />
          <p className="text-sm text-gray-500">Loading standings from Sportradar…</p>
        </div>
      )}

      {isError && !isLoading && (
        <div className="rounded-xl bg-red-950/30 border border-red-800/40 p-8 text-center">
          <p className="text-red-400 text-sm font-medium mb-1">
            Failed to load standings
          </p>
          <p className="text-red-500/60 text-xs mb-4">
            Sportradar may be unavailable or rate-limiting the request.
          </p>
          <button
            onClick={() => refetch()}
            className="px-4 py-1.5 rounded-lg bg-red-900/40 text-red-300 text-sm hover:bg-red-900/60 transition-colors"
          >
            Try again
          </button>
        </div>
      )}

      {data && !isLoading && (
        <>
          {tab === "division"   && <DivisionView   conferences={data.conferences} />}
          {tab === "conference" && <ConferenceView conferences={data.conferences} />}
          {tab === "playoff"    && <PlayoffView    conferences={data.conferences} />}
        </>
      )}
    </div>
  );
}
