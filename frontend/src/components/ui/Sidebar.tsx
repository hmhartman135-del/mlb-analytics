"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, ClipboardList, Users, Target, TrendingUp, User, UserCheck, BookOpen, Trophy, Briefcase, ArrowLeftRight } from "lucide-react";
import clsx from "clsx";

const nav = [
  { href: "/", icon: Activity, label: "Dashboard" },
  { href: "/lineup", icon: ClipboardList, label: "Lineup" },
  { href: "/roster", icon: Users, label: "Roster" },
  { href: "/scouting", icon: Target, label: "Scouting" },
  { href: "/analytics", icon: TrendingUp, label: "Analytics" },
  { href: "/players", icon: User, label: "Players" },
  { href: "/free-agency", icon: UserCheck, label: "Free Agency" },
  { href: "/draft", icon: BookOpen, label: "Draft" },
  { href: "/standings", icon: Trophy, label: "Standings" },
  { href: "/offseason", icon: Briefcase, label: "Offseason" },
  { href: "/trades", icon: ArrowLeftRight, label: "Trades" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-56 flex-shrink-0 border-r border-gray-800 bg-gray-950 flex flex-col py-6 px-3">
      <div className="flex items-center gap-2 px-3 mb-8">
        <Activity className="h-6 w-6 text-blue-400" />
        <span className="font-bold text-sm tracking-wide text-gray-100">MLB Analytics</span>
      </div>
      <nav className="flex flex-col gap-1">
        {nav.map(({ href, icon: Icon, label }) => (
          <Link
            key={href}
            href={href}
            className={clsx(
              "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
              pathname === href
                ? "bg-blue-600/20 text-blue-400"
                : "text-gray-400 hover:text-gray-100 hover:bg-gray-800"
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
