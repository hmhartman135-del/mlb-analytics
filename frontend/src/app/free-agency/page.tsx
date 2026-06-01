"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  freeAgencyApi,
  type FreeAgent,
  type FreeAgentStats,
  type SpotracFreeAgent,
} from "@/lib/api";
import { UserCheck, Search, ChevronLeft, ChevronRight, Flag, ExternalLink } from "lucide-react";

// ── Constants ──────────────────────────────────────────────────────────────────

const POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "SP", "RP"];
const PAGE_SIZE = 50;

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmt(v: number | null | undefined, d = 3): string {
  if (v == null) return "—";
  return v.toFixed(d);
}
function fmtM(salary: number | null | undefined): string {
  if (salary == null) return "—";
  return salary >= 1_000_000
    ? `$${(salary / 1_000_000).toFixed(1)}M`
    : `$${(salary / 1_000).toFixed(0)}K`;
}
function fmtSvc(v: number | null | undefined): string {
  if (v == null) return "—";
  const full = Math.floor(v);
  const days = Math.round((v - full) * 172);
  return `${full}.${String(days).padStart(3, "0")}`;
}

// ── Stat color helpers ─────────────────────────────────────────────────────────

function wrcColor(v: number | null | undefined) {
  if (v == null) return "text-gray-400";
  if (v >= 140) return "text-green-400";
  if (v >= 115) return "text-blue-400";
  if (v >= 100) return "text-gray-200";
  if (v >= 80)  return "text-amber-400";
  return "text-red-400";
}
function eraColor(v: number | null | undefined) {
  if (v == null) return "text-gray-400";
  if (v < 3.0)  return "text-green-400";
  if (v < 3.75) return "text-blue-400";
  if (v < 4.5)  return "text-gray-200";
  return "text-red-400";
}
function warColor(v: number | null | undefined) {
  if (v == null) return "text-gray-400";
  if (v >= 4)  return "text-green-400";
  if (v >= 2)  return "text-blue-400";
  if (v >= 0)  return "text-gray-200";
  return "text-red-400";
}
function opsColor(v: number | null | undefined) {
  if (v == null) return "text-gray-400";
  if (v >= 0.9)  return "text-green-400";
  if (v >= 0.75) return "text-blue-400";
  if (v >= 0.65) return "text-gray-200";
  return "text-red-400";
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function PosBadge({ pos }: { pos: string | null }) {
  const colors: Record<string, string> = {
    SP: "bg-blue-500/20 text-blue-300 border-blue-500/30",
    RP: "bg-indigo-500/20 text-indigo-300 border-indigo-500/30",
    C:  "bg-amber-500/20 text-amber-300 border-amber-500/30",
    DH: "bg-gray-500/20 text-gray-300 border-gray-500/30",
  };
  const hitter = "bg-emerald-500/20 text-emerald-300 border-emerald-500/30";
  const cls = colors[pos ?? ""] ?? hitter;
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${cls}`}>
      {pos ?? "?"}
    </span>
  );
}

function StatsCells({ stats, position }: { stats: FreeAgentStats | null; position: string | null }) {
  const isPitcher = position === "SP" || position === "RP";

  if (!stats) {
    return <td className="py-3 pr-3 text-gray-600 text-xs" colSpan={6}>No stats</td>;
  }

  if (isPitcher && stats.type === "pitching") {
    return (
      <>
        <td className="py-3 pr-3 text-gray-400 text-xs">{stats.season}</td>
        <td className={`py-3 pr-3 font-mono text-sm ${eraColor(stats.era)}`}>{fmt(stats.era, 2)}</td>
        <td className="py-3 pr-3 font-mono text-sm text-gray-300">{fmt(stats.whip, 2)}</td>
        <td className="py-3 pr-3 font-mono text-sm text-gray-300">{fmt(stats.fip, 2)}</td>
        <td className={`py-3 pr-3 font-mono text-sm ${warColor(stats.war)}`}>{fmt(stats.war, 1)}</td>
        <td className="py-3 pr-3 font-mono text-sm text-gray-300">
          {stats.k_pct != null ? `${(stats.k_pct * 100).toFixed(1)}%` : "—"}
        </td>
      </>
    );
  }

  // Hitter
  return (
    <>
      <td className="py-3 pr-3 text-gray-400 text-xs">{stats.season}</td>
      <td className={`py-3 pr-3 font-mono text-sm ${opsColor(stats.ops)}`}>{fmt(stats.ops, 3)}</td>
      <td className={`py-3 pr-3 font-mono text-sm ${wrcColor(stats.wrc_plus)}`}>
        {stats.wrc_plus != null ? stats.wrc_plus : "—"}
      </td>
      <td className="py-3 pr-3 font-mono text-sm text-gray-300">{stats.home_runs ?? "—"}</td>
      <td className={`py-3 pr-3 font-mono text-sm ${warColor(stats.war)}`}>{fmt(stats.war, 1)}</td>
      <td className="py-3 pr-3 font-mono text-sm text-gray-300">{fmt(stats.xwoba, 3)}</td>
    </>
  );
}

function StatHeader({ position }: { position: string | null }) {
  const isPitcher = position === "SP" || position === "RP";
  if (isPitcher) {
    return (
      <>
        <th className="pb-2 pr-3 font-medium text-gray-500">Szn</th>
        <th className="pb-2 pr-3 font-medium text-gray-500">ERA</th>
        <th className="pb-2 pr-3 font-medium text-gray-500">WHIP</th>
        <th className="pb-2 pr-3 font-medium text-gray-500">FIP</th>
        <th className="pb-2 pr-3 font-medium text-gray-500">WAR</th>
        <th className="pb-2 pr-3 font-medium text-gray-500">K%</th>
      </>
    );
  }
  return (
    <>
      <th className="pb-2 pr-3 font-medium text-gray-500">Szn</th>
      <th className="pb-2 pr-3 font-medium text-gray-500">OPS</th>
      <th className="pb-2 pr-3 font-medium text-gray-500">wRC+</th>
      <th className="pb-2 pr-3 font-medium text-gray-500">HR</th>
      <th className="pb-2 pr-3 font-medium text-gray-500">WAR</th>
      <th className="pb-2 pr-3 font-medium text-gray-500">xwOBA</th>
    </>
  );
}

function FaRow({ player }: { player: FreeAgent }) {
  const isPitcher = player.position === "SP" || player.position === "RP";
  return (
    <tr className="border-b border-gray-800 hover:bg-gray-800/40 transition-colors">
      <td className="py-3 pr-4">
        <div className="font-medium text-gray-100">{player.full_name}</div>
        <div className="text-[11px] text-gray-500 mt-0.5">
          {[player.age ? `Age ${player.age}` : null, player.birth_country].filter(Boolean).join(" · ")}
        </div>
      </td>
      <td className="py-3 pr-3"><PosBadge pos={player.position} /></td>
      <td className="py-3 pr-3 text-gray-400 text-sm">
        {isPitcher
          ? (player.throws ?? "—")
          : `${player.bats ?? "?"}/${player.throws ?? "?"}`}
      </td>
      <td className="py-3 pr-3 font-mono text-sm text-gray-300">{fmtSvc(player.service_time)}</td>
      <td className="py-3 pr-3 font-mono text-sm text-gray-300">{fmtM(player.salary)}</td>
      <td className="py-3 pr-3 text-gray-400 text-xs">{player.team_name ?? "—"}</td>
      <StatsCells stats={player.stats} position={player.position} />
    </tr>
  );
}

function Pagination({
  total, offset, limit, onChange,
}: { total: number; offset: number; limit: number; onChange: (o: number) => void }) {
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  if (pages <= 1) return null;
  return (
    <div className="flex items-center gap-3 justify-between mt-4 text-sm text-gray-400">
      <span>{total.toLocaleString()} players · page {page} of {pages}</span>
      <div className="flex gap-2">
        <button
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
          className="p-1.5 rounded hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <button
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
          className="p-1.5 rounded hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ── Filters bar ────────────────────────────────────────────────────────────────

interface Filters {
  search: string;
  position: string;
  country: string;
  minSvc: string;
  teamId: string;
}

function FiltersBar({
  filters, onChange, showTeam = false,
}: {
  filters: Filters;
  onChange: (f: Filters) => void;
  showTeam?: boolean;
}) {
  const set = (key: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    onChange({ ...filters, [key]: e.target.value });

  return (
    <div className="flex flex-wrap gap-3 mb-5">
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
        <input
          className="bg-gray-800 border border-gray-700 rounded-lg pl-8 pr-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 w-44"
          placeholder="Search player…"
          value={filters.search}
          onChange={set("search")}
        />
      </div>
      <select
        className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
        value={filters.position}
        onChange={set("position")}
      >
        <option value="">All positions</option>
        {POSITIONS.map(p => <option key={p} value={p}>{p}</option>)}
      </select>
      <input
        className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 w-36"
        placeholder="Country…"
        value={filters.country}
        onChange={set("country")}
      />
      <input
        className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 w-32"
        placeholder="Min svc (yrs)"
        type="number"
        min={0}
        step={0.5}
        value={filters.minSvc}
        onChange={set("minSvc")}
      />
    </div>
  );
}

// ── Current FAs tab ────────────────────────────────────────────────────────────

function CurrentFAs() {
  const [filters, setFilters] = useState<Filters>({
    search: "", position: "", country: "", minSvc: "", teamId: "",
  });
  const [offset, setOffset] = useState(0);

  const params = {
    search: filters.search || undefined,
    position: filters.position || undefined,
    country: filters.country || undefined,
    min_svc: filters.minSvc ? parseFloat(filters.minSvc) : undefined,
    offset,
    limit: PAGE_SIZE,
  };

  const { data, isLoading, isError } = useQuery({
    queryKey: ["free-agents", "current", params],
    queryFn: () => freeAgencyApi.listCurrent(params).then(r => r.data),
  });

  // Group by position type for the header
  const pitchers = data?.free_agents.filter(p => p.position === "SP" || p.position === "RP") ?? [];
  const hitters  = data?.free_agents.filter(p => p.position !== "SP" && p.position !== "RP") ?? [];

  function TableSection({
    players, label, isPitcher,
  }: { players: FreeAgent[]; label: string; isPitcher: boolean }) {
    if (!players.length) return null;
    return (
      <div className="mb-6">
        <p className="text-[10px] uppercase tracking-widest text-gray-500 mb-2">{label}</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
                <th className="pb-2 pr-4 font-medium">Name</th>
                <th className="pb-2 pr-3 font-medium">Pos</th>
                <th className="pb-2 pr-3 font-medium">{isPitcher ? "T" : "B/T"}</th>
                <th className="pb-2 pr-3 font-medium">Svc</th>
                <th className="pb-2 pr-3 font-medium">Salary</th>
                <th className="pb-2 pr-3 font-medium">Last team</th>
                <StatHeader position={isPitcher ? "SP" : "1B"} />
              </tr>
            </thead>
            <tbody>
              {players.map(p => <FaRow key={p.id} player={p} />)}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  return (
    <>
      <FiltersBar filters={filters} onChange={f => { setFilters(f); setOffset(0); }} />

      {isLoading && (
        <div className="text-gray-500 text-sm py-12 text-center">Loading free agents…</div>
      )}
      {isError && (
        <div className="text-red-400 text-sm py-12 text-center">Failed to load free agents.</div>
      )}
      {data && (
        <>
          <div className="flex items-center gap-2 mb-4">
            <span className="text-sm text-gray-400">{data.total.toLocaleString()} free agents</span>
          </div>
          <TableSection players={hitters}  label="Position Players" isPitcher={false} />
          <TableSection players={pitchers} label="Pitchers"          isPitcher={true}  />
          <Pagination total={data.total} offset={offset} limit={PAGE_SIZE} onChange={setOffset} />
        </>
      )}
    </>
  );
}

// ── Upcoming FAs tab (Spotrac-sourced) ────────────────────────────────────────

function FaTypeBadge({ type }: { type: string | null }) {
  if (!type) return null;
  const colors: Record<string, string> = {
    UFA:    "bg-amber-500/20 text-amber-300 border-amber-500/30",
    ARFA:   "bg-purple-500/20 text-purple-300 border-purple-500/30",
    MILBFA: "bg-gray-500/20 text-gray-400 border-gray-500/30",
  };
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${colors[type] ?? "bg-gray-700 text-gray-400 border-gray-600"}`}>
      {type}
    </span>
  );
}

