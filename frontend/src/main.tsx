import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import CompanyOverview from './CompanyOverview'

type PriceBar = {
  symbol: string
  bar_date: string
  open: number | string
  high: number | string
  low: number | string
  close: number | string
  volume: number | string
}

async function apiRequest(path: string, method = 'GET') {
  const response = await fetch(`/api${path}`, {
    method,
    signal: AbortSignal.timeout(90000),
  })

  const data = await response.json()

  if (!response.ok) {
    const detail = data.detail
    throw new Error(
      typeof detail === 'string'
        ? detail
        : `Request failed (${response.status}): ${JSON.stringify(detail)}`
    )
  }

  return data
}

function App() {
  const [symbol, setSymbol] = useState('NVDA')
  const [loadedSymbol, setLoadedSymbol] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [prices, setPrices] = useState<PriceBar[]>([])

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const ticker = symbol.trim().toUpperCase()
    if (!ticker || loading) return

    setLoading(true)
    setPrices([])
    setLoadedSymbol('')
    setMessage(`Fetching prices for ${ticker}...`)

    try {
      const result = await apiRequest(
        `/ingest/prices/${encodeURIComponent(ticker)}`,
        'POST'
      )

      setMessage(`Reading saved prices for ${ticker}...`)

      const data = await apiRequest(
        `/price-bars?symbol=${encodeURIComponent(ticker)}&limit=20`
      )

      setPrices(data.items)
      setLoadedSymbol(ticker)

      if (data.items.length === 0) {
        setMessage(`No saved prices were returned for ${ticker}.`)
      } else {
        const source =
          result.source === 'cache'
            ? 'Reused a cached provider response.'
            : 'Fetched data from the provider.'

        setMessage(
          `${source} Showing ${data.items.length} saved price records for ${ticker}.`
        )
      }
    } catch (error) {
      setMessage(
        error instanceof Error
          ? `Could not load prices: ${error.message}`
          : 'Could not load prices. Please try again.'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="shell">
      <header>
        <span className="eyebrow">
          TEAM 5 · FINANCIAL LITERACY SERVICE
        </span>
        <h1>Stock research dashboard</h1>
        <p>Explore company information, historical prices, and news.</p>
      </header>

      <section>
        <article>
          <h2>Explore a stock</h2>

          <form onSubmit={handleSubmit}>
            <label htmlFor="symbol">Stock ticker </label>
            <input
              id="symbol"
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              placeholder="Example: NVDA"
              maxLength={15}
              required
              disabled={loading}
            />
            <button type="submit" disabled={loading}>
              {loading ? 'Loading...' : 'Load prices'}
            </button>
          </form>

          <p role="status">{message}</p>

          {loadedSymbol && (
            <CompanyOverview key={loadedSymbol} symbol={loadedSymbol} />
          )}

          {prices.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', textAlign: 'left' }}>
                <caption>Recent daily prices for {loadedSymbol}</caption>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Open</th>
                    <th>High</th>
                    <th>Low</th>
                    <th>Close</th>
                    <th>Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {prices.map((bar) => (
                    <tr key={`${bar.symbol}-${bar.bar_date}`}>
                      <td>{bar.bar_date}</td>
                      <td>{Number(bar.open).toFixed(2)}</td>
                      <td>{Number(bar.high).toFixed(2)}</td>
                      <td>{Number(bar.low).toFixed(2)}</td>
                      <td>{Number(bar.close).toFixed(2)}</td>
                      <td>{Number(bar.volume).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>
      </section>

      <p className="note">
        <a href="http://localhost:8000/docs">Open API documentation →</a>
      </p>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)