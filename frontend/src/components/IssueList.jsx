import { useNavigate } from 'react-router-dom'
import StatusBadge from './StatusBadge'

function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

const TYPE_COLORS = {
  feature: 'text-blue-400',
  bug: 'text-rose-400',
  chore: 'text-purple-400',
}

export default function IssueList({ issues }) {
  const navigate = useNavigate()

  if (issues.length === 0) {
    return (
      <div className="panel p-16 text-center">
        <p className="text-text-muted text-sm">No issues yet. Submit one to get started.</p>
      </div>
    )
  }

  return (
    <div className="panel overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/10">
            <th className="text-left px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider">Title</th>
            <th className="text-left px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider">Type</th>
            <th className="text-left px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider">Size</th>
            <th className="text-left px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider">Status</th>
            <th className="text-left px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider">Created</th>
            <th className="text-left px-4 py-3 text-xs font-medium text-text-muted uppercase tracking-wider">PR</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, i) => (
            <tr
              key={issue.id}
              onClick={() => navigate(`/issues/${issue.id}`)}
              className={`cursor-pointer hover:bg-white/[0.03] transition-colors ${
                i < issues.length - 1 ? 'border-b border-white/5' : ''
              }`}
            >
              <td className="px-4 py-3">
                <span className="font-medium text-text-primary line-clamp-1">{issue.title}</span>
                {issue.github_repo && (
                  <span className="block text-xs text-text-muted font-mono mt-0.5">{issue.github_repo}</span>
                )}
              </td>
              <td className="px-4 py-3">
                <span className={`font-mono text-xs capitalize ${TYPE_COLORS[issue.issue_type] || 'text-text-muted'}`}>
                  {issue.issue_type}
                </span>
              </td>
              <td className="px-4 py-3">
                {issue.size ? (
                  <span className="font-mono text-xs border border-white/10 rounded px-1.5 py-0.5 text-text-muted">
                    {issue.size}
                  </span>
                ) : '—'}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={issue.status} />
              </td>
              <td className="px-4 py-3 text-xs text-text-muted font-mono whitespace-nowrap">
                {formatDate(issue.created_at)}
              </td>
              <td className="px-4 py-3">
                {issue.github_pr_url ? (
                  <a
                    href={issue.github_pr_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={e => e.stopPropagation()}
                    className="text-xs text-accent hover:text-amber-300 font-mono underline underline-offset-2"
                  >
                    PR
                  </a>
                ) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
