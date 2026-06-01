"use client";
import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  rosterApi, playersApi,
  type FinancesData, type ContractEntry, type OrgRoster, type OrgGroup,
  type OrgPlayer, type RosterBreakdown, type RosterPlayer, LEVEL_FULL,
} from "@/lib/api";
import { TeamSelector } from "@/components/ui/TeamSelector";
import { SyncBar } from "@/components/ui/SyncBar";
import { useQueryClient } from "@tanstack/react-query";
import { Users, DollarSign, TrendingUp, AlertTriangle, RefreshCw, X, Building2, ShieldCheck, Shield } from "lucide-react";

// ── Constants ─────────────────────────────────────────────────────────────────
const LEVEL_COLORS: Record<string, string> = {
  MLB:    "bg-blue-500/20 text-blue-300 border-blue-500/30",
  AAA:    "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  AA:     "bg-teal-500/20 text-teal-300 border-teal-500/30",
  "A+":   "bg-amber-500/20 text-amber-300 border-amber-500/30",
  A:      "bg-orange-500/20 text-orange-300 border-orange-500/30",
  Rookie: "bg-violet-500/20 text-violet-300 border-violet-500/30",
};

const LEVEL_BORDER: Record<string, string> = {
  MLB:    "border-l-blue-500",
  AAA:    "border-l-emerald-500",
  AA:     "border-l-teal-400",
  "A+":   "border-l-amber-400",
  A:      "border-l-orange-400",
  Rookie: "border-l-violet-400",
};

const LEVEL_META: Record<string, { full: string; label: string }> = {
  MLB:    { full: "Major League Roster",   label: "MLB" },
  AAA:    { full: "Triple-A Affiliate",    label: "AAA" },
  AA:     { full: "Double-A Affiliate",    label: "AA" },
  "A+":   { full: "High-A Affiliate",      label: "A+" },
  A:      { full: "Single-A Affiliate",    label: "A" },
  Rookie: { full: "Rookie Affiliate",      label: "Rookie" },
};

type Tab = "26man" | "40man" | "AAA" | "AA" | "A+" | "A" | "Rookie" | "finances" | "free-agents";

const MINOR_TABS: { id: Tab; label: string; level: string }[] = [
  { id: "AAA",    label: "Triple-A",  level: "AAA" },
  { id: "AA",     label: "Double-A",  level: "AA"  },
  { id: "A+",     label: "High-A",    level: "A+"  },
  { id: "A",      label: "Single-A",  level: "A"   },
  { id: "Rookie", label: "Rookie",    level: "Rookie" },
];
const MINOR_LEVEL_IDS = new Set(MINOR_TABS.map(t => t.id));

function fmt(v: number | null | undefined, d = 3) {
  return v == null ? "—" : v.toFixed(d);
}
function fmtPct(v: number | null | undefined) {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}
function fmtM(v: number | null | undefined) {
  return v == null ? "—" : `$${v.toFixed(1)}M`;
}

// ── Shared small components ───────────────────────────────────────────────────

function LevelBadge({ level, showFull = false }: { level: string; showFull?: boolean }) {
  const full = LEVEL_FULL[level] ?? level;
  return showFull ? (
    <div className="flex flex-col gap-0.5">
      <span className={`px-2 py-0.5 rounded text-[11px] font-bold border w-fit ${LEVEL_COLORS[level] ?? "bg-gray-700 text-gray-400 border-gray-600"}`}>
        {level}
      </span>
      <span className="text-[10px] text-gray-500 pl-0.5">{full}</span>
    </div>
  ) : (
    <span title={full} className={`px-2 py-0.5 rounded text-xs font-bold border cursor-default ${LEVEL_COLORS[level] ?? "bg-gray-700 text-gray-400 border-gray-600"}`}>
      {level}
    </span>
  );
}

function RosterStatusBadge({ label, status }: { label: string; status: string }) {
  if (status === "A") {
    return <span className="px-2 py-0.5 rounded text-[11px] font-bold border bg-emerald-900/30 text-emerald-400 border-emerald-700/40">Active</span>;
  }
  if (status === "RM") {
    return <span className="px-2 py-0.5 rounded text-[11px] font-bold border bg-purple-900/30 text-purple-400 border-purple-700/40">Reassigned</span>;
  }
  // IL codes: D10, D15, D60, etc.
  return <span className="px-2 py-0.5 rounded text-[11px] font-bold border bg-red-900/30 text-red-400 border-red-700/40">{label}</span>;
}

