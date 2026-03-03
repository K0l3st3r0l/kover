import { useState, useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine
} from 'recharts'

interface TWRPoint {
  date: string
  twr_pct: number
}

interface BenchmarkPoint {
  date: string
  pct: number
}

interface TWRData {
  twr_series: TWRPoint[]
  twr_final: number
  benchmark_series: BenchmarkPoint[]   // NASDAQ (^IXIC)
  sp500_series: BenchmarkPoint[]       // S&P 500 (^GSPC)
  error: string | null
}

interface Props {
  data: TWRData
}

const formatDate = (d: string) => {
  const dt = new Date(d + 'T00:00:00')
  return dt.toLocaleDateString('es-CL', { month: 'short', year: '2-digit' })
}

const formatPct = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`

export default function TWRChart({ data }: Props) {
  const [showNasdaq, setShowNasdaq] = useState(true)
  const [showSP500, setShowSP500] = useState(true)

  // Merge twr + both benchmarks on aligned dates (sample every N points for performance)
  const chartData = useMemo(() => {
    const twrMap  = new Map(data.twr_series.map(p => [p.date, p.twr_pct]))
    const nqMap   = new Map((data.benchmark_series ?? []).map(p => [p.date, p.pct]))
    const sp500Map = new Map((data.sp500_series ?? []).map(p => [p.date, p.pct]))

    const allDates = [...new Set([
      ...data.twr_series.map(p => p.date),
      ...(data.benchmark_series ?? []).map(p => p.date),
      ...(data.sp500_series ?? []).map(p => p.date),
    ])].sort()

    const sampled = allDates.filter((_, i) => i % 3 === 0 || i === allDates.length - 1)

    return sampled.map(d => ({
      date: d,
      twr:    twrMap.get(d) ?? null,
      nasdaq: nqMap.get(d)  ?? null,
      sp500:  sp500Map.get(d) ?? null,
    }))
  }, [data])

  const twrColor    = (data.twr_final ?? 0) >= 0 ? '#16a34a' : '#dc2626'
  const nasdaqColor = '#7c3aed'
  const sp500Color  = '#f59e0b'

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    const d = new Date(label + 'T00:00:00').toLocaleDateString('es-CL', {
      day: 'numeric', month: 'long', year: 'numeric'
    })
    return (
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-3 text-sm">
        <p className="font-semibold text-gray-700 dark:text-gray-200 mb-2">{d}</p>
        {payload.map((entry: any) => {
          if (entry.value === null || entry.value === undefined) return null
          return (
            <p key={entry.dataKey} style={{ color: entry.color }} className="font-medium">
              {entry.name}: {formatPct(entry.value)}
            </p>
          )
        })}
      </div>
    )
  }

  if (data.error) {
    return (
      <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8">
        <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-2">📊 Rendimiento TWR</h3>
        <p className="text-red-500 text-sm">Error al cargar datos históricos: {data.error}</p>
      </div>
    )
  }

  if (!data.twr_series.length) {
    return null
  }

  return (
    <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-5">
        <div>
          <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">📊 Rendimiento TWR</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Time-Weighted Return — metodología idéntica a IBKR
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-3xl font-bold ${data.twr_final >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600'}`}>
            {formatPct(data.twr_final)}
          </span>
          <button
            onClick={() => setShowNasdaq(v => !v)}
            className={`text-xs px-3 py-1.5 rounded border transition-colors ${
              showNasdaq
                ? 'bg-purple-100 border-purple-300 text-purple-700 dark:bg-purple-900/30 dark:border-purple-600 dark:text-purple-300'
                : 'border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700'
            }`}
          >
            vs NASDAQ
          </button>
          <button
            onClick={() => setShowSP500(v => !v)}
            className={`text-xs px-3 py-1.5 rounded border transition-colors ${
              showSP500
                ? 'bg-amber-100 border-amber-300 text-amber-700 dark:bg-amber-900/30 dark:border-amber-600 dark:text-amber-300'
                : 'border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700'
            }`}
          >
            vs S&amp;P 500
          </button>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={380}>
        <LineChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            stroke="#9ca3af"
            style={{ fontSize: '11px' }}
            interval="preserveStartEnd"
            minTickGap={60}
          />
          <YAxis
            tickFormatter={(v: number) => `${v.toFixed(0)}%`}
            stroke="#9ca3af"
            style={{ fontSize: '11px' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '12px' }} iconType="line" />
          <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="4 4" />

          <Line
            type="monotone"
            dataKey="twr"
            name="Performance TWR"
            stroke={twrColor}
            strokeWidth={2.5}
            dot={false}
            activeDot={{ r: 5 }}
            connectNulls
          />
          {showNasdaq && (
            <Line
              type="monotone"
              dataKey="nasdaq"
              name="NASDAQ"
              stroke={nasdaqColor}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 4 }}
              strokeDasharray="4 2"
              connectNulls
            />
          )}
          {showSP500 && (
            <Line
              type="monotone"
              dataKey="sp500"
              name="S&P 500"
              stroke={sp500Color}
              strokeWidth={1.5}
              dot={false}
              activeDot={{ r: 4 }}
              strokeDasharray="6 3"
              connectNulls
            />
          )}
        </LineChart>
      </ResponsiveContainer>

      <p className="text-xs text-gray-400 dark:text-gray-500 mt-3">
        TWR elimina el efecto de los flujos de caja — mide la rentabilidad pura de las decisiones de inversión.
        Cada transacción marca un nuevo sub-período; los retornos se encadenan multiplicativamente.
      </p>
    </div>
  )
}
