import React from 'react'

const CARDS = [
  { id: 'total', label: 'Total Reviews', value: '—', hint: 'No reviews analyzed yet' },
  { id: 'themes', label: 'Detected Themes', value: '—', hint: 'Awaiting analysis' },
  { id: 'issue', label: 'Top Customer Issue', value: 'None yet', hint: 'No issues detected' },
  { id: 'report', label: 'Weekly Report Status', value: 'Not generated', hint: 'Generate after analysis' },
]

export default function SummaryCards() {
  return (
    <section className="summary-grid" aria-label="Summary cards">
      {CARDS.map((card) => (
        <article key={card.id} className="summary-card">
          <p className="card-label">{card.label}</p>
          <p className="card-value">{card.value}</p>
          <p className="card-hint">{card.hint}</p>
        </article>
      ))}
    </section>
  )
}