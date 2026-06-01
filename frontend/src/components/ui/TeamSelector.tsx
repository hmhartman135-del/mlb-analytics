"use client";
import { useQuery } from "@tanstack/react-query";
import { teamsApi, type Team } from "@/lib/api";

interface Props {
  value: string;
  onChange: (teamId: string, team: Team) => void;
  placeholder?: string;
}

export function TeamSelector({ value, onChange, placeholder = "Select a team…" }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["teams"],
    queryFn: () => teamsApi.list("MLB").then((r) => r.data),
  });

  const teams = data?.teams ?? [];

  // Group by division
  const divisions: Record<string, Team[]> = {};
  for (const t of teams) {
    const div = t.division ?? "Other";
    if (!divisions[div]) divisions[div] = [];
    divisions[div].push(t);
  }

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const team = teams.find((t) => t.id === e.target.value);
    if (team) onChange(team.id, team);
  };

  return (
    <select
      className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
      value={value}
      onChange={handleChange}
      disabled={isLoading}
    >
      <option value="">{isLoading ? "Loading teams…" : placeholder}</option>
      {Object.entries(divisions).sort().map(([div, divTeams]) => (
        <optgroup key={div} label={div}>
          {divTeams.map((t) => (
            <option key={t.id} value={t.id}>
              {t.city} {t.name} ({t.abbreviation})
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
