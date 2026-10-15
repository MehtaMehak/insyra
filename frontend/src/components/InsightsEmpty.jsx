import React from 'react'

export default function InsightsEmpty() {
  return (
    <section className="card empty-state">
      <div className="empty-illustration" aria-hidden="true">
        <svg
          width="72"
          height="72"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M12 3a7 7 0 0 0-4 12.74V18a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-2.26A7 7 0 0 0 12 3z" />
          <path d="M10 22h4" />
          <path d="M9 12h6" />
        </svg>
      </div>
      <h3>AI Insights</h3>
      <p>
        No insights generated yet. Upload customer reviews and run analysis to
        discover themes, issues, and recommendations.
      </p>
      <span className="empty-badge">Coming soon</span>
    </section>
  )
}