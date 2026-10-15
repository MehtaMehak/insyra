import React from 'react'

import { API_BASE } from '../config/api'

export default function CsvUpload({ selectedFile, onFileSelect, fileInputRef }) {
  const [isDragging, setIsDragging] = React.useState(false)
  const [isUploading, setIsUploading] = React.useState(false)
  const [uploadResult, setUploadResult] = React.useState(null)
  const [uploadError, setUploadError] = React.useState(null)
  const [trackedFile, setTrackedFile] = React.useState(selectedFile)

  if (trackedFile !== selectedFile) {
    // Reset stale upload state when the selected file changes.
    setTrackedFile(selectedFile)
    setUploadResult(null)
    setUploadError(null)
  }

  function handleChange(event) {
    onFileSelect(event.target.files)
  }

  function handleDrop(event) {
    event.preventDefault()
    setIsDragging(false)
    onFileSelect(event.dataTransfer.files)
  }

  function openPicker() {
    fileInputRef.current?.click()
  }

  async function handleUpload() {
    if (!selectedFile || isUploading) {
      return
    }

    setIsUploading(true)
    setUploadResult(null)
    setUploadError(null)

    try {
      const formData = new FormData()
      formData.append('file', selectedFile, selectedFile.name)

      const response = await fetch(`${API_BASE}/api/reviews/upload`, {
        method: 'POST',
        body: formData,
      })

      let data = null
      try {
        data = await response.json()
      } catch {
        data = null
      }

      if (!response.ok) {
        throw new Error(
          (data && (data.detail || data.message)) ||
            `Upload failed with status ${response.status}.`
        )
      }

      setUploadResult(data)
    } catch (error) {
      setUploadError(
        error instanceof Error ? error.message : 'Upload failed. Please try again.'
      )
    } finally {
      setIsUploading(false)
    }
  }

  const previewRows = Array.isArray(uploadResult?.preview)
    ? uploadResult.preview
    : []

  return (
    <section className="card upload-card">
      <div className="card-header">
        <div>
          <h3>Customer Review Upload</h3>
          <p>Upload a CSV file of customer reviews to begin analysis.</p>
        </div>
      </div>

      <div
        className={`drop-zone ${isDragging ? 'is-dragging' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragging(true)
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={openPicker}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') openPicker()
        }}
      >
        <div className="drop-icon">
          <svg
            width="36"
            height="36"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 16V4" />
            <path d="M7 9l5-5 5 5" />
            <rect x="4" y="17" width="16" height="3" rx="1" />
          </svg>
        </div>
        <p className="drop-title">Drag and drop a CSV file here</p>
        <p className="drop-subtitle">or click to browse your files</p>
        <p className="drop-hint">Accepted format: .csv</p>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,text/csv"
        className="file-input"
        onChange={handleChange}
      />

      {selectedFile && (
        <div className="selected-file">
          <div className="file-badge">CSV</div>
          <div className="file-meta">
            <p className="file-name">{selectedFile.name}</p>
            <p className="file-size">{(selectedFile.size / 1024).toFixed(1)} KB</p>
          </div>
          <button
            type="button"
            className="clear-file"
            onClick={() => onFileSelect(null)}
            disabled={isUploading}
          >
            Remove
          </button>
        </div>
      )}

      <div className="upload-actions">
        <button
          type="button"
          className="upload-button"
          onClick={handleUpload}
          disabled={!selectedFile || isUploading}
        >
          {isUploading ? 'Uploading...' : 'Upload & Validate'}
        </button>
      </div>

      {isUploading && (
        <p className="upload-status" role="status" aria-live="polite">
          Uploading and validating CSV...
        </p>
      )}

      {uploadError && (
        <p className="upload-error" role="alert">
          {uploadError}
        </p>
      )}

      {uploadResult && (
        <div className="upload-result">
          <p className="upload-result-title">
            Uploaded: <strong>{uploadResult.filename}</strong>
          </p>
          <p className="upload-result-meta">
            Total reviews: <strong>{uploadResult.total_reviews}</strong>
          </p>
          {uploadResult.message && (
            <p className="upload-result-message">{uploadResult.message}</p>
          )}

          <div className="upload-preview">
            <table className="preview-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Review</th>
                  <th>Rating</th>
                </tr>
              </thead>
              <tbody>
                {previewRows.length === 0 ? (
                  <tr>
                    <td colSpan={3}>No preview rows available.</td>
                  </tr>
                ) : (
                  previewRows.map((row, index) => (
                    <tr key={`${row?.date ?? ''}-${index}`}>
                      <td>{row?.date ?? ''}</td>
                      <td>{row?.review ?? ''}</td>
                      <td>{row?.rating ?? ''}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <p className="upload-note">
        AI analysis will be connected in a later step. Uploading a file does not start processing yet.
      </p>
    </section>
  )
}