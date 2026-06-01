"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  teamsApi,
  playersApi,
  rosterApi,
  tradesApi,
  type Team,
  type OrgPlayer,
  type RosterPlayer,
  type TradeEvaluateResponse,
  type TradeTeamGrade,
  type TradeProposal,
  type TradeFinderResponse,
  type TeamAdvisorResponse,
} from "@/lib/api";
import { TeamSelector } from "@/components/ui/TeamSelector";
import {
  ArrowLeftRight,
  Plus,
  X,
  Search,
  Loader2,
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Users,
  Zap,
  Sparkles,
  TrendingUp,
  BarChart2,
  ShoppingCart,
  PackageOpen,
  Target,
} from "lucide-react";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtSalary(v: number | null): string {
  if (!v) return "arb";
  return `$${v.toFixed(1)}M`;
}

function gradeColor(g: string): string {
  if (g.startsWith("A")) return "text-green-400";
  if (g.startsWith("B")) return "text-blue-400";
  if (g.startsWith("C")) return "text-amber-400";
  return "text-red-400";
}

function gradeBg(g: string): string {
  if (g.startsWith("A")) return "bg-green-500/15 border-green-500/30 text-green-300";
  if (g.startsWith("B")) return "bg-blue-500/15 border-blue-500/30 text-blue-300";
  if (g.startsWith("C")) return "bg-amber-500/15 border-amber-500/30 text-amber-300";
  return "bg-red-500/15 border-red-500/30 text-red-300";
}

function doableVariant(d: string): {
  bg: string; text: string; icon: React.ReactNode;
} {
  switch (d) {
    case "Yes":
      return { bg: "bg-green-500/15 border-green-500/30", text: "text-green-300", icon: <CheckCircle2 className="h-4 w-4" /> };
    case "Likely":
      return { bg: "bg-blue-500/15 border-blue-500/30", text: "text-blue-300", icon: <CheckCircle2 className="h-4 w-4" /> };
    case "Unlikely":
      return { bg: "bg-amber-500/15 border-amber-500/30", text: "text-amber-300", icon: <AlertCircle className="h-4 w-4" /> };
    default:
      return { bg: "bg-red-500/15 border-red-500/30", text: "text-red-300", icon: <X className="h-4 w-4" /> };
  }
}

function PosBadge({ pos }: { pos: string | null | undefined }) {
  const colors: Record<string, string> = {
    SP: "bg-blue-500/20 text-blue-300 border-blue-500/30",
    RP: "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
    C:  "bg-amber-500/20 text-amber-300 border-amber-500/30",
    DH: "bg-gray-500/20 text-gray-300 border-gray-500/30",
  };
  const hitter = "bg-emerald-500/20 text-emerald-300 border-emerald-500/30";
  const cls = colors[pos ?? ""] ?? hitter;
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border flex-shrink-0 ${cls}`}>
      {pos ?? "?"}
    </span>
  );
}

const LEVEL_COLORS: Record<string, string> = {
  MLB:    "bg-purple-500/20 text-purple-300 border-purple-500/30",
  AAA:    "bg-blue-500/20 text-blue-300 border-blue-500/30",
  AA:     "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
  "A+":   "bg-green-500/20 text-green-300 border-green-500/30",
  A:      "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  Rookie: "bg-gray-500/20 text-gray-400 border-gray-600/40",
};

function LevelBadge({ level }: { level: string }) {
  const cls = LEVEL_COLORS[level] ?? "bg-gray-800 text-gray-500 border-gray-700";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border flex-shrink-0 ${cls}`}>
      {level}
    </span>
  );
}

const ALL_LEVELS = ["MLB", "AAA", "AA", "A+", "A", "Rookie"];

const LEVEL_TABS: { value: string; label: string }[] = [
  { value: "MLB",    label: "26-Man"   },
  { value: "AAA",    label: "Triple-A" },
  { value: "AA",     label: "Double-A" },
  { value: "A+",     label: "High-A"   },
  { value: "A",      label: "Single-A" },
  { value: "Rookie", label: "Rookie"   },
];

// ── Types ─────────────────────────────────────────────────────────────────────

interface TradeLegPlayer {
  id: string;
  name: string;
  position: string | null;
  age: number | null;
  salary: number | null;
  contract_years: number | null;
  level: string;   // MLB | AAA | AA | A+ | A | Rookie
}

interface TradeLeg {
  legId: string;
  teamId: string;
  teamName: string;
  teamAbbr: string;
  players: TradeLegPlayer[];
}

let _legCounter = 0;
function newLeg(): TradeLeg {
  return { legId: String(++_legCounter), teamId: "", teamName: "", teamAbbr: "", players: [] };
}

// ── Team card ─────────────────────────────────────────────────────────────────

