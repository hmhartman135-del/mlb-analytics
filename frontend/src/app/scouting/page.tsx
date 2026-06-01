"use client";
import { useState, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { scoutingApi, type Prospect, type CareerRow, type PlayerHistoryResponse } from "@/lib/api";
import {
  Target, Search, ChevronLeft, ChevronRight, FileText, RefreshCw,
  MapPin, Ruler, Weight, GraduationCap, Calendar, User, X,
} from "lucide-react";

// ── constants ──────────────────────────────────────────────────────────────────

const LEVELS = ["AAA", "AA", "A+", "A", "Rookie", "draft_prospect"] as const;
const LEVEL_LABELS: Record<string, string> = {
  AAA: "Triple-A", AA: "Double-A", "A+": "High-A", A: "Single-A",
  Rookie: "Rookie", draft_prospect: "Draft Prospects",
};
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
  { value: "full", label: "Full Report" },
  { value: "brief", label: "Brief" },
  { value: "draft", label: "Draft" },
  { value: "trade", label: "Trade" },
] as const;
const PAGE_SIZE = 50;

const MLB_ORGS: { abbr: string; name: string }[] = [
  { abbr: "ARI", name: "Arizona" },
  { abbr: "ATL", name: "Atlanta" },
  { abbr: "BAL", name: "Baltimore" },
  { abbr: "BOS", name: "Boston" },
  { abbr: "CHC", name: "Chicago (NL)" },
  { abbr: "CWS", name: "Chicago (AL)" },
  { abbr: "CIN", name: "Cincinnati" },
  { abbr: "CLE", name: "Cleveland" },
  { abbr: "COL", name: "Colorado" },
  { abbr: "DET", name: "Detroit" },
  { abbr: "HOU", name: "Houston" },
  { abbr: "KCR", name: "Kansas City" },
  { abbr: "LAA", name: "LA Angels" },
  { abbr: "LAD", name: "LA Dodgers" },
  { abbr: "MIA", name: "Miami" },
  { abbr: "MIL", name: "Milwaukee" },
  { abbr: "MIN", name: "Minnesota" },
  { abbr: "NYM", name: "NY Mets" },
  { abbr: "NYY", name: "NY Yankees" },
  { abbr: "OAK", name: "Oakland" },
  { abbr: "PHI", name: "Philadelphia" },
  { abbr: "PIT", name: "Pittsburgh" },
  { abbr: "SDP", name: "San Diego" },
  { abbr: "SFG", name: "San Francisco" },
  { abbr: "SEA", name: "Seattle" },
  { abbr: "STL", name: "St. Louis" },
  { abbr: "TBR", name: "Tampa Bay" },
  { abbr: "TEX", name: "Texas" },
  { abbr: "TOR", name: "Toronto" },
  { abbr: "WSN", name: "Washington" },
];

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
  if (isNaN(n)) return v;
  return n.toFixed(3).replace(/^0/, "");
}

function fmt2(v: number | string | null | undefined) {
  if (v == null) return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (isNaN(n)) return v;
  return n.toFixed(2);
}

