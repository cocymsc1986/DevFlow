export default function StatusBadge({ status, size = 'sm' }) {
  const configs = {
    pending:        { label: 'Pending',         cls: 'bg-white/5 text-text-muted border-white/10' },
    running:        { label: 'Running',         cls: 'bg-amber-500/10 text-accent border-amber-500/30 animate-pulse' },
    completed:      { label: 'Completed',       cls: 'bg-emerald-500/10 text-success border-emerald-500/30' },
    awaiting_review:{ label: 'Awaiting Review', cls: 'bg-blue-500/10 text-blue-400 border-blue-500/30' },
    failed:         { label: 'Failed',          cls: 'bg-rose-500/10 text-error border-rose-500/30' },
    skipped:        { label: 'Skipped',         cls: 'bg-white/5 text-text-muted border-white/10' },
  }

  const cfg = configs[status] || { label: status, cls: 'bg-white/5 text-text-muted border-white/10' }
  const px = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1 text-sm'

  return (
    <span className={`inline-flex items-center rounded border font-mono font-medium ${px} ${cfg.cls}`}>
      {cfg.label}
    </span>
  )
}
