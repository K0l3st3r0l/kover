import { useEffect, useState, useCallback } from 'react'
import {
  LineChart,
  Line,
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
  value: number    // normalised (base 100)
  raw_value: number
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

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-3 shadow-lg text-sm">
      <p className="font-semibold text-gray-700 dark:text-gray-200 mb-2">{formatDate(label)}</p>
      {payload.map((entry: any) => (
        <p key={entry.dataKey} style={{ color: entry.color }} className="font-medium">
          {entry.name}: {entry.value?.toFixed(2)}
        </p>
      ))}
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ChileanMarkets() {
  const [afpData, setAfpData] = useState<AFPResponse | null>(null)
  const [afpLoading, setAfpLoading] = useState(false)
  const [afpError, setAfpError] = useState<string | null>(null)
  const [selectedDays, setSelectedDays] = useState(365)
  const [chartData, setChartData] = useState<any[]>([])
  const [activeFunds, setActiveFunds] = useState<Set<string>>(new Set(['A', 'B', 'C', 'D', 'E']))

  const fetchAFP = useCallback(async (days: number) => {
    setAfpLoading(true)
    setAfpError(null)
    try {
      const res = await api.get<AFPResponse>(`/api/market/afp-funds?days=${days}`)
      setAfpData(res.data)

      // Build unified chart data: one row per date
      const dateMap = new Map<string, any>()
      for (const [fund, series] of Object.entries(res.data.funds)) {
        for (const point of series.data) {
          if (!dateMap.has(point.date)) {
            dateMap.set(point.date, { date: point.date })
          }
          dateMap.get(point.date)[fund] = point.value
        }
      }
      const sorted = Array.from(dateMap.values()).sort(
        (a, b) => a.date.localeCompare(b.date)
      )
      setChartData(sorted)
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
        if (next.size > 1) next.delete(fund) // keep at least one
      } else {
        next.add(fund)
      }
      return next
    })
  }

  const funds = afpData?.funds ?? {}
  const fundKeys = Object.keys(funds).sort()

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

        {/* Fund toggle pills */}
        {fundKeys.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-6">
            {fundKeys.map(fund => {
              const isActive = activeFunds.has(fund)
              const color = funds[fund].color
              return (
                <button
                  key={fund}
                  onClick={() => toggleFund(fund)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${
                    isActive
                      ? 'text-white shadow-md'
                      : 'bg-transparent text-gray-400 dark:text-gray-500 border-gray-200 dark:border-gray-600'
                  }`}
                  style={
                    isActive
                      ? { backgroundColor: color, borderColor: color }
                      : { borderColor: color, color: color }
                  }
                >
                  <span>{FUND_NAMES[fund]}</span>
                  <span className="text-xs opacity-70">({funds[fund].risk_label})</span>
                </button>
              )
            })}
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
            <ResponsiveContainer width="100%" height={400}>
              <LineChart
                data={chartData}
                margin={{ top: 5, right: 20, left: 0, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                <XAxis
                  dataKey="date"
                  tickFormatter={formatDate}
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  minTickGap={40}
                />
                <YAxis
                  domain={['auto', 'auto']}
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  tickFormatter={v => `${v.toFixed(0)}`}
                  width={50}
                />
                <Tooltip content={<CustomTooltip />} />
                <Legend
                  formatter={value => FUND_NAMES[value] ?? value}
                  wrapperStyle={{ fontSize: '13px' }}
                />
                {fundKeys
                  .filter(f => activeFunds.has(f))
                  .map(fund => (
                    <Line
                      key={fund}
                      type="monotone"
                      dataKey={fund}
                      name={fund}
                      stroke={funds[fund].color}
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                  ))}
              </LineChart>
            </ResponsiveContainer>

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
