// Temporary assistant panel for POST /ask. The dashboard owner will replace this; keep it self-contained.
import React, { useState } from 'react'

type Citation = {
  n: number
  title: string
  url: string
  publisher: string
  published_at: string
  retrieved_at: string
  tier: string | null
  cited: boolean
}

type Glossary = { term: string; definition: string; source_title: string; source_url: string }

type Governance = {
  intent: string
  action: string
  mode: string
  confidence: number
  status: 'PASS' | 'REVIEW' | 'BLOCK' | 'SKIPPED'
  reasons: string[]
  risk_indicators: string[]
  guidance: string[]
}

type TraceStep = { step: string; ms: number; note: string }

type AskResponse = {
  answer: string
  citations: Citation[]
  governance: Governance
  concepts: string[]
  glossary: Glossary[]
  generated: boolean
  generator: string
  trace: TraceStep[] | null
}

const EXAMPLES: { label: string; query: string; expect: string }[] = [
  {
    label: 'Explain a term',
    query: 'What is an ETF and how is it different from a mutual fund?',
    expect: 'Educational: SEC glossary definitions cited as sources.',
  },
  {
    label: 'Market data',
    query: 'What is the current stock price trend for NVDA?',
    expect: 'Cited information: news plus stored daily prices, with a review caveat on news sources.',
  },
  {
    label: 'Concept links',
    query: 'How does inflation affect bond prices?',
    expect: 'Ontology match: related concepts expand the search.',
  },
  {
    label: 'Personal advice',
    query: 'Should I put $5000 into NVDA for my retirement?',
    expect: 'Safe redirect: factors and risks, no recommendation.',
  },
  {
    label: 'Trade request',
    query: 'Buy 10 shares of NVDA for me',
    expect: 'Refused: the service cannot execute transactions.',
  },
]

const STATUS_TEXT: Record<Governance['status'], string> = {
  PASS: 'Passed governance checks.',
  REVIEW: 'Returned with caveats: some sources are journalism or unverified, or some claims lack a citation. Verify important figures with a primary source.',
  BLOCK: 'The generated answer was rejected for advice-like language twice; showing glossary definitions instead.',
  SKIPPED: 'No answer was generated for this kind of request.',
}

const TIER_TEXT: Record<string, string> = {
  TIER_1: 'Regulator or government',
  TIER_2: 'Exchange or official data',
  TIER_3: 'Established journalism',
  TIER_4: 'User-generated',
  UNCLASSIFIED: 'Unclassified source',
  INVALID: 'Invalid source',
}

async function askApi(query: string, debug: boolean): Promise<AskResponse> {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, debug }),
    signal: AbortSignal.timeout(300000),
  })
  const data = await response.json()
  if (!response.ok) {
    const detail = data.detail
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status})`)
  }
  return data as AskResponse
}

// Minimal rendering: paragraphs, **bold**, and [n] markers that jump to the citation list.
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|\[\d+\])/g
  let last = 0
  let match: RegExpExecArray | null
  let i = 0
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    const token = match[0]
    if (token.startsWith('**')) {
      nodes.push(<strong key={`${keyPrefix}-b${i}`}>{token.slice(2, -2)}</strong>)
    } else {
      const n = token.slice(1, -1)
      nodes.push(
        <a key={`${keyPrefix}-c${i}`} className="cite" href={`#cite-${n}`}>
          [{n}]
        </a>
      )
    }
    last = match.index + token.length
    i += 1
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

function renderAnswer(answer: string): React.ReactNode {
  return answer
    .split(/\n\s*\n/)
    .filter((block) => block.trim())
    .map((block, index) => (
      <p key={index} className="answer-block">
        {block.split('\n').map((line, j) => (
          <React.Fragment key={j}>
            {j > 0 && <br />}
            {renderInline(line, `${index}-${j}`)}
          </React.Fragment>
        ))}
      </p>
    ))
}