// ── 26-Man Roster Tab ─────────────────────────────────────────────────────────


function RosterTable({ players, title }: { players: RosterPlayer[]; title: string }) {
  if (!players.length) return null;
  const hitters  = players.filter(p => p.position !== "SP" && p.position !== "RP");
  const pitchers = players.filter(p => p.position === "SP" || p.position === "RP");

  return (
    <div className="mb-6">
      <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mb-2">{title}</p>
      {hitters.length > 0 && (
        <div className="overflow-x-auto mb-4">
          <p className="text-[10px] text-gray-600 mb-1 pl-1">Position Players</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
                <th className="pb-2 pr-4 font-medium">Name</th>
                <th className="pb-2 pr-3 font-medium">Pos</th>
                <th className="pb-2 pr-3 font-medium">Age</th>
                <th className="pb-2 pr-3 font-medium">B/T</th>
                <th className="pb-2 pr-3 font-medium text-right">Salary</th>
                <th className="pb-2 pr-3 font-medium text-right">Svc</th>
                <th className="pb-2 font-medium text-right">Overall</th>
              </tr>
            </thead>
            <tbody>
              {hitters.map(p => (
                <tr key={p.id} className="border-b border-gray-800/30 hover:bg-gray-800/20 transition-colors">
                  <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.full_name}</td>
                  <td className="py-2 pr-3">
                    <span className="badge-grade bg-gray-700/60 text-gray-300 text-[11px]">{p.position}</span>
                  </td>
                  <td className="py-2 pr-3 text-gray-400 text-xs">{p.age ?? "—"}</td>
                  <td className="py-2 pr-3 text-gray-400 font-mono text-xs">{p.bats}/{p.throws}</td>
                  <td className="py-2 pr-3 text-right font-mono text-xs text-amber-300/80">
                    {p.salary ? fmtM(p.salary) : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right text-gray-400 text-xs">
                    {p.service_time != null ? p.service_time.toFixed(1) : "—"}
                  </td>
                  <td className="py-2 text-right">
                    {p.scouting?.overall
                      ? <span className={`badge-grade text-xs font-bold ${gradeColor(p.scouting.overall)}`}>{p.scouting.overall}</span>
                      : <span className="text-gray-600 text-xs">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pitchers.length > 0 && (
        <div className="overflow-x-auto">
          <p className="text-[10px] text-gray-600 mb-1 pl-1">Pitchers</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
                <th className="pb-2 pr-4 font-medium">Name</th>
                <th className="pb-2 pr-3 font-medium">Pos</th>
                <th className="pb-2 pr-3 font-medium">Age</th>
                <th className="pb-2 pr-3 font-medium">B/T</th>
                <th className="pb-2 pr-3 font-medium text-right">Salary</th>
                <th className="pb-2 pr-3 font-medium text-right">Svc</th>
                <th className="pb-2 font-medium text-right">Overall</th>
              </tr>
            </thead>
            <tbody>
              {pitchers.map(p => (
                <tr key={p.id} className="border-b border-gray-800/30 hover:bg-gray-800/20 transition-colors">
                  <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.full_name}</td>
                  <td className="py-2 pr-3">
                    <span className={`badge-grade text-[11px] ${p.position === "SP" ? "bg-indigo-500/20 text-indigo-300" : "bg-sky-500/20 text-sky-300"}`}>
                      {p.position}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-gray-400 text-xs">{p.age ?? "—"}</td>
                  <td className="py-2 pr-3 text-gray-400 font-mono text-xs">{p.bats}/{p.throws}</td>
                  <td className="py-2 pr-3 text-right font-mono text-xs text-amber-300/80">
                    {p.salary ? fmtM(p.salary) : "—"}
                  </td>
                  <td className="py-2 pr-3 text-right text-gray-400 text-xs">
                    {p.service_time != null ? p.service_time.toFixed(1) : "—"}
                  </td>
                  <td className="py-2 text-right">
                    {p.scouting?.overall
                      ? <span className={`badge-grade text-xs font-bold ${gradeColor(p.scouting.overall)}`}>{p.scouting.overall}</span>
                      : <span className="text-gray-600 text-xs">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function TwentySixTab({ data }: { data: RosterBreakdown }) {
  const { twenty_six, twenty_six_count } = data;
  if (!twenty_six_count) {
    return (
      <div className="text-center py-12 text-gray-500">
        <ShieldCheck className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="font-medium">26-Man roster not yet loaded</p>
        <p className="text-sm mt-1 text-gray-600">Re-run start.py and type <code>reload</code> to refresh roster data</p>
      </div>
    );
  }
  return (
    <div className="stat-card">
      <div className="flex items-center gap-2 mb-5">
        <ShieldCheck className="h-4 w-4 text-blue-400" />
        <h3 className="font-semibold text-sm">26-Man Active Roster</h3>
        <span className="text-gray-500 text-xs ml-auto">{twenty_six_count} players</span>
      </div>
      <RosterTable players={twenty_six} title="" />
    </div>
  );
}

// ── 40-Man Roster Tab ─────────────────────────────────────────────────────────

function FortyManTab({ data }: { data: RosterBreakdown }) {
  const { twenty_six, forty_extra, twenty_six_count, forty_man_count } = data;

  if (!forty_man_count) {
    return (
      <div className="text-center py-12 text-gray-500">
        <Shield className="h-10 w-10 mx-auto mb-3 opacity-30" />
        <p className="font-medium">40-Man roster not yet loaded</p>
        <p className="text-sm mt-1 text-gray-600">Re-run start.py and type <code>reload</code> to refresh roster data</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* 26-Man section */}
      <div className="stat-card">
        <div className="flex items-center gap-2 mb-4">
          <span className="px-2 py-0.5 rounded text-xs font-bold bg-blue-500/20 text-blue-300 border border-blue-500/30">Active</span>
          <h3 className="font-semibold text-sm">26-Man Roster</h3>
          <span className="text-gray-500 text-xs ml-auto">{twenty_six_count} players</span>
        </div>
        <RosterTable players={twenty_six} title="" />
      </div>

      {/* IL / Reassigned section */}
      {forty_extra.length > 0 && (
        <div className="stat-card">
          <div className="flex items-center gap-2 mb-4">
            <span className="px-2 py-0.5 rounded text-xs font-bold bg-red-500/20 text-red-300 border border-red-500/30">40-Man Only</span>
            <h3 className="font-semibold text-sm">Injured List &amp; Reassigned</h3>
            <span className="text-gray-500 text-xs ml-auto">{forty_extra.length} players</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
                  <th className="pb-2 pr-4 font-medium">Name</th>
                  <th className="pb-2 pr-3 font-medium">Status</th>
                  <th className="pb-2 pr-3 font-medium">Pos</th>
                  <th className="pb-2 pr-3 font-medium">Age</th>
                  <th className="pb-2 pr-3 font-medium">B/T</th>
                  <th className="pb-2 font-medium text-right">Salary</th>
                </tr>
              </thead>
              <tbody>
                {forty_extra.map(p => (
                  <tr key={p.id} className="border-b border-gray-800/30 hover:bg-gray-800/20 transition-colors">
                    <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.full_name}</td>
                    <td className="py-2 pr-3">
                      <span className={`badge-grade text-[11px] ${
                        p.roster_label?.includes("Minors")
                          ? "bg-amber-500/20 text-amber-300"
                          : "bg-red-500/20 text-red-300"
                      }`}>
                        {p.roster_label}
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      <span className="badge-grade bg-gray-700/60 text-gray-300 text-[11px]">{p.position ?? "—"}</span>
                    </td>
                    <td className="py-2 pr-3 text-gray-400 text-xs">{p.age ?? "—"}</td>
                    <td className="py-2 pr-3 text-gray-400 font-mono text-xs">{p.bats}/{p.throws}</td>
                    <td className="py-2 text-right font-mono text-xs text-amber-300/80">
                      {p.salary ? fmtM(p.salary) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <p className="text-xs text-gray-600 text-right">40-Man total: {forty_man_count} players</p>
    </div>
  );
}

// ── Per-level Minor League Tab ────────────────────────────────────────────────

function LevelTab({ level, data }: { level: string; data: OrgRoster }) {
  const group   = data.groups.find(g => g.level === level);
  const aff     = (data.affiliate_map ?? {})[level];
  const meta    = LEVEL_META[level] ?? { full: level, label: level };
  const border  = LEVEL_BORDER[level] ?? "border-l-gray-500";

  // Placeholder when minor league data not yet loaded
  if (!group) {
    const teamName = aff?.team_name ?? null;
    const city     = aff?.city ?? "";
    return (
      <div className={`stat-card border-l-4 ${border} opacity-70`}>
        <div className="flex items-center gap-3 mb-2">
          <span className={`px-2 py-0.5 rounded text-[11px] font-bold border ${LEVEL_COLORS[level] ?? "bg-gray-700 text-gray-400 border-gray-600"}`}>
            {meta.label}
          </span>
          <div>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">{meta.full}</p>
            {teamName
              ? <p className="font-semibold text-gray-300 text-sm">{city ? `${city} ` : ""}{teamName}</p>
              : <p className="text-gray-600 text-sm italic">Not loaded</p>}
          </div>
        </div>
        <p className="text-sm text-gray-500 mt-3">
          Minor league roster not yet loaded.{" "}
          <span className="text-gray-600">Re-run start.py and type <code className="text-gray-400">reload</code> to load all affiliate rosters.</span>
        </p>
      </div>
    );
  }

  const hitters  = group.players.filter(p => p.position !== "SP" && p.position !== "RP");
  const pitchers = group.players.filter(p => p.position === "SP" || p.position === "RP");

  return (
    <div>
      {/* Header */}
      <div className={`stat-card border-l-4 ${border} mb-5`}>
        <div className="flex items-center gap-3">
          <span className={`px-2 py-0.5 rounded text-xs font-bold border ${LEVEL_COLORS[level] ?? "bg-gray-700 text-gray-400 border-gray-600"}`}>
            {meta.label}
          </span>
          <div>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider leading-none mb-0.5">{meta.full}</p>
            <p className="font-bold text-white text-sm">
              {aff?.city ? `${aff.city} ` : ""}{group.team_name}
            </p>
          </div>
          <span className="ml-auto text-gray-400 text-sm font-medium">{group.players.length} players</span>
        </div>
      </div>

      {/* Position Players */}
      {hitters.length > 0 && (
        <div className="stat-card mb-4">
          <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mb-3">
            Position Players · {hitters.length}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
                  <th className="pb-2 pr-4 font-medium">Name</th>
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
                {hitters.map(p => {
                  const s = p.stats?.type === "batting" ? p.stats : null;
                  return (
                    <tr key={p.id} className="border-b border-gray-800/30 hover:bg-gray-800/20 transition-colors">
                      <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.full_name}</td>
                      <td className="py-2 pr-3">
                        <span className="badge-grade bg-gray-700/60 text-gray-300 text-[11px]">{p.position}</span>
                      </td>
                      <td className="py-2 pr-3 text-gray-400 text-xs">{p.age ?? "—"}</td>
                      <td className="py-2 pr-3 text-gray-400 font-mono text-xs">{p.bats}/{p.throws}</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-gray-300 text-xs">{s?.games ?? "—"}</td>
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
      )}

      {/* Pitchers */}
      {pitchers.length > 0 && (
        <div className="stat-card">
          <p className="text-[10px] uppercase tracking-widest text-gray-500 font-semibold mb-3">
            Pitchers · {pitchers.length}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
                  <th className="pb-2 pr-4 font-medium">Name</th>
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
                {pitchers.map(p => {
                  const s = p.stats?.type === "pitching" ? p.stats : null;
                  return (
                    <tr key={p.id} className="border-b border-gray-800/30 hover:bg-gray-800/20 transition-colors">
                      <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.full_name}</td>
                      <td className="py-2 pr-3">
                        <span className={`badge-grade text-[11px] ${p.position === "SP" ? "bg-indigo-500/20 text-indigo-300" : "bg-sky-500/20 text-sky-300"}`}>
                          {p.position}
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-gray-400 text-xs">{p.age ?? "—"}</td>
                      <td className="py-2 pr-3 text-gray-400 font-mono text-xs">{p.bats}/{p.throws}</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-gray-300 text-xs">{s?.games ?? "—"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-xs">{s?.games_started ?? "—"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums font-mono text-xs">{s?.innings_pitched != null ? s.innings_pitched.toFixed(1) : "—"}</td>
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
      )}

      {group.players.length === 0 && (
        <div className="stat-card text-center py-8 text-gray-600">
          <p className="text-sm">No players on this roster yet.</p>
        </div>
      )}
    </div>
  );
}

// ── Finances Tab ──────────────────────────────────────────────────────────────

function PayrollBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="mb-3">
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-400">{label}</span>
        <span className="text-gray-300 font-mono">{fmtM(value)}</span>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function valueGradeColor(g: string | null) {
  if (!g) return "bg-gray-700 text-gray-400";
  if (g === "AAA") return "bg-green-500/20 text-green-400";
  if (g === "AA")  return "bg-blue-500/20 text-blue-300";
  if (g === "A")   return "bg-gray-700 text-gray-300";
  return "bg-red-500/20 text-red-400";
}

function gradeLabel(g: string | null) {
  if (g === "AAA") return "Elite";
  if (g === "AA")  return "Great";
  if (g === "A")   return "Fair";
  if (g === "B")   return "Below";
  return "—";
}

function FinancesTab({ data }: { data: FinancesData }) {
  const p = data.payroll;
  const taxPct = Math.min((p.total_m / p.luxury_tax_threshold_m) * 100, 105);
  const groups = data.payroll_by_group;
  const maxGroup = Math.max(...Object.values(groups), 1);

  return (
    <div className="space-y-6">
      <div className="stat-card">
        <div className="flex items-start justify-between mb-4 flex-wrap gap-2">
          <div>
            <h3 className="font-semibold text-sm uppercase tracking-wide text-gray-400 mb-1">Team Payroll</h3>
            {p.all_estimated && (
              <p className="text-[11px] text-amber-400/80">★ Salaries estimated from WAR + service time</p>
            )}
            {!p.all_estimated && p.real_salary_count < p.roster_size && (
              <p className="text-[11px] text-amber-400/80">★ {p.roster_size - p.real_salary_count} players use estimated salary (marked ~)</p>
            )}
            {!p.all_estimated && (
              <p className="text-[11px] text-gray-600">Salary &amp; contract data via Spotrac · <span className="font-medium text-red-400">EXP</span> = expiring this season</p>
            )}
          </div>
        </div>

        <div className="flex items-end gap-4 mb-4 flex-wrap">
          <div>
            <p className="text-3xl font-bold tabular-nums">{fmtM(p.total_m)}</p>
            <p className="text-xs text-gray-500 mt-0.5">{p.roster_size}-man MLB roster</p>
          </div>
          <div className="text-right ml-auto">
            <p className={`text-lg font-bold ${p.over_threshold ? "text-red-400" : "text-emerald-400"}`}>
              {p.over_threshold ? "+" + fmtM(Math.abs(p.gap_m)) + " OVER" : fmtM(p.gap_m) + " under"}
            </p>
            <p className="text-xs text-gray-500">{fmtM(p.luxury_tax_threshold_m)} CBT threshold</p>
          </div>
        </div>

        <div className="h-3 bg-gray-800 rounded-full overflow-hidden mb-1">
          <div className={`h-full rounded-full transition-all ${p.over_threshold ? "bg-red-500" : "bg-emerald-500"}`} style={{ width: `${taxPct}%` }} />
        </div>
        <div className="flex justify-between text-[10px] text-gray-600 mb-5">
          <span>$0</span>
          <span className="text-gray-400">CBT: {fmtM(p.luxury_tax_threshold_m)}</span>
        </div>

        <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">Payroll by Group</p>
        {Object.entries(groups).filter(([, v]) => v > 0).map(([label, val]) => (
          <PayrollBar key={label} label={label} value={val} max={maxGroup} color="bg-blue-500" />
        ))}
        <p className="text-xs text-gray-600 mt-2">Avg per player: {fmtM(p.avg_salary_m)}</p>
      </div>

      <div className="stat-card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-sm uppercase tracking-wide text-gray-400">Contracts — sorted by salary</h3>
          {p.all_estimated && (
            <span className="text-[10px] text-amber-400/70 border border-amber-400/20 px-2 py-0.5 rounded">~ = estimated</span>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
                <th className="pb-2 pr-4 font-medium">Player</th>
                <th className="pb-2 pr-3 font-medium">Status</th>
                <th className="pb-2 pr-3 font-medium">Pos</th>
                <th className="pb-2 pr-3 font-medium">Age</th>
                <th className="pb-2 pr-3 font-medium text-right">Salary</th>
                <th className="pb-2 pr-3 font-medium text-right">Yrs Left</th>
                <th className="pb-2 pr-3 font-medium text-right">Svc</th>
                <th className="pb-2 pr-3 font-medium text-right">WAR</th>
                <th className="pb-2 pr-3 font-medium text-right">Mkt Val</th>
                <th className="pb-2 pr-3 font-medium text-right">Surplus</th>
                <th className="pb-2 font-medium text-right">Grade</th>
              </tr>
            </thead>
            <tbody>
              {data.contracts.map((c: ContractEntry) => (
                <tr key={c.player_id} className={`border-b border-gray-800/40 hover:bg-gray-800/30 transition-colors ${c.roster_status !== "A" ? "opacity-75" : ""}`}>
                  <td className="py-2 pr-4 font-medium whitespace-nowrap">{c.name}</td>
                  <td className="py-2 pr-3">
                    <RosterStatusBadge label={c.roster_label ?? "Active"} status={c.roster_status ?? "A"} />
                  </td>
                  <td className="py-2 pr-3">
                    <span className="badge-grade bg-gray-700/60 text-gray-300 text-[11px]">{c.position ?? "—"}</span>
                  </td>
                  <td className="py-2 pr-3 text-gray-400">{c.age ?? "—"}</td>
                  <td className="py-2 pr-3 text-right font-mono">
                    <span className={c.is_estimated ? "text-amber-300/70" : "text-amber-300"}>
                      {c.is_estimated ? "~" : ""}{fmtM(c.salary_m)}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right">
                    {c.contract_years == null ? (
                      <span className="text-gray-600 text-xs">—</span>
                    ) : c.contract_years === 0 ? (
                      <span className="inline-block px-1.5 py-0.5 rounded text-[11px] font-bold bg-red-500/20 text-red-400 border border-red-500/30">EXP</span>
                    ) : c.contract_years === 1 ? (
                      <span className="inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold bg-amber-500/15 text-amber-400">{c.contract_years}</span>
                    ) : c.contract_years <= 3 ? (
                      <span className="text-yellow-300/80 text-xs font-medium">{c.contract_years}</span>
                    ) : (
                      <span className="text-gray-300 text-xs font-medium">{c.contract_years}</span>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right text-gray-400">{c.service_time != null ? c.service_time.toFixed(1) : "—"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    <span className={c.war >= 3 ? "text-emerald-400 font-semibold" : c.war >= 1 ? "text-blue-300" : "text-gray-400"}>
                      {c.war.toFixed(1)}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right font-mono text-gray-300">{fmtM(c.market_value_m)}</td>
                  <td className="py-2 pr-3 text-right font-mono">
                    <span className={c.surplus_value_m >= 0 ? "text-emerald-400" : "text-red-400"}>
                      {c.surplus_value_m >= 0 ? "+" : ""}{c.surplus_value_m.toFixed(1)}M
                    </span>
                  </td>
                  <td className="py-2 text-right">
                    <span className={`badge-grade text-xs font-bold ${valueGradeColor(c.value_grade)}`}>{gradeLabel(c.value_grade)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.contracts.length === 0 && (
            <p className="text-center text-gray-500 py-6 text-sm">No roster data found.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Free Agents Tab ───────────────────────────────────────────────────────────

function FreeAgentsTab({ teamId, teamName }: { teamId: string; teamName: string }) {
  const [budget, setBudget] = useState(20);
  const [aiRec, setAiRec] = useState(false);

  const { mutate, data, isPending } = useMutation({
    mutationFn: () =>
      rosterApi.analyzeNeeds({ team_id: teamId, budget_remaining_m: budget, generate_ai_recommendation: aiRec })
        .then(r => r.data),
  });

  return (
    <div className="space-y-6">
      <div className="stat-card flex flex-wrap gap-4 items-end">
        <div>
          <label className="block text-xs text-gray-400 mb-1">Available Budget ($M)</label>
          <input type="number" className="w-36 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-emerald-500"
            value={budget} min={0} max={500} onChange={e => setBudget(Number(e.target.value))} />
        </div>
        <label className="flex items-center gap-2 cursor-pointer pb-2">
          <input type="checkbox" className="rounded" checked={aiRec} onChange={e => setAiRec(e.target.checked)} />
          <span className="text-sm text-gray-300">Generate AI front-office memo</span>
        </label>
        <button onClick={() => mutate()} disabled={isPending}
          className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
          {isPending && <RefreshCw className="h-4 w-4 animate-spin" />}
          Analyze {teamName}
        </button>
      </div>

      {data && (
        <>
          {data.needs?.length > 0 && (
            <div className="stat-card">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="h-4 w-4 text-amber-400" />
                <h2 className="font-semibold">Positional Needs</h2>
              </div>
              <div className="flex flex-wrap gap-2">
                {data.needs.map((pos: string) => (
                  <span key={pos} className="badge-grade bg-amber-500/20 text-amber-300 text-sm px-3 py-1">{pos}</span>
                ))}
              </div>
            </div>
          )}

          {data.free_agent_recommendations?.length > 0 && (
            <div className="stat-card">
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="h-4 w-4 text-emerald-400" />
                <h2 className="font-semibold">Top Free Agent Fits</h2>
                <span className="text-xs text-gray-500 ml-2">within ${budget}M budget</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
                      <th className="pb-2 pr-6">Player</th>
                      <th className="pb-2 pr-4">Pos</th>
                      <th className="pb-2 pr-4">WAR</th>
                      <th className="pb-2 pr-4">wOBA</th>
                      <th className="pb-2 pr-4">Fit</th>
                      <th className="pb-2">Score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.free_agent_recommendations.map((fa: any) => (
                      <tr key={fa.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
                        <td className="py-2 pr-6 font-medium">{fa.name}</td>
                        <td className="py-2 pr-4 text-gray-400">{fa.position}</td>
                        <td className="py-2 pr-4 font-mono text-blue-400">{fa.war?.toFixed(1) ?? "—"}</td>
                        <td className="py-2 pr-4 font-mono">{fa.woba?.toFixed(3) ?? "—"}</td>
                        <td className="py-2 pr-4">
                          {fa.position_match
                            ? <span className="badge-grade bg-emerald-500/20 text-emerald-400">Match</span>
                            : <span className="badge-grade bg-gray-700 text-gray-500">—</span>}
                        </td>
                        <td className="py-2 text-amber-400 font-bold">{fa.fit_score}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {data.ai_recommendation && (
            <div className="stat-card border-emerald-800/50">
              <p className="text-xs text-emerald-400 font-medium mb-3 uppercase tracking-wide">AI Front Office Memo</p>
              <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">{data.ai_recommendation}</p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RosterPage() {
  const [teamId, setTeamId]     = useState("");
  const [teamName, setTeamName] = useState("");
  const [tab, setTab]           = useState<Tab>("26man");
  const qc = useQueryClient();

  const breakdownQuery = useQuery({
    queryKey: ["roster-breakdown", teamId],
    queryFn: () => rosterApi.breakdown(teamId).then(r => r.data),
    enabled: !!teamId,
    staleTime: 3 * 60 * 1000,
  });

  const orgQuery = useQuery({
    queryKey: ["org-roster", teamId],
    queryFn: () => playersApi.orgRoster(teamId).then(r => r.data),
    enabled: !!teamId && MINOR_LEVEL_IDS.has(tab),
    staleTime: 3 * 60 * 1000,
  });

  const financesQuery = useQuery({
    queryKey: ["team-finances", teamId],
    queryFn: () => rosterApi.finances(teamId).then(r => r.data),
    enabled: !!teamId && tab === "finances",
    staleTime: 3 * 60 * 1000,
  });

  const bd  = breakdownQuery.data;
  const org = orgQuery.data;
  const fin = financesQuery.data;

  const TABS: { id: Tab; label: string }[] = [
    { id: "26man",       label: "26-Man Roster" },
    { id: "40man",       label: "40-Man Roster" },
    { id: "AAA",         label: "Triple-A" },
    { id: "AA",          label: "Double-A" },
    { id: "A+",          label: "High-A" },
    { id: "A",           label: "Single-A" },
    { id: "Rookie",      label: "Rookie" },
    { id: "finances",    label: "Contracts & Finances" },
    { id: "free-agents", label: "Free Agents" },
  ];

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Users className="h-7 w-7 text-emerald-400" />
        <h1 className="text-2xl font-bold">Roster Builder</h1>
      </div>

      {/* Live sync bar */}
      <SyncBar
        className="mb-4"
        onSyncComplete={() => {
          qc.invalidateQueries({ queryKey: ["roster-breakdown", teamId] });
          qc.invalidateQueries({ queryKey: ["org-roster", teamId] });
        }}
      />

      {/* Team selector */}
      <div className="stat-card mb-6">
        <label className="text-xs text-gray-500 uppercase tracking-wider mb-2 block">Select Organization</label>
        <div className="flex gap-3 items-center">
          <div className="flex-1">
            <TeamSelector
              value={teamId}
              onChange={(id, team) => { setTeamId(id); setTeamName(`${team.city} ${team.name}`); setTab("26man"); }}
              placeholder="Pick an MLB team to explore their full organization…"
            />
          </div>
          {teamId && (
            <button onClick={() => { setTeamId(""); setTeamName(""); }}
              className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 rounded-lg transition-colors whitespace-nowrap">
              <X className="h-3.5 w-3.5" /> Clear
            </button>
          )}
        </div>
      </div>

      {!teamId ? (
        <div className="text-center py-20 text-gray-600">
          <Building2 className="h-12 w-12 mx-auto mb-4 opacity-30" />
          <p className="text-lg font-medium text-gray-500">Select a team to explore their organization</p>
          <p className="text-sm mt-1">View 26-Man, 40-Man, minor league system, contracts, and free agent fits</p>
        </div>
      ) : (
        <>
          {/* Stats bar */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <StatCard label="26-Man Roster"
              value={bd ? String(bd.twenty_six_count) : "—"}
              sub="Active MLB roster"
              icon={<ShieldCheck className="h-4 w-4 text-blue-400" />} />
            <StatCard label="40-Man Roster"
              value={bd ? String(bd.forty_man_count) : "—"}
              sub={bd ? `${bd.forty_extra.length} on IL / reassigned` : "Loading…"}
              icon={<Shield className="h-4 w-4 text-gray-400" />} />
            <StatCard label="Total Payroll"
              value={fin ? fmtM(fin.payroll.total_m) : "—"}
              sub={fin ? (fin.payroll.over_threshold ? "Over CBT threshold" : "Under CBT threshold") : "Open Finances tab"}
              icon={<DollarSign className="h-4 w-4 text-amber-400" />}
              accent={fin?.payroll.over_threshold ? "text-red-400" : "text-white"} />
            <StatCard label="Org Players"
              value={org ? String(org.groups.reduce((n, g) => n + g.players.length, 0)) : "—"}
              sub="Across all affiliate levels"
              icon={<Users className="h-4 w-4 text-emerald-400" />} />
          </div>

          {/* Tabs */}
          <div className="flex gap-1 mb-6 bg-gray-900 p-1 rounded-lg w-fit flex-wrap">
            {TABS.map(t => (
              <button key={t.id} onClick={() => setTab(t.id)}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  tab === t.id ? "bg-gray-700 text-white" : "text-gray-500 hover:text-gray-300"
                }`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {tab === "26man" && (
            breakdownQuery.isLoading ? <LoadingMsg msg={`Loading ${teamName} roster…`} /> :
            bd ? <TwentySixTab data={bd} /> : <ErrorMsg />
          )}
          {tab === "40man" && (
            breakdownQuery.isLoading ? <LoadingMsg msg="Loading 40-man roster…" /> :
            bd ? <FortyManTab data={bd} /> : <ErrorMsg />
          )}
          {MINOR_LEVEL_IDS.has(tab) && (
            orgQuery.isLoading
              ? <LoadingMsg msg={`Loading ${teamName} minor league data…`} />
              : org
                ? <LevelTab level={tab} data={org} />
                : <ErrorMsg />
          )}
          {tab === "finances" && (
            financesQuery.isLoading ? <LoadingMsg msg="Loading financial data…" /> :
            fin ? <FinancesTab data={fin} /> : <ErrorMsg />
          )}
          {tab === "free-agents" && (
            <FreeAgentsTab teamId={teamId} teamName={teamName} />
          )}
        </>
      )}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, icon, accent = "text-white" }: {
  label: string; value: string; sub: string; icon: React.ReactNode; accent?: string;
}) {
  return (
    <div className="stat-card flex items-start gap-3">
      <div className="mt-0.5">{icon}</div>
      <div>
        <p className="text-xs text-gray-500 mb-0.5">{label}</p>
        <p className={`text-lg font-bold tabular-nums ${accent}`}>{value}</p>
        <p className="text-[11px] text-gray-600 mt-0.5">{sub}</p>
      </div>
    </div>
  );
}

function LoadingMsg({ msg }: { msg: string }) {
  return <p className="text-gray-500 text-sm py-8 text-center">{msg}</p>;
}

function ErrorMsg() {
  return <p className="text-red-400 text-sm py-8 text-center">Failed to load data.</p>;
}

function gradeColor(g: number) {
  if (g >= 70) return "bg-green-500/20 text-green-400";
  if (g >= 55) return "bg-blue-500/20 text-blue-400";
  if (g >= 45) return "bg-gray-700 text-gray-300";
  return "bg-red-500/20 text-red-400";
}

function wrcColor(wrc: number) {
  if (wrc >= 140) return "bg-green-500/20 text-green-400";
  if (wrc >= 115) return "bg-blue-500/20 text-blue-300";
  if (wrc >= 85)  return "bg-gray-700 text-gray-300";
  return "bg-red-500/20 text-red-400";
}
