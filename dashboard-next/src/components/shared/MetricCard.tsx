interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  subText?: string;
  className?: string;
}

export function MetricCard({ label, value, subText, className = "" }: MetricCardProps) {
  return (
    <div className={`rounded-lg bg-[#131720] border border-white/5 p-4 ${className}`}>
      <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-1">
        {label}
      </div>
      <div className="text-xl font-mono font-semibold text-zinc-100">
        {value}
      </div>
      {subText && (
        <div className="text-xs text-zinc-500 mt-1">{subText}</div>
      )}
    </div>
  );
}
