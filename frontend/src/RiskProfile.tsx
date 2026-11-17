// Historical risk profile card. Data comes from the Spark KMeans job via GET /risk-profiles/{symbol}.
import { useEffect, useState } from 'react'

type Quarter = {
  quarter_start: string
  risk_profile: string
  profile_rank: number
  profile_count: number
  annualized_volatility: number
  max_drawdown: number
  beta_vs_benchmark: number
  benchmark: string
}

type Profile = {
  symbol: string
  latest: Quarter
  quarters_total: number
  first_quarter: string
  profile_mix: { risk_profile: string; profile_rank: number; quarters: number; pct_of_quarters: number }[]
  history: Quarter[]
  disclaimer: string
}

function quarterName(start: string) {
  const [year, month] = start.split('-').map(Number)
  return `${year} Q${Math.floor((month - 1) / 3) + 1}`
}

const pct = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`

export default function RiskProfile({ symbol }: { symbol: string }) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [message, setMessage] = useState('Loading historical risk profile...')

  useEffect(() => {
    let cancelled = false
    setProfile(null)
    setMessage('Loading historical risk profile...')

    fetch(`/api/risk-profiles/${encodeURIComponent(symbol)}?history=8`, { signal: AbortSignal.timeout(30000) })
      .then(async (response) => {
        const data = await response.json()
        if (cancelled) return
        if (response.ok) {
          setProfile(data)
          setMessage('')
        } else if (response.status === 404) {
          setMessage(`No risk profile has been computed for ${symbol} yet. It appears after the Spark clustering job runs.`)
        } else {
          setMessage('The risk profile service is unavailable right now.')
        }
      })
      .catch(() => {
        if (!cancelled) setMessage('The risk profile service is unavailable right now.')
      })

    return () => {
      cancelled = true
    }
  }, [symbol])

  return (
    <section className="risk-panel">
      <span className="eyebrow">HOW IT HAS BEHAVED</span>
      <h2>Historical risk profile</h2>

      {message && <p role="status" className="note">{message}</p>}

      {profile && (
        <>
          <p>
            In <strong>{quarterName(profile.latest.quarter_start)}</strong>, {profile.symbol} was in the{' '}
            <span className={`profile-tag rank-${profile.latest.profile_rank}`}>{profile.latest.risk_profile}</span>{' '}
            group.
          </p>

          <dl className="risk-facts">
            <div>
              <dt>Volatility (annualized)</dt>
              <dd>{pct(profile.latest.annualized_volatility)}</dd>
            </div>
            <div>
              <dt>Largest drop in the quarter</dt>
              <dd>{pct(profile.latest.max_drawdown)}</dd>
            </div>
            <div>
              <dt>Beta vs {profile.latest.benchmark}</dt>
              <dd>{profile.latest.beta_vs_benchmark.toFixed(2)}</dd>
            </div>
          </dl>

          <p className="note">
            Across {profile.quarters_total} quarters since {quarterName(profile.first_quarter)}:{' '}
            {profile.profile_mix.map((m) => `${m.pct_of_quarters.toFixed(1)}% ${m.risk_profile}`).join(', ')}.
          </p>

          <div className="quarter-strip" aria-label="Profile in the most recent quarters, oldest first">
            {[...profile.history].reverse().map((q) => (
              <span
                key={q.quarter_start}
                className={`quarter-chip rank-${q.profile_rank}`}
                title={`${quarterName(q.quarter_start)}: ${q.risk_profile}, volatility ${pct(q.annualized_volatility)}`}
              >
                {quarterName(q.quarter_start).slice(2)}
              </span>
            ))}
          </div>

          <details>
            <summary>What do these numbers mean?</summary>
            <p>
              <strong>Volatility</strong> measures how much the daily price moved. <strong>Largest drop</strong> is the
              biggest fall from a high point inside the quarter. <strong>Beta</strong> compares the stock's moves to the
              benchmark: above 1 means it moved more than the market on average. Quarters are grouped by a clustering
              model that compares the securities in this project to each other.
            </p>
          </details>

          <p className="note">{profile.disclaimer}</p>
        </>
      )}
    </section>
  )
}
