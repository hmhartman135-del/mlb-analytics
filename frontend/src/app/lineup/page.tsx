"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  lineupsApi,
  type LineupResult,
  type LineupSlot,
  type BenchSlot,
  type PitcherSlot,
} from "@/lib/api";
import { TeamSelector } from "@/components/ui/TeamSelector";
import { SyncBar } from "@/components/ui/SyncBar";
import { ClipboardList, RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";

export default function LineupPage() {
  const [teamId, setTeamId] = useState("");
  const [teamName, setTeamName] = useState("");
  const [parkFactor, setParkFactor] = useState(100);
  const [pitcherHand, setPitcherHand] = useState("R");
  const [season] = useState(2026);

  const { mutate, data, isPending, error } = useMutation({
    mutationFn: () =>
      lineupsApi
        .optimize({ team_id: teamId, opposing_pitcher_hand: pitcherHand, park_factor: parkFactor, season })
        .then((r) => r.data),
  });

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-8">
        <ClipboardList className="h-7 w-7 text-blue-400" />
        <h1 className="text-2xl font-bold">Lineup Optimizer</h1>
        <span className="text-xs text-gray-500 mt-1">26-man roster</span>
      </div>

      {/* Live sync bar */}
      <SyncBar className="mb-5" />

      {/* Controls */}
      <div className="stat-card mb-6 grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="col-span-2">
          <label className="block text-xs text-gray-400 mb-1">Team</label>
          <TeamSelector
            value={teamId}
            onChange={(id, team) => {
              setTeamId(id);
              setTeamName(team.full_name);
              setParkFactor(team.park_factor_runs ?? 100);
            }}
          />
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Opposing Pitcher</label>
          <select
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
            value={pitcherHand}
            onChange={(e) => setPitcherHand(e.target.value)}
          >
            <option value="R">RHP</option>
            <option value="L">LHP</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-400 mb-1">Park Factor</label>
          <input
            type="number"
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
            value={parkFactor}
            min={80}
            max={120}
            onChange={(e) => setParkFactor(Number(e.target.value))}
          />
        </div>
      </div>

      <button
        onClick={() => mutate()}
        disabled={!teamId || isPending}
        className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors mb-6"
      >
        {isPending && <RefreshCw className="h-4 w-4 animate-spin" />}
        {teamId ? `Build ${teamName} Game Plan` : "Select a team first"}
      </button>

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg p-4 text-sm text-red-300 mb-6">
          Could not build lineup — make sure roster data has been loaded for this team.
        </div>
      )}

      {data && <GamePlan result={data} pitcherHand={pitcherHand} />}
    </div>
  );
}

/* ─── Game Plan: three-section layout ─────────────────────────────────────── */

function GamePlan({ result, pitcherHand }: { result: LineupResult; pitcherHand: string }) {
  return (
    <div className="space-y-6">
      {result.warnings.length > 0 && (
        <div className="bg-amber-900/20 border border-amber-800 rounded-lg p-3">
          {result.warnings.map((w, i) => (
            <p key={i} className="text-amber-300 text-xs">{w}</p>
          ))}
        </div>
      )}

      {/* Header stats */}
      <div className="flex gap-4 text-sm text-gray-400 flex-wrap">
        <span>
          Opposing starter:{" "}
          <span className="text-white font-medium">{pitcherHand === "R" ? "RHP" : "LHP"}</span>
        </span>
        <span>
          Park Factor:{" "}
          <span className="text-white font-medium">{result.park_factor}</span>
        </span>
        <span>
          Lineup Score:{" "}
          <span className="text-blue-400 font-bold">{result.total_score.toFixed(1)}</span>
        </span>
      </div>

      {/* Starting Lineup */}
      <StartingLineup slots={result.starting_lineup} />

      {/* Bench */}
      {result.bench.length > 0 && <Bench players={result.bench} />}

      {/* Pitching Staff */}
      {(result.pitching_staff.rotation.length > 0 || result.pitching_staff.bullpen.length > 0) && (
        <PitchingStaff
          rotation={result.pitching_staff.rotation}
          bullpen={result.pitching_staff.bullpen}
        />
      )}
    </div>
  );
}

