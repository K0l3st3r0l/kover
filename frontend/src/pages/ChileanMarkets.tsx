import { useEffect, useState, useCallback, useMemo } from 'react'
import {
  LineChart,
  BarChart,
  Bar,
  Line,
  ReferenceDot,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { format, parseISO } from 'date-fns'
import { es } from 'date-fns/locale'
import TradingViewChart from '../components/TradingViewChart'
import api from '../services/api'

// ─── Types ────────────────────────────────────────────────────────────────────

interface FundDataPoint {
  date: string
  value: number      // normalised (base 100)
  raw_value: number
  patrimonio: number // total system patrimonio (MM CLP)
  obv: number        // on-balance volume
}

interface FundSeries {
  color: string
  risk_label: string
  data: FundDataPoint[]
}

interface AFPResponse {
  funds: Record<string, FundSeries>
  period_days: number
  errors: string[]
  source: string
}

// ─── Period options ────────────────────────────────────────────────────────────

const PERIODS: { label: string; days: number }[] = [
  { label: '1M',  days: 30   },
  { label: '3M',  days: 90   },
  { label: '6M',  days: 180  },
  { label: '1A',  days: 365  },
  { label: '3A',  days: 1095 },
  { label: '5A',  days: 1825 },
  { label: 'Max', days: 5000 },
]

const FUND_NAMES: Record<string, string> = {
  A: 'Fondo A',
  B: 'Fondo B',
  C: 'Fondo C',
  D: 'Fondo D',
  E: 'Fondo E',
}

// ─── AFP Chart ────────────────────────────────────────────────────────────────

function formatDate(dateStr: string) {
  try {
    return format(parseISO(dateStr), 'dd MMM yy', { locale: es })
  } catch {
    return dateStr
  }
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ChileanMarkets() {
  const [afpData, setAfpData] = useState<AFPResponse | null>(null)
  const [afpLoading, setAfpLoading] = useState(false)
  const [afpError, setAfpError] = useState<string | null>(null)
  const [selectedDays, setSelectedDays] = useState(365)
  const [chartData, setChartData] = useState<any[]>([])
  const [activeFunds, setActiveFunds] = useState<Set<string>>(new Set(['A', 'B', 'C', 'D', 'E']))
  const [patrimonioChartData, setPatrimonioChartData] = useState<any[]>([])
  const [showPatrimonio, setShowPatrimonio] = useState(true)
  const [showOBV, setShowOBV] = useState(true)
  const [showDivergences, setShowDivergences] = useState(true)
  // 'rent' | 'pat' | 'obv' | null
  const [maximized, setMaximized] = useState<'rent' | 'pat' | 'obv' | null>(null)

  const fetchAFP = useCallback(async (days: number) => {
    setAfpLoading(true)
    setAfpError(null)
    try {
      const res = await api.get<AFPResponse>(`/api/market/afp-funds?days=${days}`)
      setAfpData(res.data)

      // Build unified rentabilidad chart data: one row per date (includes obv_X keys)
      const dateMap = new Map<string, any>()
      // Build patrimonio chart data
      const patDateMap = new Map<string, any>()
      for (const [fund, series] of Object.entries(res.data.funds)) {
        for (const point of series.data) {
          if (!dateMap.has(point.date)) {
            dateMap.set(point.date, { date: point.date })
          }
          dateMap.get(point.date)[fund] = point.value
          dateMap.get(point.date)[`obv_${fund}`] = point.obv

          if (!patDateMap.has(point.date)) {
            patDateMap.set(point.date, { date: point.date })
          }
          patDateMap.get(point.date)[fund] = point.patrimonio
        }
      }
      const sorted = Array.from(dateMap.values()).sort(
        (a, b) => a.date.localeCompare(b.date)
      )
      setChartData(sorted)
      const sortedPat = Array.from(patDateMap.values()).sort(
        (a, b) => a.date.localeCompare(b.date)
      )
      setPatrimonioChartData(sortedPat)
    } catch (e: any) {
      setAfpError(e?.response?.data?.detail ?? 'Error al cargar datos AFP')
    } finally {
      setAfpLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAFP(selectedDays)
  }, [selectedDays, fetchAFP])

  const toggleFund = (fund: string) => {
    setActiveFunds(prev => {
      const next = new Set(prev)
      if (next.has(fund)) {
        if (next.size > 1) next.delete(fund)
      } else {
        next.add(fund)
      }
      return next
    })
  }

  const handleDoubleClick = (pane: 'rent' | 'pat' | 'obv') => {
    setMaximized(prev => (prev === pane ? null : pane))
  }

  const paneHeight = (pane: 'rent' | 'pat' | 'obv', defaultH: number) => {
    if (maximized === null) return defaultH
    return maximized === pane ? 560 : 0
  }

  const paneVisible = (pane: 'rent' | 'pat' | 'obv') => {
    if (maximized !== null) return maximized === pane
    if (pane === 'pat') return showPatrimonio
    if (pane === 'obv') return showOBV
    return true
  }

  const fmtBig = (v: number) => {
    const abs = Math.abs(v)
    if (abs >= 1e12) return `${(v / 1e12).toFixed(1)}T`
    if (abs >= 1e9)  return `${(v / 1e9).toFixed(1)}B`
    if (abs >= 1e6)  return `${(v / 1e6).toFixed(1)}M`
    return v.toFixed(0)
  }

  const funds = afpData?.funds ?? {}
  const fundKeys = Object.keys(funds).sort()

  // Max/min OBV per active fund within the current chartData range
  const obvExtremes = useMemo(() => {
    if (!chartData.length) return []
    const result: { fund: string; maxDate: string; maxVal: number; minDate: string; minVal: number }[] = []
    for (const fund of fundKeys.filter(f => activeFunds.has(f))) {
      const key = `obv_${fund}`
      let maxVal = -Infinity, minVal = Infinity
      let maxDate = '', minDate = ''
      for (const row of chartData) {
        const v = row[key]
        if (v === undefined || v === null) continue
        if (v > maxVal) { maxVal = v; maxDate = row.date }
        if (v < minVal) { minVal = v; minDate = row.date }
      }
      if (maxDate) result.push({ fund, maxDate, maxVal, minDate, minVal })
    }
    return result
  }, [chartData, fundKeys, activeFunds])

  // Divergence detection (hidden + regular, bearish + bullish)
  type DivType = 'hidden_bearish' | 'hidden_bullish' | 'regular_bearish' | 'regular_bullish'
  interface Divergence { type: DivType; fund: string; date: string; obv: number }

  const divergences = useMemo((): Divergence[] => {
    if (!chartData.length) return []
    // Adaptive window: ~1 swing per 20 candles, min 5
    const WIN = Math.max(5, Math.floor(chartData.length / 20))
    const result: Divergence[] = []

    for (const fund of fundKeys.filter(f => activeFunds.has(f))) {
      const priceKey = fund
      const obvKey = `obv_${fund}`

      // Find swing highs (local max in price)
      const swingHighs: { date: string; price: number; obv: number }[] = []
      for (let i = WIN; i < chartData.length - WIN; i++) {
        const price = chartData[i][priceKey]
        const obv   = chartData[i][obvKey]
        if (price == null || obv == null) continue
        let isHigh = true
        for (let j = i - WIN; j <= i + WIN; j++) {
          if (j !== i && (chartData[j][priceKey] ?? -Infinity) >= price) { isHigh = false; break }
        }
        if (isHigh) swingHighs.push({ date: chartData[i].date, price, obv })
      }

      // Find swing lows (local min in price)
      const swingLows: { date: string; price: number; obv: number }[] = []
      for (let i = WIN; i < chartData.length - WIN; i++) {
        const price = chartData[i][priceKey]
        const obv   = chartData[i][obvKey]
        if (price == null || obv == null) continue
        let isLow = true
        for (let j = i - WIN; j <= i + WIN; j++) {
          if (j !== i && (chartData[j][priceKey] ?? Infinity) <= price) { isLow = false; break }
        }
        if (isLow) swingLows.push({ date: chartData[i].date, price, obv })
      }

      // Consecutive swing highs → bearish signals
      for (let i = 1; i < swingHighs.length; i++) {
        const prev = swingHighs[i - 1], curr = swingHighs[i]
        if (curr.price < prev.price && curr.obv > prev.obv)
          result.push({ type: 'hidden_bearish',   fund, date: curr.date, obv: curr.obv })
        if (curr.price > prev.price && curr.obv < prev.obv)
          result.push({ type: 'regular_bearish',  fund, date: curr.date, obv: curr.obv })
      }

      // Consecutive swing lows → bullish signals
      for (let i = 1; i < swingLows.length; i++) {
        const prev = swingLows[i - 1], curr = swingLows[i]
        if (curr.price > prev.price && curr.obv < prev.obv)
          result.push({ type: 'hidden_bullish',   fund, date: curr.date, obv: curr.obv })
        if (curr.price < prev.price && curr.obv > prev.obv)
          result.push({ type: 'regular_bullish',  fund, date: curr.date, obv: curr.obv })
      }
    }
    return result
  }, [chartData, fundKeys, activeFunds])

  const DIV_META: Record<DivType, { color: string; label: string; pos: 'top' | 'bottom' }> = {
    hidden_bearish:  { color: '#f97316', label: '▼ Div.O.Baj', pos: 'bottom' },
    hidden_bullish:  { color: '#22c55e', label: '▲ Div.O.Alc', pos: 'top'    },
    regular_bearish: { color: '#ef4444', label: '▼ Div.Baj',   pos: 'bottom' },
    regular_bullish: { color: '#3b82f6', label: '▲ Div.Alc',   pos: 'top'    },
  }

  return (
    <div className="page space-y-8">
      {/* ── Header ── */}
      <div className="page-header">
        <div>
          <h1 className="page-title">🇨🇱 Mercado Chileno</h1>
          <p className="page-subtitle">IPSA · USD/CLP · Fondos AFP A–E</p>
        </div>
      </div>

      {/* ── TradingView charts ── */}
      <div className="grid grid-cols-1 gap-6">
        {/* IPSA */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
          <div className="mb-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
              📈 IPSA Chile
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Índice de Precio Selectivo de Acciones · Bolsa de Santiago
            </p>
          </div>
          <TradingViewChart ticker="SP_IPSA" height={560} />
        </div>

        {/* USDCLP */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
          <div className="mb-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
              💵 USD / CLP
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Tipo de cambio Dólar Estadounidense · Peso Chileno
            </p>
          </div>
          <TradingViewChart ticker="FX:USDCLP" height={560} />
        </div>
      </div>

      {/* ── AFP Funds ── */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
        {/* Title + period selector */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
              🏦 Fondos AFP — Rentabilidad Histórica
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Valor cuota promedio · normalizado a base 100 · Fuente: Superintendencia de Pensiones
            </p>
          </div>
          {/* Period buttons */}
          <div className="flex gap-1 flex-wrap">
            {PERIODS.map(p => (
              <button
                key={p.label}
                onClick={() => setSelectedDays(p.days)}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                  selectedDays === p.days
                    ? 'bg-blue-600 text-white shadow'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Fund toggle pills + indicator toggles */}
        {fundKeys.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4 items-center">
            {fundKeys.map(fund => {
              const isActive = activeFunds.has(fund)
              const color = funds[fund].color
              return (
                <button
                  key={fund}
                  onClick={() => toggleFund(fund)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${
                    isActive ? 'text-white shadow-md' : 'bg-transparent text-gray-400 dark:text-gray-500 border-gray-200 dark:border-gray-600'
                  }`}
                  style={isActive ? { backgroundColor: color, borderColor: color } : { borderColor: color, color: color }}
                >
                  <span>{FUND_NAMES[fund]}</span>
                  <span className="text-xs opacity-70">({funds[fund].risk_label})</span>
                </button>
              )
            })}
            <div className="ml-auto flex gap-2">
              <button
                onClick={() => setShowPatrimonio(v => !v)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border-2 transition-all ${
                  showPatrimonio
                    ? 'bg-slate-600 text-white border-slate-600'
                    : 'bg-transparent text-gray-400 border-gray-300 dark:border-gray-600'
                }`}
              >
                🏦 Patrimonio
              </button>
              <button
                onClick={() => setShowOBV(v => !v)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border-2 transition-all ${
                  showOBV
                    ? 'bg-slate-600 text-white border-slate-600'
                    : 'bg-transparent text-gray-400 border-gray-300 dark:border-gray-600'
                }`}
              >
                📊 OBV
              </button>
              <button
                onClick={() => setShowDivergences(v => !v)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border-2 transition-all ${
                  showDivergences
                    ? 'bg-orange-500 text-white border-orange-500'
                    : 'bg-transparent text-gray-400 border-gray-300 dark:border-gray-600'
                }`}
              >
                🔀 Divergencias
              </button>
            </div>
          </div>
        )}

        {/* Chart area */}
        {afpLoading && (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
        )}

        {afpError && !afpLoading && (
          <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300">
            <p className="font-semibold">No se pudieron cargar los datos AFP</p>
            <p className="mt-1 text-xs">{afpError}</p>
            <button
              onClick={() => fetchAFP(selectedDays)}
              className="mt-3 px-3 py-1.5 bg-red-100 dark:bg-red-900/40 hover:bg-red-200 dark:hover:bg-red-900/60 rounded-lg text-xs font-medium transition-colors"
            >
              Reintentar
            </button>
          </div>
        )}

        {!afpLoading && !afpError && chartData.length > 0 && (
          <>
            {/* ── Rentabilidad ─────────────────────────────────────────── */}
            <div
              className="relative cursor-pointer select-none"
              onDoubleClick={() => handleDoubleClick('rent')}
              title="Doble clic para maximizar / restaurar"
            >
              {maximized === 'rent' && (
                <span className="absolute top-1 right-2 text-xs text-gray-400 dark:text-gray-500 z-10">doble clic para restaurar</span>
              )}
              <p className="text-xs text-gray-400 dark:text-gray-500 mb-1 ml-1 select-none">
                Valor cuota (base 100){maximized === null ? ' · doble clic para maximizar' : ''}
              </p>
              <ResponsiveContainer width="100%" height={paneHeight('rent', 320)}>
                <LineChart syncId="afp-sync" data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                  <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 11 }} tickLine={false} minTickGap={40} hide />
                  <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11 }} tickLine={false} tickFormatter={v => v.toFixed(0)} width={50} />
                  <Tooltip
                    content={({ active, payload, label }: any) => {
                      if (!active || !payload?.length) return null
                      return (
                        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-3 shadow-lg text-sm">
                          <p className="font-semibold text-gray-700 dark:text-gray-200 mb-2">{formatDate(label)}</p>
                          {payload.map((e: any) => (
                            <p key={e.dataKey} style={{ color: e.color }} className="font-medium">
                              {FUND_NAMES[e.dataKey] ?? e.dataKey}: {e.value?.toFixed(2)}
                            </p>
                          ))}
                        </div>
                      )
                    }}
                  />
                  <Legend formatter={v => FUND_NAMES[v] ?? v} wrapperStyle={{ fontSize: '12px' }} />
                  {fundKeys.filter(f => activeFunds.has(f)).map(fund => (
                    <Line key={fund} type="monotone" dataKey={fund} name={fund}
                      stroke={funds[fund].color} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* ── Patrimonio (barras de volumen) ────────────────────────── */}
            {paneVisible('pat') && patrimonioChartData.length > 0 && (
              <div
                className="mt-1 cursor-pointer select-none"
                onDoubleClick={() => handleDoubleClick('pat')}
                title="Doble clic para maximizar / restaurar"
              >
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-1 ml-1 select-none">Patrimonio total (CLP)</p>
                <ResponsiveContainer width="100%" height={paneHeight('pat', 90)}>
                  <BarChart syncId="afp-sync" data={patrimonioChartData} margin={{ top: 0, right: 16, left: 0, bottom: 0 }} barCategoryGap="0%">
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10 }} tickLine={false} minTickGap={40}
                      hide={paneVisible('obv')} />
                    <YAxis tick={{ fontSize: 10 }} tickLine={false} width={50} tickFormatter={fmtBig} />
                    <Tooltip
                      content={({ active, payload, label }: any) => {
                        if (!active || !payload?.length) return null
                        return (
                          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-2 shadow-lg text-xs">
                            <p className="font-semibold text-gray-700 dark:text-gray-200 mb-1">{formatDate(label)}</p>
                            {payload.map((e: any) => (
                              <p key={e.dataKey} style={{ color: e.color }}>
                                {FUND_NAMES[e.dataKey] ?? e.dataKey}: {fmtBig(e.value)} CLP
                              </p>
                            ))}
                          </div>
                        )
                      }}
                    />
                    {fundKeys.filter(f => activeFunds.has(f)).map(fund => (
                      <Bar key={fund} dataKey={fund} name={fund} fill={funds[fund]?.color} fillOpacity={0.6} isAnimationActive={false} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* ── OBV ──────────────────────────────────────────────────── */}
            {paneVisible('obv') && (
              <div
                className="mt-1 cursor-pointer select-none"
                onDoubleClick={() => handleDoubleClick('obv')}
                title="Doble clic para maximizar / restaurar"
              >
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-1 ml-1 select-none">OBV — On-Balance Volume (CLP)</p>
                <div className="[&_svg]:overflow-visible">
                <ResponsiveContainer width="100%" height={paneHeight('obv', 220)}>
                  <LineChart syncId="afp-sync" data={chartData} margin={{ top: 22, right: 16, left: 0, bottom: 22 }}>
                    <CartesianGrid strokeDasharray="3 3" className="opacity-20" />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10 }} tickLine={false} minTickGap={40} />
                    <YAxis tick={{ fontSize: 10 }} tickLine={false} width={55} tickFormatter={fmtBig} domain={['auto', 'auto']} />
                    <Tooltip
                      content={({ active, payload, label }: any) => {
                        if (!active || !payload?.length) return null
                        return (
                          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-2 shadow-lg text-xs">
                            <p className="font-semibold text-gray-700 dark:text-gray-200 mb-1">{formatDate(label)}</p>
                            {payload.map((e: any) => {
                              const fund = String(e.dataKey).replace('obv_', '')
                              return (
                                <p key={e.dataKey} style={{ color: e.color }}>
                                  {FUND_NAMES[fund] ?? fund}: {fmtBig(e.value)} CLP
                                </p>
                              )
                            })}
                          </div>
                        )
                      }}
                    />
                    <Legend formatter={v => `OBV ${FUND_NAMES[v.replace('obv_', '')] ?? v}`} wrapperStyle={{ fontSize: '11px' }} />
                    {fundKeys.filter(f => activeFunds.has(f)).map(fund => (
                      <Line key={`obv_${fund}`} type="monotone" dataKey={`obv_${fund}`} name={`obv_${fund}`}
                        stroke={funds[fund]?.color} strokeWidth={1.5} dot={false} activeDot={{ r: 3 }} />
                    ))}
                    {/* Max/min markers — círculo hueco con borde del color del fondo */}
                    {obvExtremes.map(({ fund, maxDate, maxVal, minDate, minVal }) => {
                      const color = funds[fund]?.color
                      return [
                        <ReferenceDot key={`max_${fund}`} x={maxDate} y={maxVal}
                          r={6} fill="transparent" stroke={color} strokeWidth={2} strokeDasharray="3 2"
                          label={{ value: `MAX ${fmtBig(maxVal)}`, position: 'top', fontSize: 8, fill: '#9ca3af', fontWeight: 600 }} />,
                        <ReferenceDot key={`min_${fund}`} x={minDate} y={minVal}
                          r={6} fill="transparent" stroke={color} strokeWidth={2} strokeDasharray="3 2"
                          label={{ value: `MIN ${fmtBig(minVal)}`, position: 'bottom', fontSize: 8, fill: '#9ca3af', fontWeight: 600 }} />,
                      ]
                    })}
                    {/* Divergence markers */}
                    {showDivergences && divergences.map((d, i) => {
                      const meta = DIV_META[d.type]
                      return (
                        <ReferenceDot key={`div_${i}`} x={d.date} y={d.obv}
                          r={5} fill={meta.color} stroke="#fff" strokeWidth={1.5} opacity={0.9}
                          label={{ value: meta.label, position: meta.pos, fontSize: 8, fill: meta.color, fontWeight: 'bold' }}
                        />
                      )
                    })}
                  </LineChart>
                </ResponsiveContainer>
                </div>
                {showDivergences && (
                  <div className="mt-2 flex flex-wrap gap-3 text-xs ml-1 items-center">
                    {(Object.entries(DIV_META) as [DivType, typeof DIV_META[DivType]][]).map(([type, meta]) => (
                      <span key={type} className="flex items-center gap-1">
                        <span style={{ color: meta.color }} className="font-bold text-base leading-none">●</span>
                        <span className="text-gray-500 dark:text-gray-400">{meta.label.replace('▼ ', '').replace('▲ ', '')}</span>
                      </span>
                    ))}
                    <span className="flex items-center gap-1 ml-1">
                      <span className="inline-block w-3 h-3 rounded-full border-2 border-gray-400 border-dashed bg-transparent"></span>
                      <span className="text-gray-500 dark:text-gray-400">MAX / MIN período</span>
                    </span>
                    <span className="text-gray-400 dark:text-gray-600">
                      · Div.O = Oculta (continuación) · Div. = Regular (reversión)
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Return summary cards */}
            <div className="mt-6 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {fundKeys.map(fund => {
                const series = funds[fund].data
                if (!series.length) return null
                const first = series[0].value
                const last = series[series.length - 1].value
                const change = last - first  // base 100 → change%
                const positive = change >= 0
                return (
                  <div
                    key={fund}
                    className="rounded-xl border-2 p-3 transition-all"
                    style={{
                      borderColor: funds[fund].color,
                      opacity: activeFunds.has(fund) ? 1 : 0.45,
                    }}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span
                        className="text-sm font-bold"
                        style={{ color: funds[fund].color }}
                      >
                        {FUND_NAMES[fund]}
                      </span>
                      <span
                        className={`text-sm font-bold ${
                          positive ? 'text-green-500' : 'text-red-500'
                        }`}
                      >
                        {positive ? '+' : ''}
                        {change.toFixed(2)}%
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 dark:text-gray-500">
                      {funds[fund].risk_label}
                    </p>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                      Val. cuota: {series[series.length - 1].raw_value.toLocaleString('es-CL')}
                    </p>
                    {series[series.length - 1].patrimonio > 0 && (
                      <p className="text-xs text-gray-400 dark:text-gray-500">
                        Patrimonio: {series[series.length - 1].patrimonio >= 1e9
                          ? `${(series[series.length - 1].patrimonio / 1e9).toFixed(1)}B`
                          : `${(series[series.length - 1].patrimonio / 1e6).toFixed(0)}M`} CLP
                      </p>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Source footnote */}
            {afpData && (
              <p className="mt-4 text-xs text-gray-400 dark:text-gray-600 text-right">
                Fuente: {afpData.source}
                {afpData.errors.length > 0 && (
                  <span className="ml-2 text-yellow-500">
                    · Fondos sin datos: {afpData.errors.join(', ')}
                  </span>
                )}
              </p>
            )}
          </>
        )}

        {!afpLoading && !afpError && chartData.length === 0 && !afpData && (
          <div className="flex items-center justify-center h-40 text-gray-400 dark:text-gray-600 text-sm">
            Cargando datos...
          </div>
        )}
      </div>
    </div>
  )
}
