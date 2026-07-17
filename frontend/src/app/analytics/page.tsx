"use client";
import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { analyticsApi, teamsApi, type Team } from "@/lib/api";
import { TeamSelector } from "@/components/ui/TeamSelector";
import { SyncBar } from "@/components/ui/SyncBar";
import { TrendingUp, RefreshCw } from "lucide-react";

/* ── formatting helpers ──────────────────────────────────────────────────── */

const fmt  = (v: number | null | undefined, d = 3) =>
  v != null ? v.toFixed(d) : "—";
const fmtP = (v: number | null | undefined) =>
  v != null ? `${(v * 100).toFixed(1)}%` : "—";
const num  = (v: number | null | undefined) =>
  v != null ? String(v) : "—";

function warColor(w: number | null) {
  if (!w) return "#6b7280";
  return w >= 4 ? "#22c55e" : w >= 2 ? "#3b82f6" : w >= 0 ? "#f59e0b" : "#ef4444";
}
function eraColor(v: number | null) {
  if (v == null) return "text-gray-400";
  return v < 3.0 ? "text-green-400" : v < 3.75 ? "text-blue-400" : v < 4.5 ? "text-gray-300" : "text-red-400";
}
function wrcColor(v: number | null) {
  if (v == null) return "text-gray-400";
  return v >= 140 ? "text-green-400" : v >= 115 ? "text-blue-400" : v >= 100 ? "text-gray-300" : v >= 80 ? "text-amber-400" : "text-red-400";
}
function avgColor(v: string | null | undefined) {
  const n = parseFloat(v ?? "0");
  if (!n) return "text-gray-400";
  return n >= 0.280 ? "text-green-400" : n >= 0.250 ? "text-blue-400" : n >= 0.220 ? "text-gray-300" : "text-red-400";
}

/* ── Shared table cell primitives ────────────────────────────────────────── */