function fmtPct(v: number | null | undefined) {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

// ── Level badge ────────────────────────────────────────────────────────────────

function LevelBadge({ level, status }: { level: string | null; status: string }) {
  if (status === "draft_prospect") {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30">
        Draft
      </span>
    );
  }
  const colors: Record<string, string> = {
    AAA: "bg-purple-500/20 text-purple-400 border-purple-500/30",
    AA: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    "A+": "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
    A: "bg-teal-500/20 text-teal-400 border-teal-500/30",
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
  const cls = rank <= 10
    ? "bg-yellow-500/20 text-yellow-300 border-yellow-500/40"
    : rank <= 50
    ? "bg-orange-500/20 text-orange-300 border-orange-500/40"
    : rank <= 100
    ? "bg-blue-500/20 text-blue-300 border-blue-500/40"
    : "bg-gray-700 text-gray-400 border-gray-600";
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${cls}`}>
      #{rank}
    </span>
  );
}

// ── Inline stats display ───────────────────────────────────────────────────────

function StatLine({ stats }: { stats: Prospect["stats"] }) {
  if (!stats) return <span className="text-gray-600 text-xs">No stats</span>;
  if (stats.type === "batting") {
    return (
      <span className="text-xs text-gray-400">
        {stats.avg != null && <span className="mr-2">.{Math.round(stats.avg * 1000).toString().padStart(3, "0")} AVG</span>}
        {stats.ops != null && <span className="mr-2">{stats.ops.toFixed(3)} OPS</span>}
        {stats.home_runs != null && <span className="mr-2">{stats.home_runs} HR</span>}
        {stats.wrc_plus != null && <span>{stats.wrc_plus.toFixed(0)} wRC+</span>}
      </span>
    );
  }
  return (
    <span className="text-xs text-gray-400">
      {stats.era != null && <span className="mr-2">{stats.era.toFixed(2)} ERA</span>}
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
                <td className="py-1.5 pr-3">
                  <LevelBadge level={r.level} status="" />
                </td>
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

  // Pitching
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
              <td className="py-1.5 pr-3"><LevelBadge level={r.level} status="" /></td>
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

function PlayerProfile({
  prospect,
  onClose,
}: {
  prospect: Prospect;
  onClose: () => void;
}) {
  const [reportType, setReportType] = useState<"full" | "brief" | "draft" | "trade">("full");
  const [activeTab, setActiveTab] = useState<"career" | "report">("career");

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ["playerHistory", prospect.id],
    queryFn: () => scoutingApi.playerHistory(prospect.id).then((r) => r.data),
  });

  const { mutate: genReport, data: reportData, isPending: reportPending } = useMutation({
    mutationFn: () =>
      scoutingApi.generateReport({ player_id: prospect.id, report_type: reportType }).then((r) => r.data),
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
            <LevelBadge level={prospect.level} status={prospect.status} />
            <span className="text-xs text-gray-500">{prospect.position}</span>
            {prospect.birth_country && prospect.birth_country !== "USA" && (
              <span className="px-1.5 py-0.5 rounded text-[10px] bg-violet-500/20 text-violet-400 border border-violet-500/30">
                🌍 {prospect.birth_country}
              </span>
            )}
          </div>
          <h2 className="text-lg font-bold text-white truncate">{prospect.full_name}</h2>
          <p className="text-sm text-gray-400">
            {prospect.age ? `${prospect.age} yrs` : ""}{" "}
            {prospect.bats && `B/T: ${prospect.bats}/${prospect.throws}`}
          </p>
        </div>

        {/* Overall grade */}
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
        {prospect.height && (
          <span className="flex items-center gap-1">
            <Ruler className="h-3 w-3" /> {prospect.height}
          </span>
        )}
        {prospect.weight && (
          <span className="flex items-center gap-1">
            <Weight className="h-3 w-3" /> {prospect.weight} lbs
          </span>
        )}
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
            {prospect.draft_rank && ` · MLB #${prospect.draft_rank}`}
            {prospect.draft_pick && ` · Pick #${prospect.draft_pick}`}
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
          {gradeKeys.map((k) => (
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
                { label: "AVG", val: prospect.stats.avg != null ? fmt3(prospect.stats.avg) : null },
                { label: "OBP", val: prospect.stats.obp != null ? fmt3(prospect.stats.obp) : null },
                { label: "SLG", val: prospect.stats.slg != null ? fmt3(prospect.stats.slg) : null },
                { label: "OPS", val: prospect.stats.ops != null ? fmt3(prospect.stats.ops) : null },
                { label: "HR", val: prospect.stats.home_runs },
                { label: "RBI", val: prospect.stats.rbi },
                { label: "SB", val: prospect.stats.stolen_bases },
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
                { label: "ERA", val: prospect.stats.era != null ? fmt2(prospect.stats.era) : null },
                { label: "FIP", val: prospect.stats.fip != null ? fmt2(prospect.stats.fip) : null },
                { label: "WHIP", val: prospect.stats.whip != null ? fmt2(prospect.stats.whip) : null },
                { label: "IP", val: prospect.stats.innings_pitched != null ? prospect.stats.innings_pitched.toFixed(1) : null },
                { label: "K%", val: prospect.stats.k_pct != null ? fmtPct(prospect.stats.k_pct) : null },
                { label: "BB%", val: prospect.stats.bb_pct != null ? fmtPct(prospect.stats.bb_pct) : null },
                { label: "Velo", val: prospect.stats.avg_fastball_velo != null ? `${prospect.stats.avg_fastball_velo.toFixed(1)}` : null },
                { label: "WAR", val: prospect.stats.war != null ? prospect.stats.war.toFixed(1) : null },
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

      {/* Tab bar */}
      <div className="flex border-b border-gray-800 px-5">
        {(["career", "report"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            className={`px-4 py-2.5 text-xs font-medium capitalize transition-colors border-b-2 -mb-px ${
              activeTab === t
                ? "border-violet-500 text-violet-400"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {t === "career" ? "Career History" : "AI Report"}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {activeTab === "career" ? (
          historyLoading ? (
            <p className="text-gray-500 text-sm">Loading history…</p>
          ) : (
            <CareerTable
              rows={allHistory}
              type={isBatter ? "batting" : "pitching"}
            />
          )
        ) : (
          <div className="space-y-4">
            <div className="flex gap-2 flex-wrap">
              {REPORT_TYPES.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setReportType(value)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                    reportType === value
                      ? "border-violet-500 bg-violet-500/20 text-violet-300"
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
              className="flex items-center gap-2 w-full justify-center bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors"
            >
              {reportPending && <RefreshCw className="h-4 w-4 animate-spin" />}
              Generate AI Scouting Report
            </button>
            {reportData && (
              <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
                <p className="text-xs text-violet-400 font-medium mb-2 uppercase tracking-wide">
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
  p,
  selected,
  onClick,
  showRanked = false,
  rankBadge = null,
}: {
  p: Prospect;
  selected: boolean;
  onClick: () => void;
  showRanked?: boolean;
  rankBadge?: number | null;
}) {
  const isBatter = !["SP", "RP"].includes(p.position ?? "");
  const grades = p.grades;

  return (
    <tr
      onClick={onClick}
      className={`border-b border-gray-800/50 cursor-pointer transition-colors ${
        selected ? "bg-violet-500/10 border-violet-800/50" : "hover:bg-gray-800/40"
      }`}
    >
      {/* Name + level */}
      <td className="py-2.5 pl-4 pr-3">
        <p className="text-sm font-medium text-white">{p.full_name}</p>
        <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
          {rankBadge != null
            ? <RankBadge rank={rankBadge} />
            : (p.draft_rank && <RankBadge rank={p.draft_rank} />)
          }
          <LevelBadge level={p.level} status={p.status} />
          {p.school && !p.draft_rank && (
            <span className="text-[10px] text-gray-500 truncate max-w-[120px]">{p.school}</span>
          )}
          {p.draft_pick && (
            <span className="text-[10px] text-gray-500">Pk #{p.draft_pick}</span>
          )}
          {p.birth_country && p.birth_country !== "USA" && (
            <span className="text-[10px] text-violet-400">{p.birth_country}</span>
          )}
        </div>
      </td>

      {/* Position / B/T */}
      <td className="py-2.5 pr-3 text-xs text-gray-400">
        <p className="font-medium text-gray-300">{p.position ?? "—"}</p>
        <p>{p.bats}/{p.throws}</p>
      </td>

      {/* Age / physical */}
      <td className="py-2.5 pr-3 text-xs text-gray-400 hidden md:table-cell">
        <p>{p.age ? `${p.age}` : "—"}</p>
        <p>{p.height ?? "—"} / {p.weight ? `${p.weight}` : "—"}</p>
      </td>

      {/* Grades or school (ranked mode) */}
      <td className="py-2.5 pr-3 hidden lg:table-cell">
        {showRanked ? (
          <div className="text-xs">
            <p className="text-gray-300 truncate max-w-[160px]">{p.school ?? "—"}</p>
            <p className="text-gray-500">{p.school_class ?? ""}</p>
          </div>
        ) : (
          <div className="flex gap-2">
            {isBatter
              ? (["hit", "power", "speed", "field", "arm"] as const).map((k) => (
                  <span key={k} className={`text-xs ${gradeClass(grades[k])}`}>
                    {grades[k] ?? "—"}
                  </span>
                ))
              : (["fb_velo", "command"] as const).map((k) => (
                  <span key={k} className={`text-xs ${gradeClass(grades[k])}`}>
                    {grades[k] ?? "—"}
                  </span>
                ))}
          </div>
        )}
      </td>

      {/* Pick or overall */}
      <td className="py-2.5 pr-3 text-center">
        {showRanked ? (
          <span className="text-xs text-gray-300">
            {p.draft_pick ? `#${p.draft_pick}` : "—"}
          </span>
        ) : (
          <span className={`inline-block w-9 py-0.5 rounded text-xs text-center ${gradeBadge(grades.overall)}`}>
            {grades.overall ?? "—"}
          </span>
        )}
      </td>

      {/* Bonus or stats */}
      <td className="py-2.5 pr-4 hidden xl:table-cell">
        {showRanked ? (
          p.signing_bonus ? (
            <span className="text-xs text-green-400">
              ${(p.signing_bonus / 1_000_000).toFixed(2)}M
            </span>
          ) : <span className="text-xs text-gray-600">—</span>
        ) : (
          <StatLine stats={p.stats} />
        )}
      </td>
    </tr>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

// tab value → API params
type ScoutingTab = "" | "AAA" | "AA" | "A+" | "A" | "Rookie" | "draft_prospect" | "ranked" | "top100" | "top30";

const TABS: { value: ScoutingTab; label: string; short: string }[] = [
  { value: "",              label: "All",           short: "All" },
  { value: "AAA",          label: "Triple-A",       short: "AAA" },
  { value: "AA",           label: "Double-A",       short: "AA" },
  { value: "A+",           label: "High-A",         short: "A+" },
  { value: "A",            label: "Single-A",       short: "A" },
  { value: "Rookie",       label: "Rookie Ball",    short: "Rookie" },
  { value: "draft_prospect", label: "Draft",        short: "Draft" },
  { value: "ranked",       label: "⭐ Top Ranked",  short: "⭐ Ranked" },
  { value: "top100",       label: "Top 100",         short: "Top 100" },
  { value: "top30",        label: "Top 30 / Org",    short: "Top 30" },
];

export default function ScoutingPage() {
  const [activeTab, setActiveTab] = useState<ScoutingTab>("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [position, setPosition] = useState("");
  const [country, setCountry] = useState("");
  const [school, setSchool] = useState("");
  const [schoolClass, setSchoolClass] = useState("");
  const [page, setPage] = useState(0);
  const [selectedProspect, setSelectedProspect] = useState<Prospect | null>(null);
  const [selectedOrg, setSelectedOrg] = useState("NYY");

  const rankedOnly = activeTab === "ranked";
  const isTop100 = activeTab === "top100";
  const isTop30 = activeTab === "top30";
  const level = (rankedOnly || isTop100 || isTop30) ? "" : activeTab;

  // Debounce search
  const handleSearch = useCallback((val: string) => {
    setSearch(val);
    clearTimeout((handleSearch as any)._t);
    (handleSearch as any)._t = setTimeout(() => {
      setDebouncedSearch(val);
      setPage(0);
    }, 300);
  }, []);

  const { data, isLoading } = useQuery({
    queryKey: ["prospects", debouncedSearch, activeTab, position, country, school, schoolClass, page, selectedOrg],
    queryFn: () =>
      scoutingApi.listProspects({
        search: debouncedSearch || undefined,
        level: level || undefined,
        position: position || undefined,
        country: country || undefined,
        school: school || undefined,
        school_class: schoolClass || undefined,
        ranked_only: rankedOnly || undefined,
        top100: isTop100 || undefined,
        top30_org: isTop30 ? selectedOrg : undefined,
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }).then((r) => r.data),
    placeholderData: (prev) => prev,
  });

  const prospects = data?.prospects ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE);

  const handleFilterChange = (setter: (v: string) => void) => (e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>) => {
    setter(e.target.value);
    setPage(0);
  };

  const switchTab = (tab: ScoutingTab) => {
    setActiveTab(tab);
    setPage(0);
  };

  const clearFilters = () => {
    setSearch(""); setDebouncedSearch(""); setPosition("");
    setCountry(""); setSchool(""); setSchoolClass(""); setPage(0);
  };

  return (
    <div className="-m-6 flex h-screen overflow-hidden">
      {/* Left: prospect database */}
      <div className={`flex flex-col transition-all duration-300 ${selectedProspect ? "w-3/5" : "w-full"}`}>
        {/* Header */}
        <div className="px-5 pt-4 border-b border-gray-800 shrink-0">
          <div className="flex items-center gap-3 mb-3">
            <Target className="h-6 w-6 text-violet-400 shrink-0" />
            <div>
              <h1 className="text-xl font-bold">Scouting</h1>
              <p className="text-xs text-gray-400">
                {total.toLocaleString()} players
                {isTop100 && " · Overall top-100 prospects by age-adjusted score"}
                {isTop30 && ` · ${selectedOrg} top-30 org prospects`}
                {!isTop100 && !isTop30 && " · Minor leagues, college, draft & international"}
              </p>
            </div>
          </div>

          {/* Level tabs */}
          <div className="flex gap-0 overflow-x-auto -mx-5 px-5 scrollbar-none">
            {TABS.map((tab) => {
              const active = activeTab === tab.value;
              return (
                <button
                  key={tab.value}
                  onClick={() => switchTab(tab.value)}
                  className={`shrink-0 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
                    active
                      ? tab.value === "ranked"
                        ? "border-yellow-400 text-yellow-300"
                        : tab.value === "top100"
                        ? "border-amber-500 text-amber-300"
                        : tab.value === "top30"
                        ? "border-orange-500 text-orange-300"
                        : "border-violet-500 text-violet-300"
                      : "border-transparent text-gray-500 hover:text-gray-300"
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Filters row */}
        <div className="flex flex-wrap gap-2 px-5 py-2.5 border-b border-gray-800/60 shrink-0 bg-gray-950/50">
          {/* Search */}
          <div className="relative flex-1 min-w-[150px]">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-8 pr-3 py-1.5 text-sm focus:outline-none focus:border-violet-500 transition-colors"
              placeholder="Search players…"
              value={search}
              onChange={(e) => handleSearch(e.target.value)}
            />
          </div>

          {/* School */}
          <div className="relative min-w-[130px]">
            <GraduationCap className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
            <input
              className="w-full bg-gray-800 border border-gray-700 rounded-lg pl-8 pr-3 py-1.5 text-sm focus:outline-none focus:border-violet-500 transition-colors"
              placeholder="School…"
              value={school}
              onChange={(e) => { setSchool(e.target.value); setPage(0); }}
            />
          </div>

          {/* School class — show only on Draft / Ranked tabs */}
          {(activeTab === "draft_prospect" || activeTab === "ranked" || activeTab === "") && (
            <select
              className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-violet-500"
              value={schoolClass}
              onChange={handleFilterChange(setSchoolClass)}
            >
              <option value="">All Classes</option>
              {SCHOOL_CLASSES.map(({ value, label }) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          )}

          {/* Org selector — show only on Top 30 tab */}
          {isTop30 && (
            <select
              className="bg-gray-800 border border-orange-700/60 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-orange-500 text-orange-300"
              value={selectedOrg}
              onChange={(e) => { setSelectedOrg(e.target.value); setPage(0); }}
            >
              {MLB_ORGS.map(({ abbr, name }) => (
                <option key={abbr} value={abbr}>{abbr} – {name}</option>
              ))}
            </select>
          )}

          {/* Position */}
          <select
            className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-violet-500"
            value={position}
            onChange={handleFilterChange(setPosition)}
          >
            <option value="">All Positions</option>
            {POSITIONS.map((pos) => (
              <option key={pos} value={pos}>{pos}</option>
            ))}
          </select>

          {/* Country */}
          <select
            className="bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:border-violet-500"
            value={country}
            onChange={handleFilterChange(setCountry)}
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

          {(search || position || country || school || schoolClass) && (
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
              <RefreshCw className="h-6 w-6 animate-spin text-violet-400" />
            </div>
          ) : prospects.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 gap-2">
              <User className="h-8 w-8 text-gray-600" />
              <p className="text-gray-500 text-sm">No players match your filters.</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="sticky top-0 bg-gray-900 z-10">
                <tr className="border-b border-gray-800 text-gray-500 text-xs">
                  <th className="text-left py-2.5 pl-4 pr-3">Player</th>
                  <th className="text-left py-2.5 pr-3">Pos / B/T</th>
                  <th className="text-left py-2.5 pr-3 hidden md:table-cell">Age / Size</th>
                  <th className="text-left py-2.5 pr-3 hidden lg:table-cell">
                    {rankedOnly ? "School / Class" : "Grades"}
                  </th>
                  <th className="text-center py-2.5 pr-3">
                    {rankedOnly ? "Pick" : "OVR"}
                  </th>
                  <th className="text-left py-2.5 pr-4 hidden xl:table-cell">
                    {rankedOnly ? "Signing Bonus" : "Stats"}
                  </th>
                </tr>
              </thead>
              <tbody>
                {prospects.map((p) => (
                  <ProspectRow
                    key={p.id}
                    p={p}
                    showRanked={rankedOnly}
                    rankBadge={isTop100 ? p.prospect_rank : isTop30 ? p.org_prospect_rank : null}
                    selected={selectedProspect?.id === p.id}
                    onClick={() => setSelectedProspect(p)}
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
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="p-1.5 rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="flex items-center px-3 text-xs text-gray-400">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="p-1.5 rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Right: player profile panel */}
      {selectedProspect && (
        <div className="w-2/5 border-l border-gray-800 flex flex-col bg-gray-900 overflow-hidden">
          <PlayerProfile
            prospect={selectedProspect}
            onClose={() => setSelectedProspect(null)}
          />
        </div>
      )}
    </div>
  );
}