function UpcomingRow({ fa }: { fa: SpotracFreeAgent }) {
  return (
    <tr className="border-b border-gray-800 hover:bg-gray-800/40 transition-colors">
      <td className="py-3 pr-4">
        <div className="font-medium text-gray-100">{fa.full_name}</div>
        {fa.age != null && (
          <div className="text-[11px] text-gray-500 mt-0.5">Age {fa.age.toFixed(1)}</div>
        )}
      </td>
      <td className="py-3 pr-3"><PosBadge pos={fa.position} /></td>
      <td className="py-3 pr-3 text-gray-400 text-sm font-mono">{fa.former_team ?? "—"}</td>
      <td className="py-3 pr-3"><FaTypeBadge type={fa.fa_type} /></td>
      <td className="py-3 pr-3">
        {fa.signed ? (
          <span className="text-xs px-2 py-0.5 rounded bg-green-500/20 text-green-400 border border-green-500/30">
            Signed
          </span>
        ) : (
          <span className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
            Unsigned
          </span>
        )}
      </td>
      <td className="py-3 pr-3 font-mono text-sm text-gray-300">
        {fa.contract_years != null ? `${fa.contract_years} yr` : "—"}
      </td>
      <td className="py-3 pr-3 font-mono text-sm text-gray-300">
        {fa.aav != null ? fmtM(fa.aav) : "—"}
      </td>
      <td className="py-3 pr-3 font-mono text-sm text-gray-400">
        {fa.contract_value != null ? fmtM(fa.contract_value) : "—"}
      </td>
    </tr>
  );
}

