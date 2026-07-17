"use client";
import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { scoutingApi, teamsApi, draftApi, draftResultsApi, standingsApi, type Prospect, type CareerRow, type Team, type DraftPlanResponse, type DraftDepthRow, type MockDraftPick, type MockDraftResponse, type DraftGradeResponse, type DraftResultPick, type TeamDraftClassResponse } from "@/lib/api";
import {
  BookOpen, Search, ChevronLeft, ChevronRight, FileText, RefreshCw,
  MapPin, Ruler, Weight, GraduationCap, Calendar, User, X,
  Briefcase, ChevronDown, Loader2, Target, AlertCircle, TrendingUp,
  ArrowUp, ArrowDown, Zap, RotateCcw, CheckCircle2, ChevronsRight, Award,
  Users, Sparkles, DollarSign,
} from "lucide-react";

// ── Constants ──────────────────────────────────────────────────────────────────

const POSITIONS = ["SP", "RP", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"];
const SCHOOL_CLASSES = [
  { value: "4YR FR", label: "College Freshman" },
  { value: "4YR SO", label: "College Sophomore" },
  { value: "4YR JR", label: "College Junior" },
  { value: "4YR SR", label: "College Senior" },
  { value: "4YR GR", label: "Grad Student" },
  { value: "COLLEGE", label: "College (Any)" },
  { value: "HS SR", label: "HS Senior" },
  { value: "JC J1", label: "JuCo Freshman" },
  { value: "JC J2", label: "JuCo Sophomore" },
  { value: "JC J3", label: "JuCo Junior" },
  { value: "INTL", label: "International" },
];
const REPORT_TYPES = [
  { value: "full",  label: "Full Report" },
  { value: "brief", label: "Brief" },
  { value: "draft", label: "Draft" },
  { value: "trade", label: "Trade" },
] as const;
const PAGE_SIZE = 50;

// ── Grade helpers ──────────────────────────────────────────────────────────────

function gradeClass(g: number | null) {
  if (!g) return "text-gray-600";
  if (g >= 70) return "text-green-400 font-bold";
  if (g >= 55) return "text-blue-400 font-semibold";
  if (g >= 45) return "text-gray-300";
  return "text-red-400";
}
function gradeBadge(g: number | null) {
  if (!g) return "bg-gray-800 text-gray-500";
  if (g >= 70) return "bg-green-500/20 text-green-400 border border-green-500/30";
  if (g >= 55) return "bg-blue-500/20 text-blue-400 border border-blue-500/30";
  if (g >= 45) return "bg-gray-700 text-gray-300";
  return "bg-red-500/20 text-red-400 border border-red-500/30";
}
function GradePill({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="text-center min-w-[36px]">
      <p className="text-[10px] text-gray-500 uppercase tracking-wide mb-0.5">{label}</p>
      <span className={`inline-block px-1.5 py-0.5 rounded text-xs ${gradeBadge(value)}`}>
        {value ?? "—"}
      </span>
    </div>
  );
}

// ── Stat formatting ────────────────────────────────────────────────────────────

function fmt3(v: number | string | null | undefined) {
  if (v == null) return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (isNaN(n)) return String(v);
  return n.toFixed(3).replace(/^0/, "");
}
function fmt2(v: number | string | null | undefined) {
  if (v == null) return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (isNaN(n)) return String(v);
  return n.toFixed(2);
}
function fmtPct(v: number | null | undefined) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

// ── Badges ─────────────────────────────────────────────────────────────────────

function DraftBadge() {
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30">
      Draft
    </span>
  );
}
function LevelBadge({ level }: { level: string | null }) {
  const colors: Record<string, string> = {
    AAA:    "bg-purple-500/20 text-purple-400 border-purple-500/30",
    AA:     "bg-blue-500/20 text-blue-400 border-blue-500/30",
    "A+":   "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
    A:      "bg-teal-500/20 text-teal-400 border-teal-500/30",
    Rookie: "bg-green-500/20 text-green-400 border-green-500/30",
  };
  const cls = colors[level ?? ""] ?? "bg-gray-700 text-gray-400";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium border ${cls}`}>
      {level ?? "MiLB"}
    </span>
  );
}
function RankBadge({ rank }: { rank: number | null }) {
  if (!rank) return null;
  const cls =
    rank <= 10  ? "bg-yellow-500/20 text-yellow-300 border-yellow-500/40"
    : rank <= 50  ? "bg-orange-500/20 text-orange-300 border-orange-500/40"
    : rank <= 100 ? "bg-blue-500/20 text-blue-300 border-blue-500/40"
    : "bg-gray-700 text-gray-400 border-gray-600";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${cls}`}>
      #{rank}
    </span>
  );
}

// ── Stat line ──────────────────────────────────────────────────────────────────

function StatLine({ stats }: { stats: Prospect["stats"] }) {
  if (!stats) return <span className="text-gray-600 text-xs">No stats</span>;
  if (stats.type === "batting") {
    return (
      <span className="text-xs text-gray-400">
        {stats.avg   != null && <span className="mr-2">.{Math.round(stats.avg * 1000).toString().padStart(3, "0")} AVG</span>}
        {stats.ops   != null && <span className="mr-2">{stats.ops.toFixed(3)} OPS</span>}
        {stats.home_runs != null && <span className="mr-2">{stats.home_runs} HR</span>}
        {stats.wrc_plus  != null && <span>{stats.wrc_plus.toFixed(0)} wRC+</span>}
      </span>
    );
  }
  return (
    <span className="text-xs text-gray-400">
      {stats.era  != null && <span className="mr-2">{stats.era.toFixed(2)} ERA</span>}
      {stats.innings_pitched != null && <span className="mr-2">{stats.innings_pitched.toFixed(1)} IP</span>}
      {stats.k_pct != null && <span className="mr-2">{(stats.k_pct * 100).toFixed(1)}% K</span>}
    </span>
  );
}

// ── Career history table ───────────────────────────────────────────────────────

