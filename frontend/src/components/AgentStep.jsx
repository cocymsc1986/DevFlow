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

export default function AgentStep({ step, isLast, onRetryFromStage, issueFailed }) {
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

        {/* Retry from this stage */}
        {step.status === 'failed' && issueFailed && onRetryFromStage && (
          <button
            onClick={() => onRetryFromStage(step.agent_name)}
            className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-amber-500/30 text-accent hover:bg-amber-500/10 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Retry from here
          </button>
        )}

        {/* Skipped reason */}
        {step.status === 'skipped' && step.output_data?.reason && (
          <p className="mt-1 text-xs text-text-muted italic">{step.output_data.reason}</p>
        )}

        {/* PR link for escalation step */}
        {step.agent_name === 'escalation' && step.status === 'completed' && step.output_data?.github_pr_url && (
          <div className="mt-3 p-4 bg-accent/5 border border-accent/20 rounded-lg">
            <div className="flex items-center gap-2 mb-2">
              <svg className="w-5 h-5 text-accent" fill="currentColor" viewBox="0 0 16 16">
                <path d="M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z" />
              </svg>
              <span className="text-sm font-semibold text-text-primary">Pull Request Ready for Review</span>
            </div>
            {step.output_data.github_branch && (
              <div className="text-xs font-mono text-text-muted mb-3">
                Branch: <span className="text-text-primary">{step.output_data.github_branch}</span>
              </div>
            )}
            <a
              href={step.output_data.github_pr_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 px-4 py-2 bg-accent/10 hover:bg-accent/20 border border-accent/30 rounded-md text-sm text-accent hover:text-amber-300 font-medium transition-colors"
            >
              Review Pull Request
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
            </a>
          </div>
        )}

        {/* Escalation summary */}
        {step.agent_name === 'escalation' && step.status === 'completed' && step.output_data?.tldr && (
          <div className="mt-3 p-3 bg-bg-overlay border border-white/5 rounded">
            <p className="text-sm text-text-primary font-medium mb-1">{step.output_data.tldr}</p>
            {step.output_data.priority && (
              <span className={`inline-block text-xs font-mono px-2 py-0.5 rounded border mt-1 ${
                step.output_data.priority === 'critical' ? 'text-rose-400 border-rose-400/20 bg-rose-400/5' :
                step.output_data.priority === 'high' ? 'text-orange-400 border-orange-400/20 bg-orange-400/5' :
                step.output_data.priority === 'medium' ? 'text-amber-400 border-amber-400/20 bg-amber-400/5' :
                'text-emerald-400 border-emerald-400/20 bg-emerald-400/5'
              }`}>
                {step.output_data.priority}
              </span>
            )}
          </div>
        )}

        {/* PR Review verdict badge */}
        {(step.agent_name === 'pr_review' || step.agent_name?.startsWith('pr_review_revision')) && step.status === 'completed' && step.output_data?.verdict && (
          <div className="mt-2">
            <span className={`inline-block text-xs font-mono px-2 py-0.5 rounded border ${
              step.output_data.verdict === 'APPROVE' ? 'text-emerald-400 border-emerald-400/20 bg-emerald-400/5' :
              step.output_data.verdict === 'REQUEST_CHANGES' ? 'text-rose-400 border-rose-400/20 bg-rose-400/5' :
              'text-blue-400 border-blue-400/20 bg-blue-400/5'
            }`}>
              {step.output_data.verdict}
            </span>
          </div>
        )}

        {/* JSON panels */}
        <JsonPanel label="Input" data={step.input_data} />
        <JsonPanel label="Output" data={step.output_data} />
      </div>
    </div>
  )
}
