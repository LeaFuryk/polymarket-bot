interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  subText?: string;
  className?: string;
}

export function MetricCard({
  label,
  value,
  subText,
  className = "",
}: MetricCardProps) {
  return (
    <div
      className={`rounded-lg border border-white/5 bg-[#131720] p-4 ${className}`}
    >
      <div className="mb-1 text-[11px] tracking-wider text-zinc-500 uppercase">
        {label}
      </div>
      <div className="font-mono text-xl font-semibold text-zinc-100">
        {value}
      </div>
      {subText && <div className="mt-1 text-xs text-zinc-500">{subText}</div>}
    </div>
  );
}
