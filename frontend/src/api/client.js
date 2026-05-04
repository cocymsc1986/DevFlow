const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  health: () => request('/health'),
  githubInfo: () => request('/github/info'),
  githubRepos: () => request('/github/repos'),

  listIssues: () => request('/issues'),
  getIssue: (id) => request(`/issues/${id}`),
  createIssue: (data) => request('/issues', { method: 'POST', body: JSON.stringify(data) }),
  retryIssue: (id) => request(`/issues/${id}/retry`, { method: 'POST' }),
  deleteIssue: (id) => request(`/issues/${id}`, { method: 'DELETE' }),
  rerunIssue: (id) => request(`/issues/${id}/rerun`, { method: 'POST' }),
  retryFromStage: (id, stageName) => request(`/issues/${id}/retry-stage`, { method: 'POST', body: JSON.stringify({ stage_name: stageName }) }),
}

export function createWebSocket(issueId) {
  const wsBase = window.location.hostname === 'localhost'
    ? 'ws://localhost:8000'
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
  return new WebSocket(`${wsBase}/ws/${issueId}`)
}