function CareerTable({ rows, type }: { rows: CareerRow[]; type: "batting" | "pitching" }) {
  if (!rows.length) return <p className="text-gray-500 text-sm py-4">No history available.</p>;

  if (type === "batting") {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-800 text-gray-500">
              <th className="text-left py-2 pr-3">Year</th>
              <th className="text-left py-2 pr-3">Level</th>
              <th className="text-left py-2 pr-3">Team</th>
              <th className="text-right py-2 pr-2">G</th>
              <th className="text-right py-2 pr-2">PA</th>
              <th className="text-right py-2 pr-2">AVG</th>
              <th className="text-right py-2 pr-2">OBP</th>
              <th className="text-right py-2 pr-2">SLG</th>
              <th className="text-right py-2 pr-2">OPS</th>
              <th className="text-right py-2 pr-2">HR</th>
              <th className="text-right py-2 pr-2">RBI</th>
              <th className="text-right py-2 pr-2">SB</th>
              <th className="text-right py-2">wRC+</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="py-1.5 pr-3 font-medium">{r.season ?? "—"}</td>
                <td className="py-1.5 pr-3"><LevelBadge level={r.level} /></td>
                <td className="py-1.5 pr-3 text-gray-400">{r.team ?? "—"}</td>
                <td className="py-1.5 pr-2 text-right text-gray-300">{r.games ?? "—"}</td>
                <td className="py-1.5 pr-2 text-right text-gray-300">{r.plate_appearances ?? "—"}</td>
                <td className="py-1.5 pr-2 text-right">{r.avg ? fmt3(r.avg) : "—"}</td>
                <td className="py-1.5 pr-2 text-right">{r.obp ? fmt3(r.obp) : "—"}</td>
                <td className="py-1.5 pr-2 text-right">{r.slg ? fmt3(r.slg) : "—"}</td>
                <td className="py-1.5 pr-2 text-right font-medium">{r.ops ? fmt3(r.ops) : "—"}</td>
                <td className="py-1.5 pr-2 text-right text-amber-400">{r.home_runs ?? "—"}</td>
                <td className="py-1.5 pr-2 text-right text-gray-300">{r.rbi ?? "—"}</td>
                <td className="py-1.5 pr-2 text-right text-gray-300">{r.stolen_bases ?? "—"}</td>
                <td className="py-1.5 text-right">
                  {r.wrc_plus != null ? (
                    <span className={Number(r.wrc_plus) >= 120 ? "text-green-400" : Number(r.wrc_plus) < 90 ? "text-red-400" : ""}>
                      {Math.round(Number(r.wrc_plus))}
                    </span>
                  ) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-800 text-gray-500">
            <th className="text-left py-2 pr-3">Year</th>
            <th className="text-left py-2 pr-3">Level</th>
            <th className="text-left py-2 pr-3">Team</th>
            <th className="text-right py-2 pr-2">G</th>
            <th className="text-right py-2 pr-2">GS</th>
            <th className="text-right py-2 pr-2">IP</th>
            <th className="text-right py-2 pr-2">ERA</th>
            <th className="text-right py-2 pr-2">WHIP</th>
            <th className="text-right py-2 pr-2">K</th>
            <th className="text-right py-2">BB</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
              <td className="py-1.5 pr-3 font-medium">{r.season ?? "—"}</td>
              <td className="py-1.5 pr-3"><LevelBadge level={r.level} /></td>
              <td className="py-1.5 pr-3 text-gray-400">{r.team ?? "—"}</td>
              <td className="py-1.5 pr-2 text-right text-gray-300">{r.games ?? "—"}</td>
              <td className="py-1.5 pr-2 text-right text-gray-300">{r.games_started ?? "—"}</td>
              <td className="py-1.5 pr-2 text-right">{r.innings_pitched ?? "—"}</td>
              <td className="py-1.5 pr-2 text-right font-medium">
                {r.era != null ? (
                  <span className={parseFloat(String(r.era)) <= 3.5 ? "text-green-400" : parseFloat(String(r.era)) >= 5.0 ? "text-red-400" : ""}>
                    {fmt2(r.era)}
                  </span>
                ) : "—"}
              </td>
              <td className="py-1.5 pr-2 text-right">{r.whip ? fmt2(r.whip) : "—"}</td>
              <td className="py-1.5 pr-2 text-right text-blue-400">{r.strikeouts ?? "—"}</td>
              <td className="py-1.5 text-right text-orange-400">{r.walks ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Player Profile Panel ───────────────────────────────────────────────────────

function PlayerProfile({ prospect, onClose }: { prospect: Prospect; onClose: () => void }) {
  const [reportType, setReportType] = useState<"full" | "brief" | "draft" | "trade">("draft");
  const [activeTab, setActiveTab] = useState<"career" | "report">("career");

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ["playerHistory", prospect.id],
    queryFn: () => scoutingApi.playerHistory(prospect.id).then(r => r.data),
  });
  const { mutate: genReport, data: reportData, isPending: reportPending } = useMutation({
    mutationFn: () =>
      scoutingApi.generateReport({ player_id: prospect.id, report_type: reportType }).then(r => r.data),
  });

  const isBatter = !["SP", "RP"].includes(prospect.position ?? "");
  const allHistory = [
    ...(historyData?.db_history ?? []),
    ...(historyData?.minor_league_history ?? []),
  ].sort((a, b) => (b.season ?? 0) - (a.season ?? 0));

  const grades = prospect.grades;
  const gradeKeys = isBatter
    ? (["hit", "power", "speed", "field", "arm"] as const)
    : (["fb_velo", "command", "field", "arm"] as const);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-start justify-between p-5 border-b border-gray-800">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <DraftBadge />
            <span className="text-xs text-gray-500">{prospect.position}</span>
            {prospect.birth_country && prospect.birth_country !== "USA" && (
              <span className="px-1.5 py-0.5 rounded text-[10px] bg-violet-500/20 text-violet-400 border border-violet-500/30">
                🌍 {prospect.birth_country}
              </span>
            )}
          </div>
          <h2 className="text-lg font-bold text-white truncate">{prospect.full_name}</h2>
          <p className="text-sm text-gray-400">
            {prospect.age ? `${prospect.age} yrs` : ""}
            {prospect.bats && ` · B/T: ${prospect.bats}/${prospect.throws}`}
          </p>
        </div>

        {grades.overall && (
          <div className={`ml-3 w-14 h-14 rounded-xl flex flex-col items-center justify-center shrink-0 ${gradeBadge(grades.overall)}`}>
            <span className="text-xl font-black">{grades.overall}</span>
            <span className="text-[9px] uppercase tracking-wider opacity-70">OVR</span>
          </div>
        )}

        <button onClick={onClose} className="ml-2 p-1.5 rounded-lg hover:bg-gray-800 text-gray-500 hover:text-gray-300 transition-colors">
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Bio strip */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-5 py-3 border-b border-gray-800 text-xs text-gray-400 bg-gray-900/50">
        {prospect.height && <span className="flex items-center gap-1"><Ruler className="h-3 w-3" />{prospect.height}</span>}
        {prospect.weight && <span className="flex items-center gap-1"><Weight className="h-3 w-3" />{prospect.weight} lbs</span>}
        {(prospect.birth_city || prospect.birth_country) && (
          <span className="flex items-center gap-1">
            <MapPin className="h-3 w-3" />
            {[prospect.birth_city, prospect.birth_country].filter(Boolean).join(", ")}
          </span>
        )}
        {prospect.school && (
          <span className="flex items-center gap-1">
            <GraduationCap className="h-3 w-3" />
            {prospect.school}
            {prospect.school_class && <span className="text-gray-600 ml-1">({prospect.school_class})</span>}
          </span>
        )}
        {prospect.draft_year && (
          <span className="flex items-center gap-1">
            <Calendar className="h-3 w-3" />
            {prospect.draft_year} Draft
            {prospect.draft_rank  && ` · MLB #${prospect.draft_rank}`}
            {prospect.draft_pick  && ` · Pick #${prospect.draft_pick}`}
            {prospect.signing_bonus && ` · $${(prospect.signing_bonus / 1_000_000).toFixed(2)}M`}
          </span>
        )}
      </div>

      {/* MLB Pipeline blurb */}
      {prospect.notes && prospect.draft_rank && (
        <div className="px-5 py-3 border-b border-gray-800 bg-amber-500/5">
          <p className="text-[10px] text-amber-400 uppercase tracking-wider mb-1.5 font-medium">
            MLB Pipeline Scouting Report
          </p>
          <p className="text-xs text-gray-300 leading-relaxed">{prospect.notes}</p>
        </div>
      )}

      {/* Scouting grades */}
      <div className="px-5 py-3 border-b border-gray-800">
        <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">Scouting Grades (20-80)</p>
        <div className="flex gap-3 flex-wrap">
          {gradeKeys.map(k => (
            <GradePill key={k} label={k === "fb_velo" ? "Velo" : k} value={grades[k as keyof typeof grades]} />
          ))}
        </div>
      </div>

      {/* Current stats */}
      {prospect.stats && (
        <div className="px-5 py-3 border-b border-gray-800 bg-gray-900/30">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-2">
            {prospect.stats.season ?? "Recent"} Stats
          </p>
          {prospect.stats.type === "batting" ? (
            <div className="grid grid-cols-4 gap-2 text-center">
              {[
                { label: "AVG",  val: prospect.stats.avg  != null ? fmt3(prospect.stats.avg)  : null },
                { label: "OBP",  val: prospect.stats.obp  != null ? fmt3(prospect.stats.obp)  : null },
                { label: "SLG",  val: prospect.stats.slg  != null ? fmt3(prospect.stats.slg)  : null },
                { label: "OPS",  val: prospect.stats.ops  != null ? fmt3(prospect.stats.ops)  : null },
                { label: "HR",   val: prospect.stats.home_runs },
                { label: "RBI",  val: prospect.stats.rbi },
                { label: "SB",   val: prospect.stats.stolen_bases },
                { label: "wRC+", val: prospect.stats.wrc_plus != null ? Math.round(prospect.stats.wrc_plus) : null },
              ].map(({ label, val }) => (
                <div key={label} className="bg-gray-800/50 rounded-lg py-1.5">
                  <p className="text-[10px] text-gray-500">{label}</p>
                  <p className="text-sm font-semibold text-white">{val ?? "—"}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-2 text-center">
              {[
                { label: "ERA",  val: prospect.stats.era  != null ? fmt2(prospect.stats.era)  : null },
                { label: "FIP",  val: prospect.stats.fip  != null ? fmt2(prospect.stats.fip)  : null },
                { label: "WHIP", val: prospect.stats.whip != null ? fmt2(prospect.stats.whip) : null },
                { label: "IP",   val: prospect.stats.innings_pitched != null ? prospect.stats.innings_pitched.toFixed(1) : null },
                { label: "K%",   val: prospect.stats.k_pct != null ? fmtPct(prospect.stats.k_pct) : null },
                { label: "BB%",  val: prospect.stats.bb_pct != null ? fmtPct(prospect.stats.bb_pct) : null },
                { label: "Velo", val: prospect.stats.avg_fastball_velo != null ? `${prospect.stats.avg_fastball_velo.toFixed(1)}` : null },
                { label: "WAR",  val: prospect.stats.war  != null ? prospect.stats.war.toFixed(1)  : null },
              ].map(({ label, val }) => (
                <div key={label} className="bg-gray-800/50 rounded-lg py-1.5">
                  <p className="text-[10px] text-gray-500">{label}</p>
                  <p className="text-sm font-semibold text-white">{val ?? "—"}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Sub-tab bar */}
      <div className="flex border-b border-gray-800 px-5">
        {(["career", "report"] as const).map(t => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            className={`px-4 py-2.5 text-xs font-medium capitalize transition-colors border-b-2 -mb-px ${
              activeTab === t
                ? "border-amber-500 text-amber-400"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {t === "career" ? "Career History" : "AI Report"}
          </button>
        ))}
      </div>

      {/* Sub-tab content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {activeTab === "career" ? (
          historyLoading
            ? <p className="text-gray-500 text-sm">Loading history…</p>
            : <CareerTable rows={allHistory} type={isBatter ? "batting" : "pitching"} />
        ) : (
          <div className="space-y-4">
            <div className="flex gap-2 flex-wrap">
              {REPORT_TYPES.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setReportType(value)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    reportType === value
                      ? "border-amber-500 bg-amber-500/20 text-amber-300"
                      : "border-gray-700 text-gray-400 hover:border-gray-500"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <button
              onClick={() => genReport()}
              disabled={reportPending}
              className="flex items-center gap-2 w-full justify-center bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors"
            >
              {reportPending && <RefreshCw className="h-4 w-4 animate-spin" />}
              Generate AI Scouting Report
            </button>
            {reportData && (
              <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
                <p className="text-xs text-amber-400 font-medium mb-2 uppercase tracking-wide">
                  {reportData.player_name} · {reportType} Report
                </p>
                <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap">
                  {reportData.report}
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Prospect row ───────────────────────────────────────────────────────────────

function ProspectRow({
  p, selected, onClick,
}: {
  p: Prospect; selected: boolean; onClick: () => void;
}) {
  const isBatter = !["SP", "RP"].includes(p.position ?? "");
  const grades = p.grades;

  return (
    <tr
      onClick={onClick}
      className={`border-b border-gray-800/50 cursor-pointer transition-colors ${
        selected ? "bg-amber-500/10 border-amber-800/50" : "hover:bg-gray-800/40"
      }`}
    >
      {/* Name */}
      <td className="py-2.5 pl-4 pr-3">
        <p className="text-sm font-medium text-white">{p.full_name}</p>
        <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
          {p.draft_rank && <RankBadge rank={p.draft_rank} />}
          <DraftBadge />
          {p.school && (
            <span className="text-[10px] text-gray-500 truncate max-w-[140px]">{p.school}</span>
          )}
          {p.draft_pick && <span className="text-[10px] text-gray-500">Pk #{p.draft_pick}</span>}
          {p.birth_country && p.birth_country !== "USA" && (
            <span className="text-[10px] text-violet-400">{p.birth_country}</span>
          )}
        </div>
      </td>

      {/* Pos / B/T */}
      <td className="py-2.5 pr-3 text-xs text-gray-400">
        <p className="font-medium text-gray-300">{p.position ?? "—"}</p>
        <p>{p.bats}/{p.throws}</p>
      </td>

      {/* Age / size */}
      <td className="py-2.5 pr-3 text-xs text-gray-400 hidden md:table-cell">
        <p>{p.age ?? "—"}</p>
        <p>{p.height ?? "—"} / {p.weight ?? "—"}</p>
      </td>

      {/* School / class */}
      <td className="py-2.5 pr-3 hidden lg:table-cell">
        <div className="text-xs">
          <p className="text-gray-300 truncate max-w-[180px]">{p.school ?? "—"}</p>
          <p className="text-gray-500">{p.school_class ?? ""}</p>
        </div>
      </td>

      {/* Pick # */}
      <td className="py-2.5 pr-3 text-center text-xs text-gray-300">
        {p.draft_pick ? `#${p.draft_pick}` : "—"}
      </td>

      {/* Signing bonus */}
      <td className="py-2.5 pr-4 hidden xl:table-cell">
        {p.signing_bonus ? (
          <span className="text-xs text-green-400">${(p.signing_bonus / 1_000_000).toFixed(2)}M</span>
        ) : (
          <StatLine stats={p.stats} />
        )}
      </td>
    </tr>
  );
}

// ── Draft Planner ─────────────────────────────────────────────────────────────

const _LEVELS = ["AAA", "AA", "A+", "A", "Rookie"] as const;
const _POSITIONS = ["SP", "RP", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"];

function depthColor(count: number): string {
  if (count === 0) return "bg-red-900/60 text-red-300";
  if (count === 1) return "bg-amber-900/50 text-amber-300";
  if (count <= 3) return "bg-gray-700/70 text-gray-300";
  return "bg-emerald-900/50 text-emerald-300";
}

function PlanText({ text }: { text: string }) {
  return (
    <div className="space-y-3 text-sm leading-relaxed">
      {text.split("\n").map((line, i) => {
        const t = line.trim();
        if (t.startsWith("## "))
          return (
            <h3 key={i} className="text-base font-semibold text-amber-300 border-b border-gray-700 pb-1 mt-6 first:mt-0">
              {t.slice(3)}
            </h3>
          );
        if (t.startsWith("- "))
          return (
            <div key={i} className="flex gap-2 pl-2">
              <span className="text-amber-400 mt-0.5 flex-shrink-0">•</span>
              <span className="text-gray-300">{t.slice(2)}</span>
            </div>
          );
        if (t === "") return <div key={i} className="h-1" />;
        return <p key={i} className="text-gray-300">{t}</p>;
      })}
    </div>
  );
}

function DepthMatrix({ rows }: { rows: DraftDepthRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-gray-500 border-b border-gray-700">
            <th className="text-left py-2 pr-4 font-medium">Pos</th>
            {_LEVELS.map(l => (
              <th key={l} className="text-center py-2 px-2 font-medium w-14">{l}</th>
            ))}
            <th className="text-center py-2 pl-2 font-medium w-14">Total</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/60">
          {rows.map(row => (
            <tr key={row.position} className="hover:bg-gray-800/20 transition-colors">
              <td className="py-1.5 pr-4">
                <span className="font-bold text-gray-200">{row.position}</span>
              </td>
              {_LEVELS.map(lvl => {
                const count = row[lvl as keyof DraftDepthRow] as number;
                const topName = row[`${lvl}_top` as keyof DraftDepthRow] as string | null;
                return (
                  <td key={lvl} className="py-1.5 px-2 text-center">
                    <div
                      className={`inline-flex items-center justify-center w-8 h-6 rounded font-bold ${depthColor(count)}`}
                      title={topName ? `Top: ${topName}` : undefined}
                    >
                      {count}
                    </div>
                  </td>
                );
              })}
              <td className="py-1.5 pl-2 text-center">
                <span className={`font-bold ${row.total === 0 ? "text-red-400" : row.total <= 3 ? "text-amber-400" : "text-gray-200"}`}>
                  {row.total}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[10px] text-gray-600 mt-2 pl-1">
        Color: <span className="text-red-400">0 = barren</span> ·{" "}
        <span className="text-amber-400">1 = thin</span> ·{" "}
        <span className="text-gray-400">2–3 = adequate</span> ·{" "}
        <span className="text-emerald-400">4+ = deep</span>
        {" "}· Hover a cell to see top prospect
      </p>
    </div>
  );
}

function OrgProspectList({ prospects }: { prospects: DraftPlanResponse["org_prospects"] }) {
  if (!prospects.length)
    return <p className="text-gray-500 text-xs italic py-2">No org prospect rankings loaded.</p>;

  return (
    <div className="overflow-y-auto max-h-64 space-y-1 pr-1">
      {prospects.map((p, i) => (
        <div key={p.id} className="flex items-center gap-3 px-3 py-1.5 rounded-lg bg-gray-800/40 hover:bg-gray-800/70 transition-colors">
          <span className="text-gray-500 text-xs w-6 text-right flex-shrink-0">
            #{p.org_rank ?? i + 1}
          </span>
          <span className="text-gray-200 text-sm font-medium flex-1 min-w-0 truncate">{p.name}</span>
          <span className="text-[10px] border rounded px-1 py-0.5 bg-gray-700/50 text-gray-400 border-gray-600 flex-shrink-0">
            {p.position ?? "?"}
          </span>
          {p.overall && (
            <span className="text-[10px] font-bold text-blue-400 flex-shrink-0">{p.overall}</span>
          )}
          <span className="text-gray-500 text-[10px] flex-shrink-0">{p.level}</span>
        </div>
      ))}
    </div>
  );
}

function DraftClassPanel({ prospects }: { prospects: DraftPlanResponse["draft_prospects"] }) {
  const [posFilter, setPosFilter] = useState("ALL");

  const byPos = prospects.reduce<Record<string, typeof prospects>>((acc, p) => {
    const pos = p.position ?? "UNK";
    (acc[pos] ??= []).push(p);
    return acc;
  }, {});
  const available = _POSITIONS.filter(p => byPos[p]?.length);
  const displayed = posFilter === "ALL" ? prospects : (byPos[posFilter] ?? []);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        <button
          onClick={() => setPosFilter("ALL")}
          className={`px-2 py-0.5 rounded text-xs font-medium border transition-colors ${
            posFilter === "ALL" ? "bg-amber-600/30 text-amber-300 border-amber-500/50" : "text-gray-400 border-gray-700 hover:border-gray-500 hover:text-gray-200"
          }`}
        >
          All ({prospects.length})
        </button>
        {available.map(pos => (
          <button
            key={pos}
            onClick={() => setPosFilter(pos)}
            className={`px-2 py-0.5 rounded text-xs font-medium border transition-colors ${
              posFilter === pos ? "bg-amber-600/30 text-amber-300 border-amber-500/50" : "text-gray-400 border-gray-700 hover:border-gray-500 hover:text-gray-200"
            }`}
          >
            {pos} ({byPos[pos]?.length ?? 0})
          </button>
        ))}
      </div>
      <div className="overflow-y-auto max-h-60 space-y-1 pr-1">
        {displayed.map(p => (
          <div key={p.id} className="flex items-center gap-3 px-3 py-1.5 rounded-lg bg-gray-800/40 hover:bg-gray-800/70 transition-colors">
            {p.rank && <span className="text-gray-500 text-xs w-6 text-right flex-shrink-0">#{p.rank}</span>}
            <span className="text-gray-200 text-sm font-medium flex-1 min-w-0 truncate">{p.name}</span>
            <span className="text-[10px] border rounded px-1 py-0.5 bg-gray-700/50 text-gray-400 border-gray-600 flex-shrink-0">
              {p.position ?? "?"}
            </span>
            {p.school && <span className="text-gray-500 text-[10px] flex-shrink-0 truncate max-w-[100px]">{p.school}</span>}
            {p.throws && <span className="text-gray-600 text-[10px] flex-shrink-0">{p.bats}/{p.throws}</span>}
          </div>
        ))}
        {displayed.length === 0 && <p className="text-gray-500 text-xs italic py-2">No prospects at this position.</p>}
      </div>
    </div>
  );
}

function DraftPlannerPanel() {
  const [selectedTeamId, setSelectedTeamId] = useState("");
  const [plan, setPlan] = useState<DraftPlanResponse | null>(null);

  const { data: teamsData, isLoading: teamsLoading } = useQuery({
    queryKey: ["teams", "MLB"],
    queryFn: () => teamsApi.list("MLB"),
  });
  const teams: Team[] = (teamsData?.data?.teams ?? []).sort((a, b) =>
    a.full_name.localeCompare(b.full_name)
  );

  const mutation = useMutation({
    mutationFn: (teamId: string) => draftApi.generatePlan(teamId),
    onSuccess: res => setPlan(res.data),
  });

  const handleGenerate = () => {
    if (!selectedTeamId) return;
    setPlan(null);
    mutation.mutate(selectedTeamId);
  };

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-5 max-w-6xl mx-auto w-full">
      {/* Team picker */}
      <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
        <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
          <div className="flex-1 min-w-0">
            <label className="block text-xs text-gray-500 uppercase tracking-wider mb-2">Select a Team</label>
            <div className="relative">
              <select
                value={selectedTeamId}
                onChange={e => setSelectedTeamId(e.target.value)}
                disabled={teamsLoading}
                className="w-full appearance-none bg-gray-800 border border-gray-600 rounded-xl px-4 py-2.5 pr-10 text-gray-200 text-sm focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/50 disabled:opacity-50 cursor-pointer"
              >
                <option value="">— Choose a team —</option>
                {teams.map(t => (
                  <option key={t.id} value={t.id}>
                    {t.full_name}{t.division ? ` (${t.division})` : ""}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
            </div>
          </div>
          <button
            onClick={handleGenerate}
            disabled={!selectedTeamId || mutation.isPending}
            className="flex items-center gap-2 px-6 py-2.5 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition-colors whitespace-nowrap"
          >
            {mutation.isPending ? (
              <><Loader2 className="h-4 w-4 animate-spin" />Generating…</>
            ) : (
              <><Target className="h-4 w-4" />Generate Draft Plan</>
            )}
          </button>
        </div>

        {mutation.isPending && (
          <div className="mt-4 flex items-center gap-3 text-sm text-gray-400 bg-amber-950/30 rounded-xl px-4 py-3 border border-amber-800/30">
            <Loader2 className="h-4 w-4 animate-spin text-amber-400 flex-shrink-0" />
            <span>Analyzing system depth, positional gaps, and the 2026 draft class — Claude is writing the memo (15–30 seconds)…</span>
          </div>
        )}
        {mutation.isError && (
          <div className="mt-4 flex items-center gap-3 text-sm text-red-400 bg-red-950/30 rounded-xl px-4 py-3 border border-red-800/30">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span>Failed to generate plan. The team may not have minor league roster data loaded.</span>
          </div>
        )}
      </div>

      {plan && (
        <>
          {/* Team badge */}
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-gray-100">{plan.team.full_name}</h2>
            {plan.team.division && (
              <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded-full border border-gray-700">
                {plan.team.division}
              </span>
            )}
          </div>

          {/* Stat cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[
              { label: "MLB Roster", value: String(plan.context.mlb_roster_size), sub: "players on 40-man" },
              { label: "Minor Leaguers", value: String(plan.context.minor_league_count), sub: "across system levels" },
              { label: "Org Prospects", value: String(plan.context.org_prospects_ranked), sub: "ranked in top-30" },
              { label: "Draft Class", value: String(plan.context.draft_class_size), sub: "2026 prospects tracked" },
            ].map(({ label, value, sub }) => (
              <div key={label} className="bg-gray-800/60 rounded-xl border border-gray-700/50 p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</p>
                <p className="text-2xl font-bold text-gray-100">{value}</p>
                <p className="text-xs text-gray-500 mt-0.5">{sub}</p>
              </div>
            ))}
          </div>

          {/* Depth matrix + org prospects */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp className="h-4 w-4 text-amber-400" />
                <h3 className="text-sm font-semibold text-gray-200">System Depth by Position</h3>
              </div>
              <DepthMatrix rows={plan.depth_summary} />
            </div>

            <div className="space-y-5">
              <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
                <div className="flex items-center gap-2 mb-4">
                  <BookOpen className="h-4 w-4 text-amber-400" />
                  <h3 className="text-sm font-semibold text-gray-200">Top-30 Org Prospects</h3>
                </div>
                <OrgProspectList prospects={plan.org_prospects} />
              </div>

              <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
                <div className="flex items-center gap-2 mb-4">
                  <Target className="h-4 w-4 text-amber-400" />
                  <h3 className="text-sm font-semibold text-gray-200">2026 Draft Class</h3>
                </div>
                <DraftClassPanel prospects={plan.draft_prospects} />
              </div>
            </div>
          </div>

          {/* AI plan */}
          <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-6">
            <div className="flex items-center gap-2 mb-5">
              <Briefcase className="h-4 w-4 text-amber-400" />
              <h3 className="text-sm font-semibold text-gray-200">Draft Strategy Memo</h3>
              <span className="ml-auto text-xs text-gray-600 italic">Generated by Claude</span>
            </div>
            <PlanText text={plan.plan} />
          </div>
        </>
      )}
    </div>
  );
}

// ── Mock Draft ────────────────────────────────────────────────────────────────

const POS_COLORS: Record<string, string> = {
  SP: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  RP: "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
  C:  "bg-amber-500/20 text-amber-300 border-amber-500/30",
  DH: "bg-gray-500/20 text-gray-300 border-gray-500/30",
};
const HITTER_COLOR = "bg-emerald-500/20 text-emerald-300 border-emerald-500/30";

function MockPosBadge({ pos }: { pos: string }) {
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border flex-shrink-0 ${POS_COLORS[pos] ?? HITTER_COLOR}`}>
      {pos || "?"}
    </span>
  );
}

function RoundTable({ picks, highlight }: { picks: MockDraftPick[]; highlight: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] text-gray-500 uppercase tracking-wider border-b border-gray-700">
            <th className="text-right pb-2 pr-3 w-10 font-medium">Pick</th>
            <th className="text-left pb-2 pr-4 font-medium">Team</th>
            <th className="text-left pb-2 pr-4 font-medium">Player</th>
            <th className="text-center pb-2 pr-3 w-10 font-medium">Pos</th>
            <th className="text-left pb-2 pr-4 font-medium hidden sm:table-cell">School</th>
            <th className="text-left pb-2 font-medium hidden lg:table-cell">Note</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/60">
          {picks.map(pick => {
            const isHighlighted = highlight && pick.team_abbr === highlight;
            return (
              <tr
                key={pick.overall}
                className={`transition-colors ${isHighlighted ? "bg-amber-500/10" : "hover:bg-gray-800/30"}`}
              >
                <td className="py-2 pr-3 text-right">
                  <span className={`text-xs font-mono ${isHighlighted ? "text-amber-400 font-bold" : "text-gray-500"}`}>
                    #{pick.overall}
                  </span>
                </td>
                <td className="py-2 pr-4">
                  <span className={`text-xs font-semibold ${isHighlighted ? "text-amber-300" : "text-gray-300"}`}>
                    {pick.team_name}
                  </span>
                </td>
                <td className="py-2 pr-4">
                  <span className={`font-medium ${isHighlighted ? "text-amber-100" : "text-gray-100"}`}>
                    {pick.player_name}
                  </span>
                </td>
                <td className="py-2 pr-3 text-center">
                  <MockPosBadge pos={pick.position} />
                </td>
                <td className="py-2 pr-4 hidden sm:table-cell">
                  <span className="text-xs text-gray-500 truncate max-w-[140px] block">{pick.school}</span>
                </td>
                <td className="py-2 hidden lg:table-cell">
                  <span className="text-xs text-gray-500 italic">{pick.note}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Order for sorting round labels: "1", "PPI", "CBA", "2", "CBB", "3", "4", "5", …
const ROUND_SORT_ORDER = ["1", "PPI", "CBA", "2", "CBB", "3", "4", "5"];
function sortRoundLabels(labels: string[]): string[] {
  return [...labels].sort((a, b) => {
    const ia = ROUND_SORT_ORDER.indexOf(a);
    const ib = ROUND_SORT_ORDER.indexOf(b);
    if (ia !== -1 && ib !== -1) return ia - ib;
    if (ia !== -1) return -1;
    if (ib !== -1) return 1;
    return a.localeCompare(b);
  });
}

function MockDraftPanel() {
  const [rounds, setRounds] = useState(3);
  const [highlight, setHighlight] = useState("");
  const [activeRound, setActiveRound] = useState<string>("1");
  const [result, setResult] = useState<MockDraftResponse | null>(null);

  const mutation = useMutation({
    mutationFn: (r: number) => draftApi.generateMock(r),
    onSuccess: res => {
      setResult(res.data);
      setActiveRound("1");
    },
  });

  // Group picks by round label
  const byRound: Record<string, MockDraftPick[]> = {};
  for (const pick of result?.picks ?? []) {
    (byRound[pick.round] ??= []).push(pick);
  }
  const roundNums = sortRoundLabels(Object.keys(byRound));

  // All unique teams in result for the highlight filter
  const teams = [...new Set((result?.picks ?? []).map(p => p.team_abbr))].sort();
  const teamNames: Record<string, string> = {};
  for (const p of result?.picks ?? []) teamNames[p.team_abbr] = p.team_name;

  const currentPicks = byRound[activeRound] ?? [];

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-5 max-w-6xl mx-auto w-full">
      {/* Controls */}
      <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
        <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-end">
          {/* Rounds selector */}
          <div>
            <label className="block text-xs text-gray-500 uppercase tracking-wider mb-2">Rounds to simulate</label>
            <div className="flex gap-2">
              {[1, 2, 3, 5].map(r => (
                <button
                  key={r}
                  onClick={() => setRounds(r)}
                  className={`px-4 py-2 rounded-lg text-sm font-semibold border transition-colors ${
                    rounds === r
                      ? "bg-amber-600/30 text-amber-300 border-amber-500/60"
                      : "text-gray-400 border-gray-700 hover:border-gray-500 hover:text-gray-200"
                  }`}
                >
                  {r === 1 ? "1st" : r === 2 ? "1–2" : r === 3 ? "1–3" : "1–5"}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={() => mutation.mutate(rounds)}
            disabled={mutation.isPending}
            className="flex items-center gap-2 px-6 py-2.5 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold rounded-xl transition-colors whitespace-nowrap"
          >
            {mutation.isPending ? (
              <><Loader2 className="h-4 w-4 animate-spin" />Simulating…</>
            ) : (
              <><BookOpen className="h-4 w-4" />Run Mock Draft</>
            )}
          </button>
        </div>

        {mutation.isPending && (
          <div className="mt-4 flex items-center gap-3 text-sm text-gray-400 bg-amber-950/30 rounded-xl px-4 py-3 border border-amber-800/30">
            <Loader2 className="h-4 w-4 animate-spin text-amber-400 flex-shrink-0" />
            <span>
              Claude is simulating all 30 teams across {rounds} round{rounds > 1 ? "s" : ""} + compensatory picks (PPI, CBA{rounds >= 2 ? ", CBB" : ""}). This takes ~20 seconds…
            </span>
          </div>
        )}
        {mutation.isError && (
          <div className="mt-4 flex items-center gap-3 text-sm text-red-400 bg-red-950/30 rounded-xl px-4 py-3 border border-red-800/30">
            <AlertCircle className="h-4 w-4 flex-shrink-0" />
            <span>Simulation failed. Make sure the draft prospect database is loaded.</span>
          </div>
        )}
      </div>

      {result && (
        <>
          {/* Summary bar */}
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex gap-4">
              {[
                { label: "Rounds", value: String(result.rounds) },
                { label: "Total Picks", value: String(result.total_picks) },
                { label: "Teams", value: "30" },
              ].map(({ label, value }) => (
                <div key={label} className="bg-gray-800/60 rounded-xl border border-gray-700/50 px-4 py-3">
                  <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
                  <p className="text-xl font-bold text-gray-100">{value}</p>
                </div>
              ))}
            </div>

            {/* Team highlight filter */}
            <div className="flex-1 min-w-[200px] max-w-xs relative ml-auto">
              <label className="block text-xs text-gray-500 uppercase tracking-wider mb-1">Highlight team</label>
              <div className="relative">
                <select
                  value={highlight}
                  onChange={e => setHighlight(e.target.value)}
                  className="w-full appearance-none bg-gray-800 border border-gray-600 rounded-xl px-3 py-2 pr-8 text-gray-200 text-sm focus:outline-none focus:border-amber-500"
                >
                  <option value="">All teams</option>
                  {teams.map(abbr => (
                    <option key={abbr} value={abbr}>{teamNames[abbr] ?? abbr}</option>
                  ))}
                </select>
                <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
              </div>
            </div>
          </div>

          {/* If a team is highlighted, show all their picks first */}
          {highlight && (
            <div className="bg-amber-950/20 border border-amber-700/40 rounded-2xl p-5">
              <h3 className="text-sm font-semibold text-amber-300 mb-4">
                {teamNames[highlight]} — All {rounds} Pick{rounds > 1 ? "s" : ""}
              </h3>
              <div className="space-y-2">
                {result.picks
                  .filter(p => p.team_abbr === highlight)
                  .map(pick => (
                    <div key={pick.overall} className="flex items-center gap-3">
                      <span className="text-xs text-amber-600 font-mono w-16 flex-shrink-0">
                        {roundTabLabel(pick.round)} #{pick.overall}
                      </span>
                      <span className="text-amber-100 font-medium">{pick.player_name}</span>
                      <MockPosBadge pos={pick.position} />
                      <span className="text-gray-400 text-xs">{pick.school}</span>
                      {pick.note && <span className="text-gray-500 text-xs italic hidden sm:block">— {pick.note}</span>}
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Round navigation */}
          {roundNums.length > 1 && (
            <div className="flex gap-2 flex-wrap">
              {roundNums.map(r => {
                const isBonus = r === "PPI" || r === "CBA" || r === "CBB";
                const label = r === "PPI" ? "PPI Award Picks"
                  : r === "CBA" ? "Comp. Balance A"
                  : r === "CBB" ? "Comp. Balance B"
                  : `Round ${r}`;
                return (
                  <button
                    key={r}
                    onClick={() => setActiveRound(r)}
                    className={`px-4 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                      activeRound === r
                        ? isBonus
                          ? "bg-blue-600/30 text-blue-300 border-blue-500/60"
                          : "bg-amber-600/30 text-amber-300 border-amber-500/60"
                        : isBonus
                          ? "text-blue-400 border-gray-700 hover:border-blue-500/50 hover:text-blue-200"
                          : "text-gray-400 border-gray-700 hover:border-gray-500 hover:text-gray-200"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          )}

          {/* Active round picks */}
          <div className="bg-gray-900 border border-gray-700/60 rounded-2xl p-5">
            <div className="flex items-center gap-2 mb-4">
              <BookOpen className="h-4 w-4 text-amber-400" />
              <h3 className="text-sm font-semibold text-gray-200">
{roundDisplayName(activeRound)} — {currentPicks.length} picks
              </h3>
              {roundNums.length > 1 && (
                <div className="ml-auto flex gap-1">
                  <button
                    disabled={roundNums.indexOf(activeRound) <= 0}
                    onClick={() => { const idx = roundNums.indexOf(activeRound); if (idx > 0) setActiveRound(roundNums[idx - 1]); }}
                    className="p-1.5 rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 disabled:opacity-30 transition-colors"
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </button>
                  <button
                    disabled={roundNums.indexOf(activeRound) >= roundNums.length - 1}
                    onClick={() => { const idx = roundNums.indexOf(activeRound); if (idx < roundNums.length - 1) setActiveRound(roundNums[idx + 1]); }}
                    className="p-1.5 rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 disabled:opacity-30 transition-colors"
                  >
                    <ChevronRight className="h-3.5 w-3.5" />
                  </button>
                </div>
              )}
            </div>
            <RoundTable picks={currentPicks} highlight={highlight} />
          </div>
        </>
      )}
    </div>
  );
}

// ── Manual Mock Draft ─────────────────────────────────────────────────────────

const MOCK_ROUNDS = 20;

// Round 1 — 25 non-CBT teams only (source: mlb.com/draft/2026/order).
// The 5 CBT-penalised teams do NOT pick in Round 1.
const R1_TEAMS_2026: string[] = [
  "Chicago White Sox",      //  1
  "Tampa Bay Rays",         //  2
  "Minnesota Twins",        //  3
  "San Francisco Giants",   //  4
  "Pittsburgh Pirates",     //  5
  "Kansas City Royals",     //  6
  "Baltimore Orioles",      //  7
  "Athletics",              //  8
  "Atlanta Braves",         //  9
  "Colorado Rockies",       // 10
  "Washington Nationals",   // 11
  "Los Angeles Angels",     // 12
  "St. Louis Cardinals",    // 13
  "Miami Marlins",          // 14
  "Arizona Diamondbacks",   // 15
  "Texas Rangers",          // 16
  "Houston Astros",         // 17
  "Cincinnati Reds",        // 18
  "Cleveland Guardians",    // 19
  "Boston Red Sox",         // 20
  "San Diego Padres",       // 21
  "Detroit Tigers",         // 22
  "Chicago Cubs",           // 23
  "Seattle Mariners",       // 24
  "Milwaukee Brewers",      // 25
];

// Round 2 and all subsequent rounds — 30 teams.
// Rockies lead (worst overall record). Blue Jays & Dodgers are picks 2-3 because
// their CBT penalty pushed them completely out of Round 1 into Round 2.
// Yankees & Phillies also appear here (they picked in CBA; normal from R2 onward).
const DRAFT_ORDER_2026: string[] = [
  "Colorado Rockies",       // R2  1 (overall #38)
  "Toronto Blue Jays",      // R2  2 (CBT — skipped R1 entirely)
  "Los Angeles Dodgers",    // R2  3 (CBT — skipped R1 entirely)
  "Chicago White Sox",      // R2  4
  "Washington Nationals",   // R2  5
  "Minnesota Twins",        // R2  6
  "Pittsburgh Pirates",     // R2  7
  "Los Angeles Angels",     // R2  8
  "Baltimore Orioles",      // R2  9
  "Athletics",              // R2 10
  "Atlanta Braves",         // R2 11
  "Tampa Bay Rays",         // R2 12
  "St. Louis Cardinals",    // R2 13
  "Miami Marlins",          // R2 14
  "Arizona Diamondbacks",   // R2 15
  "Texas Rangers",          // R2 16
  "San Francisco Giants",   // R2 17
  "Kansas City Royals",     // R2 18
  "Houston Astros",         // R2 19
  "Cincinnati Reds",        // R2 20
  "Cleveland Guardians",    // R2 21
  "Boston Red Sox",         // R2 22
  "San Diego Padres",       // R2 23
  "Detroit Tigers",         // R2 24
  "Chicago Cubs",           // R2 25
  "New York Yankees",       // R2 26 (CBT — CBA first pick; normal R2 onward)
  "Philadelphia Phillies",  // R2 27 (CBT — CBA first pick; normal R2 onward)
  "Seattle Mariners",       // R2 28
  "Milwaukee Brewers",      // R2 29
  "New York Mets",          // R2 30 (CBT — PPI first pick; normal R2 onward)
];

// PPI — 3 picks after Round 1, overall picks 26-28.
// Awarded for 2025 performances. Mets CBT penalty placed their pick here.
const PPI_TEAMS_2026: string[] = [
  "Atlanta Braves",         // 26 — Drake Baldwin NL Rookie of the Year
  "New York Mets",          // 27 — CBT penalty (pick lands in PPI zone)
  "Houston Astros",         // 28 — Hunter Brown AL Cy Young top-3
];

// CBA — 9 picks after PPI, overall picks 29-37.
// 7 small-market eligible teams + Yankees + Phillies (CBT penalty → first pick in CBA).
const CBA_TEAMS_2026: string[] = [
  "Cleveland Guardians",    // 29 (traded to SF Giants in reality)
  "Kansas City Royals",     // 30
  "Arizona Diamondbacks",   // 31
  "St. Louis Cardinals",    // 32
  "Baltimore Orioles",      // 33 (traded to TB Rays in reality)
  "Pittsburgh Pirates",     // 34
  "New York Yankees",       // 35 — CBT penalty; first pick is here
  "Philadelphia Phillies",  // 36 — CBT penalty
  "Colorado Rockies",       // 37
];

// CBB — 8 picks after Round 2, overall picks 68-75.
const CBB_TEAMS_2026: string[] = [
  "Milwaukee Brewers",      // 68 (traded to BOS in reality)
  "Seattle Mariners",       // 69 (traded to STL in reality)
  "Detroit Tigers",         // 70
  "Cincinnati Reds",        // 71
  "Miami Marlins",          // 72
  "Tampa Bay Rays",         // 73 (traded to STL in reality)
  "Athletics",              // 74
  "Minnesota Twins",        // 75
];

/**
 * Sort teams into the official 2026 draft order.
 * Uses R2 order (DRAFT_ORDER_2026) as the primary sort key — this is the
 * 30-team repeating order used for the setup screen and R2+ slots.
 */
function sortByDraftOrder(teams: DraftTeam[]): DraftTeam[] {
  return [...teams].sort((a, b) => {
    const ia = DRAFT_ORDER_2026.indexOf(a.full_name);
    const ib = DRAFT_ORDER_2026.indexOf(b.full_name);
    const ra = ia === -1 ? 999 : ia;
    const rb = ib === -1 ? 999 : ib;
    return ra - rb;
  });
}

type ManualPick = {
  overall: number;
  round: string;        // "1", "2", "CBA", "CBB", etc.
  roundPick: number;
  teamAbbr: string;
  teamName: string;
  playerId: string;
  playerName: string;
  position: string | null;
  school: string | null;
  rank: number | null;
};

// ── Draft slot ─────────────────────────────────────────────────────────────────
// One entry per pick in the full draft sequence (regular rounds + CBA + CBB).
type DraftSlot = {
  overall: number;
  roundLabel: string;   // "1", "2", "CBA", "CBB", etc.
  roundPick: number;
  teamAbbr: string;
  teamName: string;
};

/** Build the ordered flat list of every draft slot for a given team order. */
function buildDraftSlots(order: DraftTeam[], rounds: number): DraftSlot[] {
  const slots: DraftSlot[] = [];
  const findTeam = (name: string) => order.find(t => t.full_name === name);

  /** Push fixed-team bonus picks (PPI / CBA / CBB). */
  const pushBonus = (roundLabel: string, names: string[]) => {
    names.forEach((name, i) => {
      const t = findTeam(name);
      slots.push({
        overall: slots.length + 1, roundLabel, roundPick: i + 1,
        teamAbbr: t?.abbr ?? "?", teamName: name,
      });
    });
  };

  // ── Round 1: exactly 25 non-CBT teams ──────────────────────────────────
  R1_TEAMS_2026.forEach((name, i) => {
    const t = findTeam(name);
    slots.push({
      overall: slots.length + 1, roundLabel: "1", roundPick: i + 1,
      teamAbbr: t?.abbr ?? "?", teamName: name,
    });
  });

  // ── PPI (3 picks) then CBA (9 picks) ───────────────────────────────────
  pushBonus("PPI", PPI_TEAMS_2026);
  pushBonus("CBA", CBA_TEAMS_2026);

  // ── Rounds 2+ — all 30 teams (order seeded by DRAFT_ORDER_2026 / R2 order)
  for (let r = 2; r <= rounds; r++) {
    order.forEach((t, i) =>
      slots.push({ overall: slots.length + 1, roundLabel: String(r), roundPick: i + 1, teamAbbr: t.abbr, teamName: t.full_name }),
    );
    if (r === 2) pushBonus("CBB", CBB_TEAMS_2026);  // CBB after Round 2
  }

  return slots;
}

/** Human-readable display name for a round label. */
function roundDisplayName(label: string): string {
  if (label === "PPI") return "Prospect Promo Incentive";
  if (label === "CBA") return "Comp. Balance A";
  if (label === "CBB") return "Comp. Balance B";
  return `Round ${label}`;
}

/** Short tab label for a round (fits in a narrow button). */
function roundTabLabel(label: string): string {
  if (label === "PPI") return "PPI";
  if (label === "CBA") return "CBA";
  if (label === "CBB") return "CBB";
  return `R${label}`;
}

type DraftTeam = { abbr: string; name: string; city: string; full_name: string };

// ── Setup screen ──────────────────────────────────────────────────────────────

function TeamOrderRow({
  team, index, total,
  onUp, onDown,
}: {
  team: DraftTeam; index: number; total: number;
  onUp: () => void; onDown: () => void;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 rounded-lg bg-gray-800/50 hover:bg-gray-800/80 transition-colors">
      <span className="text-xs text-gray-500 font-mono w-6 text-right flex-shrink-0">{index + 1}</span>
      <span className="flex-1 text-sm text-gray-200 font-medium">{team.full_name}</span>
      <span className="text-xs text-gray-600 font-mono w-8">{team.abbr}</span>
      <div className="flex gap-1">
        <button
          onClick={onUp}
          disabled={index === 0}
          className="p-1 rounded hover:bg-gray-700 text-gray-500 hover:text-gray-200 disabled:opacity-20 transition-colors"
        >
          <ArrowUp className="h-3 w-3" />
        </button>
        <button
          onClick={onDown}
          disabled={index === total - 1}
          className="p-1 rounded hover:bg-gray-700 text-gray-500 hover:text-gray-200 disabled:opacity-20 transition-colors"
        >
          <ArrowDown className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

// ── Available prospect row ────────────────────────────────────────────────────

function AvailableRow({ p, onPick, disabled }: { p: Prospect; onPick: () => void; disabled?: boolean }) {
  const gradeCls = p.grades.overall
    ? p.grades.overall >= 60 ? "text-green-400 font-bold"
      : p.grades.overall >= 50 ? "text-blue-400"
      : "text-gray-500"
    : "text-gray-600";

  return (
    <tr
      className={`border-b border-gray-800/50 transition-colors group ${
        disabled
          ? "opacity-40 cursor-not-allowed"
          : "hover:bg-amber-500/5 cursor-pointer"
      }`}
      onClick={disabled ? undefined : onPick}
    >
      <td className="py-2 pl-3 pr-2 text-right">
        {p.draft_rank
          ? <span className="text-[11px] font-mono text-gray-400">#{p.draft_rank}</span>
          : <span className="text-[11px] text-gray-600">NR</span>
        }
      </td>
      <td className="py-2 pr-3">
        <span className={`text-sm font-medium transition-colors ${disabled ? "text-gray-400" : "text-gray-100 group-hover:text-amber-300"}`}>
          {p.full_name}
        </span>
      </td>
      <td className="py-2 pr-2">
        <MockPosBadge pos={p.position ?? "?"} />
      </td>
      <td className="py-2 pr-3 hidden md:table-cell">
        <span className="text-xs text-gray-500 truncate max-w-[140px] block">{p.school ?? "—"}</span>
      </td>
      <td className="py-2 pr-3 hidden lg:table-cell text-xs text-gray-600">
        {p.bats}/{p.throws}
      </td>
      <td className={`py-2 pr-3 text-xs font-mono text-right ${gradeCls}`}>
        {p.grades.overall ?? "—"}
      </td>
      <td className="py-2 pr-3 text-right">
        {!disabled && (
          <span className="opacity-0 group-hover:opacity-100 transition-opacity text-[11px] text-amber-400 font-semibold uppercase tracking-wide">
            Draft →
          </span>
        )}
      </td>
    </tr>
  );
}

// ── Pick result row ───────────────────────────────────────────────────────────

function ManualPickResultRow({
  pick, isCurrentTeam,
}: {
  pick: ManualPick; isCurrentTeam: boolean;
}) {
  return (
    <div className={`flex items-center gap-3 px-3 py-1.5 rounded-lg transition-colors ${
      isCurrentTeam ? "bg-amber-500/10" : "hover:bg-gray-800/30"
    }`}>
      <span className={`text-xs font-mono w-5 text-right flex-shrink-0 ${isCurrentTeam ? "text-amber-500" : "text-gray-600"}`}>
        {pick.roundPick}
      </span>
      <span className={`text-xs font-medium w-10 flex-shrink-0 ${isCurrentTeam ? "text-amber-400" : "text-gray-500"}`}>
        {pick.teamAbbr}
      </span>
      <span className={`text-sm font-medium flex-1 min-w-0 truncate ${isCurrentTeam ? "text-amber-100" : "text-gray-200"}`}>
        {pick.playerName}
      </span>
      <MockPosBadge pos={pick.position ?? "?"} />
    </div>
  );
}

// ── Team needs indicator ──────────────────────────────────────────────────────

function TeamNeeds({ teamAbbr, picks }: { teamAbbr: string; picks: ManualPick[] }) {
  const teamPicks = picks.filter(p => p.teamAbbr === teamAbbr);
  const pickedPos = new Set(teamPicks.map(p => p.position).filter(Boolean));
  const allPos = ["SP", "C", "SS", "CF", "RP", "1B", "2B", "3B", "LF", "RF", "DH"];
  const unfilled = allPos.filter(p => !pickedPos.has(p));

  return (
    <div className="flex flex-wrap gap-1">
      {teamPicks.length === 0 ? (
        <span className="text-xs text-gray-600 italic">No picks yet</span>
      ) : (
        unfilled.slice(0, 8).map(pos => (
          <span key={pos} className="text-[10px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500 border border-gray-700">
            {pos}
          </span>
        ))
      )}
    </div>
  );
}

// ── Main manual mock draft panel ──────────────────────────────────────────────

function ManualMockDraftPanel() {
  const [phase, setPhase] = useState<"setup" | "drafting">("setup");
  const [draftOrder, setDraftOrder] = useState<DraftTeam[]>([]);
  const [picks, setPicks] = useState<ManualPick[]>([]);
  const [draftedIds, setDraftedIds] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [posFilter, setPosFilter] = useState("");
  const [viewRound, setViewRound] = useState<string>("1");
  const [sortingStandings, setSortingStandings] = useState(false);
  const [highlightAbbr, setHighlightAbbr] = useState("");
  const [controlledTeamAbbr, setControlledTeamAbbr] = useState<string>("");
  const [draftGrade, setDraftGrade] = useState<DraftGradeResponse | null>(null);
  const [gradingDraft, setGradingDraft] = useState(false);
  const [showGradePanel, setShowGradePanel] = useState(false);

  // ── Data fetching ──────────────────────────────────────────────────────────
  const { data: teamsData, isLoading: teamsLoading } = useQuery({
    queryKey: ["teams", "MLB"],
    queryFn: () => teamsApi.list("MLB"),
  });

  const { data: prospectsData, isLoading: prospectsLoading } = useQuery({
    queryKey: ["draft-prospects-full"],
    queryFn: () =>
      scoutingApi.listProspects({ level: "draft_prospect", limit: 800 }).then(r => r.data),
  });

  const allTeams = useMemo(
    () => (teamsData?.data?.teams ?? []).sort((a, b) => a.full_name.localeCompare(b.full_name)),
    [teamsData],
  );
  const allProspects: Prospect[] = prospectsData?.prospects ?? [];

  // Seed draft order once teams load — default to official 2026 order
  useEffect(() => {
    if (allTeams.length > 0 && draftOrder.length === 0) {
      const mapped = allTeams.map(t => ({
        abbr: t.abbreviation,
        name: t.name,
        city: t.city || "",
        full_name: t.full_name,
      }));
      setDraftOrder(sortByDraftOrder(mapped));
    }
  }, [allTeams, draftOrder.length]);

  // ── Sort by standings ──────────────────────────────────────────────────────
  const handleSortByStandings = async () => {
    setSortingStandings(true);
    try {
      const res = await standingsApi.get(2026);
      const pctMap: Record<string, number> = {};
      for (const conf of res.data.conferences) {
        for (const div of conf.divisions) {
          for (const team of div.teams) {
            // standings uses `alias`, teams uses `abbreviation` — try both
            pctMap[team.alias.toUpperCase()] = team.pct;
            pctMap[team.full_name.toUpperCase()] = team.pct;
          }
        }
      }
      setDraftOrder(prev =>
        [...prev].sort((a, b) => {
          const pa = pctMap[a.abbr.toUpperCase()] ?? pctMap[a.full_name.toUpperCase()] ?? 0.5;
          const pb = pctMap[b.abbr.toUpperCase()] ?? pctMap[b.full_name.toUpperCase()] ?? 0.5;
          return pa - pb; // worst record picks first
        }),
      );
    } catch {
      // standings unavailable — leave order as-is
    } finally {
      setSortingStandings(false);
    }
  };

  const moveTeam = useCallback((idx: number, dir: -1 | 1) => {
    setDraftOrder(prev => {
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  }, []);

  // ── Draft slots (flat ordered pick sequence incl. CBA / CBB) ──────────────
  const slots = useMemo(() => buildDraftSlots(draftOrder, MOCK_ROUNDS), [draftOrder]);
  const allRoundLabels = useMemo(() => {
    const seen = new Set<string>();
    return slots.map(s => s.roundLabel).filter(l => { if (seen.has(l)) return false; seen.add(l); return true; });
  }, [slots]);

  // ── Draft mechanics ────────────────────────────────────────────────────────
  const totalPicks = slots.length;
  const currentOverall = picks.length + 1;
  const currentSlot = picks.length < slots.length ? slots[picks.length] : null;
  const currentRoundLabel = currentSlot?.roundLabel ?? "1";
  const currentRoundPick = currentSlot?.roundPick ?? 1;
  const currentTeam: DraftTeam | null = currentSlot
    ? (draftOrder.find(t => t.abbr === currentSlot.teamAbbr) ?? {
        abbr: currentSlot.teamAbbr,
        name: currentSlot.teamName,
        city: "",
        full_name: currentSlot.teamName,
      })
    : null;
  const isComplete = picks.length >= totalPicks;

  // Advance view round automatically when a new round starts
  const prevRoundRef = useRef<string>("1");
  useEffect(() => {
    if (currentRoundLabel !== prevRoundRef.current) {
      setViewRound(currentRoundLabel);
      prevRoundRef.current = currentRoundLabel;
    }
  }, [currentRoundLabel]);

  // ── Controlled-team mode ──────────────────────────────────────────────────
  // When the user has chosen a team, all other picks are handled by AI.
  const isMyTurn = !controlledTeamAbbr || controlledTeamAbbr === "ALL" || currentSlot?.teamAbbr === controlledTeamAbbr;

  // Auto-advance AI picks: fire 350ms after each pick lands when it's not the user's turn
  useEffect(() => {
    if (phase !== "drafting" || isComplete || !controlledTeamAbbr || controlledTeamAbbr === "ALL") return;
    if (currentSlot?.teamAbbr === controlledTeamAbbr) return; // user's turn — do nothing
    const timer = setTimeout(() => {
      const top = allProspects.find(p => !draftedIds.has(p.id));
      if (top) makePick(top);
    }, 350);
    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picks.length, phase, isComplete, controlledTeamAbbr, currentSlot?.teamAbbr]);

  // Skip ahead through all AI picks until user's team is on the clock
  const skipToMyPick = useCallback(() => {
    if (!controlledTeamAbbr) return;
    let drafted = new Set(draftedIds);
    const newPicks: ManualPick[] = [];
    let i = picks.length;
    while (i < slots.length) {
      const slot = slots[i];
      if (slot.teamAbbr === controlledTeamAbbr) break; // user's turn next
      const top = allProspects.find(p => !drafted.has(p.id));
      if (!top) break;
      newPicks.push({
        overall: slot.overall,
        round: slot.roundLabel,
        roundPick: slot.roundPick,
        teamAbbr: slot.teamAbbr,
        teamName: slot.teamName,
        playerId: top.id,
        playerName: top.full_name,
        position: top.position,
        school: top.school,
        rank: top.draft_rank,
      });
      drafted = new Set([...drafted, top.id]);
      i++;
    }
    if (newPicks.length) {
      setPicks(prev => [...prev, ...newPicks]);
      setDraftedIds(drafted);
    }
  }, [controlledTeamAbbr, draftedIds, picks.length, slots, allProspects]);

  // Available prospects (filtered, undrafted)
  const available = useMemo(() => {
    return allProspects
      .filter(p => !draftedIds.has(p.id))
      .filter(p => !posFilter || p.position === posFilter)
      .filter(p => !search || p.full_name.toLowerCase().includes(search.toLowerCase()));
  }, [allProspects, draftedIds, posFilter, search]);

  const makePick = useCallback((prospect: Prospect) => {
    if (isComplete || !currentSlot) return;
    const pick: ManualPick = {
      overall: currentOverall,
      round: currentRoundLabel,
      roundPick: currentRoundPick,
      teamAbbr: currentSlot.teamAbbr,
      teamName: currentSlot.teamName,
      playerId: prospect.id,
      playerName: prospect.full_name,
      position: prospect.position,
      school: prospect.school,
      rank: prospect.draft_rank,
    };
    setPicks(prev => [...prev, pick]);
    setDraftedIds(prev => new Set([...prev, prospect.id]));
  }, [isComplete, currentSlot, currentOverall, currentRoundLabel, currentRoundPick]);

  const autoPick = useCallback(() => {
    const top = allProspects.find(p => !draftedIds.has(p.id));
    if (top) makePick(top);
  }, [allProspects, draftedIds, makePick]);

  // Auto-fill rest of the current round (including CB rounds)
  const autoFillRound = useCallback(() => {
    let drafted = new Set(draftedIds);
    const newPicks: ManualPick[] = [];
    let i = picks.length;
    // Fill until we leave the current round label
    while (i < slots.length && slots[i].roundLabel === currentRoundLabel) {
      const slot = slots[i];
      const top = allProspects.find(p => !drafted.has(p.id));
      if (!top) break;
      newPicks.push({
        overall: slot.overall,
        round: slot.roundLabel,
        roundPick: slot.roundPick,
        teamAbbr: slot.teamAbbr,
        teamName: slot.teamName,
        playerId: top.id,
        playerName: top.full_name,
        position: top.position,
        school: top.school,
        rank: top.draft_rank,
      });
      drafted = new Set([...drafted, top.id]);
      i++;
    }
    setPicks(prev => [...prev, ...newPicks]);
    setDraftedIds(drafted);
  }, [allProspects, currentRoundLabel, draftedIds, picks.length, slots]);

  // Auto-complete entire draft
  const autoComplete = useCallback(() => {
    let drafted = new Set(draftedIds);
    const newPicks: ManualPick[] = [];
    for (let i = picks.length; i < slots.length; i++) {
      const slot = slots[i];
      const top = allProspects.find(p => !drafted.has(p.id));
      if (!top) break;
      newPicks.push({
        overall: slot.overall,
        round: slot.roundLabel,
        roundPick: slot.roundPick,
        teamAbbr: slot.teamAbbr,
        teamName: slot.teamName,
        playerId: top.id,
        playerName: top.full_name,
        position: top.position,
        school: top.school,
        rank: top.draft_rank,
      });
      drafted = new Set([...drafted, top.id]);
    }
    setPicks(prev => [...prev, ...newPicks]);
    setDraftedIds(drafted);
  }, [allProspects, draftedIds, picks.length, slots]);

  const undoLastPick = useCallback(() => {
    setPicks(prev => {
      if (!prev.length) return prev;
      const last = prev[prev.length - 1];
      setDraftedIds(d => { const n = new Set(d); n.delete(last.playerId); return n; });
      return prev.slice(0, -1);
    });
  }, []);

  const resetDraft = () => {
    setPicks([]);
    setDraftedIds(new Set());
    setViewRound("1");
    setControlledTeamAbbr("");
    setDraftGrade(null);
    setShowGradePanel(false);
    setPhase("setup");
  };

  // Picks grouped by round label
  const picksByRound = useMemo(() => {
    const g: Record<string, ManualPick[]> = {};
    for (const p of picks) (g[p.round] ??= []).push(p);
    return g;
  }, [picks]);

  // ── Team summary for a highlighted team ──────────────────────────────────
  // Default highlight to user's controlled team so their picks are always visible
  const effectiveHighlight = highlightAbbr || controlledTeamAbbr;
  const teamSummaryPicks = useMemo(
    () => picks.filter(p => p.teamAbbr === effectiveHighlight),
    [picks, effectiveHighlight],
  );

  // ── Grade my draft ────────────────────────────────────────────────────────
  const myPicks = useMemo(() => {
    if (!controlledTeamAbbr || controlledTeamAbbr === "ALL") return picks;
    return picks.filter(p => p.teamAbbr === controlledTeamAbbr);
  }, [picks, controlledTeamAbbr]);

  const handleGradeMyDraft = async () => {
    if (!myPicks.length) return;
    setGradingDraft(true);
    setDraftGrade(null);
    const teamInfo = controlledTeamAbbr && controlledTeamAbbr !== "ALL"
      ? draftOrder.find(t => t.abbr === controlledTeamAbbr)
      : null;
    try {
      const res = await draftApi.gradeDraft({
        team_abbr: teamInfo?.abbr ?? "MLB",
        team_name: teamInfo?.full_name ?? "All Teams",
        picks: myPicks.map(p => ({
          round: String(p.round),   // "1", "2", "CBA", "CBB", etc.
          pick_in_round: p.roundPick,
          player_name: p.playerName,
          position: p.position ?? null,
          school: p.school ?? null,
          rank: p.rank ?? null,
        })),
      });
      setDraftGrade(res.data);
      setShowGradePanel(true);
    } catch {
      // silently fail — user can retry
    } finally {
      setGradingDraft(false);
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // SETUP SCREEN
  // ─────────────────────────────────────────────────────────────────────────
  if (phase === "setup") {
    return (
      <div className="flex-1 overflow-y-auto p-6 max-w-2xl mx-auto w-full space-y-5">
        <div>
          <h2 className="text-xl font-bold text-gray-100 mb-1">2026 Manual Mock Draft</h2>
          <p className="text-sm text-gray-500">
            20 rounds · 30 teams · {MOCK_ROUNDS * 30} total picks.
          </p>
        </div>

        {/* Official order notice */}
        <div className="flex items-start gap-3 bg-amber-950/30 border border-amber-800/40 rounded-xl px-4 py-3">
          <CheckCircle2 className="h-4 w-4 text-amber-400 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm text-amber-300 font-medium">Official 2026 MLB Draft Order loaded</p>
            <p className="text-xs text-amber-700 mt-0.5">
              R1: White Sox #1 → Brewers #25 (25 teams, no CBT teams) · PPI: Braves/Mets/Astros (26-28) · CBA: 9 picks incl. Yankees+Phillies (29-37) · R2 leads with Rockies, Blue Jays, Dodgers · CBB after R2.
            </p>
          </div>
        </div>

        {/* Team selector */}
        <div className="space-y-2">
          <label className="text-sm font-semibold text-gray-200">Choose your team</label>
          <p className="text-xs text-gray-500">You control this team's picks — AI handles everyone else.</p>
          <select
            value={controlledTeamAbbr}
            onChange={e => setControlledTeamAbbr(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-500 transition-colors"
          >
            <option value="">— Select a team —</option>
            <option value="ALL">🎮 All Teams (Full Manual)</option>
            {draftOrder.map(t => (
              <option key={t.abbr} value={t.abbr}>{t.full_name} ({t.abbr})</option>
            ))}
          </select>
          {controlledTeamAbbr === "ALL" && (
            <div className="flex items-center gap-2 mt-1">
              <CheckCircle2 className="h-3.5 w-3.5 text-green-400" />
              <span className="text-xs text-green-400">Full manual mode — you control every pick for all 30 teams.</span>
            </div>
          )}
          {controlledTeamAbbr && controlledTeamAbbr !== "ALL" && (
            <div className="flex items-center gap-2 mt-1">
              <CheckCircle2 className="h-3.5 w-3.5 text-green-400" />
              <span className="text-xs text-green-400">
                You are controlling <strong>{draftOrder.find(t => t.abbr === controlledTeamAbbr)?.full_name}</strong> — AI will auto-pick for all other teams.
              </span>
            </div>
          )}
        </div>

        {/* Sort by standings button */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleSortByStandings}
            disabled={sortingStandings || teamsLoading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-gray-800 border border-gray-700 text-sm text-gray-300 hover:border-amber-500/60 hover:text-amber-300 disabled:opacity-50 transition-colors"
          >
            {sortingStandings ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <TrendingUp className="h-3.5 w-3.5" />}
            Re-sort by live 2026 standings
          </button>
          <span className="text-xs text-gray-600">· or reorder manually with arrows</span>
        </div>

        {/* Draft order list */}
        <div className="space-y-1.5 max-h-[50vh] overflow-y-auto pr-1">
          {teamsLoading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2 className="h-5 w-5 animate-spin text-amber-400" />
            </div>
          ) : (
            draftOrder.map((team, i) => (
              <TeamOrderRow
                key={team.abbr}
                team={team}
                index={i}
                total={draftOrder.length}
                onUp={() => moveTeam(i, -1)}
                onDown={() => moveTeam(i, 1)}
              />
            ))
          )}
        </div>

        {/* Start button */}
        <button
          onClick={() => setPhase("drafting")}
          disabled={draftOrder.length < 2 || prospectsLoading || allProspects.length === 0 || !controlledTeamAbbr}
          className="w-full flex items-center justify-center gap-2 py-3 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-colors"
        >
          {prospectsLoading ? (
            <><Loader2 className="h-4 w-4 animate-spin" />Loading prospects…</>
          ) : !controlledTeamAbbr ? (
            <><User className="h-4 w-4" />Select a team to get started</>
          ) : controlledTeamAbbr === "ALL" ? (
            <><BookOpen className="h-4 w-4" />Start Full Manual Draft — {allProspects.length} prospects</>
          ) : (
            <><BookOpen className="h-4 w-4" />Start Draft as {draftOrder.find(t => t.abbr === controlledTeamAbbr)?.name} — {allProspects.length} prospects</>
          )}
        </button>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // DRAFT SCREEN
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      {/* ── On-the-clock bar ─────────────────────────────────────────────── */}
      <div className={`shrink-0 px-5 py-3 border-b border-gray-800 flex items-center gap-4 flex-wrap transition-colors ${
        isComplete ? "bg-gray-950" : isMyTurn ? "bg-amber-950/30" : "bg-gray-950"
      }`}>
        {isComplete ? (
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-2 text-green-400">
              <CheckCircle2 className="h-5 w-5" />
              <span className="font-semibold">Draft Complete — {picks.length} picks made</span>
            </div>
            {myPicks.length > 0 && (
              <button
                onClick={handleGradeMyDraft}
                disabled={gradingDraft}
                className="flex items-center gap-2 px-4 py-1.5 bg-amber-600/20 hover:bg-amber-600/40 border border-amber-500/40 rounded-xl text-sm text-amber-300 font-semibold transition-colors disabled:opacity-60"
              >
                {gradingDraft
                  ? <><Loader2 className="h-4 w-4 animate-spin" />Grading…</>
                  : <><Award className="h-4 w-4" />Grade My Draft</>}
              </button>
            )}
          </div>
        ) : isMyTurn ? (
          /* ── User's turn ── */
          <>
            <div className="flex items-center gap-3">
              <div className="text-[10px] font-bold text-amber-500 uppercase tracking-widest bg-amber-500/15 border border-amber-500/30 rounded px-2 py-0.5">
                Your Pick
              </div>
              <div className="text-base font-bold text-amber-300">{currentTeam?.full_name}</div>
              <div className="text-xs text-gray-500">
                {roundDisplayName(currentRoundLabel)}, Pick {currentRoundPick} · #{currentOverall} overall
              </div>
            </div>
            <div className="flex items-center gap-1.5 flex-wrap ml-auto">
              <TeamNeeds teamAbbr={currentTeam?.abbr ?? ""} picks={picks} />
            </div>
          </>
        ) : (
          /* ── AI's turn ── */
          <>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-gray-500 uppercase tracking-widest bg-gray-800 border border-gray-700 rounded px-2 py-0.5">
                <Loader2 className="h-3 w-3 animate-spin" />AI Drafting
              </div>
              <div className="text-base font-semibold text-gray-400">{currentTeam?.full_name}</div>
              <div className="text-xs text-gray-600">
                {roundDisplayName(currentRoundLabel)}, Pick {currentRoundPick} · #{currentOverall} overall
              </div>
            </div>
          </>
        )}

        {/* Action buttons */}
        <div className="flex items-center gap-2 ml-auto flex-wrap">
          {!isComplete && (
            <>
              {/* When it's the user's turn: show Auto Pick for their own pick */}
              {isMyTurn && (
                <button
                  onClick={autoPick}
                  title="Auto-pick best available for your team"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-300 hover:border-amber-500/50 hover:text-amber-300 transition-colors"
                >
                  <Zap className="h-3.5 w-3.5" />Auto Pick
                </button>
              )}
              {/* When AI is picking: show skip button */}
              {!isMyTurn && (
                <button
                  onClick={skipToMyPick}
                  title="Skip ahead to your next pick"
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-900/40 border border-amber-700/50 text-xs text-amber-300 hover:bg-amber-800/50 hover:border-amber-500/60 transition-colors"
                >
                  <ChevronsRight className="h-3.5 w-3.5" />Skip to my pick
                </button>
              )}
            </>
          )}
          {myPicks.length > 0 && (
            <button
              onClick={handleGradeMyDraft}
              disabled={gradingDraft}
              title="Grade my draft picks"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-800/30 border border-amber-700/50 text-xs text-amber-300 hover:bg-amber-800/50 transition-colors disabled:opacity-50"
            >
              {gradingDraft ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Award className="h-3.5 w-3.5" />}
              Grade
            </button>
          )}
          {picks.length > 0 && (
            <button
              onClick={undoLastPick}
              title="Undo last pick"
              className="p-1.5 rounded-lg bg-gray-800 border border-gray-700 text-gray-500 hover:text-gray-200 transition-colors"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          )}
          <button
            onClick={resetDraft}
            className="p-1.5 rounded-lg bg-gray-800 border border-gray-700 text-gray-500 hover:text-red-400 transition-colors"
            title="Reset draft"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* ── Main content: prospects list + results ───────────────────────── */}
      <div className="flex-1 overflow-hidden flex">

        {/* LEFT: Available prospects ─────────────────────────────────────── */}
        <div className="flex flex-col border-r border-gray-800" style={{ width: "58%" }}>
          {/* Search + filter */}
          <div className="shrink-0 flex gap-2 px-4 py-2.5 border-b border-gray-800/60 bg-gray-950/60">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
              <input
                className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-8 pr-3 py-1.5 text-sm focus:outline-none focus:border-amber-500 transition-colors"
                placeholder="Search prospects…"
                value={search}
                onChange={e => setSearch(e.target.value)}
              />
            </div>
            <select
              value={posFilter}
              onChange={e => setPosFilter(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-amber-500"
            >
              <option value="">All Pos</option>
              {["SP", "RP", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"].map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
            <span className="text-xs text-gray-600 flex items-center px-1">
              {available.length} avail.
            </span>
          </div>

          {/* Prospect table */}
          <div className="flex-1 overflow-y-auto relative">
            {/* AI-picking overlay banner */}
            {!isComplete && !isMyTurn && (
              <div className="sticky top-0 z-20 flex items-center gap-2 px-4 py-2 bg-gray-900/95 border-b border-gray-700/50 text-xs text-gray-500">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-600" />
                <span>AI is picking for <span className="text-gray-400 font-medium">{currentTeam?.full_name}</span> — waiting for your pick…</span>
                <button onClick={skipToMyPick} className="ml-auto text-amber-500 hover:text-amber-300 font-medium underline underline-offset-2 transition-colors">
                  Skip ahead
                </button>
              </div>
            )}
            {isComplete ? (
              <div className="flex flex-col items-center justify-center h-40 gap-3 text-gray-500">
                <CheckCircle2 className="h-8 w-8 text-green-500" />
                <p className="text-sm">Draft complete!</p>
                <button onClick={resetDraft} className="text-amber-400 text-sm underline">Start over</button>
              </div>
            ) : available.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 gap-2 text-gray-500">
                <User className="h-6 w-6" />
                <p className="text-sm">No prospects match filters.</p>
              </div>
            ) : (
              <table className="w-full">
                <thead className="sticky top-0 bg-gray-900 z-10">
                  <tr className="border-b border-gray-800 text-[11px] text-gray-500 uppercase tracking-wider">
                    <th className="py-2 pl-3 pr-2 text-right w-10">#</th>
                    <th className="py-2 pr-3 text-left">Player</th>
                    <th className="py-2 pr-2 text-center w-10">Pos</th>
                    <th className="py-2 pr-3 text-left hidden md:table-cell">School</th>
                    <th className="py-2 pr-3 hidden lg:table-cell text-left">B/T</th>
                    <th className="py-2 pr-3 text-right w-10">OVR</th>
                    <th className="py-2 pr-3 w-12"></th>
                  </tr>
                </thead>
                <tbody>
                  {available.slice(0, 200).map(p => (
                    <AvailableRow
                      key={p.id}
                      p={p}
                      onPick={() => makePick(p)}
                      disabled={!isMyTurn}
                    />
                  ))}
                  {available.length > 200 && (
                    <tr>
                      <td colSpan={7} className="py-3 text-center text-xs text-gray-600 italic">
                        {available.length - 200} more — narrow with search or position filter
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* RIGHT: Draft results ───────────────────────────────────────────── */}
        <div className="flex flex-col overflow-hidden" style={{ width: "42%" }}>
          {/* Round tabs */}
          <div className="shrink-0 border-b border-gray-800 overflow-x-auto">
            <div className="flex px-3 py-1.5 gap-1 min-w-max">
              {/* Team filter */}
              <div className="relative mr-2">
                <select
                  value={highlightAbbr}
                  onChange={e => setHighlightAbbr(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1 text-[11px] focus:outline-none focus:border-amber-500 pr-5"
                >
                  <option value="">All teams</option>
                  {draftOrder.map(t => (
                    <option key={t.abbr} value={t.abbr}>{t.abbr}</option>
                  ))}
                </select>
              </div>
              {allRoundLabels.map(label => {
                const count = picksByRound[label]?.length ?? 0;
                const isCurrent = label === currentRoundLabel && !isComplete;
                const isBonus = label === "PPI" || label === "CBA" || label === "CBB";
                return (
                  <button
                    key={label}
                    onClick={() => setViewRound(label)}
                    className={`px-2.5 py-1 rounded text-[11px] font-medium transition-colors relative flex-shrink-0 ${
                      viewRound === label
                        ? isBonus
                          ? "bg-blue-600/30 text-blue-300 border border-blue-500/40"
                          : "bg-amber-600/30 text-amber-300 border border-amber-500/40"
                        : count > 0
                          ? isBonus ? "text-blue-400 hover:text-blue-200" : "text-gray-400 hover:text-gray-200"
                          : "text-gray-700 cursor-default"
                    }`}
                  >
                    {roundTabLabel(label)}
                    {isCurrent && (
                      <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-amber-500" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Highlighted team summary strip */}
          {effectiveHighlight && teamSummaryPicks.length > 0 && (
            <div className="shrink-0 px-3 py-2 border-b border-amber-800/30 bg-amber-950/20">
              <p className="text-[11px] text-amber-500 font-semibold uppercase tracking-wider mb-1.5">
                {draftOrder.find(t => t.abbr === effectiveHighlight)?.full_name} picks
                {effectiveHighlight === controlledTeamAbbr && (
                  <span className="ml-2 font-normal text-amber-700">(your team)</span>
                )}
              </p>
              <div className="space-y-1 max-h-28 overflow-y-auto">
                {teamSummaryPicks.map(p => (
                  <div key={p.overall} className="flex items-center gap-2 text-xs">
                    <span className="text-amber-700 font-mono w-16 flex-shrink-0">{roundTabLabel(p.round)} #{p.overall}</span>
                    <span className="text-amber-200 font-medium truncate">{p.playerName}</span>
                    <MockPosBadge pos={p.position ?? "?"} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Picks for viewed round */}
          <div className="flex-1 overflow-y-auto px-3 py-2 space-y-0.5">
            {(picksByRound[viewRound] ?? []).length === 0 ? (
              <div className="flex items-center justify-center h-24 text-gray-600 text-sm">
                {!picksByRound[viewRound] && !isComplete
                  ? "Picks will appear here as you draft."
                  : "No picks in this round yet."}
              </div>
            ) : (
              (picksByRound[viewRound] ?? []).map(pick => (
                <ManualPickResultRow
                  key={pick.overall}
                  pick={pick}
                  isCurrentTeam={pick.teamAbbr === effectiveHighlight}
                />
              ))
            )}
          </div>

          {/* Progress bar */}
          <div className="shrink-0 px-3 pb-2 pt-1 border-t border-gray-800 bg-gray-950/60">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] text-gray-600">
                {picks.length} / {totalPicks} picks
              </span>
              <span className="text-[11px] text-gray-600">
                {draftedIds.size} drafted · {allProspects.length - draftedIds.size} available
              </span>
            </div>
            <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-500 rounded-full transition-all duration-300"
                style={{ width: `${(picks.length / totalPicks) * 100}%` }}
              />
            </div>
          </div>
        </div>

      </div>

      {/* ── Draft grade panel ──────────────────────────────────────────────── */}
      {showGradePanel && draftGrade && (
        <div className="shrink-0 border-t border-amber-800/40 bg-amber-950/20 overflow-y-auto max-h-80">
          <div className="px-5 py-4">
            {/* Header */}
            <div className="flex items-center gap-3 mb-4">
              <Award className="h-5 w-5 text-amber-400" />
              <h3 className="text-sm font-semibold text-gray-200">Draft Class Grade</h3>
              {controlledTeamAbbr && controlledTeamAbbr !== "ALL" && (
                <span className="text-xs text-amber-600">{draftOrder.find(t => t.abbr === controlledTeamAbbr)?.full_name}</span>
              )}
              <div className="ml-auto flex items-center gap-3">
                <span className={`text-2xl font-bold ${
                  draftGrade.overall_grade.startsWith("A") ? "text-green-400"
                  : draftGrade.overall_grade.startsWith("B") ? "text-blue-400"
                  : draftGrade.overall_grade.startsWith("C") ? "text-amber-400"
                  : "text-red-400"
                }`}>{draftGrade.overall_grade}</span>
                <button onClick={() => setShowGradePanel(false)} className="text-gray-500 hover:text-gray-300 transition-colors">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            {/* Summary */}
            <p className="text-sm text-gray-300 mb-4 leading-relaxed">{draftGrade.summary}</p>
            {/* Pick grades */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {draftGrade.pick_grades.map((pg, i) => (
                <div key={i} className="flex items-start gap-2.5 px-3 py-2 bg-gray-900/60 rounded-xl border border-gray-800">
                  <span className={`text-sm font-bold w-7 flex-shrink-0 ${
                    pg.grade.startsWith("A") ? "text-green-400"
                    : pg.grade.startsWith("B") ? "text-blue-400"
                    : pg.grade.startsWith("C") ? "text-amber-400"
                    : "text-red-400"
                  }`}>{pg.grade}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 mb-0.5">
                      <span className="text-xs font-semibold text-gray-200 truncate">{pg.player_name}</span>
                      <span className="text-[10px] text-amber-600 flex-shrink-0">{roundTabLabel(String(pg.round))}</span>
                    </div>
                    <p className="text-[11px] text-gray-500 leading-snug">{pg.note}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

function MockDraftPlanner() {
  const [activeTab, setActiveTab] = useState<"prospects" | "planner" | "mock" | "manual">("prospects");
  const [search, setSearch]           = useState("");
  const [debouncedSearch, setDebounced] = useState("");
  const [position, setPosition]       = useState("");
  const [country, setCountry]         = useState("");
  const [school, setSchool]           = useState("");
  const [schoolClass, setSchoolClass] = useState("");
  const [page, setPage]               = useState(0);
  const [selected, setSelected]       = useState<Prospect | null>(null);

  const handleSearch = useCallback((val: string) => {
    setSearch(val);
    clearTimeout((handleSearch as any)._t);
    (handleSearch as any)._t = setTimeout(() => { setDebounced(val); setPage(0); }, 300);
  }, []);

  const { data, isLoading } = useQuery({
    queryKey: ["draft-prospects", debouncedSearch, position, country, school, schoolClass, page],
    queryFn: () =>
      scoutingApi.listProspects({
        level: "draft_prospect",
        search: debouncedSearch || undefined,
        position: position || undefined,
        country: country || undefined,
        school: school || undefined,
        school_class: schoolClass || undefined,
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }).then(r => r.data),
    placeholderData: prev => prev,
  });

  const prospects   = data?.prospects ?? [];
  const total       = data?.total ?? 0;
  const totalPages  = Math.ceil(total / PAGE_SIZE);

  const clearFilters = () => {
    setSearch(""); setDebounced(""); setPosition("");
    setCountry(""); setSchool(""); setSchoolClass(""); setPage(0);
  };
  const hasFilters = !!(search || position || country || school || schoolClass);

  return (
    <div className="-m-6 flex flex-col h-screen overflow-hidden">
      {/* ── Tab bar ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-1 px-5 pt-3 pb-0 border-b border-gray-800 shrink-0 bg-gray-950">
        <BookOpen className="h-5 w-5 text-amber-400 mr-2 shrink-0" />
        <h1 className="text-lg font-bold mr-4">Draft</h1>
        {([
          { key: "prospects", label: "Prospect Database" },
          { key: "planner",   label: "Team Draft Plan" },
          { key: "mock",      label: "AI Mock Draft" },
          { key: "manual",    label: "Manual Mock Draft" },
        ] as const).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap ${
              activeTab === key
                ? "border-amber-500 text-amber-400"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Planner tab ─────────────────────────────────────────────────────── */}
      {activeTab === "planner" && (
        <div className="flex-1 overflow-hidden flex">
          <DraftPlannerPanel />
        </div>
      )}

      {/* ── AI Mock draft tab ───────────────────────────────────────────────── */}
      {activeTab === "mock" && (
        <div className="flex-1 overflow-hidden flex">
          <MockDraftPanel />
        </div>
      )}

      {/* ── Manual mock draft tab ───────────────────────────────────────────── */}
      {activeTab === "manual" && (
        <div className="flex-1 overflow-hidden flex">
          <ManualMockDraftPanel />
        </div>
      )}

      {/* ── Prospect browser tab ────────────────────────────────────────────── */}
      {activeTab === "prospects" && (
      <div className="flex-1 flex overflow-hidden">
      {/* Left panel — prospect list */}
      <div className={`flex flex-col transition-all duration-300 ${selected ? "w-3/5" : "w-full"}`}>

        {/* Sub-header */}
        <div className="px-5 pt-3 pb-2.5 border-b border-gray-800 shrink-0">
          <p className="text-xs text-gray-400">
            {total.toLocaleString()} prospects · 2026 MLB Draft class
          </p>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap gap-2 px-5 py-2.5 border-b border-gray-800/60 shrink-0 bg-gray-950/50">
          <div className="relative flex-1 min-w-[150px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-8 pr-3 py-1.5 text-sm focus:outline-none focus:border-amber-500 transition-colors"
              placeholder="Search players…"
              value={search}
              onChange={e => handleSearch(e.target.value)}
            />
          </div>

          <div className="relative min-w-[130px]">
            <GraduationCap className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-8 pr-3 py-1.5 text-sm focus:outline-none focus:border-amber-500 transition-colors"
              placeholder="School…"
              value={school}
              onChange={e => { setSchool(e.target.value); setPage(0); }}
            />
          </div>

          <select
            className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-amber-500"
            value={schoolClass}
            onChange={e => { setSchoolClass(e.target.value); setPage(0); }}
          >
            <option value="">All Classes</option>
            {SCHOOL_CLASSES.map(({ value, label }) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>

          <select
            className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-amber-500"
            value={position}
            onChange={e => { setPosition(e.target.value); setPage(0); }}
          >
            <option value="">All Positions</option>
            {POSITIONS.map(pos => <option key={pos} value={pos}>{pos}</option>)}
          </select>

          <select
            className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-amber-500"
            value={country}
            onChange={e => { setCountry(e.target.value); setPage(0); }}
          >
            <option value="">All Countries</option>
            <option value="Dominican Republic">Dominican Republic</option>
            <option value="Venezuela">Venezuela</option>
            <option value="Cuba">Cuba</option>
            <option value="Mexico">Mexico</option>
            <option value="Panama">Panama</option>
            <option value="Colombia">Colombia</option>
            <option value="Japan">Japan</option>
            <option value="South Korea">South Korea</option>
            <option value="Taiwan">Taiwan</option>
            <option value="Puerto Rico">Puerto Rico</option>
            <option value="Canada">Canada</option>
          </select>

          {hasFilters && (
            <button
              onClick={clearFilters}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-gray-800 border border-gray-700 text-xs text-gray-400 hover:text-gray-200 transition-colors"
            >
              <X className="h-3 w-3" /> Clear
            </button>
          )}
        </div>

        {/* Table */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-40">
              <RefreshCw className="h-6 w-6 animate-spin text-amber-400" />
            </div>
          ) : prospects.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 gap-2">
              <User className="h-8 w-8 text-gray-600" />
              <p className="text-gray-500 text-sm">No prospects match your filters.</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="sticky top-0 bg-gray-900 z-10">
                <tr className="border-b border-gray-800 text-gray-500 text-xs">
                  <th className="text-left py-2.5 pl-4 pr-3">Player</th>
                  <th className="text-left py-2.5 pr-3">Pos / B/T</th>
                  <th className="text-left py-2.5 pr-3 hidden md:table-cell">Age / Size</th>
                  <th className="text-left py-2.5 pr-3 hidden lg:table-cell">School / Class</th>
                  <th className="text-center py-2.5 pr-3">Pick</th>
                  <th className="text-left py-2.5 pr-4 hidden xl:table-cell">Bonus / Stats</th>
                </tr>
              </thead>
              <tbody>
                {prospects.map(p => (
                  <ProspectRow
                    key={p.id}
                    p={p}
                    selected={selected?.id === p.id}
                    onClick={() => setSelected(p)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-gray-800 shrink-0 bg-gray-900/50">
          <span className="text-xs text-gray-500">
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total.toLocaleString()}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="p-1.5 rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="flex items-center px-3 text-xs text-gray-400">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="p-1.5 rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Right panel — player profile */}
      {selected && (
        <div className="w-2/5 border-l border-gray-800 flex flex-col bg-gray-900 overflow-hidden">
          <PlayerProfile prospect={selected} onClose={() => setSelected(null)} />
        </div>
      )}
      </div>
      )}
    </div>
  );
}

// ── Real 2026 Draft Results ─────────────────────────────────────────────────────
// Real completed draft (MLB Stats API), distinct from the mock-draft planner
// above. One pick row can be expanded for an AI-written background/stats
// explanation; selecting a team shows its full class + an AI overall grade.

const REAL_DRAFT_YEAR = 2026;

function draftBonusStr(v: number | null) {
  if (!v) return null;
  return `$${(v / 1_000_000).toFixed(2)}M`;
}

function gradeLetterClass(g: string | null) {
  if (!g) return "text-gray-500";
  if (g.startsWith("A")) return "text-green-400";
  if (g.startsWith("B")) return "text-blue-400";
  if (g.startsWith("C")) return "text-amber-400";
  return "text-red-400";
}

function PickRow({ pick, teamAbbr }: { pick: DraftResultPick; teamAbbr?: string }) {
  const [expanded, setExpanded] = useState(false);

  const explainMutation = useMutation({
    mutationFn: () => draftResultsApi.explainPick(pick.id).then(r => r.data),
  });

  const handleToggle = () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !pick.ai_draft_blurb && !explainMutation.data) {
      explainMutation.mutate();
    }
  };

  const blurb = explainMutation.data?.explanation ?? pick.ai_draft_blurb;

  return (
    <div className="border-b border-gray-800">
      <button
        onClick={handleToggle}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-900/60 transition-colors"
      >
        <span className="w-14 shrink-0 text-xs text-gray-500 font-mono">
          Rd {pick.draft_round}
        </span>
        <span className="w-12 shrink-0 text-xs text-gray-500 font-mono">
          #{pick.draft_pick ?? "—"}
        </span>
        <span className="flex-1 min-w-0">
          <span className="font-medium text-gray-100">{pick.full_name}</span>
          {teamAbbr && <span className="ml-2 text-xs text-gray-500">{teamAbbr}</span>}
        </span>
        <span className="w-10 shrink-0 text-xs text-amber-400 font-mono">{pick.position ?? "—"}</span>
        <span className="hidden sm:block flex-1 min-w-0 text-xs text-gray-400 truncate">
          {pick.school ?? "—"}
        </span>
        <span className="hidden md:block w-20 shrink-0 text-xs text-gray-500 text-right">
          {draftBonusStr(pick.signing_bonus) ?? "—"}
        </span>
        <ChevronDown className={`h-4 w-4 text-gray-500 shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`} />
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 bg-gray-950/50">
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500 mb-2">
            {pick.age && <span>Age {pick.age}</span>}
            {pick.height && pick.weight && <span>{pick.height}, {pick.weight} lbs</span>}
            {pick.bats && pick.throws && <span>B/T: {pick.bats}/{pick.throws}</span>}
            {pick.birth_city && <span>From {pick.birth_city}{pick.birth_country && pick.birth_country !== "USA" ? `, ${pick.birth_country}` : ""}</span>}
            {pick.school_class && <span>{pick.school_class}</span>}
            {pick.draft_rank && <span>Pre-draft rank #{pick.draft_rank}</span>}
          </div>
          {explainMutation.isPending && !blurb ? (
            <div className="flex items-center gap-2 text-xs text-gray-500 py-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>Writing background & stats explanation…</span>
            </div>
          ) : blurb ? (
            <div className="space-y-2">
              {blurb.split("\n\n").map((para, i) => (
                <p key={i} className="text-sm text-gray-300 leading-relaxed">{para}</p>
              ))}
            </div>
          ) : explainMutation.isError ? (
            <p className="text-xs text-red-400">Failed to generate explanation. Try again.</p>
          ) : null}
        </div>
      )}
    </div>
  );
}

function RealDraftResults() {
  const [teamId, setTeamId] = useState<string>("");
  const [round, setRound] = useState<string>("");

  const { data: teamsData } = useQuery({
    queryKey: ["draft-results-teams"],
    queryFn: () => teamsApi.list("MLB").then(r => r.data.teams),
  });
  const teams = teamsData ?? [];
  const teamById = useMemo(() => Object.fromEntries(teams.map(t => [t.id, t])), [teams]);

  const { data: rounds } = useQuery({
    queryKey: ["draft-results-rounds", REAL_DRAFT_YEAR],
    queryFn: () => draftResultsApi.listRounds(REAL_DRAFT_YEAR).then(r => r.data),
  });

  const { data: allPicks, isLoading: picksLoading } = useQuery({
    queryKey: ["draft-results-picks", REAL_DRAFT_YEAR, round],
    queryFn: () => draftResultsApi.listPicks(REAL_DRAFT_YEAR, round ? { round } : undefined).then(r => r.data),
    enabled: !teamId,
  });

  const { data: teamClass, isLoading: teamLoading, refetch: refetchTeamClass } = useQuery({
    queryKey: ["draft-results-team-class", REAL_DRAFT_YEAR, teamId],
    queryFn: () => draftResultsApi.teamClass(REAL_DRAFT_YEAR, teamId).then(r => r.data),
    enabled: !!teamId,
  });

  const gradeMutation = useMutation({
    mutationFn: () => draftResultsApi.gradeTeam(REAL_DRAFT_YEAR, teamId).then(r => r.data),
    onSuccess: () => refetchTeamClass(),
  });

  const selectedTeam = teamId ? teamById[teamId] : null;
  const displayGrade = gradeMutation.data?.grade ?? teamClass?.grade;
  const displayAnalysis = gradeMutation.data?.analysis ?? teamClass?.analysis;

  return (
    <div className="-m-6 flex flex-col h-screen overflow-hidden">
      {/* Filter bar */}
      <div className="flex items-center gap-3 px-5 pt-3 pb-3 border-b border-gray-800 shrink-0 bg-gray-950">
        <BookOpen className="h-5 w-5 text-amber-400 shrink-0" />
        <h1 className="text-lg font-bold mr-2 shrink-0">Draft — {REAL_DRAFT_YEAR} Results</h1>
        <Users className="h-4 w-4 text-gray-500 shrink-0" />
        <select
          value={teamId}
          onChange={(e) => setTeamId(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200"
        >
          <option value="">All Teams — Full Draft Board</option>
          {teams.map(t => (
            <option key={t.id} value={t.id}>{t.full_name}</option>
          ))}
        </select>

        {!teamId && (
          <select
            value={round}
            onChange={(e) => setRound(e.target.value)}
            className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200"
          >
            <option value="">All Rounds</option>
            {(rounds ?? []).map(r => (
              <option key={r} value={r}>Round {r}</option>
            ))}
          </select>
        )}

        {teamId && (
          <button
            onClick={() => gradeMutation.mutate()}
            disabled={gradeMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-sm font-medium hover:bg-amber-500/20 transition-colors disabled:opacity-50 whitespace-nowrap"
          >
            {gradeMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
            {displayGrade ? "Re-grade This Draft" : "Grade This Draft"}
          </button>
        )}
      </div>

      {/* Team grade card */}
      {teamId && (displayGrade || gradeMutation.isPending) && (
        <div className="px-5 py-4 border-b border-gray-800 bg-gray-900/40 shrink-0">
          {gradeMutation.isPending && !displayGrade ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Analyzing {selectedTeam?.full_name}'s draft class…</span>
            </div>
          ) : (
            <div className="flex items-start gap-4">
              <div className="shrink-0 text-center">
                <p className="text-[10px] text-gray-500 uppercase tracking-wide mb-1">Draft Grade</p>
                <span className={`text-3xl font-bold ${gradeLetterClass(displayGrade ?? null)}`}>{displayGrade}</span>
              </div>
              <div className="flex-1 space-y-2">
                {(displayAnalysis ?? "").split("\n\n").map((para, i) => (
                  <p key={i} className="text-sm text-gray-300 leading-relaxed">{para}</p>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Picks list */}
      <div className="flex-1 overflow-y-auto">
        {teamId ? (
          teamLoading ? (
            <div className="flex items-center justify-center h-40 text-gray-500 text-sm">
              <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading {selectedTeam?.full_name}'s picks…
            </div>
          ) : !teamClass?.picks.length ? (
            <div className="flex items-center justify-center h-40 text-gray-500 text-sm">
              No {REAL_DRAFT_YEAR} picks found for this team.
            </div>
          ) : (
            teamClass.picks.map(p => <PickRow key={p.id} pick={p} />)
          )
        ) : picksLoading ? (
          <div className="flex items-center justify-center h-40 text-gray-500 text-sm">
            <Loader2 className="h-4 w-4 animate-spin mr-2" /> Loading {REAL_DRAFT_YEAR} draft board…
          </div>
        ) : !allPicks?.length ? (
          <div className="flex items-center justify-center h-40 text-gray-500 text-sm">
            No {REAL_DRAFT_YEAR} picks loaded yet.
          </div>
        ) : (
          allPicks.map(p => (
            <PickRow key={p.id} pick={p} teamAbbr={p.draft_team_id ? teamById[p.draft_team_id]?.abbreviation : undefined} />
          ))
        )}
      </div>
    </div>
  );
}

// ── Page (top-level 2026 / 2027 switcher) ───────────────────────────────────────

export default function DraftPage() {
  const [year, setYear] = useState<"2026" | "2027">("2026");

  return (
    <>
      {/* Floating year switcher — sits above whichever view is active without
          altering that view's own layout (the 2027 planner below is a
          self-contained full-screen component left completely untouched). */}
      <div className="fixed top-3 right-6 z-50 flex items-center gap-1 bg-gray-950 border border-gray-800 rounded-lg p-1 shadow-lg">
        {(["2026", "2027"] as const).map((y) => (
          <button
            key={y}
            onClick={() => setYear(y)}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors whitespace-nowrap ${
              year === y
                ? "bg-amber-500/20 text-amber-400"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            {y === "2026" ? "2026 Draft (Results)" : "2027 Draft (Planner)"}
          </button>
        ))}
      </div>
      {year === "2026" ? <RealDraftResults /> : <MockDraftPlanner />}
    </>
  );
}
