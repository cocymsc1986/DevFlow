import { useState, useEffect, useCallback } from 'react'
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom'
import { api } from './api/client'
import IssueList from './components/IssueList'
import IssueForm from './components/IssueForm'
import IssueDetail from './components/IssueDetail'

function Dashboard() {
  const navigate = useNavigate()
  const [issues, setIssues] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [githubConfigured, setGithubConfigured] = useState(false)
  const [loading, setLoading] = useState(true)

  const loadIssues = useCallback(async () => {
    try {
      const data = await api.listIssues()
      setIssues(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadIssues()
    api.health()
      .then(h => setGithubConfigured(h.github_configured))
      .catch(() => {})
    // Poll for updates every 5s when running issues exist
    const interval = setInterval(() => {
      loadIssues()
    }, 5000)
    return () => clearInterval(interval)
  }, [loadIssues])

  const handleCreated = (issue) => {
    setShowForm(false)
    navigate(`/issues/${issue.id}`)
  }

  return (
    <div className="min-h-screen bg-bg-base">
      <header className="border-b border-white/10 bg-bg-surface sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded bg-accent flex items-center justify-center">
              <svg className="w-4 h-4 text-bg-base" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <span className="text-base font-semibold tracking-tight text-text-primary">DevFlow</span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <div className={`w-1.5 h-1.5 rounded-full ${githubConfigured ? 'bg-success' : 'bg-text-muted'}`} />
              <span className="text-xs text-text-muted font-mono">
                {githubConfigured ? 'GitHub connected' : 'GitHub not configured'}
              </span>
            </div>
            <button onClick={() => setShowForm(true)} className="btn-primary">
              + New Issue
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-text-primary">Issues</h1>
          <span className="text-xs text-text-muted font-mono">{issues.length} total</span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-32">
            <svg className="w-5 h-5 text-accent animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
        ) : (
          <IssueList issues={issues} />
        )}
      </main>

      {showForm && (
        <IssueForm
          onClose={() => setShowForm(false)}
          onCreated={handleCreated}
          githubConfigured={githubConfigured}
        />
      )}
    </div>
  )
}

function IssueDetailPage() {
  return (
    <div className="min-h-screen bg-bg-base">
      <header className="border-b border-white/10 bg-bg-surface sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 rounded bg-accent flex items-center justify-center">
              <svg className="w-4 h-4 text-bg-base" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <span className="text-base font-semibold tracking-tight text-text-primary">DevFlow</span>
          </div>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-6 py-8">
        <IssueDetail />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/issues/:id" element={<IssueDetailPage />} />
      </Routes>
    </BrowserRouter>
  )
}