/* ─── Starting Lineup ──────────────────────────────────────────────────────── */

function StartingLineup({ slots }: { slots: LineupSlot[] }) {
  return (
    <div className="stat-card">
      <h2 className="font-semibold text-lg mb-4">Starting Lineup</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
              <th className="pb-2 pr-3 w-6">#</th>
              <th className="pb-2 pr-3 w-12">Pos</th>
              <th className="pb-2 pr-6">Player</th>
              <th className="pb-2 pr-3 w-10">Bats</th>
              <th className="pb-2 pr-3 w-16">wRC+</th>
              <th className="pb-2 pr-3 w-16">wOBA</th>
              <th className="pb-2 w-24">Platoon</th>
            </tr>
          </thead>
          <tbody>
            {slots.map((slot) => (
              <tr key={slot.order} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="py-2.5 pr-3 font-mono text-gray-500">{slot.order}</td>
                <td className="py-2.5 pr-3">
                  <span className="badge-grade bg-gray-700 text-gray-200">{slot.position}</span>
                </td>
                <td className="py-2.5 pr-6 font-medium">{slot.player_name}</td>
                <td className="py-2.5 pr-3 text-gray-400">{slot.bats}</td>
                <td className="py-2.5 pr-3">
                  <WrcBadge value={slot.wrc_plus} />
                </td>
                <td className="py-2.5 pr-3 font-mono text-gray-300">{slot.woba.toFixed(3)}</td>
                <td className="py-2.5">
                  <PlatoonBadge platoon={slot.platoon} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Bench ────────────────────────────────────────────────────────────────── */

function Bench({ players }: { players: BenchSlot[] }) {
  return (
    <div className="stat-card">
      <h2 className="font-semibold text-lg mb-4">Bench</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-gray-500 border-b border-gray-800">
              <th className="pb-2 pr-3 w-12">Pos</th>
              <th className="pb-2 pr-6">Player</th>
              <th className="pb-2 pr-3 w-10">Bats</th>
              <th className="pb-2 pr-3 w-16">wRC+</th>
              <th className="pb-2 pr-3 w-16">wOBA</th>
              <th className="pb-2 pr-4 w-36">Role</th>
              <th className="pb-2">Use When</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p) => (
              <tr key={p.player_id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="py-2.5 pr-3">
                  <span className="badge-grade bg-gray-700 text-gray-200">{p.position}</span>
                </td>
                <td className="py-2.5 pr-6 font-medium">{p.player_name}</td>
                <td className="py-2.5 pr-3 text-gray-400">{p.bats}</td>
                <td className="py-2.5 pr-3">
                  <WrcBadge value={p.wrc_plus} />
                </td>
                <td className="py-2.5 pr-3 font-mono text-gray-300">{p.woba.toFixed(3)}</td>
                <td className="py-2.5 pr-4">
                  <RoleBadge role={p.role} />
                </td>
                <td className="py-2.5 text-gray-400 text-xs">{p.use_when}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Pitching Staff ───────────────────────────────────────────────────────── */

function PitchingStaff({ rotation, bullpen }: { rotation: PitcherSlot[]; bullpen: PitcherSlot[] }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Rotation */}
      {rotation.length > 0 && (
        <div className="stat-card">
          <h2 className="font-semibold text-lg mb-4">Starting Rotation</h2>
          <div className="space-y-2">
            {rotation.map((p, i) => (
              <PitcherRow key={p.player_id} pitcher={p} rank={i + 1} />
            ))}
          </div>
        </div>
      )}

      {/* Bullpen */}
      {bullpen.length > 0 && (
        <div className="stat-card">
          <h2 className="font-semibold text-lg mb-4">Bullpen</h2>
          <div className="space-y-2">
            {bullpen.map((p) => (
              <PitcherRow key={p.player_id} pitcher={p} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PitcherRow({ pitcher, rank }: { pitcher: PitcherSlot; rank?: number }) {
  return (
    <div className="flex items-center gap-3 py-2 border-b border-gray-800/50 last:border-0">
      {rank && (
        <span className="text-gray-600 font-mono text-xs w-4 shrink-0">{rank}</span>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-sm">{pitcher.player_name}</span>
          <span className="text-xs text-gray-500">{pitcher.throws}HP</span>
          <BullpenRoleBadge role={pitcher.role} />
        </div>
        <p className="text-xs text-gray-500 mt-0.5">{pitcher.use_when}</p>
      </div>
      <div className="text-right shrink-0 space-y-0.5">
        <div className="flex gap-3 text-xs font-mono">
          <span>
            <span className="text-gray-500">ERA </span>
            <span className={eraColor(pitcher.era)}>{pitcher.era.toFixed(2)}</span>
          </span>
          <span>
            <span className="text-gray-500">FIP </span>
            <span className={eraColor(pitcher.fip)}>{pitcher.fip.toFixed(2)}</span>
          </span>
        </div>
        <div className="text-xs text-gray-600 text-right">
          {pitcher.ip.toFixed(1)} IP · {pitcher.games}G
          {pitcher.saves > 0 && ` · ${pitcher.saves} SV`}
        </div>
      </div>
    </div>
  );
}

/* ─── Badges & helpers ─────────────────────────────────────────────────────── */

function WrcBadge({ value }: { value: number }) {
  const color =
    value >= 140 ? "bg-green-500/20 text-green-400" :
    value >= 115 ? "bg-blue-500/20 text-blue-400" :
    value >= 100 ? "bg-gray-700 text-gray-300" :
    value >= 80  ? "bg-amber-500/20 text-amber-400" :
    "bg-red-500/20 text-red-400";
  return <span className={`badge-grade ${color} font-mono`}>{value.toFixed(0)}</span>;
}

function PlatoonBadge({ platoon }: { platoon: "advantage" | "disadvantage" | "neutral" }) {
  if (platoon === "advantage") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-green-400">
        <TrendingUp className="h-3 w-3" /> Advantage
      </span>
    );
  }
  if (platoon === "disadvantage") {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-red-400">
        <TrendingDown className="h-3 w-3" /> Disadvantage
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-gray-500">
      <Minus className="h-3 w-3" /> Neutral
    </span>
  );
}

const ROLE_COLORS: Record<string, string> = {
  "Backup Catcher":  "bg-purple-500/20 text-purple-300",
  "Platoon Bat":     "bg-blue-500/20 text-blue-300",
  "Bench Bat":       "bg-gray-700 text-gray-300",
  "Utility":         "bg-teal-500/20 text-teal-300",
};

function RoleBadge({ role }: { role: string }) {
  const cls = ROLE_COLORS[role] ?? "bg-gray-700 text-gray-300";
  return <span className={`badge-grade text-xs ${cls}`}>{role}</span>;
}

const BULLPEN_ROLE_COLORS: Record<string, string> = {
  "Closer":           "bg-red-500/20 text-red-300",
  "Setup":            "bg-orange-500/20 text-orange-300",
  "Lefty Specialist": "bg-blue-500/20 text-blue-300",
  "High-Leverage":    "bg-amber-500/20 text-amber-300",
  "Middle Relief":    "bg-gray-700 text-gray-300",
  "Long Man":         "bg-teal-500/20 text-teal-300",
  "Starting Pitcher": "bg-purple-500/20 text-purple-300",
};

function BullpenRoleBadge({ role }: { role: string }) {
  const cls = BULLPEN_ROLE_COLORS[role] ?? "bg-gray-700 text-gray-300";
  return <span className={`badge-grade text-xs ${cls}`}>{role}</span>;
}

function eraColor(val: number): string {
  if (!val) return "text-gray-400";
  if (val < 3.00) return "text-green-400";
  if (val < 3.75) return "text-blue-400";
  if (val < 4.50) return "text-gray-300";
  return "text-red-400";
}
