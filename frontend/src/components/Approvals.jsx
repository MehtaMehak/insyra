import React from 'react'

const API_BASE = 'http://127.0.0.1:8001'

function formatDate(value) {
  if (!value) return 'Not available'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

function firstText(value) {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(firstText).filter(Boolean).join(', ')
  if (typeof value === 'object') {
    for (const key of ['report', 'markdown', 'content', 'text', 'value', 'theme']) {
      if (value[key]) return firstText(value[key])
    }
  }
  return ''
}

function snapshotOf(approval) {
  return approval?.snapshot || approval?.snapshots || {}
}

export default function Approvals() {
  const [approvals, setApprovals] = React.useState([])
  const [status, setStatus] = React.useState('loading')
  const [error, setError] = React.useState('')
  const [success, setSuccess] = React.useState('')
  const [weeklyPulse, setWeeklyPulse] = React.useState(null)
  const [feeExplainer, setFeeExplainer] = React.useState(null)
  const [sourceStatus, setSourceStatus] = React.useState('loading')
  const [creating, setCreating] = React.useState(false)
  const [processingId, setProcessingId] = React.useState(null)
  const [confirmingId, setConfirmingId] = React.useState(null)

  const loadApprovals = React.useCallback(async (signal) => {
    const response = await fetch(`${API_BASE}/api/approvals`, { signal })
    const body = await response.json().catch(() => ({}))
    if (!response.ok) {
      throw new Error(body?.detail || `Request failed with status ${response.status}.`)
    }
    setApprovals(Array.isArray(body?.approvals) ? body.approvals : [])
  }, [])

  const loadSources = React.useCallback(async (signal) => {
    const [pulseResponse, feeResponse] = await Promise.all([
      fetch(`${API_BASE}/api/weekly-pulse`, { signal }),
      fetch(`${API_BASE}/api/fee-explainer`, { signal }),
    ])

    const pulseBody = await pulseResponse.json().catch(() => ({}))
    const feeBody = await feeResponse.json().catch(() => ({}))

    if (pulseResponse.ok) setWeeklyPulse(pulseBody)
    if (feeResponse.ok) setFeeExplainer(feeBody)
  }, [])

  const loadAll = React.useCallback(async () => {
    setStatus('loading')
    setError('')
    setSourceStatus('loading')
    const controller = new AbortController()

    try {
      await Promise.all([loadApprovals(controller.signal), loadSources(controller.signal)])
      setStatus('ready')
      setSourceStatus('ready')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load approvals.')
      setStatus('error')
      setSourceStatus('error')
    }
  }, [loadApprovals, loadSources])

  React.useEffect(() => {
    loadAll()
  }, [loadAll])

  async function handleCreateRequest() {
    if (!weeklyPulse || !feeExplainer) {
      setError('Weekly Product Pulse and Fee Explainer data must be available before creating an approval request.')
      return
    }

    setCreating(true)
    setError('')
    setSuccess('')

    try {
      const pulseSnapshot = weeklyPulse || {}
      const feeSnapshot = feeExplainer || {}
      const payload = {
        title: 'Weekly Product Pulse and customer clarification',
        snapshot: {
          date: pulseSnapshot.report_date || new Date().toISOString().slice(0, 10),
          top_themes: Array.isArray(pulseSnapshot.top_themes)
            ? pulseSnapshot.top_themes
            : Array.isArray(pulseSnapshot.supported_themes)
              ? pulseSnapshot.supported_themes
              : [],
          weekly_pulse:
            pulseSnapshot.report ||
            pulseSnapshot.markdown ||
            pulseSnapshot.content ||
            '',
          identified_fee_issue:
            pulseSnapshot.fee_observation ||
            feeSnapshot.customer_context ||
            'Review fee confusion context',
          explanation_bullets: (feeSnapshot.explanation_bullets || feeSnapshot.bullets || [])
            .map((bullet) => (typeof bullet === 'string' ? bullet : bullet?.text || ''))
            .filter(Boolean),
          source_links:
            feeSnapshot.official_source_urls ||
            feeSnapshot.source_urls ||
            [],
        },
      }

      const response = await fetch(`${API_BASE}/api/approvals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(body?.detail || `Request failed with status ${response.status}.`)
      }

      setApprovals((current) => [body, ...current])
      setSuccess('Approval request created. Review it before approving.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create approval request.')
    } finally {
      setCreating(false)
    }
  }

  async function handleApprove(requestId) {
    setProcessingId(requestId)
    setError('')
    setSuccess('')

    try {
      const response = await fetch(`${API_BASE}/api/approvals/${requestId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Approved from dashboard', decided_by: 'dashboard user' }),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(body?.detail || `Request failed with status ${response.status}.`)
      }

      setApprovals((current) =>
        current.map((approval) => (approval.id === requestId ? body : approval)),
      )
      setConfirmingId(null)
      setSuccess('Approval completed. Local note and mock Gmail draft were created. No email was sent.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to approve request.')
    } finally {
      setProcessingId(null)
    }
  }

  async function handleReject(requestId) {
    if (!window.confirm('Reject this approval request?')) return

    setProcessingId(requestId)
    setError('')
    setSuccess('')

    try {
      const response = await fetch(`${API_BASE}/api/approvals/${requestId}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Rejected from dashboard', decided_by: 'dashboard user' }),
      })
      const body = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(body?.detail || `Request failed with status ${response.status}.`)
      }

      setApprovals((current) =>
        current.map((approval) => (approval.id === requestId ? body : approval)),
      )
      setSuccess('Approval request rejected. No providers were executed.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to reject request.')
    } finally {
      setProcessingId(null)
    }
  }

  const isEmpty = status === 'ready' && approvals.length === 0
  const isBusy = creating || processingId !== null

  return (
    <section className="card" aria-labelledby="approvals-title">
      <div className="card-header">
        <div>
          <h3 id="approvals-title">Approvals</h3>
          <p>
            Review generated product insights before any local note or mock Gmail draft is created.
          </p>
        </div>
        <button
          type="button"
          className="upload-button"
          onClick={handleCreateRequest}
          disabled={isBusy || !weeklyPulse || !feeExplainer}
        >
          {creating ? 'Creating Request...' : 'Create Approval Request'}
        </button>
      </div>

      {success && <p className="upload-result-message">{success}</p>}
      {error && <p className="upload-error" role="alert">{error}</p>}

      {status === 'loading' && (
        <p role="status" aria-live="polite">Loading approvals, Weekly Product Pulse, and Fee Explainer...</p>
      )}

      {sourceStatus === 'error' && (
        <p className="upload-note">
          Source data is unavailable, so new requests cannot be created until the backend reports are available.
        </p>
      )}

      {isEmpty && (
        <div className="empty-card">
          <h3>No approval requests yet</h3>
          <p>Create an approval request from the current Weekly Product Pulse and Fee Explainer.</p>
        </div>
      )}

      <div className="ai-insights-grid">
        {approvals.map((approval) => {
          const snapshot = snapshotOf(approval)
          const execution = approval.execution || {}
          const themes = Array.isArray(snapshot.top_themes) ? snapshot.top_themes : []
          const sources = Array.isArray(snapshot.source_links) ? snapshot.source_links : []
          const isPending = approval.status === 'pending'
          const isProcessing = processingId === approval.id

          return (
            <section key={approval.id} className="ai-insights-panel" aria-labelledby={`approval-${approval.id}`}>
              <div className="ai-theme-heading">
                <strong id={`approval-${approval.id}`}>Request {approval.id}</strong>
                <span className={`sentiment-badge sentiment-${String(approval.status || 'unknown').toLowerCase()}`}>
                  {approval.status || 'unknown'}
                </span>
              </div>

              <p className="upload-note">Created: {formatDate(approval.created_at)}</p>

              {themes.length > 0 && (
                <div>
                  <strong>Top themes</strong>
                  <ul className="ai-theme-list">
                    {themes.map((theme, index) => (
                      <li key={`${theme}-${index}`} className="ai-theme-item">{firstText(theme)}</li>
                    ))}
                  </ul>
                </div>
              )}

              {snapshot.weekly_pulse && (
                <div>
                  <strong>Weekly Product Pulse preview</strong>
                  <p>{String(snapshot.weekly_pulse).slice(0, 360)}</p>
                </div>
              )}

              {snapshot.identified_fee_issue && (
                <div>
                  <strong>Fee issue context</strong>
                  <p>{firstText(snapshot.identified_fee_issue)}</p>
                </div>
              )}

              {Array.isArray(snapshot.explanation_bullets) && snapshot.explanation_bullets.length > 0 && (
                <div>
                  <strong>Fee Explainer preview</strong>
                  <ul className="ai-theme-list">
                    {snapshot.explanation_bullets.slice(0, 3).map((bullet, index) => (
                      <li key={`${bullet}-${index}`} className="ai-theme-item">{firstText(bullet)}</li>
                    ))}
                  </ul>
                </div>
              )}

              {sources.length > 0 && (
                <div>
                  <strong>Official source links</strong>
                  <ul className="ai-theme-list">
                    {sources.map((source) => (
                      <li key={source} className="ai-theme-item">
                        <a href={source} target="_blank" rel="noopener noreferrer">{source}</a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {approval.status === 'approved' && (
                <div className="upload-result">
                  <p className="upload-result-title">Execution status: {execution.state || execution.execution_state || 'not_started'}</p>
                  {execution.notes?.path && (
                    <p className="upload-result-meta">Local note: {execution.notes.path}</p>
                  )}
                  {execution.gmail_draft?.path && (
                    <p className="upload-result-meta">
                      MOCK Gmail draft: {execution.gmail_draft.path}
                    </p>
                  )}
                  {execution.gmail_draft?.draft_id && (
                    <p className="upload-result-meta">Mock draft ID: {execution.gmail_draft.draft_id}</p>
                  )}
                  {execution.notes?.error && (
                    <p className="upload-error">{execution.notes.error}</p>
                  )}
                  {execution.gmail_draft?.error && (
                    <p className="upload-error">{execution.gmail_draft.error}</p>
                  )}
                </div>
              )}

              {approval.status === 'rejected' && (
                <p className="upload-result-message">
                  Rejected{approval.decision?.reason ? `: ${approval.decision.reason}` : ''}. No providers were executed.
                </p>
              )}

              {isPending && confirmingId !== approval.id && (
                <div className="upload-actions">
                  <button
                    type="button"
                    className="upload-button"
                    onClick={() => setConfirmingId(approval.id)}
                    disabled={isBusy}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="clear-file"
                    onClick={() => handleReject(approval.id)}
                    disabled={isBusy}
                  >
                    {isProcessing ? 'Processing...' : 'Reject'}
                  </button>
                </div>
              )}

              {isPending && confirmingId === approval.id && (
                <div className="upload-result">
                  <p>
                    Confirm approval. This will create one local Markdown note and one MOCK Gmail draft only.
                    No email will be sent, and no real Gmail draft or external record will be created.
                  </p>
                  <div className="upload-actions">
                    <button
                      type="button"
                      className="upload-button"
                      onClick={() => handleApprove(approval.id)}
                      disabled={isProcessing}
                    >
                      {isProcessing ? 'Processing...' : 'Confirm Approval'}
                    </button>
                    <button
                      type="button"
                      className="clear-file"
                      onClick={() => setConfirmingId(null)}
                      disabled={isProcessing}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </section>
          )
        })}
      </div>
    </section>
  )
}
