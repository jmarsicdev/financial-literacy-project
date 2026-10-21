import React from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
function App() {
  return <main className="shell">
    <header><span className="eyebrow">TEAM 5 · FINANCIAL LITERACY SERVICE</span><h1>Persistent data layer</h1>
    <p>A shared starter for beginner-friendly financial research, market history, and cited news context.</p></header>
    <section className="grid">
      <article><h2>API status</h2><p>FastAPI backend</p><a href="http://localhost:8000/health">Open health check →</a></article>
      <article><h2>Database status</h2><p>PostgreSQL + pgvector</p><a href="http://localhost:8000/db/health">Test database connection →</a></article>
      <article><h2>API documentation</h2><p>Explore starter endpoints</p><a href="http://localhost:8000/docs">Open Swagger docs →</a></article>
    </section><p className="note">External ingestion and embedding generation are planned follow-up tasks.</p>
  </main>
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)
