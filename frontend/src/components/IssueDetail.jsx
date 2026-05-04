import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api, createWebSocket } from '../api/client'
import AgentStep from './AgentStep'
import StatusBadge from './StatusBadge'

const TYPE_COLORS = {
  feature: 'text-blue-400 border-blue-400/20 bg-blue-400/5',
  bug: 'text-rose-400 border-rose-400/20 bg-rose-400/5',
  chore: 'text-purple-400 border-purple-400/20 bg-purple-400/5',
}

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'long', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function IssueDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [issue, setIssue] = useState(null)
  const [steps, setSteps] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [rerunning, setRerunning] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const wsRef = useRef(null)
  const bottomRef = useRef(null)
  const fetchingRef = useRef(false)

  const getLatestRun = useCallback((iss) => {
    if (!iss?.pipeline_runs?.length) return null
    return iss.pipeline_runs[iss.pipeline_runs.length - 1]
  }, [])

  const loadIssue = useCallback(async () => {
    if (fetchingRef.current) return
    fetchingRef.current = true
    try {
      const data = await api.getIssue(id)
      setIssue(data)
      const run = getLatestRun(data)
      setSteps(run?.agent_steps || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
      fetchingRef.current = false
    }
  }, [id, getLatestRun])

  useEffect(() => {
    loadIssue()
  }, [loadIssue])

  // WebSocket for real-time updates, with polling fallback if WS fails
  useEffect(() => {
    if (!id) return
    const ws = createWebSocket(id)
    wsRef.current = ws
    let pollInterval = null

    const startPolling = () => {
      if (pollInterval) return
      pollInterval = setInterval(loadIssue, 5000)
    }

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)

      if (msg.type === 'agent_start') {
        setSteps(prev => {
          const existing = prev.find(s => s.agent_name === msg.agent)
          if (existing) {
            return prev.map(s => s.agent_name === msg.agent ? { ...s, status: 'running' } : s)
          }
          return [...prev, {
            id: msg.step_id,
            agent_name: msg.agent,
            agent_label: msg.label,
            step_number: msg.step_number,
            status: 'running',
          }]
        })
        setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 100)
      }

      if (msg.type === 'agent_complete') {
        setSteps(prev => prev.map(s =>
          s.agent_name === msg.agent
            ? { ...s, status: 'completed', output_data: msg.output, model_used: msg.model, tokens_used: msg.tokens, duration_seconds: msg.duration }
            : s
        ))
      }

      if (msg.type === 'agent_skipped') {
        setSteps(prev => {
          const existing = prev.find(s => s.agent_name === msg.agent)
          const skipped = {
            id: msg.step_id,
            agent_name: msg.agent,
            agent_label: msg.label,
            step_number: msg.step_number,
            status: 'skipped',
            output_data: { reason: msg.reason },
          }
          if (existing) return prev.map(s => s.agent_name === msg.agent ? skipped : s)
          return [...prev, skipped]
        })
      }

      if (msg.type === 'agent_error') {
        setSteps(prev => prev.map(s =>
          s.agent_name === msg.agent ? { ...s, status: 'failed', error_message: msg.error } : s
        ))
      }

      if (msg.type === 'pipeline_complete') {
        setIssue(prev => prev ? { ...prev, status: 'awaiting_review', github_pr_url: msg.pr_url } : prev)
      }

      if (msg.type === 'pipeline_error') {
        setIssue(prev => prev ? { ...prev, status: 'failed' } : prev)
      }
    }

    ws.onerror = () => startPolling()
    ws.onclose = () => startPolling()

    return () => {
      ws.close()
      clearInterval(pollInterval)
    }
  }, [id, loadIssue])

  const handleRerun = async () => {
    setRerunning(true)
    try {
      await api.rerunIssue(id)
      setSteps([])
      await loadIssue()
    } catch (e) {
      console.error(e)
    } finally {
      setRerunning(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await api.deleteIssue(id)
      navigate('/')
    } catch (e) {
      console.error(e)
      setDeleting(false)
      setShowDeleteConfirm(false)
    }
  }

  const getSizing = () => {
    const step = steps.find(s => s.agent_name === 'sizing' && s.output_data)
    return step?.output_data?.size
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <svg className="w-6 h-6 text-accent animate-spin" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </div>
    )
  }

  if (error) {
    return (
      <div className="panel p-8 text-center">
        <p className="text-error text-sm">{error}</p>
      </div>
    )
  }

  const size = getSizing()

  return (
    <div className="max-w-7xl mx-auto">
      {/* Back nav */}
      <button
        onClick={() => navigate('/')}
        className="flex items-center gap-2 text-sm text-text-muted hover:text-text-primary transition-colors mb-6"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        All Issues
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Left column - Issue info */}
        <div className="lg:col-span-2 space-y-4">
          <div className="panel p-5">
            <div className="flex items-start justify-between gap-3 mb-3">
              <h1 className="text-lg font-semibold text-text-primary leading-snug">{issue?.title}</h1>
              <StatusBadge status={issue?.status} size="md" />
            </div>

            <div className="flex flex-wrap gap-2 mb-4">
              {issue?.issue_type && (
                <span className={`text-xs font-mono px-2 py-0.5 rounded border capitalize ${TYPE_COLORS[issue.issue_type] || 'text-text-muted border-white/10'}`}>
                  {issue.issue_type}
                </span>
              )}
              {size && (
                <span className="text-xs font-mono px-2 py-0.5 rounded border border-white/10 text-text-muted">
                  {size}
                </span>
              )}
              {issue?.has_ui && (
                <span className="text-xs font-mono px-2 py-0.5 rounded border border-purple-400/20 bg-purple-400/5 text-purple-400">
                  UI
                </span>
              )}
            </div>

            <p className="text-sm text-text-muted leading-relaxed whitespace-pre-wrap">{issue?.description}</p>
          </div>

          {/* GitHub info */}
          {issue?.github_repo && (
            <div className="panel p-4 space-y-3">
              <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider">GitHub</h3>
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-text-muted" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
                </svg>
                <span className="text-sm font-mono text-text-primary">{issue.github_repo}</span>
              </div>
              {issue.github_branch && (
                <div className="text-xs font-mono text-text-muted">
                  Branch: <span className="text-text-primary">{issue.github_branch}</span>
                </div>
              )}
              {issue.github_pr_url && (
                <a
                  href={issue.github_pr_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 text-sm text-accent hover:text-amber-300 font-medium transition-colors"
                >
                  View Pull Request
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                  </svg>
                </a>
              )}
            </div>
          )}

          {/* Meta */}
          <div className="panel p-4">
            <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-3">Details</h3>
            <dl className="space-y-2 text-xs font-mono">
              <div className="flex justify-between">
                <dt className="text-text-muted">Created</dt>
                <dd className="text-text-primary">{formatDate(issue?.created_at)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">Updated</dt>
                <dd className="text-text-primary">{formatDate(issue?.updated_at)}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-text-muted">ID</dt>
                <dd className="text-text-primary">#{issue?.id}</dd>
              </div>
            </dl>
          </div>

          {/* Actions */}
          <div className="space-y-2">
            {issue?.status !== 'running' && issue?.status !== 'pending' && (
              <button
                onClick={handleRerun}
                disabled={rerunning}
                className="btn-primary w-full disabled:opacity-50 flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                {rerunning ? 'Re-running…' : 'Re-run Pipeline'}
              </button>
            )}

            {issue?.status !== 'running' && (
              <>
                {!showDeleteConfirm ? (
                  <button
                    onClick={() => setShowDeleteConfirm(true)}
                    className="w-full px-4 py-2 text-sm font-medium rounded-md border border-rose-500/20 text-rose-400 hover:bg-rose-500/10 transition-colors"
                  >
                    Delete Issue
                  </button>
                ) : (
                  <div className="panel p-3 border-rose-500/20 space-y-2">
                    <p className="text-xs text-rose-400">This will permanently delete the issue and all pipeline data.</p>
                    <div className="flex gap-2">
                      <button
                        onClick={handleDelete}
                        disabled={deleting}
                        className="flex-1 px-3 py-1.5 text-xs font-medium rounded-md bg-rose-500/20 text-rose-400 hover:bg-rose-500/30 transition-colors disabled:opacity-50"
                      >
                        {deleting ? 'Deleting…' : 'Confirm Delete'}
                      </button>
                      <button
                        onClick={() => setShowDeleteConfirm(false)}
                        className="flex-1 px-3 py-1.5 text-xs font-medium rounded-md border border-white/10 text-text-muted hover:bg-white/5 transition-colors"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* Right column - Pipeline audit trail */}
        <div className="lg:col-span-3">
          <div className="panel p-5">
            <h2 className="text-sm font-semibold text-text-primary mb-6 flex items-center gap-2">
              <svg className="w-4 h-4 text-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              Pipeline Audit Trail
              {issue?.status === 'running' && (
                <span className="ml-auto text-xs text-accent animate-pulse">Live</span>
              )}
            </h2>

            {steps.length === 0 ? (
              <p className="text-text-muted text-sm text-center py-8">Pipeline not started yet.</p>
            ) : (
              <div>
                {[...steps]
                  .sort((a, b) => a.step_number - b.step_number)
                  .map((step, i, arr) => (
                    <AgentStep key={step.id || step.agent_name} step={step} isLast={i === arr.length - 1} />
                  ))
                }
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>
      </div>
    </div>
  )
}
