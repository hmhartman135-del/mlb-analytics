import axios from "axios";

function makeBaseUrl(raw: string | undefined): string {
  const fallback =
    typeof window !== "undefined" && window.location.hostname !== "localhost"
      ? "https://mlb-analytics-production-b36c.up.railway.app"
      : "http://localhost:8000";
  const url = raw || fallback;
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  return "https://" + url;
}

const BASE_URL = makeBaseUrl(process.env.NEXT_PUBLIC_API_URL);

export const api = axios.create({
  baseURL: `${BASE_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
});

// --- Types ---

export interface Player {
  id: string;
  full_name: string;
  position: string;
  secondary_positions: string[] | null;
  bats: string | null;
  throws: string | null;
  age: number | null;
  status: string;
  roster_status: string | null;
  team_id: string | null;
  salary: number | null;
  contract_years: number | null;
  service_time: number | null;
  scouting: {
    hit: number | null;
    power: number | null;
    speed: number | null;
    field: number | null;
    arm: number | null;
    fb_velo: number | null;
    command: number | null;
    overall: number | null;
    notes: string | null;
  };
}

export interface BattingStats {
  season: number;
  split: string;
  games: number;
  plate_appearances: number;
  hits: number;
  home_runs: number;
  rbi: number;
  avg: number | null;
  obp: number | null;
  slg: number | null;
  ops: number | null;
  woba: number | null;
  wrc_plus: number | null;
  war: number | null;
  barrel_pct: number | null;
  hard_hit_pct: number | null;
  sprint_speed: number | null;
}

export interface PitchingStats {
  season: number;
  split: string;
  games: number;
  games_started: number;
  innings_pitched: number;
  era: number | null;
  fip: number | null;
  xfip: number | null;
  whip: number | null;
  k_pct: number | null;
  bb_pct: number | null;
  war: number | null;
  avg_fastball_velo: number | null;
}

export interface LineupSlot {
  order: number;
  position: string;
  player_id: string;
  player_name: string;
  wrc_plus: number;
  woba: number;
  bats: string;
  adjusted_score: number;
  platoon: "advantage" | "disadvantage" | "neutral";
}

export interface BenchSlot {
  player_id: string;
  player_name: string;
  position: string;
  bats: string;
  wrc_plus: number;
  woba: number;
  role: string;
  use_when: string;
}

export interface PitcherSlot {
  player_id: string;
  player_name: string;
  throws: string;
  era: number;
  fip: number;
  ip: number;
  games: number;
  saves: number;
  role: string;
  use_when: string;
}

export interface LineupResult {
  starting_lineup: LineupSlot[];
  bench: BenchSlot[];
  pitching_staff: {
    rotation: PitcherSlot[];
    bullpen: PitcherSlot[];
  };
  total_score: number;
  park_factor: number;
  opposing_pitcher_hand: string;
  warnings: string[];
}

export interface Team {
  id: string;
  name: string;
  city: string;
  full_name: string;
  abbreviation: string;
  division: string | null;
  league: string | null;
  level: string;
  ballpark: string | null;
  park_factor_runs: number | null;
}

export interface OrgPlayer extends Player {
  level: string;
  stats: {
    type: "batting" | "pitching";
    games: number;
    // batting
    plate_appearances?: number;
    avg?: number | null;
    obp?: number | null;
    slg?: number | null;
    ops?: number | null;
    home_runs?: number | null;
    rbi?: number | null;
    stolen_bases?: number | null;
    woba?: number | null;
    wrc_plus?: number | null;
    // pitching
    games_started?: number | null;
    innings_pitched?: number | null;
    era?: number | null;
    fip?: number | null;
    whip?: number | null;
    k_pct?: number | null;
    bb_pct?: number | null;
    war?: number | null;
  } | null;
}

export interface OrgGroup {
  level: string;
  team_name: string;
  city: string;
  team_id: string;
  players: OrgPlayer[];
}

export interface AffiliateInfo {
  level: string;
  team_name: string;
  city: string;
  team_id: string;
}

export interface OrgRoster {
  org_name: string;
  affiliate_map: Record<string, AffiliateInfo>;
  groups: OrgGroup[];
}

export interface ContractEntry {
  player_id: string;
  name: string;
  position: string | null;
  level: string;
  age: number | null;
  roster_status: string;          // "A" | "D10" | "D15" | "D60" | "RM" | …
  roster_label: string;           // "Active" | "10-Day IL" | "Reassigned" | …
  salary_m: number;
  is_estimated: boolean;
  contract_years: number | null;
  service_time: number | null;
  war: number;
  market_value_m: number;
  surplus_value_m: number;
  value_grade: string;
}

/** Human-readable level labels used across the app */
export const LEVEL_FULL: Record<string, string> = {
  MLB:    "Major League",
  AAA:    "Triple-A",
  AA:     "Double-A",
  "A+":   "High-A",
  A:      "Single-A",
  Rookie: "Rookie",
};

export interface FinancesData {
  team: { id: string; name: string; city: string; full_name: string };
  season: number;
  payroll: {
    total_m: number;
    luxury_tax_threshold_m: number;
    gap_m: number;
    over_threshold: boolean;
    roster_size: number;
    real_salary_count: number;
    avg_salary_m: number;
    all_estimated: boolean;
  };
  payroll_by_group: Record<string, number>;
  contracts: ContractEntry[];
}

// --- Teams API ---

export const teamsApi = {
  list: (level = "MLB") =>
    api.get<{ teams: Team[] }>("/teams/", { params: { level } }),

  affiliates: (teamId: string) =>
    api.get<{ parent_team: Team; affiliates: Team[] }>(`/teams/${teamId}/affiliates`),
};

// --- Player API ---

export interface LeagueRosterPlayer extends OrgPlayer {
  team_name: string;
  team_abbr: string;
}

export const playersApi = {
  list: (params?: { status?: string; position?: string; search?: string; level?: string; limit?: number; offset?: number }) =>
    api.get<{ players: Player[] }>("/players/", { params }),

  leagueRoster: (params?: { level?: string; position?: string; search?: string; season?: number }) =>
    api.get<{ players: LeagueRosterPlayer[]; level: string; total: number }>("/players/league-roster", { params }),

  get: (id: string) => api.get<Player>(`/players/${id}`),

  orgRoster: (teamId: string, season?: number) =>
    api.get<OrgRoster>(`/players/org/${teamId}`, {
      params: season ? { season } : undefined,
    }),

  freeAgents: (position?: string) =>
    api.get<{ free_agents: Player[] }>("/players/free-agents", {
      params: position ? { position } : undefined,
    }),

  draftProspects: (position?: string) =>
    api.get<{ prospects: Player[] }>("/players/draft-prospects", {
      params: position ? { position } : undefined,
    }),

  battingStats: (id: string, season?: number) =>
    api.get<{ batting_stats: BattingStats[] }>(`/players/${id}/batting-stats`, {
      params: season ? { season } : undefined,
    }),

  pitchingStats: (id: string, season?: number) =>
    api.get<{ pitching_stats: PitchingStats[] }>(`/players/${id}/pitching-stats`, {
      params: season ? { season } : undefined,
    }),
};

// --- Lineup API ---

export const lineupsApi = {
  optimize: (payload: {
    team_id: string;
    opposing_pitcher_hand: string;
    park_factor?: number;
    season?: number;
    locked_positions?: Record<string, string>;
    exclude_player_ids?: string[];
  }) => api.post<LineupResult>("/lineups/optimize", payload),

  platoonAnalysis: (batterHand: string, pitcherHand: string) =>
    api.get("/lineups/platoon-analysis", {
      params: { batter_hand: batterHand, pitcher_hand: pitcherHand },
    }),
};

export interface RosterPlayer extends Player {
  roster_status: string;
  roster_label?: string;
}

export interface RosterBreakdown {
  twenty_six: RosterPlayer[];
  forty_extra: RosterPlayer[];
  twenty_six_count: number;
  forty_man_count: number;
}

// --- Roster API ---

export const rosterApi = {
  get: (teamId: string, includeMinors = false) =>
    api.get<{ roster: Player[]; count: number }>(`/roster/${teamId}`, {
      params: { include_minors: includeMinors },
    }),

  breakdown: (teamId: string) =>
    api.get<RosterBreakdown>(`/roster/${teamId}/breakdown`),

  analyzeNeeds: (payload: {
    team_id: string;
    season?: number;
    budget_remaining_m?: number;
    generate_ai_recommendation?: boolean;
  }) => api.post("/roster/analyze-needs", payload),

  contractValues: (teamId: string, season?: number) =>
    api.get(`/roster/${teamId}/contract-values`, { params: { season } }),

  finances: (teamId: string, season?: number) =>
    api.get<FinancesData>(`/roster/${teamId}/finances`, {
      params: season ? { season } : undefined,
    }),
};

// --- Scouting Types ---

export interface ProspectGrades {
  hit: number | null;
  power: number | null;
  speed: number | null;
  field: number | null;
  arm: number | null;
  fb_velo: number | null;
  command: number | null;
  overall: number | null;
}

export interface ProspectStats {
  type: "batting" | "pitching";
  season: number | null;
  games: number | null;
  // batting
  plate_appearances?: number | null;
  avg?: number | null;
  obp?: number | null;
  slg?: number | null;
  ops?: number | null;
  home_runs?: number | null;
  rbi?: number | null;
  stolen_bases?: number | null;
  woba?: number | null;
  wrc_plus?: number | null;
  // pitching
  games_started?: number | null;
  innings_pitched?: number | null;
  era?: number | null;
  fip?: number | null;
  whip?: number | null;
  k_pct?: number | null;
  bb_pct?: number | null;
  avg_fastball_velo?: number | null;
  war?: number | null;
}

export interface Prospect {
  id: string;
  mlb_id: number | null;
  full_name: string;
  position: string | null;
  age: number | null;
  bats: string | null;
  throws: string | null;
  status: string;
  level: string | null;
  height: string | null;
  weight: number | null;
  birth_city: string | null;
  birth_country: string | null;
  school: string | null;
  school_class: string | null;
  draft_year: number | null;
  draft_pick: number | null;
  draft_rank: number | null;
  signing_bonus: number | null;
  prospect_rank: number | null;
  org_prospect_rank: number | null;
  parent_org_mlb_id: number | null;
  parent_org_abbr: string | null;
  grades: ProspectGrades;
  notes: string | null;
  stats: ProspectStats | null;
}

export interface ProspectListResponse {
  total: number;
  offset: number;
  limit: number;
  prospects: Prospect[];
}

export interface CareerRow {
  season: number | null;
  level: string;
  team?: string;
  games: number | null;
  type: "batting" | "pitching";
  // batting
  plate_appearances?: number | null;
  avg?: string | null;
  obp?: string | null;
  slg?: string | null;
  ops?: string | null;
  home_runs?: number | null;
  rbi?: number | null;
  stolen_bases?: number | null;
  strikeouts?: number | null;
  walks?: number | null;
  woba?: number | null;
  wrc_plus?: number | null;
  war?: number | null;
  // pitching
  games_started?: number | null;
  innings_pitched?: string | null;
  era?: string | null;
  whip?: string | null;
}

export interface PlayerHistoryResponse {
  player: Prospect;
  db_history: CareerRow[];
  minor_league_history: CareerRow[];
}

// --- Scouting API ---

export const scoutingApi = {
  generateReport: (payload: {
    player_id: string;
    report_type?: "full" | "brief" | "draft" | "trade";
    season?: number;
  }) => api.post<{ report: string; player_name: string }>("/scouting/report", payload),

  updateGrades: (playerId: string, grades: Partial<Player["scouting"]>) =>
    api.put(`/scouting/${playerId}/grades`, grades),

  listProspects: (params?: {
    position?: string;
    min_overall?: number;
    level?: string;
    country?: string;
    school?: string;
    school_class?: string;
    search?: string;
    ranked_only?: boolean;
    top100?: boolean;
    top30_org?: string;
    org?: string;
    offset?: number;
    limit?: number;
  }) => api.get<ProspectListResponse>("/scouting/prospects", { params }),

  playerHistory: (playerId: string) =>
    api.get<PlayerHistoryResponse>(`/scouting/player/${playerId}/history`),

  aiBio: (playerId: string) =>
    api.post<{
      player_id: string;
      player_name: string;
      background: string;
      career: string;
      current: string;
      likes: string;
      concerns: string;
    }>(`/scouting/player/${playerId}/ai-bio`),
};

// --- Analytics API ---

export const analyticsApi = {
  teamOverview: (teamId: string, season?: number) =>
    api.get(`/analytics/team/${teamId}/overview`, { params: { season } }),

  matchup: (batterId: string, pitcherId: string, season?: number) =>
    api.get("/analytics/matchup", {
      params: { batter_id: batterId, pitcher_id: pitcherId, season },
    }),
};

// --- Standings Types ---

export interface StandingsTeam {
  id: string;
  name: string;
  city: string;
  full_name: string;
  alias: string;
  win: number;
  loss: number;
  pct: number;
  games_back: number | null;
  home_win: number;
  home_loss: number;
  away_win: number;
  away_loss: number;
  last10_win: number;
  last10_loss: number;
  streak_kind: string;
  streak_length: number;
  division_rank: number;
  league_rank: number;
  wild_card_back: string;
}

export interface StandingsDivision {
  name: string;
  alias: string;
  teams: StandingsTeam[];
}

export interface StandingsConference {
  name: string;
  alias: string;
  divisions: StandingsDivision[];
}

export interface StandingsResponse {
  season: number;
  as_of: string;
  conferences: StandingsConference[];
}

// --- Standings API ---

export const standingsApi = {
  get: (season = 2026) =>
    api.get<StandingsResponse>("/standings/", { params: { season } }),
};

// --- Draft Plan Types ---

export interface DraftDepthRow {
  position: string;
  AAA: number;
  AA: number;
  "A+": number;
  A: number;
  Rookie: number;
  total: number;
  AAA_top: string | null;
  AA_top: string | null;
  "A+_top": string | null;
  A_top: string | null;
  Rookie_top: string | null;
}

export interface DraftOrgProspect {
  id: string;
  name: string;
  position: string | null;
  age: number | null;
  level: string;
  org_rank: number | null;
  overall: number | null;
  war: number;
  contract_years: number | null;
}

export interface DraftProspect {
  id: string;
  name: string;
  position: string | null;
  age: number | null;
  rank: number | null;
  school: string | null;
  school_class: string | null;
  bats: string | null;
  throws: string | null;
  overall: number | null;
}

export interface DraftPlanContext {
  mlb_roster_size: number;
  minor_league_count: number;
  org_prospects_ranked: number;
  draft_class_size: number;
}

export interface DraftPlanResponse {
  team: {
    id: string;
    name: string;
    city: string;
    full_name: string;
    division: string | null;
  };
  context: DraftPlanContext;
  depth_summary: DraftDepthRow[];
  org_prospects: DraftOrgProspect[];
  draft_prospects: DraftProspect[];
  plan: string;
}

// --- Mock Draft Types ---

export interface MockDraftPick {
  overall: number;
  round: string;        // "1", "2", "CBA", "CBB", etc.
  pick_in_round: number;
  team_name: string;
  team_abbr: string;
  player_name: string;
  position: string;
  school: string;
  note: string;
}

export interface MockDraftResponse {
  rounds: number;
  total_picks: number;
  picks: MockDraftPick[];
}

// --- Draft Grade Types ---

export interface DraftPickGrade {
  round: string;        // "1", "2", "CBA", "CBB", etc.
  player_name: string;
  grade: string;
  note: string;
}

export interface DraftGradeResponse {
  team_abbr: string;
  team_name: string;
  overall_grade: string;
  summary: string;
  pick_grades: DraftPickGrade[];
}

// --- Draft Plan + Mock Draft API ---

export const draftApi = {
  generatePlan: (teamId: string) =>
    api.post<DraftPlanResponse>("/draft/plan", { team_id: teamId }),

  generateMock: (rounds: number) =>
    api.post<MockDraftResponse>("/draft/mock", { rounds }),

  gradeDraft: (payload: {
    team_abbr: string;
    team_name: string;
    picks: Array<{
      round: string;        // "1", "2", "CBA", "CBB", etc.
      pick_in_round: number;
      player_name: string;
      position?: string | null;
      school?: string | null;
      rank?: number | null;
    }>;
  }) => api.post<DraftGradeResponse>("/draft/grade", payload),
};

// --- Real Draft Results Types (completed draft, e.g. 2026) ---

export interface DraftResultPick {
  id: string;
  mlb_id: number;
  full_name: string;
  position: string | null;
  bats: string | null;
  throws: string | null;
  age: number | null;
  height: string | null;
  weight: number | null;
  birth_city: string | null;
  birth_country: string | null;
  school: string | null;
  school_class: string | null;
  draft_year: number;
  draft_round: string;
  draft_pick: number | null;
  draft_rank: number | null;
  signing_bonus: number | null;
  draft_team_id: string | null;
  scout_notes: string | null;
  ai_draft_blurb: string | null;
  ai_draft_blurb_generated_at: string | null;
}

export interface TeamDraftClassResponse {
  year: number;
  team_id: string;
  picks: DraftResultPick[];
  grade: string | null;
  analysis: string | null;
  grade_generated_at: string | null;
}

export const draftResultsApi = {
  listPicks: (year: number, params?: { round?: string; team_id?: string }) =>
    api.get<DraftResultPick[]>(`/draft-results/${year}`, { params }),

  listRounds: (year: number) =>
    api.get<string[]>(`/draft-results/${year}/rounds`),

  teamClass: (year: number, teamId: string) =>
    api.get<TeamDraftClassResponse>(`/draft-results/${year}/team/${teamId}`),

  gradeTeam: (year: number, teamId: string) =>
    api.post<{ team_id: string; year: number; grade: string; analysis: string; generated_at: string }>(
      `/draft-results/${year}/team/${teamId}/grade`
    ),

  explainPick: (playerId: string) =>
    api.post<{ player_id: string; explanation: string; generated_at: string }>(
      `/draft-results/player/${playerId}/explain`
    ),
};

// --- Offseason Types ---

export interface OffseasonContext {
  payroll_2026_m: number;
  committed_2027_m: number;
  estimated_budget_m: number;
  cbt_threshold_m: number;
  roster_size: number;
  expiring_count: number;
}

export interface OffseasonPlayer {
  player_id: string;
  name: string;
  position: string | null;
  age: number | null;
  salary_m: number;
  contract_years: number | null;
  years_remaining: number;
  war: number;
}

export interface OffseasonFATarget {
  id: string;
  full_name: string;
  position: string | null;
  age: number | null;
  former_team: string | null;
  fa_type: string | null;
}

export interface OffseasonPlanResponse {
  team: {
    id: string;
    name: string;
    city: string;
    full_name: string;
    division: string | null;
  };
  context: OffseasonContext;
  expiring_contracts: OffseasonPlayer[];
  returning_contracts: OffseasonPlayer[];
  top_fa_targets: OffseasonFATarget[];
  plan: string;
}

// --- Offseason Simulator Types ---

export interface OffseasonContextResponse {
  team: OffseasonPlanResponse["team"];
  context: OffseasonContext;
  expiring_contracts: OffseasonPlayer[];
  returning_contracts: OffseasonPlayer[];
  fa_pool: OffseasonFATarget[];
}

export interface SigningGradeResponse {
  grade: string;
  headline: string;
  analysis: string;
}

// --- Offseason API ---

export const offseasonApi = {
  generatePlan: (teamId: string) =>
    api.post<OffseasonPlanResponse>("/offseason/plan", { team_id: teamId }),

  getContext: (teamId: string) =>
    api.post<OffseasonContextResponse>("/offseason/context", { team_id: teamId }),

  gradeMove: (payload: {
    team_name: string;
    roster_needs: string[];
    player_name: string;
    position?: string | null;
    age?: number | null;
    former_team?: string | null;
    contract_years: number;
    contract_aav_m: number;
    budget_remaining_m: number;
    existing_signings: Array<{
      player_name: string;
      position?: string | null;
      years: number;
      aav_m: number;
      grade: string;
    }>;
  }) => api.post<SigningGradeResponse>("/offseason/grade-move", payload),
};

// --- Trade Types ---

export interface TradeTeamGrade {
  team_name: string;
  team_abbr: string;
  grade: string;
  analysis: string;
}

export interface TradeEvaluateResponse {
  doable: "Yes" | "Likely" | "Unlikely" | "No" | string;
  reason: string;
  team_grades: TradeTeamGrade[];
  overall: string;
  num_teams: number;
}

// --- Trade Finder types ---

export interface TradeProposal {
  acquiring_team: string;
  acquiring_team_abbr: string;
  why: string;
  return_package: string[];
  buyer_grade: string;
  seller_grade: string;
  analysis: string;
}

export interface TradeFinderResponse {
  player: {
    id: string;
    name: string;
    position: string | null;
    age: number | null;
    team: string;
    salary: number | null;
    contract_years: number | null;
    war: number;
    stats: string;
  };
  proposals: TradeProposal[];
}

// --- Team Advisor types ---

export interface TeamAdvisorSell {
  player: string;
  why: string;
  returns: string;
}

export interface TeamAdvisorTarget {
  need: string;
  why: string;
  example: string;
}

export interface TeamAdvisorResponse {
  team_name: string;
  team_abbr: string;
  direction: string;   // BUY | SELL | HOLD | REBUILD | MIXED
  summary: string;
  sells: TeamAdvisorSell[];
  targets: TeamAdvisorTarget[];
  analysis: string;
}

// --- Trade API ---

export const tradesApi = {
  evaluate: (payload: {
    legs: Array<{
      team_id: string;
      team_name: string;
      team_abbr: string;
      players_sending: Array<{ player_id: string; player_name: string }>;
    }>;
  }) => api.post<TradeEvaluateResponse>("/trades/evaluate", payload),

  findTrades: (payload: { player_id: string }) =>
    api.post<TradeFinderResponse>("/trades/finder", payload),

  teamAdvisor: (payload: { team_id: string }) =>
    api.post<TeamAdvisorResponse>("/trades/team-advisor", payload),
};

// --- Free Agency Types ---

export interface FreeAgentStats {
  type: "batting" | "pitching";
  season: number;
  games: number;
  // batting
  plate_appearances?: number;
  avg?: number | null;
  obp?: number | null;
  slg?: number | null;
  ops?: number | null;
  home_runs?: number;
  rbi?: number;
  stolen_bases?: number;
  strikeouts?: number;
  walks?: number;
  war?: number | null;
  wrc_plus?: number | null;
  xba?: number | null;
  xwoba?: number | null;
  // pitching
  games_started?: number;
  wins?: number;
  losses?: number;
  saves?: number;
  innings_pitched?: number;
  era?: number | null;
  whip?: number | null;
  k_per_9?: number | null;
  bb_per_9?: number | null;
  fip?: number | null;
  k_pct?: number | null;
  bb_pct?: number | null;
}

export interface FreeAgent {
  id: string;
  mlb_id: number | null;
  full_name: string;
  first_name: string | null;
  last_name: string | null;
  age: number | null;
  position: string | null;
  bats: string | null;
  throws: string | null;
  height: string | null;
  weight: number | null;
  birth_country: string | null;
  status: string;
  salary: number | null;
  contract_years: number | null;
  service_time: number | null;
  team_id: string | null;
  team_name: string | null;
  stats: FreeAgentStats | null;
}

export interface FreeAgentsResponse {
  total: number;
  offset: number;
  limit: number;
  free_agents: FreeAgent[];
}

export interface UpcomingFreeAgentsResponse {
  total: number;
  offset: number;
  limit: number;
  source: string;
  upcoming: SpotracFreeAgent[];
}

// Spotrac-sourced upcoming FA (different shape from current FAs)
export interface SpotracFreeAgent {
  id: string;
  full_name: string;
  position: string | null;
  age: number | null;
  former_team: string | null;
  fa_type: string | null;   // "UFA", "ARFA", etc.
  signed: boolean;
  contract_years: number | null;
  contract_value: number | null;
  aav: number | null;
  scraped_at: string | null;
}

// --- Free Agency API ---

export const freeAgencyApi = {
  listCurrent: (params?: {
    position?: string;
    search?: string;
    country?: string;
    min_svc?: number;
    offset?: number;
    limit?: number;
  }) =>
    api.get<FreeAgentsResponse>("/free-agents", { params }),

  listUpcoming: (params?: {
    position?: string;
    team?: string;
    search?: string;
    signed?: boolean;
    offset?: number;
    limit?: number;
  }) =>
    api.get<UpcomingFreeAgentsResponse>("/free-agents/upcoming", { params }),

  predictSigningCurrent: (playerId: string) =>
    api.post<SigningPrediction>(`/free-agents/player/${playerId}/predict-signing`),

  predictSigningUpcoming: (faId: string) =>
    api.post<SigningPrediction>(`/free-agents/upcoming/${faId}/predict-signing`),
};

export interface SigningPrediction {
  player_id: string;
  player_name: string;
  predicted_team: string;
  reasoning: string;
}

// --- Live Sync ---

export interface SyncStatus {
  status: "idle" | "running" | "error";
  last_run_iso: string | null;
  age_display: string;         // "5m ago", "2h 10m ago", "never"
  is_stale: boolean;
  roster_updates: number;
  stat_updates: number;
  teams_synced: number;
  last_error: string | null;
}

export const syncApi = {
  status: () => api.get<SyncStatus>("/sync/status"),
  run:    () => api.post<{ queued: boolean; message: string }>("/sync/run"),
};
