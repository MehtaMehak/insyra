import React from 'react'

import { API_BASE } from '../config/api'

export default function WeeklyPulse() {
  const [status, setStatus] = React.useState('loading')
  const [reportData, setReportData] = React.useState(null)
  const [error, setError] = React.useState('')

  React.useEffect(() => {
    let isActive = true

    async function loadReport() {
      try {
        const response = await fetch(`${API_BASE}/api/weekly-pulse`)
        const body = await response.json().catch(() => ({}))

        if (!response.ok) {
          throw new Error(body?.detail || `Request failed with status ${response.status}.`)
        }

        if (isActive) {
          setReportData(body)
          setStatus('ready')
        }
      } catch (err) {
        if (isActive) {
          setError(err instanceof Error ? err.message : 'Unable to load Weekly Pulse.')
          setStatus('error')
        }
      }
    }

    loadReport()

    return () => {
      isActive = false
    }
  }, [])

  const markdown = reportData?.report || reportData?.markdown || reportData?.content || ''

  function downloadReport() {
    if (!markdown) {
      return
    }

    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'weekly_pulse.md'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  if (status === 'loading') {
    return (
      <section className="card empty-card" role="status" aria-live="polite">
        <h3>Weekly Pulse</h3>
        <p>Loading Weekly Product Pulse...</p>
      </section>
    )
  }

  if (status === 'error') {
    return (
      <section className="card empty-card" role="alert">
        <h3>Weekly Pulse</h3>
        <p>{error}</p>
        <p className="upload-note">
          Generate the analysis report from the backend, then refresh this page.
        </p>
      </section>
    )
  }

  if (!reportData || !markdown) {
    return (
      <section className="card empty-card">
        <h3>Weekly Pulse</h3>
        <p>No Weekly Product Pulse is available yet.</p>
      </section>
    )
  }

  return (
    <section className="card empty-card" aria-labelledby="weekly-pulse-title">
      <div className="card-header">
        <div>
          <h3 id="weekly-pulse-title">Weekly Pulse</h3>
          <p>
            Report date: <strong>{reportData.report_date}</strong> ·{' '}
            {reportData.word_count} words · Sample of{' '}
            {reportData.sample_size || 300} reviews
          </p>
        </div>
        <button type="button" className="upload-button" onClick={downloadReport}>
          Download Markdown
        </button>
      </div>

      <pre className="weekly-pulse-report">{markdown}</pre>

      {Array.isArray(reportData.verified_quotes) && reportData.verified_quotes.length > 0 && (
        <section className="ai-insights-panel">
          <h4>Quote Sources</h4>
          <ul className="ai-theme-list">
            {reportData.verified_quotes.map((quote, index) => (
              <li key={`${quote.source}-${index}`} className="ai-theme-item">
                <p>{quote.quote}</p>
                <footer className="upload-note">
                  <a href={quote.source} target="_blank" rel="noopener noreferrer">
                    View original review
                  </a>
                </footer>
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  )
}