function UpcomingFAs() {
  const [search, setSearch]       = useState("");
  const [position, setPosition]   = useState("");
  const [teamSearch, setTeamSearch] = useState("");
  const [signedFilter, setSignedFilter] = useState<string>("");
  const [offset, setOffset]       = useState(0);

  const params = {
    search:   search || undefined,
    position: position || undefined,
    team:     teamSearch || undefined,
    signed:   signedFilter === "signed" ? true : signedFilter === "unsigned" ? false : undefined,
    offset,
    limit: PAGE_SIZE,
  };

  const { data, isLoading, isError } = useQuery({
    queryKey: ["free-agents", "upcoming", params],
    queryFn: () => freeAgencyApi.listUpcoming(params).then(r => r.data),
  });

  const reset = () => setOffset(0);

  return (
    <>
      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-5">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500" />
          <input
            className="bg-gray-800 border border-gray-700 rounded-lg pl-8 pr-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 w-44"
            placeholder="Search player…"
            value={search}
            onChange={e => { setSearch(e.target.value); reset(); }}
          />
        </div>
        <select
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          value={position}
          onChange={e => { setPosition(e.target.value); reset(); }}
        >
          <option value="">All positions</option>
          {POSITIONS.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <input
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500 w-28"
          placeholder="Team (e.g. NYY)"
          value={teamSearch}
          onChange={e => { setTeamSearch(e.target.value); reset(); }}
        />
        <select
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
          value={signedFilter}
          onChange={e => { setSignedFilter(e.target.value); reset(); }}
        >
          <option value="">All statuses</option>
          <option value="signed">Signed</option>
          <option value="unsigned">Unsigned</option>
        </select>
      </div>

      {isLoading && (
        <div className="text-gray-500 text-sm py-12 text-center">Loading upcoming free agents…</div>
      )}
      {isError && (
        <div className="text-red-400 text-sm py-12 text-center">Failed to load upcoming free agents.</div>
      )}

      {data && (
        <>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <Flag className="h-3.5 w-3.5 text-amber-400" />
              <span>{data.total.toLocaleString()} upcoming free agents · post-2026 season</span>
            </div>
            <a
              href="https://www.spotrac.com/mlb/free-agents"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              <ExternalLink className="h-3 w-3" />
              spotrac.com
            </a>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-gray-500 border-b border-gray-800">
                  <th className="pb-2 pr-4 font-medium">Name</th>
                  <th className="pb-2 pr-3 font-medium">Pos</th>
                  <th className="pb-2 pr-3 font-medium">Team</th>
                  <th className="pb-2 pr-3 font-medium">Type</th>
                  <th className="pb-2 pr-3 font-medium">Status</th>
                  <th className="pb-2 pr-3 font-medium">Yrs</th>
                  <th className="pb-2 pr-3 font-medium">AAV</th>
                  <th className="pb-2 pr-3 font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {data.upcoming.map(fa => <UpcomingRow key={fa.id} fa={fa} />)}
              </tbody>
            </table>
          </div>

          <Pagination total={data.total} offset={offset} limit={PAGE_SIZE} onChange={setOffset} />
        </>
      )}
    </>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────────

type Tab = "current" | "upcoming";

const TABS: { id: Tab; label: string }[] = [
  { id: "current",  label: "Current Free Agents" },
  { id: "upcoming", label: "Upcoming (Post-2026)" },
];

export default function FreeAgencyPage() {
  const [tab, setTab] = useState<Tab>("current");

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <UserCheck className="h-7 w-7 text-blue-400" />
        <h1 className="text-2xl font-bold">Free Agency</h1>
      </div>

      {/* Tab bar */}
      <div className="flex rounded-lg overflow-hidden border border-gray-700 text-sm w-fit mb-6">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-5 py-2 font-medium transition-colors whitespace-nowrap ${
              tab === t.id
                ? "bg-blue-600 text-white"
                : "text-gray-400 hover:text-white hover:bg-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="stat-card">
        {tab === "current"  && <CurrentFAs />}
        {tab === "upcoming" && <UpcomingFAs />}
      </div>
    </div>
  );
}
