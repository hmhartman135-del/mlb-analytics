"use client";
import { useState, useMemo } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { playersApi, scoutingApi, type LeagueRosterPlayer, type PlayerHistoryResponse } from "@/lib/api";
import { SyncBar } from "@/components/ui/SyncBar";
import { Users, Search, X, Sparkles, Loader2 } from "lucide-react";

// ── Constants ──────────────────────────────────────────────────────────────────

const LEVEL_TABS = [
  { value: "26man",  label: "26-Man"   },
  { value: "AAA",    label: "Triple-A" },
  { value: "AA",     label: "Double-A" },
  { value: "A+",     label: "High-A"   },
  { value: "A",      label: "Single-A" },
  { value: "Rookie", label: "Rookie"   },
] as const;

type LevelTab = (typeof LEVEL_TABS)[number]["value"];

const LEVEL_COLORS: Record<string, string> = {
  "26man": "bg-blue-500/20 text-blue-300 border-blue-500/30",
  MLB:     "bg-blue-500/20 text-blue-300 border-blue-500/30",
  AAA:     "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  AA:      "bg-teal-500/20 text-teal-300 border-teal-500/30",
  "A+":    "bg-amber-500/20 text-amber-300 border-amber-500/30",
  A:       "bg-orange-500/20 text-orange-300 border-orange-500/30",
  Rookie:  "bg-violet-500/20 text-violet-300 border-violet-500/30",
};

const LEVEL_BORDER: Record<string, string> = {
  "26man": "border-b-blue-500",
  AAA:     "border-b-emerald-500",
  AA:      "border-b-teal-400",
  "A+":    "border-b-amber-400",
  A:       "border-b-orange-400",
  Rookie:  "border-b-violet-400",
};

const POSITIONS = ["C","1B","2B","3B","SS","LF","CF","RF","DH","SP","RP"];

function fmt(v: number | null | undefined, d = 3) {
  return v == null ? "—" : v.toFixed(d);
}
function fmtPct(v: number | null | undefined) {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}
function wrcColor(w: number) {
  if (w >= 140) return "bg-green-500/20 text-green-400";
  if (w >= 115) return "bg-blue-500/20 text-blue-300";
  if (w >= 85)  return "bg-gray-700 text-gray-300";
  return "bg-red-500/20 text-red-400";
}

// ── Team badge ─────────────────────────────────────────────────────────────────

function TeamBadge({ abbr }: { abbr: string }) {
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-gray-700/80 text-gray-300 border border-gray-600/50 flex-shrink-0 font-mono">
      {abbr}
    </span>
  );
}

// ── Hitters table ──────────────────────────────────────────────────────────────

