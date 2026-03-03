interface StatusBadgeProps {
  label: string;
  variant?: "green" | "red" | "amber" | "cyan" | "purple" | "zinc";
  className?: string;
}

const variantClasses: Record<string, string> = {
  green: "bg-green-500/15 text-green-400 border-green-500/20",
  red: "bg-red-500/15 text-red-400 border-red-500/20",
  amber: "bg-amber-500/15 text-amber-400 border-amber-500/20",
  cyan: "bg-cyan-500/15 text-cyan-400 border-cyan-500/20",
  purple: "bg-purple-500/15 text-purple-400 border-purple-500/20",
  zinc: "bg-zinc-500/15 text-zinc-400 border-zinc-500/20",
};

export function StatusBadge({ label, variant = "zinc", className = "" }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono uppercase tracking-wide border ${variantClasses[variant]} ${className}`}
    >
      {label}
    </span>
  );
}
