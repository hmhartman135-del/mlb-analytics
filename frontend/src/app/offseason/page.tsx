"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  teamsApi,
  offseasonApi,
  type Team,
  type OffseasonPlanResponse,
  type OffseasonPlayer,
  type OffseasonFATarget,
  type OffseasonContextResponse,
  type SigningGradeResponse,
} from "@/lib/api";
import {
  Briefcase,
  ChevronDown,
  Loader2,
  DollarSign,
  TrendingUp,
  UserMinus,
  Target,
  AlertCircle,
  CheckCircle2,
  PenLine,
  X,
  ChevronRight,
} from "lucide-react";

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtM(v: number): string {
  return `$${v.toFixed(1)}M`;
}

function warColor(v: number): string {
  if (v >= 4) return "text-green-400";
  if (v >= 2) return "text-blue-400";
  if (v >= 0) return "text-gray-300";
  return "text-red-400";
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

// ── Shared UI components ───────────────────────────────────────────────────────

function PlanSection({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="space-y-4 text-sm leading-relaxed">
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("## "))
          return (
            <h3 key={i} className="text-base font-semibold text-blue-300 border-b border-gray-700 pb-1 mt-6 first:mt-0">
              {trimmed.slice(3)}
            </h3>
          );
        if (trimmed.startsWith("- "))
          return (
            <div key={i} className="flex gap-2 pl-2">
              <span className="text-blue-400 mt-0.5 flex-shrink-0">•</span>
              <span className="text-gray-300">{trimmed.slice(2)}</span>
            </div>
          );
        if (trimmed === "") return <div key={i} className="h-1" />;
        return <p key={i} className="text-gray-300">{trimmed}</p>;
      })}
    </div>
  );
}

