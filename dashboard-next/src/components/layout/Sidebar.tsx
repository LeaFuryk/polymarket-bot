"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems = [
  { href: "/", label: "Trading", icon: "chart" },
  { href: "/status", label: "Status", icon: "pulse" },
  { href: "/history", label: "History", icon: "clock" },
  { href: "/forensics", label: "Forensics", icon: "search" },
];

const icons: Record<string, React.ReactNode> = {
  chart: (
    <svg
      className="h-4 w-4"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 13l4-4 4 4 4-8 4 4"
      />
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 20h18" />
    </svg>
  ),
  pulse: (
    <svg
      className="h-4 w-4"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 12h4l3-9 4 18 3-9h4"
      />
    </svg>
  ),
  clock: (
    <svg
      className="h-4 w-4"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </svg>
  ),
  search: (
    <svg
      className="h-4 w-4"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={2}
    >
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  ),
};

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-14 shrink-0 flex-col border-r border-white/5 bg-[#0d1017] lg:w-48">
      <div className="border-b border-white/5 p-3 lg:p-4">
        <div className="hidden text-sm font-bold text-zinc-200 lg:block">
          polybot
        </div>
        <div className="text-center text-sm font-bold text-zinc-200 lg:hidden">
          PB
        </div>
      </div>
      <nav className="flex-1 p-2">
        {navItems.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`mb-1 flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors ${
                active
                  ? "bg-white/5 text-zinc-100"
                  : "text-zinc-500 hover:bg-white/[0.02] hover:text-zinc-300"
              }`}
            >
              {icons[item.icon]}
              <span className="hidden lg:inline">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
