import React, { useEffect, useMemo, useRef, useState } from 'react'

// Price history as a line chart. One series (adjusted close), so no legend; the title names it.
// The data table below the chart stays as the accessible / copyable view of the same numbers.

type Bar = {
  bar_date: string
  close: number | string
  adjusted_close?: number | string | null
}

type Point = { date: string; value: number }

const RANGES: { label: string; bars: number }[] = [
  { label: '1M', bars: 22 },
  { label: '3M', bars: 66 },
  { label: '6M', bars: 130 },
  { label: '1Y', bars: 252 },
  { label: '5Y', bars: 1260 },
  { label: 'Max', bars: 10000 },
]

const W = 760
const H = 320
const PAD = { top: 16, right: 72, bottom: 36, left: 56 }

function niceTicks(min: number, max: number, count = 4): number[] {
  if (!(max > min)) return [min]
  const span = max - min
  const rough = span / count
  const pow = Math.pow(10, Math.floor(Math.log10(rough)))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => span / s <= count + 1) ?? pow
  const start = Math.ceil(min / step) * step
  const ticks: number[] = []
  for (let v = start; v <= max + 1e-9; v += step) ticks.push(Number(v.toFixed(6)))
  return ticks
}

function money(v: number): string {
  return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function shortDate(iso: string, span: number): string {
  const d = new Date(iso + 'T00:00:00')
  if (span > 400) return d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export default function PriceChart({ symbol }: { symbol: string }) {
  const [range, setRange] = useState('6M')
  const [points, setPoints] = useState<Point[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [hover, setHover] = useState<number | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    const limit = RANGES.find((r) => r.label === range)?.bars ?? 130
    const controller = new AbortController()
    setLoading(true)
    setError('')
    fetch(`/api/price-bars?symbol=${encodeURIComponent(symbol)}&limit=${limit}`, { signal: controller.signal })
      .then(async (response) => {
        const data = await response.json()
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`)
        const bars: Bar[] = data.items ?? []
        const series = bars
          .map((b) => ({ date: b.bar_date, value: Number(b.adjusted_close ?? b.close) }))
          .filter((p) => Number.isFinite(p.value))
          .reverse() // API returns newest first
        setPoints(series)
      })
      .catch((err) => {
        if (err.name !== 'AbortError') setError(err instanceof Error ? err.message : 'Could not load price history.')
      })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [symbol, range])

  const geom = useMemo(() => {
    if (points.length < 2) return null
    const values = points.map((p) => p.value)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const padV = (max - min) * 0.08 || max * 0.02
    const yMin = min - padV
    const yMax = max + padV
    const innerW = W - PAD.left - PAD.right
    const innerH = H - PAD.top - PAD.bottom
    const x = (i: number) => PAD.left + (i / (points.length - 1)) * innerW
    const y = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * innerH
    const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ')
    const yTicks = niceTicks(yMin, yMax)
    const first = new Date(points[0].date).getTime()
    const last = new Date(points[points.length - 1].date).getTime()
    const spanDays = (last - first) / 86_400_000
    const xTickCount = 5
    const xTicks = Array.from({ length: xTickCount }, (_, k) => Math.round((k * (points.length - 1)) / (xTickCount - 1)))
    return { x, y, path, yTicks, xTicks, spanDays, innerW, innerH }
  }, [points])

  function onMove(event: React.PointerEvent<SVGSVGElement>) {
    if (!geom || !svgRef.current) return
    const rect = svgRef.current.getBoundingClientRect()
    const px = ((event.clientX - rect.left) / rect.width) * W
    const ratio = (px - PAD.left) / geom.innerW
    const i = Math.round(Math.min(1, Math.max(0, ratio)) * (points.length - 1))
    setHover(i)
  }

  const firstPoint = points[0]
  const lastPoint = points[points.length - 1]
  const change = firstPoint && lastPoint ? ((lastPoint.value / firstPoint.value) - 1) * 100 : 0
  const hovered = hover !== null ? points[hover] : null
  const prev = hover !== null && hover > 0 ? points[hover - 1] : null

  return (
    <div className="price-chart">
      <div className="price-chart-head">
        <div>
          <h3>Adjusted closing price, {symbol}</h3>
          {firstPoint && lastPoint && (
            <p className="price-chart-summary">
              <strong>{money(lastPoint.value)}</strong> on {lastPoint.date}
              {' · '}
              {change >= 0 ? '+' : ''}
              {change.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}% since {firstPoint.date} ({points.length} trading days)
            </p>
          )}
        </div>
        <div className="range-row" role="group" aria-label="Date range">
          {RANGES.map((r) => (
            <button
              key={r.label}
              type="button"
              className={`range-btn${r.label === range ? ' active' : ''}`}
              aria-pressed={r.label === range}
              onClick={() => setRange(r.label)}
              disabled={loading}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="ask-error">{error}</p>}
      {!error && points.length < 2 && !loading && <p className="note">Not enough stored prices to draw a chart.</p>}

      {geom && (
        <div className="price-chart-plot">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label={`${symbol} adjusted close, ${firstPoint.date} to ${lastPoint.date}`}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
          >
            {geom.yTicks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={W - PAD.right} y1={geom.y(t)} y2={geom.y(t)} className="grid" />
                <text x={PAD.left - 8} y={geom.y(t)} dy="0.35em" textAnchor="end" className="axis">
                  {t.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </text>
              </g>
            ))}
            {geom.xTicks.map((i) => (
              <text key={i} x={geom.x(i)} y={H - PAD.bottom + 20} textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'} className="axis">
                {shortDate(points[i].date, geom.spanDays)}
              </text>
            ))}
            <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} className="axis-line" />

            <path d={geom.path} className="series" />

            {/* value at the line end, surface ring under the marker */}
            <circle cx={geom.x(points.length - 1)} cy={geom.y(lastPoint.value)} r={6} className="ring" />
            <circle cx={geom.x(points.length - 1)} cy={geom.y(lastPoint.value)} r={4} className="marker" />
            <text x={geom.x(points.length - 1) + 10} y={geom.y(lastPoint.value)} dy="0.35em" className="end-label">
              {money(lastPoint.value)}
            </text>

            {hovered && hover !== null && (
              <g>
                <line x1={geom.x(hover)} x2={geom.x(hover)} y1={PAD.top} y2={H - PAD.bottom} className="crosshair" />
                <circle cx={geom.x(hover)} cy={geom.y(hovered.value)} r={6} className="ring" />
                <circle cx={geom.x(hover)} cy={geom.y(hovered.value)} r={4} className="marker" />
              </g>
            )}
          </svg>

          {hovered && hover !== null && (
            <div
              className="price-tooltip"
              style={{
                left: `${(geom.x(hover) / W) * 100}%`,
                transform: geom.x(hover) > W * 0.7 ? 'translate(calc(-100% - 12px), 0)' : 'translate(12px, 0)',
              }}
            >
              <strong>{money(hovered.value)}</strong>
              <span>{hovered.date}</span>
              {prev && (
                <span>
                  {hovered.value >= prev.value ? '+' : ''}
                  {(((hovered.value / prev.value) - 1) * 100).toFixed(2)}% vs previous close
                </span>
              )}
            </div>
          )}
        </div>
      )}

      <p className="note">
        Split- and dividend-adjusted daily closes from the stored price bars (yfinance). Past prices describe what happened;
        they are not a forecast.
      </p>
    </div>
  )
}