function PosBadge({ pos }: { pos: string | null }) {
  const colors: Record<string, string> = {
    SP: "bg-blue-500/20 text-blue-300 border-blue-500/30",
    RP: "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
    C:  "bg-amber-500/20 text-amber-300 border-amber-500/30",
    DH: "bg-gray-500/20 text-gray-300 border-gray-500/30",
  };
  const hitter = "bg-emerald-500/20 text-emerald-300 border-emerald-500/30";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${colors[pos ?? ""] ?? hitter}`}>
      {pos ?? "?"}
    </span>
  );
}

function YrsBadge({ years }: { years: number | null }) {
  if (years == null) return <span className="text-gray-600 text-xs">—</span>;
  if (years === 0)
    return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold border bg-red-500/20 text-red-400 border-red-500/30">EXP</span>;
  if (years === 1) return <span className="text-amber-400 text-xs font-medium">{years}yr</span>;
  if (years <= 3) return <span className="text-yellow-300/80 text-xs font-medium">{years}yr</span>;
  return <span className="text-gray-300 text-xs">{years}yr</span>;
}

function StatCard({ label, value, sub, color = "text-gray-100" }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="bg-gray-800/60 rounded-xl border border-gray-700/50 p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function ExpiringTable({ players }: { players: OffseasonPlayer[] }) {
  if (players.length === 0)
    return <p className="text-sm text-gray-500 italic py-4">No expiring contracts — all players under multi-year deals.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] text-gray-500 uppercase tracking-wider border-b border-gray-700">
            <th className="text-left pb-2 font-medium">Player</th>
            <th className="text-center pb-2 font-medium w-10">Pos</th>
            <th className="text-center pb-2 font-medium w-10">Age</th>
            <th className="text-right pb-2 font-medium w-20">Salary</th>
            <th className="text-center pb-2 font-medium w-16">WAR</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {players.map((p) => (
            <tr key={p.player_id} className="hover:bg-gray-800/30 transition-colors">
              <td className="py-2 pr-3"><span className="text-gray-200 font-medium">{p.name}</span></td>
              <td className="py-2 text-center"><PosBadge pos={p.position} /></td>
              <td className="py-2 text-center text-gray-400">{p.age ?? "—"}</td>
              <td className="py-2 text-right text-gray-300 font-mono text-xs">{p.salary_m > 0 ? fmtM(p.salary_m) : "—"}</td>
              <td className={`py-2 text-center font-medium text-xs ${warColor(p.war)}`}>{p.war >= 0 ? "+" : ""}{p.war.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const FA_POSITIONS = ["SP", "RP", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "OF", "DH"];

function FATargetsPanel({ targets }: { targets: OffseasonFATarget[] }) {
  const [posFilter, setPosFilter] = useState<string>("ALL");
  const byPos = targets.reduce<Record<string, OffseasonFATarget[]>>((acc, fa) => {
    const pos = fa.position ?? "UNK";
    (acc[pos] ??= []).push(fa);
    return acc;
  }, {});
  const availablePositions = FA_POSITIONS.filter((p) => byPos[p]?.length);
  const displayed = posFilter === "ALL" ? targets : (byPos[posFilter] ?? []);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        <button onClick={() => setPosFilter("ALL")} className={`px-2 py-0.5 rounded text-xs font-medium border transition-colors ${posFilter === "ALL" ? "bg-blue-600/30 text-blue-300 border-blue-500/50" : "text-gray-400 border-gray-700 hover:border-gray-500 hover:text-gray-200"}`}>
          All ({targets.length})
        </button>
        {availablePositions.map((pos) => (
          <button key={pos} onClick={() => setPosFilter(pos)} className={`px-2 py-0.5 rounded text-xs font-medium border transition-colors ${posFilter === pos ? "bg-blue-600/30 text-blue-300 border-blue-500/50" : "text-gray-400 border-gray-700 hover:border-gray-500 hover:text-gray-200"}`}>
            {pos} ({byPos[pos]?.length ?? 0})
          </button>
        ))}
      </div>
      <div className="overflow-y-auto max-h-64 space-y-1 pr-1">
        {displayed.map((fa) => (
          <div key={fa.id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-800/40 hover:bg-gray-800/70 transition-colors">
            <PosBadge pos={fa.position} />
            <span className="text-gray-200 text-sm font-medium flex-1 min-w-0 truncate">{fa.full_name}</span>
            {fa.age != null && <span className="text-gray-500 text-xs flex-shrink-0">Age {fa.age}</span>}
            {fa.former_team && <span className="text-gray-500 text-xs flex-shrink-0">{fa.former_team}</span>}
          </div>
        ))}
        {displayed.length === 0 && <p className="text-gray-500 text-xs italic py-2">No players at this position.</p>}
      </div>
    </div>
  );
}

// ── FA Simulator ───────────────────────────────────────────────────────────────

interface Signing {
  id: string;
  player_name: string;
  position: string | null;
  age: number | null;
  former_team: string | null;
  contract_years: number;
  contract_aav_m: number;
  grade: string;
  headline: string;
  analysis: string;
  expanded: boolean;
}

function GradeBadge({ grade }: { grade: string }) {
  return (
    <span className={`inline-flex items-center justify-center w-9 h-9 rounded-xl text-sm font-bold border ${gradeBg(grade)}`}>
      {grade}
    </span>
  );
}

function FASimulatorPanel({ teams }: { teams: Team[] }) {
  const [selectedTeamId, setSelectedTeamId] = useState("");
  const [context, setContext] = useState<OffseasonContextResponse | null>(null);
  const [posFilter, setPosFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [signings, setSignings] = useState<Signing[]>([]);
  const [signingPlayer, setSigningPlayer] = useState<OffseasonFATarget | null>(null);
  const [contractYears, setContractYears] = useState(2);
  const [contractAav, setContractAav] = useState("");
  const [gradingId, setGradingId] = useState<string | null>(null);

  const contextMutation = useMutation({
    mutationFn: (teamId: string) => offseasonApi.getContext(teamId),
    onSuccess: (res) => {
      setContext(res.data);
      setSignings([]);
    },
  });

  const gradeMutation = useMutation({
    mutationFn: (payload: Parameters<typeof offseasonApi.gradeMove>[0]) =>
      offseasonApi.gradeMove(payload),
  });

  const signedIds = useMemo(() => new Set(signings.map(s => s.id)), [signings]);

  const committedM = useMemo(
    () => signings.reduce((sum, s) => sum + s.contract_aav_m, 0),
    [signings],
  );

  const budgetRemainingM = (context?.context.estimated_budget_m ?? 0) - committedM;

  const rosterNeeds = useMemo(() => {
    const ALL_POS = ["SP", "SP", "SP", "SP", "SP", "RP", "RP", "RP", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"];
    const expiring = new Set((context?.expiring_contracts ?? []).map(p => p.position).filter(Boolean) as string[]);
    return [...expiring];
  }, [context]);

  const displayedFAs = useMemo(() => {
    if (!context) return [];
    return context.fa_pool
      .filter(fa => !signedIds.has(fa.id))
      .filter(fa => posFilter === "ALL" || fa.position === posFilter)
      .filter(fa => !search || fa.full_name.toLowerCase().includes(search.toLowerCase()));
  }, [context, signedIds, posFilter, search]);

  const availableByPos = useMemo(() => {
    if (!context) return {};
    return context.fa_pool.reduce<Record<string, number>>((acc, fa) => {
      const pos = fa.position ?? "UNK";
      acc[pos] = (acc[pos] ?? 0) + 1;
      return acc;
    }, {});
  }, [context]);

  const handleLoadTeam = () => {
    if (!selectedTeamId) return;
    contextMutation.mutate(selectedTeamId);
  };

  const handleSignClick = (fa: OffseasonFATarget) => {
    setSigningPlayer(fa);
    setContractYears(2);
    setContractAav("");
  };

  const handleGradeMove = async () => {
    if (!signingPlayer || !contractAav || !context) return;
    const aavNum = parseFloat(contractAav.replace(/[$,M]/g, ""));
    if (isNaN(aavNum) || aavNum <= 0) return;

    setGradingId(signingPlayer.id);
    try {
      const res = await gradeMutation.mutateAsync({
        team_name: context.team.full_name,
        roster_needs: rosterNeeds,
        player_name: signingPlayer.full_name,
        position: signingPlayer.position,
        age: signingPlayer.age,
        former_team: signingPlayer.former_team,
        contract_years: contractYears,
        contract_aav_m: aavNum,
        budget_remaining_m: budgetRemainingM,
        existing_signings: signings.map(s => ({
          player_name: s.player_name,
          position: s.position,
          years: s.contract_years,
          aav_m: s.contract_aav_m,
          grade: s.grade,
        })),
      });

      const newSigning: Signing = {
        id: signingPlayer.id,
        player_name: signingPlayer.full_name,
        position: signingPlayer.position,
        age: signingPlayer.age,
        former_team: signingPlayer.former_team,
        contract_years: contractYears,
        contract_aav_m: aavNum,
        grade: res.data.grade,
        headline: res.data.headline,
        analysis: res.data.analysis,
        expanded: false,
      };
      setSignings(prev => [newSigning, ...prev]);
      setSigningPlayer(null);
      setContractAav("");
    } finally {
      setGradingId(null);
    }
  };

  const toggleExpand = (id: string) => {
    setSignings(prev => prev.map(s => s.id === id ? { ...s, expanded: !s.expanded } : s));
  };

  const removeSigning = (id: string) => {
    setSignings(prev => prev.filter(s => s.id !== id));
  };

  // ── Team selector (shown always) ─────────────────────────────────────────
  return (
    <div className="space-y-5">
      {/* Team loader */}
      <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
        <div className="flex flex-col sm:flex-row gap-4 items-end">
          <div className="flex-1 min-w-0">
            <label className="block text-xs text-gray-500 uppercase tracking-wider mb-2">Choose your team</label>
            <div className="relative">
              <select
                value={selectedTeamId}
                onChange={e => setSelectedTeamId(e.target.value)}
                className="w-full appearance-none bg-gray-800 border border-gray-600 rounded-xl px-4 py-2.5 pr-10 text-gray-200 text-sm focus:outline-none focus:border-blue-500 cursor-pointer"
              >
                <option value="">— Choose a team —</option>
                {teams.map(t => (
                  <option key={t.id} value={t.id}>{t.full_name}{t.division ? ` (${t.division})` : ""}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>
          <button
            onClick={handleLoadTeam}
            disabled={!selectedTeamId || contextMutation.isPending}
            className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition-colors whitespace-nowrap"
          >
            {contextMutation.isPending ? <><Loader2 className="h-4 w-4 animate-spin" />Loading…</> : <><PenLine className="h-4 w-4" />Load Team</>}
          </button>
        </div>
        {contextMutation.isError && (
          <div className="mt-3 flex items-center gap-2 text-sm text-red-400 bg-red-950/30 rounded-xl px-4 py-3 border border-red-800/30">
            <AlertCircle className="h-4 w-4" />No roster data found for this team.
          </div>
        )}
      </div>

      {context && (
        <>
          {/* Budget bar */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatCard label="Estimated Budget" value={fmtM(context.context.estimated_budget_m)} sub={`vs $${context.context.cbt_threshold_m.toFixed(0)}M CBT`} color="text-green-400" />
            <StatCard label="Committed This OS" value={fmtM(committedM)} sub={`${signings.length} signing${signings.length !== 1 ? "s" : ""}`} color={committedM > context.context.estimated_budget_m ? "text-red-400" : "text-gray-100"} />
            <StatCard label="Remaining Budget" value={fmtM(Math.max(0, budgetRemainingM))} sub={budgetRemainingM < 0 ? "OVER BUDGET" : "available"} color={budgetRemainingM < 0 ? "text-red-400" : "text-green-400"} />
            <StatCard label="Expiring Contracts" value={String(context.context.expiring_count)} sub="players entering FA" color={context.context.expiring_count >= 5 ? "text-amber-400" : "text-gray-100"} />
          </div>

          {/* Expiring players + FA pool + Signings log */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">

            {/* FA Pool (left 3/5) */}
            <div className="lg:col-span-3 bg-gray-900 border border-gray-700/60 rounded-2xl flex flex-col overflow-hidden" style={{ minHeight: 500 }}>
              {/* Header + filters */}
              <div className="shrink-0 px-5 pt-5 pb-3 border-b border-gray-800">
                <div className="flex items-center gap-2 mb-3">
                  <TrendingUp className="h-4 w-4 text-blue-400" />
                  <h3 className="text-sm font-semibold text-gray-200">2027 Free Agent Pool</h3>
                  <span className="ml-auto text-xs text-gray-500">{displayedFAs.length} available</span>
                </div>
                {/* Search */}
                <input
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm mb-2 focus:outline-none focus:border-blue-500 transition-colors"
                  placeholder="Search players…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
                {/* Position pills */}
                <div className="flex flex-wrap gap-1">
                  <button onClick={() => setPosFilter("ALL")} className={`px-2 py-0.5 rounded text-xs font-medium border transition-colors ${posFilter === "ALL" ? "bg-blue-600/30 text-blue-300 border-blue-500/50" : "text-gray-400 border-gray-700 hover:border-gray-500"}`}>All</button>
                  {FA_POSITIONS.filter(p => availableByPos[p]).map(pos => (
                    <button key={pos} onClick={() => setPosFilter(pos)} className={`px-2 py-0.5 rounded text-xs font-medium border transition-colors ${posFilter === pos ? "bg-blue-600/30 text-blue-300 border-blue-500/50" : "text-gray-400 border-gray-700 hover:border-gray-500"}`}>
                      {pos}
                    </button>
                  ))}
                </div>
              </div>

              {/* FA rows */}
              <div className="flex-1 overflow-y-auto divide-y divide-gray-800/60">
                {displayedFAs.length === 0 ? (
                  <div className="flex items-center justify-center h-24 text-gray-600 text-sm">No players match filters.</div>
                ) : (
                  displayedFAs.map(fa => (
                    <div key={fa.id}>
                      <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-800/30 transition-colors">
                        <PosBadge pos={fa.position} />
                        <span className="text-gray-200 text-sm font-medium flex-1 min-w-0 truncate">{fa.full_name}</span>
                        {fa.age != null && <span className="text-gray-500 text-xs">Age {fa.age}</span>}
                        {fa.former_team && <span className="text-gray-500 text-xs hidden sm:inline">{fa.former_team}</span>}
                        {signingPlayer?.id === fa.id ? (
                          <button onClick={() => setSigningPlayer(null)} className="text-gray-500 hover:text-gray-300 text-xs transition-colors ml-2">Cancel</button>
                        ) : (
                          <button
                            onClick={() => handleSignClick(fa)}
                            className="flex items-center gap-1 px-2.5 py-1 bg-blue-600/20 hover:bg-blue-600/40 border border-blue-500/30 rounded-lg text-xs text-blue-300 font-medium transition-colors ml-2"
                          >
                            <PenLine className="h-3 w-3" />Sign
                          </button>
                        )}
                      </div>

                      {/* Inline contract form */}
                      {signingPlayer?.id === fa.id && (
                        <div className="mx-4 mb-3 px-4 py-3 bg-blue-950/30 border border-blue-800/40 rounded-xl space-y-3">
                          <p className="text-xs text-blue-300 font-semibold">Sign {fa.full_name}</p>
                          <div className="flex items-center gap-3">
                            <div className="flex-1">
                              <label className="text-[10px] text-gray-500 uppercase mb-1 block">Years</label>
                              <select
                                value={contractYears}
                                onChange={e => setContractYears(Number(e.target.value))}
                                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-blue-500"
                              >
                                {[1,2,3,4,5,6,7,8].map(y => <option key={y} value={y}>{y} year{y !== 1 ? "s" : ""}</option>)}
                              </select>
                            </div>
                            <div className="flex-1">
                              <label className="text-[10px] text-gray-500 uppercase mb-1 block">AAV ($M/yr)</label>
                              <input
                                type="text"
                                placeholder="e.g. 18.5"
                                value={contractAav}
                                onChange={e => setContractAav(e.target.value)}
                                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-blue-500"
                              />
                            </div>
                          </div>
                          {contractYears > 0 && contractAav && (
                            <p className="text-xs text-gray-400">
                              Total: ${(contractYears * parseFloat(contractAav.replace(/[$,M]/g, "") || "0")).toFixed(1)}M
                              · {contractYears}yr / ${parseFloat(contractAav.replace(/[$,M]/g, "") || "0").toFixed(1)}M AAV
                            </p>
                          )}
                          <button
                            onClick={handleGradeMove}
                            disabled={!contractAav || gradingId === fa.id}
                            className="w-full flex items-center justify-center gap-2 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition-colors"
                          >
                            {gradingId === fa.id
                              ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Grading move…</>
                              : <><Target className="h-3.5 w-3.5" />Grade This Move</>}
                          </button>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Signings log (right 2/5) */}
            <div className="lg:col-span-2 bg-gray-900 border border-gray-700/60 rounded-2xl flex flex-col overflow-hidden" style={{ minHeight: 500 }}>
              <div className="shrink-0 px-5 pt-5 pb-3 border-b border-gray-800">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-green-400" />
                  <h3 className="text-sm font-semibold text-gray-200">My Signings</h3>
                  <span className="ml-auto text-xs text-gray-500">{signings.length} move{signings.length !== 1 ? "s" : ""}</span>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto">
                {signings.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-40 gap-2 text-gray-600 text-sm">
                    <PenLine className="h-6 w-6" />
                    <p>Sign a free agent to see grades</p>
                  </div>
                ) : (
                  <div className="divide-y divide-gray-800/60">
                    {signings.map(s => (
                      <div key={s.id} className="px-4 py-3">
                        <div className="flex items-start gap-3">
                          <GradeBadge grade={s.grade} />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-0.5">
                              <span className="text-sm font-semibold text-gray-100 truncate">{s.player_name}</span>
                              <PosBadge pos={s.position} />
                            </div>
                            <p className="text-xs text-gray-500 mb-1">
                              {s.contract_years}yr / ${s.contract_aav_m.toFixed(1)}M AAV · ${(s.contract_years * s.contract_aav_m).toFixed(1)}M total
                            </p>
                            <p className={`text-xs font-medium italic ${gradeColor(s.grade)}`}>{s.headline}</p>
                            {s.expanded && (
                              <p className="text-xs text-gray-400 mt-2 leading-relaxed">{s.analysis}</p>
                            )}
                          </div>
                          <div className="flex flex-col items-end gap-1 flex-shrink-0">
                            <button onClick={() => removeSigning(s.id)} className="text-gray-700 hover:text-red-400 transition-colors">
                              <X className="h-3.5 w-3.5" />
                            </button>
                            <button onClick={() => toggleExpand(s.id)} className="text-gray-600 hover:text-gray-300 transition-colors">
                              <ChevronRight className={`h-3.5 w-3.5 transition-transform ${s.expanded ? "rotate-90" : ""}`} />
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Expiring contracts reference */}
          <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <UserMinus className="h-4 w-4 text-red-400" />
              <h3 className="text-sm font-semibold text-gray-200">Expiring After 2026</h3>
              <span className="ml-auto text-xs text-gray-500">{context.expiring_contracts.length} player{context.expiring_contracts.length !== 1 ? "s" : ""}</span>
            </div>
            <ExpiringTable players={context.expiring_contracts} />
          </div>
        </>
      )}
    </div>
  );
}

// ── AI Planner panel ───────────────────────────────────────────────────────────

function AIPlannerPanel({ teams }: { teams: Team[] }) {
  const [selectedTeamId, setSelectedTeamId] = useState<string>("");
  const [plan, setPlan] = useState<OffseasonPlanResponse | null>(null);

  const mutation = useMutation({
    mutationFn: (teamId: string) => offseasonApi.generatePlan(teamId),
    onSuccess: (res) => setPlan(res.data),
  });

  const handleGenerate = () => {
    if (!selectedTeamId) return;
    setPlan(null);
    mutation.mutate(selectedTeamId);
  };

  return (
    <div className="space-y-6">
      {/* Team selector + Generate */}
      <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
        <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
          <div className="flex-1 min-w-0">
            <label className="block text-xs text-gray-500 uppercase tracking-wider mb-2">Select a Team</label>
            <div className="relative">
              <select
                value={selectedTeamId}
                onChange={e => setSelectedTeamId(e.target.value)}
                className="w-full appearance-none bg-gray-800 border border-gray-600 rounded-xl px-4 py-2.5 pr-10 text-gray-200 text-sm focus:outline-none focus:border-blue-500 cursor-pointer"
              >
                <option value="">— Choose a team —</option>
                {teams.map(t => (
                  <option key={t.id} value={t.id}>{t.full_name}{t.division ? ` (${t.division})` : ""}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>
          <button
            onClick={handleGenerate}
            disabled={!selectedTeamId || mutation.isPending}
            className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition-colors whitespace-nowrap"
          >
            {mutation.isPending ? <><Loader2 className="h-4 w-4 animate-spin" />Generating…</> : <><Target className="h-4 w-4" />Generate Plan</>}
          </button>
        </div>
        {mutation.isPending && (
          <div className="mt-4 flex items-center gap-3 text-sm text-gray-400 bg-blue-950/30 rounded-xl px-4 py-3 border border-blue-800/30">
            <Loader2 className="h-4 w-4 animate-spin text-blue-400 flex-shrink-0" />
            Analyzing roster, payroll, and free agent class — Claude is writing the memo. This takes about 15–30 seconds…
          </div>
        )}
        {mutation.isError && (
          <div className="mt-4 flex items-center gap-3 text-sm text-red-400 bg-red-950/30 rounded-xl px-4 py-3 border border-red-800/30">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            Failed to generate plan. The team may not have roster or stats data loaded.
          </div>
        )}
      </div>

      {plan && (
        <>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-gray-100">{plan.team.full_name}</h2>
            {plan.team.division && (
              <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full border border-gray-700">{plan.team.division}</span>
            )}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatCard label="2026 Payroll" value={fmtM(plan.context.payroll_2026_m)} sub="current season total" />
            <StatCard label="2027 Committed" value={fmtM(plan.context.committed_2027_m)} sub="under contract for '27" color={plan.context.committed_2027_m > plan.context.cbt_threshold_m ? "text-red-400" : "text-gray-100"} />
            <StatCard label="Estimated Budget" value={fmtM(plan.context.estimated_budget_m)} sub={`vs $${plan.context.cbt_threshold_m.toFixed(0)}M CBT`} color="text-green-400" />
            <StatCard label="Expiring Contracts" value={String(plan.context.expiring_count)} sub="players entering FA" color={plan.context.expiring_count >= 5 ? "text-amber-400" : "text-gray-100"} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <UserMinus className="h-4 w-4 text-red-400" />
                <h3 className="text-sm font-semibold text-gray-200">Expiring After 2026</h3>
                <span className="ml-auto text-xs text-gray-500">{plan.expiring_contracts.length} player{plan.expiring_contracts.length !== 1 ? "s" : ""}</span>
              </div>
              <ExpiringTable players={plan.expiring_contracts} />
            </div>
            <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="h-4 w-4 text-blue-400" />
                <h3 className="text-sm font-semibold text-gray-200">2027 Free Agent Class</h3>
                <span className="ml-auto text-xs text-gray-500">{plan.top_fa_targets.length} players</span>
              </div>
              <FATargetsPanel targets={plan.top_fa_targets} />
            </div>
          </div>
          <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-6">
            <div className="flex items-center gap-2 mb-5">
              <DollarSign className="h-4 w-4 text-blue-400" />
              <h3 className="text-sm font-semibold text-gray-200">Offseason Strategy Memo</h3>
              <span className="ml-auto text-xs text-gray-600 italic">Generated by Claude</span>
            </div>
            <PlanSection text={plan.plan} />
          </div>
        </>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

type OffseasonTab = "planner" | "simulator";

export default function OffseasonPage() {
  const [activeTab, setActiveTab] = useState<OffseasonTab>("planner");

  const { data: teamsData, isLoading: teamsLoading } = useQuery({
    queryKey: ["teams", "MLB"],
    queryFn: () => teamsApi.list("MLB"),
  });

  const teams: Team[] = (teamsData?.data?.teams ?? []).sort((a, b) =>
    a.full_name.localeCompare(b.full_name)
  );

  const tabs: Array<{ id: OffseasonTab; label: string; icon: React.ReactNode }> = [
    { id: "planner",   label: "AI Planner",       icon: <Target className="h-4 w-4" /> },
    { id: "simulator", label: "FA Simulator",     icon: <PenLine className="h-4 w-4" /> },
  ];

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Briefcase className="h-7 w-7 text-blue-400" />
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Offseason Planner</h1>
          <p className="text-sm text-gray-500">AI-powered 2026–2027 offseason tools</p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 p-1 bg-gray-800/60 rounded-xl border border-gray-700/50 w-fit">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? "bg-blue-600/30 text-blue-300 border border-blue-500/40"
                : "text-gray-400 hover:text-gray-200"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {teamsLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-blue-400" />
        </div>
      ) : activeTab === "planner" ? (
        <AIPlannerPanel teams={teams} />
      ) : (
        <FASimulatorPanel teams={teams} />
      )}
    </div>
  );
}
