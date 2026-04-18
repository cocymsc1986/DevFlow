import { useState } from 'react'
import StatusBadge from './StatusBadge'

function StepIcon({ status }) {
  if (status === 'running') {
    return (
      <svg className="w-4 h-4 text-accent animate-spin" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
    )
  }
  if (status === 'completed') {
    return (
      <svg className="w-4 h-4 text-success" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
      </svg>
    )
  }
  if (status === 'failed') {
    return (
      <svg className="w-4 h-4 text-error" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
      </svg>
    )
  }
  if (status === 'skipped') {
    return <span className="w-4 h-4 flex items-center justify-center text-text-muted text-xs">—</span>
  }
  return <span className="w-4 h-4 flex items-center justify-center text-text-muted">·</span>
}

function JsonPanel({ label, data }) {
  const [open, setOpen] = useState(false)
  if (!data) return null

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary transition-colors"
      >
        <svg
          className={`w-3 h-3 transition-transform ${open ? 'rotate-90' : ''}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        {label}
      </button>
      {open && (
        <pre className="mt-2 p-3 bg-bg-base rounded border border-white/5 text-xs font-mono text-text-primary overflow-auto max-h-96 leading-relaxed">
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  )
}

export default function AgentStep({ step, isLast }) {
  const isActive = step.status === 'running'

  return (
    <div className="flex gap-4">
      {/* Timeline connector */}
      <div className="flex flex-col items-center">
        <div className={`w-8 h-8 rounded-full border flex items-center justify-center flex-shrink-0 ${
          isActive
            ? 'border-accent/50 bg-amber-500/10'
            : step.status === 'completed'
            ? 'border-emerald-500/30 bg-emerald-500/10'
            : step.status === 'failed'
            ? 'border-rose-500/30 bg-rose-500/10'
            : 'border-white/10 bg-bg-overlay'
        }`}>
          <StepIcon status={step.status} />
        </div>
        {!isLast && <div className="w-px flex-1 bg-white/5 mt-1" />}
      </div>

      {/* Content */}
      <div className={`flex-1 pb-6 ${isLast ? '' : ''}`}>
        <div className="flex items-start justify-between gap-3 mb-1">
          <div>
            <span className="text-xs text-text-muted font-mono mr-2">#{step.step_number}</span>
            <span className={`text-sm font-medium ${isActive ? 'text-accent' : 'text-text-primary'}`}>
              {step.agent_label}
            </span>
          </div>
          <StatusBadge status={step.status} />
        </div>

        {/* Metadata row */}
        {(step.model_used || step.tokens_used || step.duration_seconds != null) && (
          <div className="flex gap-3 mt-1 text-xs font-mono text-text-muted">
            {step.model_used && (
              <span className="text-blue-400/70">{step.model_used.replace('claude-', '')}</span>
            )}
            {step.tokens_used && <span>{step.tokens_used.toLocaleString()} tokens</span>}
            {step.duration_seconds != null && <span>{step.duration_seconds.toFixed(2)}s</span>}
          </div>
        )}

        {/* Error */}
        {step.error_message && (
          <div className="mt-2 p-2 bg-rose-500/5 border border-rose-500/20 rounded text-xs text-error font-mono">
            {step.error_message}
          </div>
        )}

        {/* Skipped reason */}
        {step.status === 'skipped' && step.output_data?.reason && (
          <p className="mt-1 text-xs text-text-muted italic">{step.output_data.reason}</p>
        )}

        {/* JSON panels */}
        <JsonPanel label="Input" data={step.input_data} />
        <JsonPanel label="Output" data={step.output_data} />
      </div>
    </div>
  )
}