export default function AskPanel() {
  const [query, setQuery] = useState(EXAMPLES[0].query)
  const [debug, setDebug] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<AskResponse | null>(null)
  const [asked, setAsked] = useState('')

  async function submit(text: string) {
    const question = text.trim()
    if (!question || loading) return
    setLoading(true)
    setError('')
    setResult(null)
    setAsked(question)
    try {
      setResult(await askApi(question, debug))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The assistant could not answer.')
    } finally {
      setLoading(false)
    }
  }

  function pickExample(example: (typeof EXAMPLES)[number]) {
    setQuery(example.query)
    void submit(example.query)
  }

  const gov = result?.governance

  return (
    <section className="ask-panel">
      <span className="eyebrow">ASK THE ASSISTANT · TEMPORARY PANEL</span>
      <h2>Ask a financial literacy question</h2>
      <p className="note">
        Educational answers with citations. The assistant explains and summarizes sources; it does not give
        personal investment advice or place trades.
      </p>

      <div className="examples">
        {EXAMPLES.map((example) => (
          <button
            key={example.query}
            type="button"
            className="example"
            title={example.expect}
            disabled={loading}
            onClick={() => pickExample(example)}
          >
            {example.label}
          </button>
        ))}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          void submit(query)
        }}
      >
        <textarea
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          rows={2}
          maxLength={2000}
          placeholder="Ask about a term, a company, or recent market news"
          disabled={loading}
        />
        <div className="ask-controls">
          <button type="submit" disabled={loading || query.trim().length < 2}>
            {loading ? 'Thinking...' : 'Ask'}
          </button>
          <label className="debug-toggle">
            <input type="checkbox" checked={debug} onChange={(event) => setDebug(event.target.checked)} /> show trace
          </label>
        </div>
      </form>

      {loading && (
        <p role="status" className="note">
          Classifying the question, retrieving sources, and generating an answer for “{asked}”...
        </p>
      )}
      {error && (
        <p role="alert" className="ask-error">
          {error}
        </p>
      )}

      {result && gov && (
        <div className="ask-result">
          <div className="gov-row">
            <span className={`badge badge-${gov.status.toLowerCase()}`}>{gov.status}</span>
            <span className="gov-meta">
              {gov.intent.replace(/_/g, ' ').toLowerCase()} · {gov.mode.replace(/_/g, ' ').toLowerCase()}
              {result.generated ? ` · ${result.generator}` : ' · no model call'}
            </span>
          </div>
          <p className="gov-text">{STATUS_TEXT[gov.status]}</p>

          <div className="answer">{renderAnswer(result.answer)}</div>

          {result.concepts.length > 0 && (
            <p className="note">
              Related concepts: {result.concepts.join(', ')}
            </p>
          )}

          {result.citations.length > 0 && (
            <div className="citations">
              <h3>Sources</h3>
              <ol>
                {result.citations.map((c) => (
                  <li key={c.n} id={`cite-${c.n}`} className={c.cited ? 'cited' : 'uncited'}>
                    <a href={c.url} target="_blank" rel="noreferrer">
                      {c.title}
                    </a>
                    <span className="cite-meta">
                      {' '}
                      {c.publisher}
                      {c.published_at ? ` · ${c.published_at.slice(0, 10)}` : ''}
                      {c.tier ? ` · ${TIER_TEXT[c.tier] ?? c.tier}` : c.cited ? '' : ' · not cited in the answer'}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {result.glossary.length > 0 && (
            <details className="glossary">
              <summary>Terms from your question ({result.glossary.length})</summary>
              <dl className="term-list">
                {result.glossary.map((g) => (
                  <div key={g.term}>
                    <dt>{g.term}</dt>
                    <dd>
                      {g.definition}{' '}
                      <a href={g.source_url} target="_blank" rel="noreferrer">
                        {g.source_title}
                      </a>
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          )}

          {(gov.reasons.length > 0 || gov.risk_indicators.length > 0) && (
            <details>
              <summary>Why this status</summary>
              <ul className="reasons">
                {gov.risk_indicators.map((r) => (
                  <li key={`risk-${r}`}>risk: {r.replace(/_/g, ' ')}</li>
                ))}
                {gov.reasons.map((r) => (
                  <li key={r}>{r.replace(/_/g, ' ')}</li>
                ))}
              </ul>
            </details>
          )}

          {result.trace && (
            <details open>
              <summary>Trace</summary>
              <table className="trace">
                <tbody>
                  {result.trace.map((step) => (
                    <tr key={step.step + step.ms}>
                      <td>{step.step}</td>
                      <td className="ms">{step.ms} ms</td>
                      <td>{step.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </div>
      )}
    </section>
  )
}