function TradeTeamCard({
  leg,
  allLegs,
  allTeams,
  onUpdate,
  onRemove,
  canRemove,
}: {
  leg: TradeLeg;
  allLegs: TradeLeg[];
  allTeams: Team[];
  onUpdate: (updated: TradeLeg) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const [showRoster, setShowRoster] = useState(false);
  const [search, setSearch] = useState("");
  const [levelFilter, setLevelFilter] = useState("MLB");

  // 26-Man roster via breakdown (same source as Roster tab)
  const { data: breakdownData, isLoading: breakdownLoading } = useQuery({
    queryKey: ["roster-breakdown", leg.teamId],
    queryFn: () => rosterApi.breakdown(leg.teamId),
    enabled: !!leg.teamId,
    staleTime: 5 * 60 * 1000,
  });

  // Minor-league org data (AAA → Rookie)
  const { data: orgData, isLoading: orgLoading } = useQuery({
    queryKey: ["org-roster", leg.teamId],
    queryFn: () => playersApi.orgRoster(leg.teamId),
    enabled: !!leg.teamId,
    staleTime: 5 * 60 * 1000,
  });

  const rosterLoading = levelFilter === "MLB" ? breakdownLoading : orgLoading;

  // Players for the currently-selected level tab
  type TabPlayer = (RosterPlayer | OrgPlayer) & { level: string };
  const tabPlayers = useMemo<TabPlayer[]>(() => {
    if (levelFilter === "MLB") {
      return (breakdownData?.data?.twenty_six ?? []).map(p => ({ ...p, level: "MLB" }));
    }
    const group = (orgData?.data?.groups ?? []).find(g => g.level === levelFilter);
    return (group?.players ?? []).map(p => ({ ...p, level: levelFilter }));
  }, [levelFilter, breakdownData, orgData]);

  // Which level tabs have players loaded?
  const presentLevels = useMemo(() => {
    const result: string[] = [];
    if ((breakdownData?.data?.twenty_six_count ?? 0) > 0) result.push("MLB");
    for (const lv of ["AAA", "AA", "A+", "A", "Rookie"]) {
      const group = (orgData?.data?.groups ?? []).find(g => g.level === lv);
      if (group && group.players.length > 0) result.push(lv);
    }
    return result;
  }, [breakdownData, orgData]);

  const addedIds = useMemo(() => new Set(leg.players.map(p => p.id)), [leg.players]);

  const filteredRoster = useMemo(() => {
    return tabPlayers
      .filter(p => !addedIds.has(p.id))
      .filter(p =>
        !search ||
        p.full_name.toLowerCase().includes(search.toLowerCase()) ||
        (p.position ?? "").toLowerCase().includes(search.toLowerCase()),
      );
  }, [tabPlayers, addedIds, search]);

  // Players this team is RECEIVING (everything other teams are sending)
  const receiving = useMemo(
    () => allLegs.filter(l => l.legId !== leg.legId).flatMap(l => l.players),
    [allLegs, leg.legId],
  );

  const handleTeamSelect = (teamId: string) => {
    const team = allTeams.find(t => t.id === teamId);
    onUpdate({ ...leg, teamId, teamName: team?.full_name ?? "", teamAbbr: team?.abbreviation ?? "", players: [] });
    setShowRoster(false);
    setSearch("");
    setLevelFilter("MLB");
  };

  const addPlayer = (p: TabPlayer) => {
    onUpdate({
      ...leg,
      players: [
        ...leg.players,
        {
          id: p.id,
          name: p.full_name,
          position: p.position,
          age: p.age,
          salary: p.salary,
          contract_years: p.contract_years,
          level: p.level,
        },
      ],
    });
  };

  const removePlayer = (id: string) => {
    onUpdate({ ...leg, players: leg.players.filter(p => p.id !== id) });
  };

  return (
    <div className="bg-gray-900 border border-gray-700/60 rounded-2xl flex flex-col overflow-hidden min-w-0">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-800 bg-gray-900/80">
        <Users className="h-4 w-4 text-gray-500 flex-shrink-0" />
        <div className="relative flex-1 min-w-0">
          <select
            value={leg.teamId}
            onChange={e => handleTeamSelect(e.target.value)}
            className="w-full appearance-none bg-gray-800 border border-gray-700 rounded-xl px-3 py-2 pr-8 text-sm text-gray-200 focus:outline-none focus:border-blue-500 cursor-pointer truncate"
          >
            <option value="">— Choose a team —</option>
            {allTeams.map(t => (
              <option key={t.id} value={t.id}>{t.full_name}</option>
            ))}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500 pointer-events-none" />
        </div>
        {canRemove && (
          <button onClick={onRemove} className="p-1 rounded-lg text-gray-600 hover:text-red-400 hover:bg-red-500/10 transition-colors flex-shrink-0">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 flex flex-col p-4 gap-4">

        {/* Trading Away */}
        <div>
          <p className="text-[10px] font-bold text-red-400 uppercase tracking-widest mb-2">
            Trading Away ({leg.players.length})
          </p>
          <div className="space-y-1.5 min-h-[44px]">
            {leg.players.length === 0 ? (
              <p className="text-xs text-gray-600 italic">No players added yet</p>
            ) : (
              leg.players.map(p => (
                <div key={p.id} className="flex items-center gap-2 px-2.5 py-1.5 bg-red-500/5 border border-red-500/20 rounded-lg group">
                  <LevelBadge level={p.level} />
                  <PosBadge pos={p.position} />
                  <span className="text-xs font-medium text-gray-200 flex-1 min-w-0 truncate">{p.name}</span>
                  <span className="text-[10px] text-gray-600 flex-shrink-0">
                    {p.age ? `${p.age}` : ""}{p.salary ? ` ${fmtSalary(p.salary)}` : ""}
                  </span>
                  <button
                    onClick={() => removePlayer(p.id)}
                    className="text-gray-700 hover:text-red-400 transition-colors flex-shrink-0 opacity-0 group-hover:opacity-100"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))
            )}
          </div>

          {/* Add player */}
          {leg.teamId && (
            <div className="mt-2">
              {!showRoster ? (
                <button
                  onClick={() => setShowRoster(true)}
                  disabled={rosterLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-750 border border-gray-700 rounded-lg text-xs text-gray-400 hover:text-gray-200 transition-colors w-full justify-center"
                >
                  {rosterLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
                  {rosterLoading
                    ? "Loading org…"
                    : `Add player (${tabPlayers.filter(p => !addedIds.has(p.id)).length} available)`}
                </button>
              ) : (
                <div className="border border-gray-700 rounded-xl overflow-hidden bg-gray-800/60">
                  {/* Search bar */}
                  <div className="flex items-center gap-2 px-2.5 py-2 border-b border-gray-700/60">
                    <Search className="h-3.5 w-3.5 text-gray-500 flex-shrink-0" />
                    <input
                      autoFocus
                      className="flex-1 bg-transparent text-sm focus:outline-none text-gray-200 placeholder-gray-600"
                      placeholder="Search name or position…"
                      value={search}
                      onChange={e => setSearch(e.target.value)}
                    />
                    <button onClick={() => { setShowRoster(false); setSearch(""); setLevelFilter("MLB"); }} className="text-gray-600 hover:text-gray-300">
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  {/* Level tabs */}
                  <div className="flex border-b border-gray-700/60 bg-gray-900/60">
                    {LEVEL_TABS.map(({ value, label }) => {
                      const hasPlayers = presentLevels.includes(value);
                      const isActive = levelFilter === value;
                      return (
                        <button
                          key={value}
                          onClick={() => setLevelFilter(value)}
                          disabled={!hasPlayers}
                          className={`flex-1 py-2 text-[10px] font-bold tracking-wide transition-colors relative
                            ${!hasPlayers
                              ? "text-gray-700 cursor-not-allowed"
                              : isActive
                                ? "text-blue-300"
                                : "text-gray-500 hover:text-gray-300"
                            }`}
                        >
                          {label}
                          {isActive && hasPlayers && (
                            <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-400 rounded-t" />
                          )}
                        </button>
                      );
                    })}
                  </div>

                  {/* Player list */}
                  <div className="max-h-56 overflow-y-auto">
                    {filteredRoster.length === 0 ? (
                      <p className="text-xs text-gray-600 text-center py-4 italic">No players match.</p>
                    ) : (
                      filteredRoster.slice(0, 60).map(p => (
                        <button
                          key={p.id}
                          onClick={() => { addPlayer(p); setSearch(""); }}
                          className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-700/50 transition-colors text-left"
                        >
                          <LevelBadge level={p.level} />
                          <PosBadge pos={p.position} />
                          <span className="text-xs font-medium text-gray-200 flex-1 truncate">{p.full_name}</span>
                          <span className="text-[10px] text-gray-500 flex-shrink-0">
                            {p.age ? `${p.age}` : ""}{p.salary ? ` ${fmtSalary(p.salary)}` : ""}
                          </span>
                        </button>
                      ))
                    )}
                    {filteredRoster.length > 60 && (
                      <p className="text-[10px] text-gray-600 text-center py-2 italic">
                        {filteredRoster.length - 60} more — narrow with search or level filter
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Receiving */}
        <div>
          <p className="text-[10px] font-bold text-green-400 uppercase tracking-widest mb-2">
            Receiving ({receiving.length})
          </p>
          <div className="space-y-1.5 min-h-[44px]">
            {receiving.length === 0 ? (
              <p className="text-xs text-gray-600 italic">
                {allLegs.filter(l => l.legId !== leg.legId).some(l => l.players.length > 0)
                  ? "Players will appear here"
                  : "Other teams haven't added players yet"}
              </p>
            ) : (
              receiving.map((p, idx) => (
                <div key={`${p.id}-${idx}`} className="flex items-center gap-2 px-2.5 py-1.5 bg-green-500/5 border border-green-500/20 rounded-lg">
                  <LevelBadge level={p.level} />
                  <PosBadge pos={p.position} />
                  <span className="text-xs font-medium text-gray-200 flex-1 min-w-0 truncate">{p.name}</span>
                  <span className="text-[10px] text-gray-600 flex-shrink-0">
                    {p.age ? `${p.age}` : ""}{p.salary ? ` ${fmtSalary(p.salary)}` : ""}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Trade result panel ─────────────────────────────────────────────────────────

function TradeResultPanel({ result }: { result: TradeEvaluateResponse }) {
  const dv = doableVariant(result.doable);

  return (
    <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-6 space-y-5">
      {/* Doability badge */}
      <div className="flex items-start gap-4 flex-wrap">
        <div className={`flex items-center gap-2.5 px-4 py-2.5 rounded-xl border ${dv.bg}`}>
          <span className={dv.text}>{dv.icon}</span>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-widest text-gray-500">Trade Feasibility</p>
            <p className={`text-lg font-bold ${dv.text}`}>{result.doable}</p>
          </div>
        </div>
        {result.reason && (
          <p className="text-sm text-gray-400 italic flex-1 min-w-0 pt-1">{result.reason}</p>
        )}
      </div>

      {/* Per-team grades */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {result.team_grades.map((tg: TradeTeamGrade) => (
          <div key={tg.team_abbr} className="bg-gray-800/60 rounded-xl border border-gray-700/50 p-4 space-y-2">
            <div className="flex items-center gap-2">
              <span className={`text-2xl font-black ${gradeColor(tg.grade)}`}>{tg.grade}</span>
              <div className="min-w-0">
                <p className="text-xs font-bold text-gray-200 truncate">{tg.team_name}</p>
                <p className="text-[10px] text-gray-500">{tg.team_abbr}</p>
              </div>
            </div>
            <p className="text-xs text-gray-400 leading-relaxed">{tg.analysis}</p>
          </div>
        ))}
      </div>

      {/* Overall analysis */}
      {result.overall && (
        <div className="bg-gray-800/40 rounded-xl border border-gray-700/40 px-4 py-3">
          <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1.5">Overall Analysis</p>
          <p className="text-sm text-gray-300 leading-relaxed">{result.overall}</p>
        </div>
      )}
    </div>
  );
}

// ── Trade Finder ───────────────────────────────────────────────────────────────

function ProposalCard({ proposal, sellerName }: { proposal: TradeProposal; sellerName: string }) {
  const bgrd = gradeBg(proposal.buyer_grade);
  const sgrd = gradeBg(proposal.seller_grade);

  return (
    <div className="bg-gray-900 border border-gray-700/60 rounded-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 bg-gray-800/60 border-b border-gray-700/40">
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Acquiring Team</p>
          <p className="font-bold text-gray-100 text-sm truncate">{proposal.acquiring_team}</p>
        </div>
        {proposal.acquiring_team_abbr && (
          <span className="px-2 py-1 rounded-lg text-xs font-bold bg-purple-500/20 text-purple-300 border border-purple-500/30 flex-shrink-0">
            {proposal.acquiring_team_abbr}
          </span>
        )}
      </div>

      <div className="p-4 space-y-3">
        {/* Why */}
        <p className="text-xs text-blue-300 italic leading-relaxed">{proposal.why}</p>

        {/* Return package */}
        <div>
          <p className="text-[10px] font-bold text-green-400 uppercase tracking-widest mb-1.5">
            {sellerName} Receives
          </p>
          <div className="flex flex-wrap gap-1.5">
            {proposal.return_package.map((item, i) => (
              <span
                key={i}
                className="px-2 py-1 rounded-lg text-[11px] bg-green-500/10 text-green-300 border border-green-500/20"
              >
                {item}
              </span>
            ))}
          </div>
        </div>

        {/* Grades */}
        <div className="flex gap-3">
          <div className="flex-1">
            <p className="text-[10px] text-gray-500 mb-1">Buyer Grade</p>
            <span className={`inline-block px-2.5 py-1 rounded-lg text-sm font-black border ${bgrd}`}>
              {proposal.buyer_grade}
            </span>
          </div>
          <div className="flex-1">
            <p className="text-[10px] text-gray-500 mb-1">Seller Grade</p>
            <span className={`inline-block px-2.5 py-1 rounded-lg text-sm font-black border ${sgrd}`}>
              {proposal.seller_grade}
            </span>
          </div>
        </div>

        {/* Analysis */}
        {proposal.analysis && (
          <p className="text-xs text-gray-400 leading-relaxed border-t border-gray-800 pt-3">
            {proposal.analysis}
          </p>
        )}
      </div>
    </div>
  );
}

function TradeFinderPanel() {
  const [query, setQuery]           = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState("");
  const [result, setResult]         = useState<TradeFinderResponse | null>(null);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropRef  = useRef<HTMLDivElement>(null);

  // Debounce search query
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (
        dropRef.current && !dropRef.current.contains(e.target as Node) &&
        inputRef.current && !inputRef.current.contains(e.target as Node)
      ) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const { data: searchData, isFetching: searching } = useQuery({
    queryKey: ["player-search", debouncedQ],
    queryFn: () => playersApi.list({ search: debouncedQ, limit: 12 }),
    enabled: debouncedQ.length >= 2,
    staleTime: 60_000,
  });

  const players = searchData?.data?.players ?? [];

  const handleSelect = (p: { id: string; full_name: string }) => {
    setSelectedId(p.id);
    setSelectedName(p.full_name);
    setQuery(p.full_name);
    setShowDropdown(false);
    setResult(null);
    setError(null);
  };

  const handleFind = async () => {
    if (!selectedId) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await tradesApi.findTrades({ player_id: selectedId });
      setResult(res.data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to generate trade proposals. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const pl = result?.player;

  return (
    <div className="space-y-6">
      {/* Search card */}
      <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Sparkles className="h-4 w-4 text-purple-400" />
          <p className="text-sm font-semibold text-gray-200">Find Trade Partners</p>
          <p className="text-xs text-gray-500 ml-1">— AI generates realistic proposals based on standings & value</p>
        </div>

        {/* Player search */}
        <div className="relative">
          <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-800 border border-gray-700 rounded-xl focus-within:border-purple-500 transition-colors">
            <Search className="h-4 w-4 text-gray-500 flex-shrink-0" />
            <input
              ref={inputRef}
              className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-500 focus:outline-none"
              placeholder="Search any player by name…"
              value={query}
              onChange={e => {
                setQuery(e.target.value);
                setSelectedId(null);
                setShowDropdown(true);
              }}
              onFocus={() => { if (query.length >= 2) setShowDropdown(true); }}
            />
            {searching && <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-500 flex-shrink-0" />}
            {query && (
              <button onClick={() => { setQuery(""); setSelectedId(null); setShowDropdown(false); setResult(null); }}
                className="text-gray-600 hover:text-gray-300 flex-shrink-0">
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Dropdown */}
          {showDropdown && debouncedQ.length >= 2 && (
            <div ref={dropRef} className="absolute top-full left-0 right-0 mt-1 bg-gray-800 border border-gray-700 rounded-xl shadow-xl z-20 overflow-hidden max-h-64 overflow-y-auto">
              {players.length === 0 && !searching ? (
                <p className="text-xs text-gray-500 text-center py-4 italic">No players found.</p>
              ) : (
                players.map(p => (
                  <button
                    key={p.id}
                    onClick={() => handleSelect(p)}
                    className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-gray-700/60 transition-colors text-left"
                  >
                    <PosBadge pos={p.position} />
                    <span className="text-sm font-medium text-gray-200 flex-1 truncate">{p.full_name}</span>
                    <span className="text-xs text-gray-500 flex-shrink-0">
                      {p.age ? `Age ${p.age}` : ""}
                      {p.salary ? `  $${p.salary.toFixed(1)}M` : ""}
                    </span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>

        {/* Selected player summary */}
        {selectedId && !result && (
          <div className="flex items-center gap-3 px-3 py-2 bg-purple-500/10 border border-purple-500/20 rounded-xl">
            <CheckCircle2 className="h-4 w-4 text-purple-400 flex-shrink-0" />
            <p className="text-sm text-purple-200 flex-1"><span className="font-semibold">{selectedName}</span> selected</p>
          </div>
        )}

        <button
          onClick={handleFind}
          disabled={!selectedId || loading}
          className="flex items-center gap-2 px-5 py-2.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-colors text-sm"
        >
          {loading ? (
            <><Loader2 className="h-4 w-4 animate-spin" />Generating proposals…</>
          ) : (
            <><Sparkles className="h-4 w-4" />Generate Trade Proposals</>
          )}
        </button>

        {loading && (
          <p className="text-xs text-gray-500 italic">
            Analyzing standings, team needs, and trade value — this takes ~10 seconds…
          </p>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-3 text-sm text-red-400 bg-red-950/30 rounded-xl px-4 py-3 border border-red-800/30">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />{error}
        </div>
      )}

      {/* Results */}
      {result && pl && (
        <div className="space-y-5">
          {/* Player context card */}
          <div className="bg-gray-900 border border-gray-700/60 rounded-2xl px-5 py-4 flex flex-wrap items-start gap-4">
            <div className="flex items-center gap-3">
              <PosBadge pos={pl.position} />
              <div>
                <p className="font-bold text-gray-100">{pl.name}</p>
                <p className="text-xs text-gray-500">{pl.team} · Age {pl.age ?? "?"}</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-4 ml-auto text-right">
              <div>
                <p className="text-[10px] text-gray-500 uppercase tracking-widest">Contract</p>
                <p className="text-sm font-semibold text-amber-300">
                  {pl.salary ? `$${pl.salary.toFixed(1)}M` : "arb"}
                  {pl.contract_years ? ` / ${pl.contract_years}yr` : ""}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-gray-500 uppercase tracking-widest">WAR</p>
                <p className={`text-sm font-bold ${pl.war >= 3 ? "text-green-400" : pl.war >= 1 ? "text-blue-300" : "text-gray-400"}`}>
                  {pl.war >= 0 ? "+" : ""}{pl.war.toFixed(1)}
                </p>
              </div>
              <div>
                <p className="text-[10px] text-gray-500 uppercase tracking-widest">Stats</p>
                <p className="text-sm font-mono text-gray-300">{pl.stats || "—"}</p>
              </div>
            </div>
          </div>

          {/* Proposals header */}
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-purple-400" />
            <p className="text-sm font-semibold text-gray-200">{result.proposals.length} Trade Proposals</p>
            <p className="text-xs text-gray-500">— ranked by seller return value</p>
          </div>

          {/* Proposal grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {result.proposals.map((proposal, i) => (
              <ProposalCard key={i} proposal={proposal} sellerName={pl.team} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Team Advisor ───────────────────────────────────────────────────────────────

const DIRECTION_META: Record<string, { label: string; bg: string; text: string; border: string }> = {
  BUY:     { label: "BUY",     bg: "bg-green-500/15",  text: "text-green-300",  border: "border-green-500/30" },
  SELL:    { label: "SELL",    bg: "bg-red-500/15",    text: "text-red-300",    border: "border-red-500/30"   },
  HOLD:    { label: "HOLD",    bg: "bg-blue-500/15",   text: "text-blue-300",   border: "border-blue-500/30"  },
  REBUILD: { label: "REBUILD", bg: "bg-amber-500/15",  text: "text-amber-300",  border: "border-amber-500/30" },
  MIXED:   { label: "MIXED",   bg: "bg-purple-500/15", text: "text-purple-300", border: "border-purple-500/30"},
};

function TeamAdvisorPanel() {
  const [teamId, setTeamId]     = useState("");
  const [teamLabel, setTeamLabel] = useState("");
  const [result, setResult]     = useState<TeamAdvisorResponse | null>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);

  const handleAnalyze = async () => {
    if (!teamId) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await tradesApi.teamAdvisor({ team_id: teamId });
      setResult(res.data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to generate trade advice. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const dm = result ? (DIRECTION_META[result.direction] ?? DIRECTION_META.HOLD) : null;

  return (
    <div className="space-y-6">
      {/* Team selector card */}
      <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <BarChart2 className="h-4 w-4 text-purple-400" />
          <p className="text-sm font-semibold text-gray-200">Team Trade Advisor</p>
          <p className="text-xs text-gray-500 ml-1">— AI analyzes what your team should do</p>
        </div>

        <TeamSelector
          value={teamId}
          onChange={(id, team) => {
            setTeamId(id);
            setTeamLabel(`${team.city} ${team.name}`);
            setResult(null);
            setError(null);
          }}
          placeholder="Pick an MLB team to analyze…"
        />

        <button
          onClick={handleAnalyze}
          disabled={!teamId || loading}
          className="flex items-center gap-2 px-5 py-2.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-colors text-sm"
        >
          {loading ? (
            <><Loader2 className="h-4 w-4 animate-spin" />Analyzing {teamLabel}…</>
          ) : (
            <><BarChart2 className="h-4 w-4" />Analyze Trade Strategy</>
          )}
        </button>

        {loading && (
          <p className="text-xs text-gray-500 italic">
            Pulling roster, standings, and contracts — building your trade plan…
          </p>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-3 text-sm text-red-400 bg-red-950/30 rounded-xl px-4 py-3 border border-red-800/30">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />{error}
        </div>
      )}

      {/* Results */}
      {result && dm && (
        <div className="space-y-5">
          {/* Direction + summary banner */}
          <div className={`rounded-2xl border px-5 py-4 flex flex-wrap items-start gap-4 ${dm.bg} ${dm.border}`}>
            <div className="flex items-center gap-3">
              <span className={`text-3xl font-black tracking-tight ${dm.text}`}>{result.direction}</span>
              <div>
                <p className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Recommended Direction</p>
                <p className="text-xs font-semibold text-gray-300">{result.team_name}</p>
              </div>
            </div>
            {result.summary && (
              <p className={`text-sm leading-relaxed flex-1 min-w-[200px] italic ${dm.text}`}>
                "{result.summary}"
              </p>
            )}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Players to shop */}
            {result.sells.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <ShoppingCart className="h-4 w-4 text-red-400" />
                  <p className="text-sm font-semibold text-gray-200">Players to Shop</p>
                </div>
                {result.sells.map((sell, i) => (
                  <div key={i} className="bg-gray-900 border border-red-500/20 rounded-xl p-4 space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-500/15 text-red-300 border border-red-500/30">
                        TRADE
                      </span>
                      <p className="font-semibold text-gray-100 text-sm">{sell.player}</p>
                    </div>
                    <p className="text-xs text-gray-400 leading-relaxed">{sell.why}</p>
                    <div className="flex items-start gap-2 pt-1 border-t border-gray-800">
                      <PackageOpen className="h-3 w-3 text-green-400 mt-0.5 flex-shrink-0" />
                      <p className="text-xs text-green-300">{sell.returns}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Positions to target */}
            {result.targets.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Target className="h-4 w-4 text-blue-400" />
                  <p className="text-sm font-semibold text-gray-200">Positions to Target</p>
                </div>
                {result.targets.map((tgt, i) => (
                  <div key={i} className="bg-gray-900 border border-blue-500/20 rounded-xl p-4 space-y-2">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/15 text-blue-300 border border-blue-500/30">
                        ACQUIRE
                      </span>
                      <p className="font-semibold text-gray-100 text-sm">{tgt.need}</p>
                    </div>
                    <p className="text-xs text-gray-400 leading-relaxed">{tgt.why}</p>
                    <div className="flex items-start gap-2 pt-1 border-t border-gray-800">
                      <Users className="h-3 w-3 text-blue-400 mt-0.5 flex-shrink-0" />
                      <p className="text-xs text-blue-300">{tgt.example}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Full analysis */}
          {result.analysis && (
            <div className="bg-gray-900 border border-gray-700/50 rounded-2xl px-5 py-4">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="h-4 w-4 text-purple-400" />
                <p className="text-xs font-bold text-gray-400 uppercase tracking-widest">Strategic Analysis</p>
              </div>
              <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">{result.analysis}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

type PageTab = "build" | "finder" | "advisor";

export default function TradesPage() {
  const [pageTab, setPageTab] = useState<PageTab>("build");
  const [legs, setLegs] = useState<TradeLeg[]>([newLeg(), newLeg()]);
  const [result, setResult] = useState<TradeEvaluateResponse | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: teamsData, isLoading: teamsLoading } = useQuery({
    queryKey: ["teams", "MLB"],
    queryFn: () => teamsApi.list("MLB"),
  });

  const allTeams: Team[] = (teamsData?.data?.teams ?? []).sort((a, b) =>
    a.full_name.localeCompare(b.full_name)
  );

  const updateLeg = useCallback((legId: string, updated: TradeLeg) => {
    setLegs(prev => prev.map(l => l.legId === legId ? updated : l));
    setResult(null);
  }, []);

  const removeLeg = useCallback((legId: string) => {
    setLegs(prev => prev.filter(l => l.legId !== legId));
    setResult(null);
  }, []);

  const addLeg = () => {
    if (legs.length < 4) {
      setLegs(prev => [...prev, newLeg()]);
      setResult(null);
    }
  };

  // Validation
  const canEvaluate = useMemo(() => {
    const teamsWithPlayers = legs.filter(l => l.teamId && l.players.length > 0);
    return teamsWithPlayers.length >= 2 && legs.every(l => !l.teamId || l.players.length > 0);
  }, [legs]);

  const validationMsg = useMemo(() => {
    const configured = legs.filter(l => l.teamId);
    if (configured.length < 2) return "Select at least 2 teams.";
    const empty = legs.find(l => l.teamId && l.players.length === 0);
    if (empty) return `${empty.teamName} has no players in the trade.`;
    return null;
  }, [legs]);

  const handleEvaluate = async () => {
    if (!canEvaluate) return;
    setEvaluating(true);
    setError(null);
    setResult(null);
    try {
      const res = await tradesApi.evaluate({
        legs: legs
          .filter(l => l.teamId && l.players.length > 0)
          .map(l => ({
            team_id: l.teamId,
            team_name: l.teamName,
            team_abbr: l.teamAbbr,
            players_sending: l.players.map(p => ({
              player_id: p.id,
              player_name: p.name,
            })),
          })),
      });
      setResult(res.data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Failed to evaluate trade. Please try again.");
    } finally {
      setEvaluating(false);
    }
  };

  const resetTrade = () => {
    setLegs([newLeg(), newLeg()]);
    setResult(null);
    setError(null);
  };

  return (
    <div className="p-6 space-y-6 max-w-screen-xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ArrowLeftRight className="h-7 w-7 text-purple-400" />
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Trade Center</h1>
          <p className="text-sm text-gray-500">Build custom trades or let AI find realistic partners</p>
        </div>
      </div>

      {/* Page tab bar */}
      <div className="flex gap-1 bg-gray-900 p-1 rounded-xl w-fit border border-gray-800">
        <button
          onClick={() => setPageTab("build")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            pageTab === "build" ? "bg-gray-700 text-white" : "text-gray-500 hover:text-gray-300"
          }`}
        >
          <ArrowLeftRight className="h-3.5 w-3.5" />Build a Trade
        </button>
        <button
          onClick={() => setPageTab("finder")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            pageTab === "finder" ? "bg-gray-700 text-white" : "text-gray-500 hover:text-gray-300"
          }`}
        >
          <Sparkles className="h-3.5 w-3.5" />Trade Finder
        </button>
        <button
          onClick={() => setPageTab("advisor")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            pageTab === "advisor" ? "bg-gray-700 text-white" : "text-gray-500 hover:text-gray-300"
          }`}
        >
          <BarChart2 className="h-3.5 w-3.5" />Team Advisor
        </button>
      </div>

      {/* ── Build a Trade panel ── */}
      {pageTab === "build" && (
        <>
          <div className="flex items-center justify-end gap-2 flex-wrap">
            {legs.length < 4 && (
              <button
                onClick={addLeg}
                className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-750 border border-gray-700 rounded-xl text-sm text-gray-300 hover:text-gray-100 transition-colors"
              >
                <Plus className="h-4 w-4" />Add Team ({legs.length}/4)
              </button>
            )}
            <button
              onClick={resetTrade}
              className="flex items-center gap-2 px-4 py-2 bg-gray-800 border border-gray-700 rounded-xl text-sm text-gray-500 hover:text-red-400 transition-colors"
            >
              <X className="h-4 w-4" />Reset
            </button>
          </div>

          {teamsLoading ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 className="h-6 w-6 animate-spin text-purple-400" />
            </div>
          ) : (
            <div className={`grid gap-4 ${
              legs.length === 2 ? "grid-cols-1 md:grid-cols-2" :
              legs.length === 3 ? "grid-cols-1 md:grid-cols-3" :
              "grid-cols-1 md:grid-cols-2 xl:grid-cols-4"
            }`}>
              {legs.map(leg => (
                <TradeTeamCard
                  key={leg.legId}
                  leg={leg}
                  allLegs={legs}
                  allTeams={allTeams}
                  onUpdate={updated => updateLeg(leg.legId, updated)}
                  onRemove={() => removeLeg(leg.legId)}
                  canRemove={legs.length > 2}
                />
              ))}
            </div>
          )}

          <div className="flex items-center gap-4 flex-wrap">
            <button
              onClick={handleEvaluate}
              disabled={!canEvaluate || evaluating}
              className="flex items-center gap-2 px-6 py-3 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-colors"
            >
              {evaluating ? (
                <><Loader2 className="h-4 w-4 animate-spin" />Evaluating trade…</>
              ) : (
                <><Zap className="h-4 w-4" />Evaluate Trade</>
              )}
            </button>
            {validationMsg && !canEvaluate && (
              <p className="text-sm text-gray-500 italic">{validationMsg}</p>
            )}
            {evaluating && (
              <p className="text-sm text-gray-400">Analyzing player value, salary fit, and team context…</p>
            )}
          </div>

          {error && (
            <div className="flex items-center gap-3 text-sm text-red-400 bg-red-950/30 rounded-xl px-4 py-3 border border-red-800/30">
              <AlertCircle className="h-4 w-4 flex-shrink-0" />{error}
            </div>
          )}

          {result && <TradeResultPanel result={result} />}
        </>
      )}

      {/* ── Trade Finder panel ── */}
      {pageTab === "finder" && <TradeFinderPanel />}

      {/* ── Team Advisor panel ── */}
      {pageTab === "advisor" && <TeamAdvisorPanel />}
    </div>
  );
}
