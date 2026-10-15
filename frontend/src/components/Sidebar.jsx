import React from 'react'

const NAV_ITEMS = [
  { id: 'overview', label: 'Overview', icon: 'grid' },
  { id: 'reviews', label: 'Customer Reviews', icon: 'reviews' },
  { id: 'insights', label: 'AI Insights', icon: 'insights' },
  { id: 'pulse', label: 'Weekly Pulse', icon: 'pulse' },
  { id: 'approvals', label: 'Approvals', icon: 'approvals' },
]

function Icon({ name }) {
  const common = {
    width: 18,
    height: 18,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
  }

  switch (name) {
    case 'grid':
      return (
        <svg {...common}>
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
        </svg>
      )
    case 'reviews':
      return (
        <svg {...common}>
          <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v7A2.5 2.5 0 0 1 17.5 15H9l-4 4v-4H6.5A2.5 2.5 0 0 1 4 12.5z" />
        </svg>
      )
    case 'insights':
      return (
        <svg {...common}>
          <path d="M12 3a7 7 0 0 0-4 12.74V18a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-2.26A7 7 0 0 0 12 3z" />
          <path d="M10 22h4" />
        </svg>
      )
    case 'pulse':
      return (
        <svg {...common}>
          <path d="M3 13h4l2-6 4 12 2-6h6" />
        </svg>
      )
    case 'approvals':
      return (
        <svg {...common}>
          <path d="M20 6L9 17l-5-5" />
        </svg>
      )
    default:
      return null
  }
}

export default function Sidebar({ activeView, onNavigate }) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">I</div>
        <div className="brand-text">
          <span className="brand-name">Insyra</span>
          <span className="brand-tagline">Product intelligence</span>
        </div>
      </div>

      <nav className="sidebar-nav" aria-label="Primary navigation">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`nav-item ${activeView === item.id ? 'is-active' : ''}`}
            onClick={() => onNavigate(item.id)}
            aria-current={activeView === item.id ? 'page' : undefined}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        <p>AI analysis coming soon</p>
      </div>
    </aside>
  )
}