function Th({ children, title }: { children: React.ReactNode; title?: string }) {
  return <th className="pb-2 pr-3 font-medium whitespace-nowrap" title={title}>{children}</th>;
}
function Td({ children, mono, gray, right }: { children: React.ReactNode; mono?: boolean; gray?: boolean; right?: boolean }) {
  return (
    <td className={`py-2 pr-3 ${mono ? "font-mono" : ""} ${gray ? "text-gray-400" : ""} ${right ? "text-right" : ""}`}>
      {children}
    </td>
  );
}
function TabBar<T extends string>({
  tabs, active, onChange,
}: { tabs: { id: T; label: string }[]; active: T; onChange: (t: T) => void }) {
  return (
    <div className="flex rounded-lg overflow-hidden border border-gray-700 text-xs">
      {tabs.map(t => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`px-3 py-1.5 transition-colors whitespace-nowrap ${active === t.id ? "bg-amber-600 text-white" : "text-gray-400 hover:text-white hover:bg-gray-700"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

/* ── Page ────────────────────────────────────────────────────────────────── */

const MINOR_LEVELS = ["AAA", "AA", "A+", "A", "Rookie"] as const;
type OrgLevel = "MLB" | (typeof MINOR_LEVELS)[number];

export default function AnalyticsPage() {
  const [orgTeamId, setOrgTeamId]     = useState("");
  const [orgTeamName, setOrgTeamName] = useState("");
  const [level, setLevel]             = useState<OrgLevel>("MLB");
  const [season, setSeason]           = useState(2026);

  const { data: affiliateData } = useQuery({
    queryKey: ["affiliates", orgTeamId],
    queryFn: () => teamsApi.affiliates(orgTeamId).then(r => r.data),
    enabled: !!orgTeamId,
  });
  const affiliates = affiliateData?.affiliates ?? [];

  // Whenever the org (or level) changes, reset back to the big-league club
  // and clear any loaded stats so a stale team's data doesn't linger.
  useEffect(() => {
    setLevel("MLB");
  }, [orgTeamId]);

  const activeTeam: { id: string; label: string } | null =
    level === "MLB"
      ? (orgTeamId ? { id: orgTeamId, label: orgTeamName } : null)
      : (() => {
          const aff = affiliates.find(a => a.level === level);
          return aff ? { id: aff.id, label: `${aff.full_name} (${level})` } : null;
        })();

  const { mutate, data, isPending, reset } = useMutation({
    mutationFn: () => analyticsApi.teamOverview(activeTeam!.id, season).then(r => r.data),
  });

  const handleLevelChange = (lvl: OrgLevel) => {
    setLevel(lvl);
    reset();
  };

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <TrendingUp className="h-7 w-7 text-amber-400" />
        <h1 className="text-2xl font-bold">Analytics</h1>
      </div>

      <SyncBar className="mb-5" />

      <div className="stat-card mb-6 flex flex-wrap gap-4 items-end">
        <div className="flex-1 min-w-48">
          <label className="block text-xs text-gray-400 mb-1">Organization</label>
          <TeamSelector value={orgTeamId} onChange={(id, t) => { setOrgTeamId(id); setOrgTeamName(t.full_name); reset(); }} />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Season</label>
          <input type="number" className="w-32 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-amber-500"
            value={season} min={2020} max={2026} onChange={e => setSeason(Number(e.target.value))} />
        </div>
        <button onClick={() => mutate()} disabled={!activeTeam || isPending}
          className="flex items-center gap-2 bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors">
          {isPending && <RefreshCw className="h-4 w-4 animate-spin" />}
          {activeTeam ? `Load ${activeTeam.label}` : "Select a team first"}
        </button>
      </div>

      {orgTeamId && (
        <div className="mb-6 flex items-center gap-2 flex-wrap">
          <span className="text-xs text-gray-500 mr-1">Level:</span>
          <TabBar
            tabs={[
              { id: "MLB" as OrgLevel, label: "Majors" },
              ...MINOR_LEVELS
                .filter(lvl => affiliates.some(a => a.level === lvl))
                .map(lvl => ({ id: lvl as OrgLevel, label: lvl })),
            ]}
            active={level}
            onChange={handleLevelChange}
          />
        </div>
      )}

      {data && (
        <div className="space-y-8">
          {/* Team summary */}
          <div>
            <p className="text-sm text-gray-400 mb-3">
              {data.team_name} {data.team_level && data.team_level !== "MLB" && (
                <span className="text-amber-400 font-medium">({data.team_level})</span>
              )} · {data.season} season
            </p>
            <div className="grid grid-cols-3 gap-4">
              <StatBox label="Team WAR"  value={data.team_war}        color="text-blue-400" />
              <StatBox label="Avg wRC+"  value={data.avg_wrc_plus}    color="text-emerald-400" />
              <StatBox label="Team FIP"  value={data.team_fip ?? "—"} color="text-amber-400" />
            </div>
          </div>

          {data.hitting_leaderboard?.length  > 0 && <OffenseSection  players={data.hitting_leaderboard} />}
          {data.pitching_leaderboard?.length > 0 && <PitchingSection pitchers={data.pitching_leaderboard} />}
          {data.hitting_leaderboard?.length === 0 && data.pitching_leaderboard?.length === 0 && (
            <p className="text-sm text-gray-500 text-center py-8">No stats found for this team/season.</p>
          )}
        </div>
      )}
    </div>
  );
}

function StatBox({ label, value, color }: { label: string; value: number | string; color: string }) {
  return (
    <div className="stat-card text-center">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   OFFENSE
═══════════════════════════════════════════════════════════════════════════ */

type HitterTab = "counting" | "rates" | "discipline" | "contact" | "splits";

const HITTER_TABS: { id: HitterTab; label: string }[] = [
  { id: "counting",   label: "Counting Stats" },
  { id: "rates",      label: "Rates" },
  { id: "discipline", label: "Plate Discipline" },
  { id: "contact",    label: "Quality of Contact" },
  { id: "splits",     label: "vs LHP / RHP" },
];

function OffenseSection({ players }: { players: any[] }) {
  const [tab, setTab] = useState<HitterTab>("counting");

  const sorted = [...players].sort((a, b) => {
    if (tab === "counting")   return (b.home_runs ?? 0) - (a.home_runs ?? 0);
    if (tab === "rates")      return (b.wrc_plus  ?? 0) - (a.wrc_plus  ?? 0);
    if (tab === "discipline") return (a.k_pct     ?? 1) - (b.k_pct     ?? 1);
    if (tab === "contact")    return (b.hard_hit_pct ?? 0) - (a.hard_hit_pct ?? 0);
    // splits: sort by overall wRC+
    return (b.wrc_plus ?? 0) - (a.wrc_plus ?? 0);
  });

  return (
    <div className="stat-card">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <h2 className="font-semibold text-lg">Offense</h2>
        <TabBar tabs={HITTER_TABS} active={tab} onChange={setTab} />
      </div>
      <div className="overflow-x-auto">
        {tab === "counting"   && <CountingTable   players={sorted} />}
        {tab === "rates"      && <RatesTable      players={sorted} />}
        {tab === "discipline" && <DisciplineTable players={sorted} />}
        {tab === "contact"    && <ContactTable    players={sorted} />}
        {tab === "splits"     && <SplitsTable     players={sorted} />}
      </div>
    </div>
  );
}

/* ── Counting stats: H, 2B, 3B, HR, RBI, BB, K ─────────────────────────── */
function CountingTable({ players }: { players: any[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
          <Th>Player</Th><Th>Pos</Th><Th>B</Th>
          <Th>G</Th><Th>PA</Th><Th>H</Th>
          <Th title="Doubles">2B</Th><Th title="Triples">3B</Th>
          <Th title="Home Runs">HR</Th><Th title="Runs Batted In">RBI</Th>
          <Th title="Walks">BB</Th><Th title="Strikeouts">K</Th>
          <Th>AVG</Th><Th>OBP</Th><Th>SLG</Th>
        </tr>
      </thead>
      <tbody>
        {players.map(p => (
          <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
            <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.name}</td>
            <Td>{p.position}</Td>
            <Td gray>{p.bats}</Td>
            <Td mono>{num(p.games)}</Td>
            <Td mono>{num(p.pa)}</Td>
            <Td mono>{num(p.hits)}</Td>
            <Td mono>{num(p.doubles)}</Td>
            <Td mono>{num(p.triples)}</Td>
            <td className="py-2 pr-3 font-mono font-semibold text-amber-300">{num(p.home_runs)}</td>
            <Td mono>{num(p.rbi)}</Td>
            <Td mono gray>{num(p.walks)}</Td>
            <td className={`py-2 pr-3 font-mono ${(p.strikeouts ?? 0) > 100 ? "text-red-400" : "text-gray-300"}`}>{num(p.strikeouts)}</td>
            <td className={`py-2 pr-3 font-mono ${avgColor(p.avg?.toFixed?.(3) ?? p.avg)}`}>{fmt(p.avg)}</td>
            <Td mono>{fmt(p.obp)}</Td>
            <Td mono>{fmt(p.slg)}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ── Rates / production ──────────────────────────────────────────────────── */
function RatesTable({ players }: { players: any[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
          <Th>Player</Th><Th>Pos</Th><Th>B</Th><Th>G</Th><Th>PA</Th>
          <Th>AVG</Th><Th>OBP</Th><Th>SLG</Th><Th>ISO</Th>
          <Th>wOBA</Th><Th>wRC+</Th><Th>WAR</Th>
        </tr>
      </thead>
      <tbody>
        {players.map(p => (
          <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
            <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.name}</td>
            <Td>{p.position}</Td><Td gray>{p.bats}</Td>
            <Td mono>{num(p.games)}</Td><Td mono>{num(p.pa)}</Td>
            <td className={`py-2 pr-3 font-mono ${avgColor(p.avg?.toFixed?.(3) ?? p.avg)}`}>{fmt(p.avg)}</td>
            <Td mono>{fmt(p.obp)}</Td><Td mono>{fmt(p.slg)}</Td><Td mono>{fmt(p.iso)}</Td>
            <Td mono>{fmt(p.woba)}</Td>
            <td className={`py-2 pr-3 font-mono font-semibold ${wrcColor(p.wrc_plus)}`}>{fmt(p.wrc_plus, 0)}</td>
            <td className="py-2 font-mono font-semibold" style={{ color: warColor(p.war) }}>{fmt(p.war, 1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ── Plate discipline ────────────────────────────────────────────────────── */
function DisciplineTable({ players }: { players: any[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
          <Th>Player</Th><Th>Pos</Th><Th>B</Th><Th>PA</Th>
          <Th title="Strikeout rate">K%</Th>
          <Th title="Walk rate">BB%</Th>
          <Th title="BABIP">BABIP</Th>
          <Th title="Expected BA">xBA</Th>
          <Th title="Expected SLG">xSLG</Th>
          <Th title="Expected wOBA">xwOBA</Th>
          <Th>wRC+</Th>
        </tr>
      </thead>
      <tbody>
        {players.map(p => (
          <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
            <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.name}</td>
            <Td>{p.position}</Td><Td gray>{p.bats}</Td><Td mono>{num(p.pa)}</Td>
            <td className={`py-2 pr-3 font-mono ${(p.k_pct ?? 0) > 0.28 ? "text-red-400" : (p.k_pct ?? 0) < 0.18 ? "text-green-400" : "text-gray-300"}`}>{fmtP(p.k_pct)}</td>
            <td className={`py-2 pr-3 font-mono ${(p.bb_pct ?? 0) >= 0.10 ? "text-green-400" : (p.bb_pct ?? 0) < 0.07 ? "text-red-400" : "text-gray-300"}`}>{fmtP(p.bb_pct)}</td>
            <Td mono>{fmt(p.babip)}</Td>
            <Td mono>{fmt(p.xba)}</Td><Td mono>{fmt(p.xslg)}</Td><Td mono>{fmt(p.xwoba)}</Td>
            <td className={`py-2 font-mono font-semibold ${wrcColor(p.wrc_plus)}`}>{fmt(p.wrc_plus, 0)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr><td colSpan={11} className="pt-2 text-[10px] text-gray-600">K% &lt;18% elite · &gt;28% poor  |  BB% ≥10% elite · &lt;7% poor</td></tr>
      </tfoot>
    </table>
  );
}

/* ── Quality of contact ──────────────────────────────────────────────────── */
function ContactTable({ players }: { players: any[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
          <Th>Player</Th><Th>Pos</Th><Th>B</Th><Th>PA</Th>
          <Th title="Hard-hit rate ≥95mph">Hard Hit%</Th>
          <Th title="Barrel rate">Barrel%</Th>
          <Th title="Isolated power">ISO</Th>
          <Th title="Expected wOBA">xwOBA</Th>
          <Th title="Sprint speed ft/s">Spd</Th>
          <Th>WAR</Th>
        </tr>
      </thead>
      <tbody>
        {players.map(p => (
          <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
            <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.name}</td>
            <Td>{p.position}</Td><Td gray>{p.bats}</Td><Td mono>{num(p.pa)}</Td>
            <td className={`py-2 pr-3 font-mono ${(p.hard_hit_pct ?? 0) >= 40 ? "text-green-400" : (p.hard_hit_pct ?? 0) < 30 ? "text-red-400" : "text-gray-300"}`}>
              {p.hard_hit_pct != null ? `${p.hard_hit_pct.toFixed(1)}%` : "—"}
            </td>
            <td className={`py-2 pr-3 font-mono ${(p.barrel_pct ?? 0) >= 10 ? "text-green-400" : (p.barrel_pct ?? 0) < 5 ? "text-red-400" : "text-gray-300"}`}>
              {p.barrel_pct != null ? `${p.barrel_pct.toFixed(1)}%` : "—"}
            </td>
            <Td mono>{fmt(p.iso)}</Td><Td mono>{fmt(p.xwoba)}</Td>
            <td className={`py-2 pr-3 font-mono ${(p.sprint_speed ?? 0) >= 28 ? "text-green-400" : (p.sprint_speed ?? 0) < 26 ? "text-red-400" : "text-gray-300"}`}>
              {p.sprint_speed != null ? p.sprint_speed.toFixed(1) : "—"}
            </td>
            <td className="py-2 font-mono font-semibold" style={{ color: warColor(p.war) }}>{fmt(p.war, 1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ── vs LHP / RHP splits ─────────────────────────────────────────────────── */
function SplitsTable({ players }: { players: any[] }) {
  const hasSplits = players.some(p => p.vs_lhp || p.vs_rhp);
  if (!hasSplits) {
    return <p className="text-sm text-gray-500 py-4 text-center">Split data not available for this team.</p>;
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
          <Th>Player</Th><Th>B</Th>
          <th className="pb-2 pr-3 text-blue-400/70" colSpan={5}>vs LHP</th>
          <th className="pb-2 pr-3 text-red-400/70"  colSpan={5}>vs RHP</th>
          <Th>Favors</Th>
        </tr>
        <tr className="text-left text-xs text-gray-600 border-b border-gray-800">
          <th className="pb-1.5 pr-3" colSpan={2}></th>
          <th className="pb-1.5 pr-3">PA</th><th className="pb-1.5 pr-3">AVG</th>
          <th className="pb-1.5 pr-3">OBP</th><th className="pb-1.5 pr-3">SLG</th>
          <th className="pb-1.5 pr-3">HR</th>
          <th className="pb-1.5 pr-3">PA</th><th className="pb-1.5 pr-3">AVG</th>
          <th className="pb-1.5 pr-3">OBP</th><th className="pb-1.5 pr-3">SLG</th>
          <th className="pb-1.5 pr-3">HR</th>
          <th className="pb-1.5"></th>
        </tr>
      </thead>
      <tbody>
        {players.map(p => {
          const l = p.vs_lhp;
          const r = p.vs_rhp;
          const lOps = parseFloat(l?.ops ?? "0");
          const rOps = parseFloat(r?.ops ?? "0");
          const favors = l && r ? (lOps > rOps ? "LHP" : "RHP") : null;
          return (
            <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
              <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.name}</td>
              <Td gray>{p.bats}</Td>
              {/* vs LHP */}
              <Td mono gray>{l?.pa ?? "—"}</Td>
              <td className={`py-2 pr-3 font-mono ${avgColor(l?.avg)}`}>{l?.avg ?? "—"}</td>
              <Td mono>{l?.obp ?? "—"}</Td>
              <Td mono>{l?.slg ?? "—"}</Td>
              <td className="py-2 pr-3 font-mono text-amber-300">{l?.hr ?? "—"}</td>
              {/* vs RHP */}
              <Td mono gray>{r?.pa ?? "—"}</Td>
              <td className={`py-2 pr-3 font-mono ${avgColor(r?.avg)}`}>{r?.avg ?? "—"}</td>
              <Td mono>{r?.obp ?? "—"}</Td>
              <Td mono>{r?.slg ?? "—"}</Td>
              <td className="py-2 pr-3 font-mono text-amber-300">{r?.hr ?? "—"}</td>
              {/* Advantage badge */}
              <td className="py-2">
                {favors && (
                  <span className={`px-2 py-0.5 rounded text-[11px] font-bold border ${
                    favors === "LHP"
                      ? "bg-blue-900/30 text-blue-300 border-blue-700/40"
                      : "bg-red-900/30 text-red-300 border-red-700/40"
                  }`}>
                    Hits {favors} better
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   PITCHING
═══════════════════════════════════════════════════════════════════════════ */

type PitcherTab = "core" | "strikeout" | "batted" | "splits";

const PITCHER_TABS: { id: PitcherTab; label: string }[] = [
  { id: "core",     label: "Core Stats" },
  { id: "strikeout", label: "Strikeouts" },
  { id: "batted",   label: "Batted Ball" },
  { id: "splits",   label: "vs LHB / RHB" },
];

function PitchingSection({ pitchers }: { pitchers: any[] }) {
  const [tab, setTab] = useState<PitcherTab>("core");

  const sorted = [...pitchers].sort((a, b) => {
    if (tab === "core")      return (a.fip    ?? 9) - (b.fip    ?? 9);
    if (tab === "strikeout") return (b.k_pct  ?? 0) - (a.k_pct  ?? 0);
    if (tab === "batted")    return (b.gb_pct ?? 0) - (a.gb_pct ?? 0);
    return (a.fip ?? 9) - (b.fip ?? 9);
  });

  return (
    <div className="stat-card">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <h2 className="font-semibold text-lg">Pitching</h2>
        <TabBar tabs={PITCHER_TABS} active={tab} onChange={setTab} />
      </div>
      <div className="overflow-x-auto">
        {tab === "core"      && <PitchingCoreTable   pitchers={sorted} />}
        {tab === "strikeout" && <PitchingKTable      pitchers={sorted} />}
        {tab === "batted"    && <PitchingBattedTable pitchers={sorted} />}
        {tab === "splits"    && <PitchingSplitsTable pitchers={sorted} />}
      </div>
    </div>
  );
}

function PitchingCoreTable({ pitchers }: { pitchers: any[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
          <Th>Pitcher</Th><Th>T</Th><Th>G</Th><Th>IP</Th>
          <Th title="ERA">ERA</Th><Th title="FIP">FIP</Th>
          <Th title="xFIP">xFIP</Th><Th title="WHIP">WHIP</Th>
          <Th title="Batting avg against (approx)">BAA</Th>
          <Th>WAR</Th><Th title="Better vs LHB or RHB">Favors</Th>
        </tr>
      </thead>
      <tbody>
        {pitchers.map(p => (
          <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
            <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.name}</td>
            <Td gray>{p.throws}</Td>
            <Td mono>{num(p.games)}</Td>
            <Td mono>{fmt(p.ip, 1)}</Td>
            <td className={`py-2 pr-3 font-mono font-semibold ${eraColor(p.era)}`}>{fmt(p.era, 2)}</td>
            <td className={`py-2 pr-3 font-mono font-semibold ${eraColor(p.fip)}`}>{fmt(p.fip, 2)}</td>
            <td className={`py-2 pr-3 font-mono ${eraColor(p.xfip)}`}>{fmt(p.xfip, 2)}</td>
            <Td mono>{fmt(p.whip, 3)}</Td>
            <Td mono>{fmt(p.baa)}</Td>
            <td className="py-2 pr-3 font-mono font-semibold" style={{ color: warColor(p.war) }}>{fmt(p.war, 1)}</td>
            <td className="py-2">
              <BetterVsBadge side={p.better_vs} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PitchingKTable({ pitchers }: { pitchers: any[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
          <Th>Pitcher</Th><Th>T</Th><Th>G</Th><Th>IP</Th>
          <Th>K</Th><Th title="K/9">K/9</Th><Th title="K%">K%</Th>
          <Th title="BB%">BB%</Th><Th title="BB/9">BB/9</Th>
          <Th title="HR/9">HR/9</Th><Th title="Avg Velo">Velo</Th>
          <Th title="Better vs LHB or RHB">Favors</Th>
        </tr>
      </thead>
      <tbody>
        {pitchers.map(p => (
          <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
            <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.name}</td>
            <Td gray>{p.throws}</Td>
            <Td mono>{num(p.games)}</Td><Td mono>{fmt(p.ip, 1)}</Td>
            <Td mono>{num(p.strikeouts)}</Td>
            <td className={`py-2 pr-3 font-mono ${(p.k_per_9 ?? 0) >= 10 ? "text-green-400" : (p.k_per_9 ?? 0) < 7 ? "text-red-400" : "text-gray-300"}`}>{fmt(p.k_per_9, 1)}</td>
            <td className={`py-2 pr-3 font-mono ${(p.k_pct ?? 0) >= 0.28 ? "text-green-400" : (p.k_pct ?? 0) < 0.18 ? "text-red-400" : "text-gray-300"}`}>{fmtP(p.k_pct)}</td>
            <td className={`py-2 pr-3 font-mono ${(p.bb_pct ?? 1) <= 0.07 ? "text-green-400" : (p.bb_pct ?? 1) > 0.10 ? "text-red-400" : "text-gray-300"}`}>{fmtP(p.bb_pct)}</td>
            <Td mono>{fmt(p.bb_per_9, 1)}</Td>
            <Td mono>{fmt(p.hr_per_9, 2)}</Td>
            <td className={`py-2 pr-3 font-mono ${(p.avg_fastball_velo ?? 0) >= 96 ? "text-green-400" : (p.avg_fastball_velo ?? 0) < 92 ? "text-red-400" : "text-gray-300"}`}>
              {p.avg_fastball_velo != null ? `${p.avg_fastball_velo.toFixed(1)}` : "—"}
            </td>
            <td className="py-2"><BetterVsBadge side={p.better_vs} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PitchingBattedTable({ pitchers }: { pitchers: any[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
          <Th>Pitcher</Th><Th>T</Th><Th>G</Th><Th>IP</Th>
          <Th title="Ground ball rate">GB%</Th><Th title="Fly ball rate">FB%</Th>
          <Th title="BABIP against">BABIP</Th><Th title="Batting avg against">BAA</Th>
          <Th title="ERA">ERA</Th><Th title="FIP">FIP</Th>
          <Th title="Better vs LHB or RHB">Favors</Th>
        </tr>
      </thead>
      <tbody>
        {pitchers.map(p => (
          <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
            <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.name}</td>
            <Td gray>{p.throws}</Td>
            <Td mono>{num(p.games)}</Td><Td mono>{fmt(p.ip, 1)}</Td>
            <td className={`py-2 pr-3 font-mono ${(p.gb_pct ?? 0) >= 50 ? "text-green-400" : (p.gb_pct ?? 0) < 38 ? "text-red-400" : "text-gray-300"}`}>
              {p.gb_pct != null ? `${p.gb_pct.toFixed(1)}%` : "—"}
            </td>
            <Td mono>{p.fb_pct != null ? `${p.fb_pct.toFixed(1)}%` : "—"}</Td>
            <Td mono>{fmt(p.babip_against)}</Td>
            <Td mono>{fmt(p.baa)}</Td>
            <td className={`py-2 pr-3 font-mono ${eraColor(p.era)}`}>{fmt(p.era, 2)}</td>
            <td className={`py-2 pr-3 font-mono ${eraColor(p.fip)}`}>{fmt(p.fip, 2)}</td>
            <td className="py-2"><BetterVsBadge side={p.better_vs} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PitchingSplitsTable({ pitchers }: { pitchers: any[] }) {
  const hasSplits = pitchers.some(p => p.vs_lhb || p.vs_rhb);
  if (!hasSplits) {
    return <p className="text-sm text-gray-500 py-4 text-center">Split data not available for this team.</p>;
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
          <Th>Pitcher</Th><Th>T</Th>
          <th className="pb-2 pr-3 text-blue-400/70" colSpan={5}>vs LHB</th>
          <th className="pb-2 pr-3 text-red-400/70"  colSpan={5}>vs RHB</th>
          <Th>Favors</Th>
        </tr>
        <tr className="text-left text-xs text-gray-600 border-b border-gray-800">
          <th className="pb-1.5 pr-3" colSpan={2}></th>
          <th className="pb-1.5 pr-3">BF</th><th className="pb-1.5 pr-3">AVG</th>
          <th className="pb-1.5 pr-3">OPS</th><th className="pb-1.5 pr-3">K/9</th>
          <th className="pb-1.5 pr-3">K</th>
          <th className="pb-1.5 pr-3">BF</th><th className="pb-1.5 pr-3">AVG</th>
          <th className="pb-1.5 pr-3">OPS</th><th className="pb-1.5 pr-3">K/9</th>
          <th className="pb-1.5 pr-3">K</th>
          <th className="pb-1.5"></th>
        </tr>
      </thead>
      <tbody>
        {pitchers.map(p => {
          const l = p.vs_lhb;
          const r = p.vs_rhb;
          const lOps = parseFloat(l?.ops ?? "9");
          const rOps = parseFloat(r?.ops ?? "9");
          const favors = l && r ? (lOps < rOps ? "LHB" : "RHB") : null;
          const pitcherAvgColor = (avg: string | null | undefined) => {
            const n = parseFloat(avg ?? "0");
            if (!n) return "text-gray-400";
            return n <= 0.220 ? "text-green-400" : n <= 0.250 ? "text-blue-400" : n <= 0.280 ? "text-gray-300" : "text-red-400";
          };
          return (
            <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/20">
              <td className="py-2 pr-4 font-medium whitespace-nowrap">{p.name}</td>
              <Td gray>{p.throws}</Td>
              {/* vs LHB */}
              <Td mono gray>{l?.pa ?? "—"}</Td>
              <td className={`py-2 pr-3 font-mono ${pitcherAvgColor(l?.avg)}`}>{l?.avg ?? "—"}</td>
              <Td mono>{l?.ops ?? "—"}</Td>
              <Td mono>{l?.k_per_9 ? parseFloat(l.k_per_9).toFixed(1) : "—"}</Td>
              <Td mono gray>{l?.k ?? "—"}</Td>
              {/* vs RHB */}
              <Td mono gray>{r?.pa ?? "—"}</Td>
              <td className={`py-2 pr-3 font-mono ${pitcherAvgColor(r?.avg)}`}>{r?.avg ?? "—"}</td>
              <Td mono>{r?.ops ?? "—"}</Td>
              <Td mono>{r?.k_per_9 ? parseFloat(r.k_per_9).toFixed(1) : "—"}</Td>
              <Td mono gray>{r?.k ?? "—"}</Td>
              {/* Favors badge */}
              <td className="py-2">
                {favors && <BetterVsBadge side={favors} />}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/* ── Shared badge ─────────────────────────────────────────────────────────── */

function BetterVsBadge({ side }: { side: string | null | undefined }) {
  if (!side) return <span className="text-gray-600 text-xs">—</span>;
  const isLeft = side === "LHB" || side === "LHP";
  return (
    <span className={`px-2 py-0.5 rounded text-[11px] font-bold border ${
      isLeft
        ? "bg-blue-900/30 text-blue-300 border-blue-700/40"
        : "bg-red-900/30  text-red-300  border-red-700/40"
    }`}>
      {isLeft ? "Better vs L" : "Better vs R"}
    </span>
  );
}
