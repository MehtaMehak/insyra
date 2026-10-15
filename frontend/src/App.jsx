import React, { useEffect, useRef, useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import SummaryCards from './components/SummaryCards.jsx'
import CsvUpload from './components/CsvUpload.jsx'
import InsightsEmpty from './components/InsightsEmpty.jsx'
import AiInsights from './components/AiInsights.jsx'
import WeeklyPulse from './components/WeeklyPulse.jsx'
import Approvals from './components/Approvals.jsx'

function App() {
  const [activeView, setActiveView] = useState('overview')
  const [selectedFile, setSelectedFile] = useState(null)
  const [backendStatus, setBackendStatus] = useState('checking')
  const fileInputRef = useRef(null)

  useEffect(() => {
    let isActive = true

    fetch('http://127.0.0.1:8000/health')
      .then(async (response) => {
        if (!response.ok) {
          throw new Error('Backend request failed')
        }

        const data = await response.json()

        if (isActive) {
          setBackendStatus(data?.status === 'ok' ? 'online' : 'offline')
        }
      })
      .catch(() => {
        if (isActive) {
          setBackendStatus('offline')
        }
      })

    return () => {
      isActive = false
    }
  }, [])

  function handleFileSelect(files) {
    if (files === null) {
      setSelectedFile(null)
      return
    }
    const file = files && files[0]
    if (file) {
      setSelectedFile(file)
    }
  }

  return (
    <div className="app-shell">
      <Sidebar activeView={activeView} onNavigate={setActiveView} />

      <main className="main-content">
        <header className="top-header">
          <div className="header-text">
            <p className="header-eyebrow">Insyra</p>
            <h1>Product Intelligence Dashboard</h1>
            <p className="header-subtitle">
              Track customer feedback and product intelligence in one place.
            </p>
          </div>

          <div
            className={`backend-status backend-status-${backendStatus}`}
            role="status"
            aria-live="polite"
          >
            <span className="backend-status-dot" aria-hidden="true" />
            <span>
              {backendStatus === 'online'
                ? 'Backend Online'
                : backendStatus === 'offline'
                  ? 'Backend Offline'
                  : 'Checking...'}
            </span>
          </div>
        </header>

        {activeView === 'overview' && (
          <>
            <SummaryCards />
            <CsvUpload
              selectedFile={selectedFile}
              onFileSelect={handleFileSelect}
              fileInputRef={fileInputRef}
            />
            <InsightsEmpty />
          </>
        )}

        {activeView === 'reviews' && (
          <>
            <CsvUpload
              selectedFile={selectedFile}
              onFileSelect={handleFileSelect}
              fileInputRef={fileInputRef}
            />
            <section className="card empty-card">
              <h3>Customer Reviews</h3>
              <p>
                Uploaded reviews will appear here once analysis is available.
              </p>
            </section>
          </>
        )}

        {activeView === 'insights' && <AiInsights />}

        {activeView === 'pulse' && <WeeklyPulse />}

        {activeView === 'approvals' && <Approvals />}
      </main>
    </div>
  )
}

export default App
