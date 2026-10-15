import React from 'react'

import { API_BASE } from '../config/api'

function sentimentLabel(value) {
  const normalized = String(value || '').toLowerCase()
  if (normalized === 'positive') return 'Positive'
  if (normalized === 'negative') return 'Negative'
  if (normalized === 'mixed') return 'Mixed'
  if (normalized === 'neutral') return 'Neutral'
  return 'Unknown'
}

export default function AiInsights() {
  const [status, setStatus] = React.useState('loading')
  const [analysis, setAnalysis] = React.useState(null)
  const [error, setError] = React.useState('')
  const [feeData, setFeeData] = React.useState(null)
  const [feeError, setFeeError] = React.useState('')

  React.useEffect(() => {
    let isActive = true

    async function loadInsights() {
      try {
        const [insightsResponse, feeResponse] = await Promise.all([
          fetch(`${API_BASE}/api/insights`),
          fetch(`${API_BASE}/api/fee-explainer`),
        ])

        const insightsBody = await insightsResponse.json().catch(() => ({}))
        const feeBody = await feeResponse.json().catch(() => ({}))

        if (!insightsResponse.ok) {
          throw new Error(insightsBody?.detail || `Request failed with status ${insightsResponse.status}.`)
        }

        if (isActive) {
          setAnalysis(insightsBody)
          setStatus('ready')

          if (feeResponse.ok) {
            setFeeData(feeBody)
            setFeeError('')
          } else {
            setFeeError(feeBody?.detail || 'Unable to load verified fee explanation.')
          }
        }
      } catch (err) {
        if (isActive) {
          setError(err instanceof Error ? err.message : 'Unable to load AI insights.')
          setStatus('error')
        }
      }
    }

    loadInsights()

    return () => {
      isActive = false
    }
  }, [])

  if (status === 'loading') {
    return (
      <section className="card empty-card" role="status" aria-live="polite">
        <h3>AI Insights</h3>
        <p>Loading saved AI analysis...</p>
      </section>
    )
  }

  if (status === 'error') {
    return (
      <section className="card empty-card" role="alert">
        <h3>AI Insights</h3>
        <p>{error}</p>
        <p className="upload-note">
          Run the collector and analysis service first, then refresh this page.
        </p>
      </section>
    )
  }

  if (!analysis) {
    return (
      <section className="card empty-card">
        <h3>AI Insights</h3>
        <p>No AI analysis is available yet.</p>
      </section>
    )
  }

  const themes = Array.isArray(analysis.themes) ? analysis.themes.slice(0, 5) : []
  const topThemes = themes.slice(0, 3)
  const additionalThemes = themes.slice(3)
  const quotes = Array.isArray(analysis.verified_quotes)
    ? analysis.verified_quotes.slice(0, 3)
    : []
  const feeConfusion = analysis.fee_confusion || {}
  const totalReviews = analysis.review_count || 0

  return (
    <section className="card" aria-labelledby="ai-insights-title">
      <div className="card-header">
        <div>
          <h3 id="ai-insights-title">AI Insights</h3>
          <p>
            Findings come from a deliberately selected analysis sample of{' '}
            <strong>{totalReviews}</strong> reviews, not the full 12,680 review set.
          </p>
        </div>
        <span className="empty-badge">Sampled analysis</span>
      </div>

      {analysis.summary && (
        <p className="upload-result-message">
          <strong>Summary:</strong> {analysis.summary}
        </p>
      )}

      <div className="ai-insights-grid">
        <section className="ai-insights-panel">
          <h4>Top Themes</h4>
          <ol className="ai-theme-list">
            {topThemes.map((theme, index) => (
              <li key={`${theme.theme}-${index}`} className="ai-theme-item">
                <div className="ai-theme-heading">
                  <strong>{index + 1}. {theme.theme || 'Untitled theme'}</strong>
                  <span className={`sentiment-badge sentiment-${String(theme.sentiment || 'unknown').toLowerCase()}`}>
                    {sentimentLabel(theme.sentiment)}
                  </span>
                </div>
                <p>{theme.description || 'No description available.'}</p>
              </li>
            ))}
          </ol>
        </section>

        {additionalThemes.length > 0 && (
          <section className="ai-insights-panel">
            <h4>Additional Themes</h4>
            <ul className="ai-theme-list">
              {additionalThemes.map((theme, index) => (
                <li key={`${theme.theme}-${index + 3}`} className="ai-theme-item">
                  <div className="ai-theme-heading">
                    <strong>{theme.theme || 'Untitled theme'}</strong>
                    <span className={`sentiment-badge sentiment-${String(theme.sentiment || 'unknown').toLowerCase()}`}>
                      {sentimentLabel(theme.sentiment)}
                    </span>
                  </div>
                  <p>{theme.description || 'No description available.'}</p>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>

      <section className="ai-insights-panel">
        <h4>Verified Customer Quotes</h4>
        {quotes.length === 0 ? (
          <p>No verified quotes available.</p>
        ) : (
          <div className="quote-list">
            {quotes.map((quote, index) => (
              <blockquote key={`${quote.source}-${index}`} className="quote-item">
                <p>“{quote.quote}”</p>
                <footer>
                  Rating: {quote.rating || 'N/A'} · Date: {quote.date || 'N/A'} ·{' '}
                  <a href={quote.source} target="_blank" rel="noopener noreferrer">
                    View original review
                  </a>
                </footer>
              </blockquote>
            ))}
          </div>
        )}
      </section>

      <section className="ai-insights-panel">
        <h4>Fee-Confusion Findings</h4>
        <p>
          <strong>Status:</strong>{' '}
          {feeConfusion.detected ? 'Potential fee confusion detected' : 'No fee keywords detected'}
        </p>
        <p>
          <strong>Keyword candidates:</strong> {feeConfusion.candidate_count || 0} from the
          300-review sample. These are keyword matches, not confirmed fee complaints.
        </p>
        {feeConfusion.unique_candidate_texts !== undefined && (
          <p>
            <strong>Unique candidate texts:</strong> {feeConfusion.unique_candidate_texts}
          </p>
        )}
        {feeConfusion.severity && (
          <p>
            <strong>Severity:</strong> {feeConfusion.severity}
          </p>
        )}
        {feeConfusion.ai_summary && <p>{feeConfusion.ai_summary}</p>}
        {feeConfusion.explanation && (
          <p className="upload-note">{feeConfusion.explanation}</p>
        )}
      </section>

      <section className="ai-insights-panel">
        <h4>Verified Fee Explanation</h4>
        {feeError && <p className="upload-error">{feeError}</p>}
        {!feeData && !feeError && <p>Loading verified fee explanation...</p>}
        {feeData && (
          <>
            <p className="upload-note">
              Last checked: {feeData.last_checked_date}. Explanations use only official
              Groww documentation; fee-related review language remains keyword candidates,
              not confirmed complaints.
            </p>
            <ul className="ai-theme-list">
              {(feeData.explanation_bullets || feeData.bullets || []).map((bullet) => {
                const sourceMap = feeData.source_references || Object.fromEntries(
                  (feeData.sources || []).map((source) => [source.source_id, source.url])
                )
                const sourceLinks = (bullet.supporting_sources || [])
                  .map((sourceId) => ({ id: sourceId, url: sourceMap[sourceId] }))
                  .filter((source) => source.url)

                return (
                  <li key={bullet.id || bullet.text} className="ai-theme-item">
                    <p>{bullet.text}</p>
                    <footer className="upload-note">
                      Supporting sources:{' '}
                      {sourceLinks.length > 0
                        ? sourceLinks.map((source, index) => (
                            <React.Fragment key={source.id}>
                              {index > 0 ? ', ' : ''}
                              <a href={source.url} target="_blank" rel="noopener noreferrer">
                                {source.id}
                              </a>
                            </React.Fragment>
                          ))
                        : (bullet.supporting_sources || []).join(', ') || 'N/A'}
                    </footer>
                  </li>
                )
              })}
            </ul>
            {(feeData.official_source_urls || feeData.source_urls || []).length > 0 && (
              <p>
                Official sources:{' '}
                {(feeData.official_source_urls || feeData.source_urls).map((url, index) => (
                  <React.Fragment key={url}>
                    {index > 0 ? ', ' : ''}
                    <a href={url} target="_blank" rel="noopener noreferrer">
                      {url}
                    </a>
                  </React.Fragment>
                ))}
              </p>
            )}
          </>
        )}
      </section>
    </section>
  )
}