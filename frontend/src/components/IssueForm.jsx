import { useState, useEffect } from 'react'
import { api } from '../api/client'

export default function IssueForm({ onClose, onCreated, githubConfigured }) {
  const [form, setForm] = useState({
    title: '',
    description: '',
    issue_type: 'feature',
    has_ui: false,
    github_repo: '',
  })
  const [repos, setRepos] = useState([])
  const [reposLoading, setReposLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!githubConfigured) return
    setReposLoading(true)
    api.githubRepos()
      .then(setRepos)
      .catch(() => setRepos([]))
      .finally(() => setReposLoading(false))
  }, [githubConfigured])

  const set = (field) => (e) => setForm(f => ({ ...f, [field]: e.target ? e.target.value : e }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.title.trim() || !form.description.trim()) {
      setError('Title and description are required')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const issue = await api.createIssue({
        title: form.title.trim(),
        description: form.description.trim(),
        issue_type: form.issue_type,
        has_ui: form.has_ui,
        github_repo: form.github_repo || null,
      })
      onCreated(issue)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="panel w-full max-w-2xl shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <h2 className="text-base font-semibold text-text-primary">New Issue</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Title */}
          <div>
            <label className="label">Title *</label>
            <input
              className="input"
              placeholder="Brief, descriptive title"
              value={form.title}
              onChange={set('title')}
              required
            />
          </div>

          {/* Description */}
          <div>
            <label className="label">Description *</label>
            <textarea
              className="input resize-none"
              rows={4}
              placeholder="Describe what needs to be built or fixed..."
              value={form.description}
              onChange={set('description')}
              required
            />
          </div>

          {/* Type + UI row */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">Type</label>
              <select className="input" value={form.issue_type} onChange={set('issue_type')}>
                <option value="feature">Feature</option>
                <option value="bug">Bug</option>
                <option value="chore">Chore</option>
              </select>
            </div>
            <div className="flex flex-col justify-end">
              <label className="flex items-center gap-3 cursor-pointer group">
                <div className="relative">
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={form.has_ui}
                    onChange={e => setForm(f => ({ ...f, has_ui: e.target.checked }))}
                  />
                  <div className={`w-10 h-5 rounded-full transition-colors ${form.has_ui ? 'bg-accent' : 'bg-bg-overlay border border-white/10'}`} />
                  <div className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${form.has_ui ? 'translate-x-5' : ''}`} />
                </div>
                <span className="text-sm text-text-primary">Involves UI</span>
              </label>
            </div>
          </div>

          {/* GitHub repo */}
          {githubConfigured ? (
            <div>
              <label className="label">GitHub Repo</label>
              {reposLoading ? (
                <div className="input flex items-center gap-2 text-text-muted">
                  <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Loading repos…
                </div>
              ) : (
                <select className="input" value={form.github_repo} onChange={set('github_repo')}>
                  <option value="">— No repo (generate only) —</option>
                  {repos.map(r => (
                    <option key={r.full_name} value={r.full_name}>
                      {r.full_name} {r.private ? '(private)' : '(public)'}
                    </option>
                  ))}
                </select>
              )}
            </div>
          ) : (
            <div className="panel-elevated px-4 py-3 text-xs text-text-muted">
              GitHub not configured — code will be generated but not pushed.
            </div>
          )}

          {error && (
            <p className="text-xs text-error">{error}</p>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
            <button type="submit" disabled={submitting} className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed">
              {submitting ? 'Submitting…' : 'Submit Issue'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
