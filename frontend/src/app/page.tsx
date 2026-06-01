import { Activity, Users, ClipboardList, Target, TrendingUp } from "lucide-react";
import Link from "next/link";

const modules = [
  {
    href: "/lineup",
    icon: ClipboardList,
    title: "Lineup Optimizer",
    description: "Build optimal daily lineups with platoon & park-factor adjustments",
    color: "from-blue-600 to-blue-800",
  },
  {
    href: "/roster",
    icon: Users,
    title: "Roster Builder",
    description: "Analyze team needs and score free agent fits against your budget",
    color: "from-emerald-600 to-emerald-800",
  },
  {
    href: "/scouting",
    icon: Target,
    title: "Scouting",
    description: "Grade prospects on 20-80 scale and generate AI scouting reports",
    color: "from-violet-600 to-violet-800",
  },
  {
    href: "/analytics",
    icon: TrendingUp,
    title: "Analytics",
    description: "wOBA, FIP, wRC+, WAR, Statcast metrics & matchup analysis",
    color: "from-amber-600 to-amber-800",
  },
];

export default function Home() {
  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-10">
        <div className="flex items-center gap-3 mb-2">
          <Activity className="h-8 w-8 text-blue-400" />
          <h1 className="text-3xl font-bold tracking-tight">MLB Analytics Platform</h1>
        </div>
        <p className="text-gray-400 text-lg">
          AI-powered roster management, lineup optimization, and scouting intelligence
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {modules.map(({ href, icon: Icon, title, description, color }) => (
          <Link key={href} href={href}>
            <div className="group relative overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 p-6 hover:border-gray-600 transition-all duration-200 cursor-pointer">
              <div className={`absolute inset-0 bg-gradient-to-br ${color} opacity-0 group-hover:opacity-10 transition-opacity`} />
              <div className="relative">
                <div className={`inline-flex p-3 rounded-xl bg-gradient-to-br ${color} mb-4`}>
                  <Icon className="h-6 w-6 text-white" />
                </div>
                <h2 className="text-xl font-semibold mb-2">{title}</h2>
                <p className="text-gray-400 text-sm leading-relaxed">{description}</p>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