function HittersTable({ players, onSelect }: { players: LeagueRosterPlayer[]; onSelect: (p: LeagueRosterPlayer) => void }) {
  if (!players.length) return null;
  return (
    <div className="mb-6">
      <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mb-2 pl-1">
        Position Players · {players.length}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
              <th className="pb-2 pr-3 font-medium">Name</th>
              <th className="pb-2 pr-3 font-medium">Team</th>
              <th className="pb-2 pr-3 font-medium">Pos</th>
              <th className="pb-2 pr-3 font-medium">Age</th>
              <th className="pb-2 pr-3 font-medium">B/T</th>
              <th className="pb-2 pr-3 font-medium text-right">G</th>
              <th className="pb-2 pr-3 font-medium text-right">PA</th>
              <th className="pb-2 pr-3 font-medium text-right">AVG</th>
              <th className="pb-2 pr-3 font-medium text-right">OBP</th>
              <th className="pb-2 pr-3 font-medium text-right">SLG</th>
              <th className="pb-2 pr-3 font-medium text-right">HR</th>
              <th className="pb-2 pr-3 font-medium text-right">RBI</th>
              <th className="pb-2 pr-3 font-medium text-right">SB</th>
              <th className="pb-2 font-medium text-right">wRC+</th>
            </tr>
          </thead>
          <tbody>
            {players.map(p => {
              const s = p.stats?.type === "batting" ? p.stats : null;
              return (
                <tr
                  key={p.id}
                  onClick={() => onSelect(p)}
                  className="border-b border-gray-800/30 hover:bg-gray-800/40 transition-colors cursor-pointer"
                >
                  <td className="py-2 pr-3 font-medium whitespace-nowrap">{p.full_name}</td>
                  <td className="py-2 pr-3"><TeamBadge abbr={p.team_abbr} /></td>
                  <td className="py-2 pr-3">
                    <span className="badge-grade bg-gray-700/60 text-gray-300 text-[11px]">{p.position}</span>
                  </td>
                  <td className="py-2 pr-3 text-gray-400 text-xs">{p.age ?? "—"}</td>
                  <td className="py-2 pr-3 text-gray-400 font-mono text-xs">{p.bats}/{p.throws}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-xs text-gray-300">{s?.games ?? "—"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-xs text-gray-400">{s?.plate_appearances ?? "—"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums font-mono text-xs">{fmt(s?.avg)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums font-mono text-xs">{fmt(s?.obp)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums font-mono text-xs">{fmt(s?.slg)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-xs">{s?.home_runs ?? "—"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-xs">{s?.rbi ?? "—"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-xs">{s?.stolen_bases ?? "—"}</td>
                  <td className="py-2 text-right">
                    {s?.wrc_plus != null
                      ? <span className={`badge-grade text-xs font-bold ${wrcColor(s.wrc_plus)}`}>{s.wrc_plus}</span>
                      : <span className="text-gray-600 text-xs">—</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Pitchers table ─────────────────────────────────────────────────────────────

function PitchersTable({ players, onSelect }: { players: LeagueRosterPlayer[]; onSelect: (p: LeagueRosterPlayer) => void }) {
  if (!players.length) return null;
  return (
    <div>
      <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mb-2 pl-1">
        Pitchers · {players.length}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
              <th className="pb-2 pr-3 font-medium">Name</th>
              <th className="pb-2 pr-3 font-medium">Team</th>
              <th className="pb-2 pr-3 font-medium">Pos</th>
              <th className="pb-2 pr-3 font-medium">Age</th>
              <th className="pb-2 pr-3 font-medium">B/T</th>
              <th className="pb-2 pr-3 font-medium text-right">G</th>
              <th className="pb-2 pr-3 font-medium text-right">GS</th>
              <th className="pb-2 pr-3 font-medium text-right">IP</th>
              <th className="pb-2 pr-3 font-medium text-right">ERA</th>
              <th className="pb-2 pr-3 font-medium text-right">FIP</th>
              <th className="pb-2 pr-3 font-medium text-right">WHIP</th>
              <th className="pb-2 pr-3 font-medium text-right">K%</th>
              <th className="pb-2 font-medium text-right">BB%</th>
            </tr>
          </thead>
          <tbody>
            {players.map(p => {
              const s = p.stats?.type === "pitching" ? p.stats : null;
              return (
                <tr
                  key={p.id}
                  onClick={() => onSelect(p)}
                  className="border-b border-gray-800/30 hover:bg-gray-800/40 transition-colors cursor-pointer"
                >
                  <td className="py-2 pr-3 font-medium whitespace-nowrap">{p.full_name}</td>
                  <td className="py-2 pr-3"><TeamBadge abbr={p.team_abbr} /></td>
                  <td className="py-2 pr-3">
                    <span className={`badge-grade text-[11px] ${p.position === "SP" ? "bg-indigo-500/20 text-indigo-300" : "bg-sky-500/20 text-sky-300"}`}>
                      {p.position}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-gray-400 text-xs">{p.age ?? "—"}</td>
                  <td className="py-2 pr-3 text-gray-400 font-mono text-xs">{p.bats}/{p.throws}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-xs text-gray-300">{s?.games ?? "—"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-xs">{s?.games_started ?? "—"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums font-mono text-xs">
                    {s?.innings_pitched != null ? s.innings_pitched.toFixed(1) : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums font-mono text-xs">{fmt(s?.era, 2)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums font-mono text-xs">{fmt(s?.fip, 2)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums font-mono text-xs">{fmt(s?.whip, 2)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-xs">{fmtPct(s?.k_pct)}</td>
                  <td className="py-2 text-right tabular-nums text-xs">{fmtPct(s?.bb_pct)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Player AI panel ──────────────────────────────────────────────────────────

function BioSection({ label, text, accent }: { label: string; text: string; accent?: "green" | "red" }) {
  if (!text) return null;
  const border = accent === "green" ? "border-emerald-500/30" : accent === "red" ? "border-red-500/30" : "border-gray-800";
  const labelColor = accent === "green" ? "text-emerald-400" : accent === "red" ? "text-red-400" : "text-gray-400";
  return (
    <div className={`border-l-2 ${border} pl-3 py-1`}>
      <p className={`text-[10px] uppercase tracking-widest font-semibold mb-1 ${labelColor}`}>{label}</p>
      <p className="text-sm text-gray-300 leading-relaxed">{text}</p>
    </div>
  );
}

function PlayerAiPanel({ player, onClose }: { player: LeagueRosterPlayer; onClose: () => void }) {
  const { data: history } = useQuery({
    queryKey: ["player-history", player.id],
    queryFn: () => scoutingApi.playerHistory(player.id).then(r => r.data),
  });

  const { mutate: generateBio, data: bio, isPending, isError } = useMutation({
    mutationFn: () => scoutingApi.aiBio(player.id).then(r => r.data),
  });

  const isPitcher = player.position === "SP" || player.position === "RP";
  const seasons: PlayerHistoryResponse["db_history"] = history?.db_history?.length
    ? history.db_history
    : (history?.minor_league_history ?? []);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-start justify-between px-5 py-4 border-b border-gray-800 shrink-0">
        <div>
          <h2 className="text-lg font-bold">{player.full_name}</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {player.team_name} · {player.position} · {player.bats}/{player.throws}
            {player.age && ` · Age ${player.age}`}
          </p>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300">
          <X className="h-5 w-5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-6">
        {/* Career stats table */}
        {seasons.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mb-2">Career</p>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-800">
                  <th className="pb-1.5 pr-2 font-medium">Yr</th>
                  <th className="pb-1.5 pr-2 font-medium">Lvl</th>
                  {isPitcher ? (
                    <>
                      <th className="pb-1.5 pr-2 font-medium text-right">IP</th>
                      <th className="pb-1.5 pr-2 font-medium text-right">ERA</th>
                      <th className="pb-1.5 font-medium text-right">WHIP</th>
                    </>
                  ) : (
                    <>
                      <th className="pb-1.5 pr-2 font-medium text-right">AVG</th>
                      <th className="pb-1.5 pr-2 font-medium text-right">HR</th>
                      <th className="pb-1.5 font-medium text-right">wRC+</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {seasons.slice(0, 8).map((s, i) => (
                  <tr key={i} className="border-b border-gray-800/30">
                    <td className="py-1.5 pr-2 text-gray-300">{s.season ?? "—"}</td>
                    <td className="py-1.5 pr-2 text-gray-500">{s.level}</td>
                    {isPitcher ? (
                      <>
                        <td className="py-1.5 pr-2 text-right font-mono">{s.innings_pitched ?? "—"}</td>
                        <td className="py-1.5 pr-2 text-right font-mono">{s.era ?? "—"}</td>
                        <td className="py-1.5 text-right font-mono">{s.whip ?? "—"}</td>
                      </>
                    ) : (
                      <>
                        <td className="py-1.5 pr-2 text-right font-mono">{s.avg ?? "—"}</td>
                        <td className="py-1.5 pr-2 text-right">{s.home_runs ?? "—"}</td>
                        <td className="py-1.5 text-right">{s.wrc_plus ?? "—"}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* AI analysis */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold">AI Analysis</p>
            {!bio && (
              <button
                onClick={() => generateBio()}
                disabled={isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 text-xs font-medium hover:bg-blue-500/20 transition-colors disabled:opacity-50"
              >
                {isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                {isPending ? "Analyzing…" : "Generate AI Analysis"}
              </button>
            )}
          </div>

          {isError && <p className="text-xs text-red-400">Failed to generate analysis. Try again.</p>}

          {bio && (
            <div className="space-y-4">
              <BioSection label="Background" text={bio.background} />
              <BioSection label="Career" text={bio.career} />
              <BioSection label="Current Production" text={bio.current} />
              <BioSection label="What Scouts Like" text={bio.likes} accent="green" />
              <BioSection label="Concerns" text={bio.concerns} accent="red" />
            </div>
          )}

          {!bio && !isPending && !isError && (
            <p className="text-xs text-gray-600">
              Generate a full AI breakdown of this player's background, career progression,
              current production, strengths, and concerns — grounded in their real stat history.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PlayersPage() {
  const [activeLevel, setActiveLevel] = useState<LevelTab>("26man");
  const [search, setSearch]           = useState("");
  const [position, setPosition]       = useState("");
  const [team, setTeam]               = useState("");
  const [selectedPlayer, setSelectedPlayer] = useState<LeagueRosterPlayer | null>(null);
  const qc = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["league-roster", activeLevel],
    queryFn: () => playersApi.leagueRoster({ level: activeLevel }).then(r => r.data),
    staleTime: 3 * 60 * 1000,
  });

  // Client-side filter for search + position + team (fast, no extra round-trip)
  const allPlayers = data?.players ?? [];

  const teams = useMemo(() => {
    const byAbbr = new Map<string, string>();
    for (const p of allPlayers) byAbbr.set(p.team_abbr, p.team_name);
    return Array.from(byAbbr.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [allPlayers]);

  const filtered = useMemo(() => {
    return allPlayers.filter(p => {
      if (position && p.position !== position) return false;
      if (team && p.team_abbr !== team) return false;
      if (search) {
        const q = search.toLowerCase();
        return (
          p.full_name.toLowerCase().includes(q) ||
          p.team_name.toLowerCase().includes(q) ||
          p.team_abbr.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [allPlayers, search, position, team]);

  const hitters  = filtered.filter(p => p.position !== "SP" && p.position !== "RP");
  const pitchers = filtered.filter(p => p.position === "SP" || p.position === "RP");

  const activeBorder = LEVEL_BORDER[activeLevel] ?? "border-b-blue-500";
  const hasFilters = !!(search || position || team);

  return (
    <div className="max-w-screen-2xl mx-auto px-6 py-6">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Users className="h-7 w-7 text-blue-400" />
        <div>
          <h1 className="text-2xl font-bold">Players</h1>
          <p className="text-sm text-gray-500">League-wide rosters across all levels</p>
        </div>
      </div>

      {/* Live sync bar */}
      <SyncBar
        className="mb-5"
        onSyncComplete={() => qc.invalidateQueries({ queryKey: ["league-roster"] })}
      />

      {/* Level tabs */}
      <div className="flex border-b border-gray-800 mb-5 overflow-x-auto">
        {LEVEL_TABS.map(({ value, label }) => {
          const isActive = activeLevel === value;
          return (
            <button
              key={value}
              onClick={() => { setActiveLevel(value); setSearch(""); setPosition(""); setTeam(""); setSelectedPlayer(null); }}
              className={`px-5 py-2.5 text-sm font-semibold whitespace-nowrap transition-colors relative flex-shrink-0
                ${isActive ? "text-white" : "text-gray-500 hover:text-gray-300"}`}
            >
              {label}
              {isActive && (
                <span className={`absolute bottom-0 left-0 right-0 h-0.5 ${activeBorder.replace("border-b-", "bg-")}`} />
              )}
            </button>
          );
        })}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-5">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-500 pointer-events-none" />
          <input
            className="w-full bg-gray-800 border border-gray-700 rounded-xl pl-9 pr-8 py-2 text-sm focus:outline-none focus:border-blue-500 text-gray-200 placeholder-gray-500"
            placeholder="Search player or team…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2.5 top-2.5 text-gray-500 hover:text-gray-300">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <select
          className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-gray-200"
          value={position}
          onChange={e => setPosition(e.target.value)}
        >
          <option value="">All positions</option>
          {POSITIONS.map(pos => <option key={pos} value={pos}>{pos}</option>)}
        </select>
        <select
          className="bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-blue-500 text-gray-200"
          value={team}
          onChange={e => setTeam(e.target.value)}
        >
          <option value="">All teams</option>
          {teams.map(([abbr, name]) => <option key={abbr} value={abbr}>{name}</option>)}
        </select>
        {hasFilters && (
          <button
            onClick={() => { setSearch(""); setPosition(""); setTeam(""); }}
            className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 rounded-xl transition-colors"
          >
            <X className="h-3.5 w-3.5" />Clear
          </button>
        )}
        {data && (
          <p className="text-xs text-gray-500 self-center ml-auto">
            {filtered.length.toLocaleString()} players
            {filtered.length !== allPlayers.length && ` (filtered from ${allPlayers.length.toLocaleString()})`}
          </p>
        )}
      </div>

      {/* Content */}
      <div className="flex gap-5 items-start">
        <div className={selectedPlayer ? "flex-1 min-w-0" : "w-full"}>
          {isLoading ? (
            <div className="flex items-center justify-center py-24 text-gray-500">
              <div className="text-center">
                <div className="h-8 w-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                <p className="text-sm">Loading {LEVEL_TABS.find(t => t.value === activeLevel)?.label} rosters…</p>
              </div>
            </div>
          ) : isError ? (
            <div className="text-center py-20 text-red-400 text-sm">Failed to load roster data.</div>
          ) : filtered.length === 0 ? (
            <div className="text-center py-20 text-gray-600">
              <Users className="h-10 w-10 mx-auto mb-3 opacity-30" />
              <p className="text-sm">No players found{search ? ` for "${search}"` : ""}.</p>
            </div>
          ) : (
            <div className="stat-card">
              <HittersTable players={hitters} onSelect={setSelectedPlayer} />
              {hitters.length > 0 && pitchers.length > 0 && (
                <div className="border-t border-gray-800 my-5" />
              )}
              <PitchersTable players={pitchers} onSelect={setSelectedPlayer} />
            </div>
          )}
        </div>

        {selectedPlayer && (
          <div className="w-[380px] shrink-0 border border-gray-800 rounded-xl bg-gray-900 sticky top-6 h-[calc(100vh-3rem)] overflow-hidden">
            <PlayerAiPanel player={selectedPlayer} onClose={() => setSelectedPlayer(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
