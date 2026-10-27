import { useState } from 'react'

type Company = {
  symbol: string
  company_name: string | null
  sector: string | null
  industry: string | null
  exchange: string | null
  business_summary: string | null
  provider: string
}

const definitions = [
  ['Stock', 'A share of ownership in a company.'],
  ['Open', 'The price at the start of a trading session.'],
  ['Close', 'The price at the end of a trading session.'],
  ['High and low', 'The highest and lowest prices during that session.'],
  ['Volume', 'The number of shares traded during that session.'],
]

async function requestCompany(path: string, method = 'GET') {
  const response = await fetch(`/api${path}`, {
    method,
    signal: AbortSignal.timeout(90000),
  })

  const data = await response.json()

  if (!response.ok) {
    throw new Error(
      typeof data.detail === 'string'
        ? data.detail
        : 'Company information could not be loaded. Please try again.'
    )
  }

  return data
}

export default function CompanyOverview({ symbol }: { symbol: string }) {
  const [company, setCompany] = useState<Company | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')

  async function loadCompany() {
    if (loading) return

    setLoading(true)
    setMessage('Loading company information...')

    try {
      const ticker = encodeURIComponent(symbol)

      const result = await requestCompany(
        `/ingest/metadata/${ticker}`,
        'POST'
      )

      const details: Company = await requestCompany(
        `/ticker-metadata/${ticker}`
      )

      setCompany(details)
      setMessage(
        result.source === 'cache'
          ? 'Company information loaded using a cached provider response.'
          : 'Company information fetched and saved.'
      )
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : 'Could not load company information.'
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="education-grid">
      <section className="company-panel">
        <h2>Meet the company</h2>
        <p>Connect {symbol} with the business behind the ticker.</p>

        <button type="button" onClick={loadCompany} disabled={loading}>
          {loading ? 'Loading company...' : `About ${symbol}`}
        </button>

        <p role="status">{message}</p>

        {company && (
          <div>
            <h3>{company.company_name || company.symbol}</h3>

            <dl className="company-facts">
              <div>
                <dt>Ticker</dt>
                <dd>{company.symbol}</dd>
              </div>
              <div>
                <dt>Sector</dt>
                <dd>{company.sector || 'Not provided'}</dd>
              </div>
              <div>
                <dt>Industry</dt>
                <dd>{company.industry || 'Not provided'}</dd>
              </div>
              <div>
                <dt>Exchange</dt>
                <dd>{company.exchange || 'Not provided'}</dd>
              </div>
            </dl>

            {company.business_summary && (
              <details>
                <summary>What does this company do?</summary>
                <p>{company.business_summary}</p>
              </details>
            )}

            <p className="note">Company data provider: {company.provider}</p>
          </div>
        )}
      </section>

      <section className="learning-panel">
        <span className="eyebrow">LEARN AS YOU EXPLORE</span>
        <h2>Understand these numbers</h2>

        <dl className="term-list">
          {definitions.map(([term, explanation]) => (
            <div key={term}>
              <dt>{term}</dt>
              <dd>{explanation}</dd>
            </div>
          ))}
        </dl>

        <p>
          <strong>Try it:</strong> Find the latest session in the table.
          Did the stock close above or below its opening price?
        </p>
      </section>
    </div>
  )
}