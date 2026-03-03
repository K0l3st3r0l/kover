import { useEffect, useState } from 'react'
import {
  LineChart, Line,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ReferenceLine, ResponsiveContainer, Dot
} from 'recharts'
import api from '../services/api'

interface Cycle {
  cycle_num: number
  ticker: string
  label: string
  opened_at: string
  end_date: string
  expiration_date: string
  strike_price: number
  contracts: number
  capital: number
  total_premium: number
  closing_cost: number
  net_premium: number
  duration_days: number
  net_yield: number
  annualized_return: number
  status: 'OPEN' | 'CLOSED' | 'EXPIRED' | 'ASSIGNED'
  notes: string
  is_roll: boolean
  roll_group: number
}

interface RollGroup {
  group_id: number
  ticker: string
  cycle_nums: number[]
  is_roll_chain: boolean
  status: 'OPEN' | 'CLOSED'
  first_opened: string
  last_end: string
  total_days: number
  base_capital: number
  total_net_premium: number
  net_yield: number
  annualized_return: number
  n_rolls: number
  last_strike: number
  last_expiration: string
}

interface OpenCycleSummary {
  ticker: string
  annualized: number
  capital: number
}

interface CycleSummary {
  total_cycles: number
  closed_cycles: number
  avg_annualized_return: number
  avg_closed_annualized: number
  total_net_premium: number
  capital_deployed: number
  open_cycles: OpenCycleSummary[]
  current_cycle_annualized: number | null
}

interface CyclesData {
  cycles: Cycle[]
  summary: CycleSummary
  roll_groups: RollGroup[]
}

function CoveredCallCycles() {
  const [data, setData] = useState<CyclesData | null>(null)
  const [loading, setLoading] = useState(true)
  // chartType removed — chart is always time-based line

  useEffect(() => {
    api.get<CyclesData>('/api/analytics/covered-call-cycles')
      .then(res => setData(res.data))
      .catch(err => console.error('Error fetching cycles:', err))
      .finally(() => setLoading(false))
  }, [])

  const fmt = (v?: number | null) =>
    v == null ? '—' :
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(v)

  const fmtPct = (v?: number | null) =>
    v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-400">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-green-500 mr-3"></div>
        Cargando ciclos...
      </div>
    )
  }

  if (!data || data.cycles.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-500 dark:text-gray-400">
        No hay ciclos de covered calls registrados aún.
      </div>
    )
  }

  const { cycles, summary, roll_groups } = data

  // ── Gráfico: evolución temporal usando roll_groups ──────────────────
  const closedGroups = roll_groups
    .filter(rg => rg.status === 'CLOSED')
    .sort((a, b) => a.last_end.localeCompare(b.last_end))
  const openGroups = roll_groups.filter(rg => rg.status === 'OPEN')

  const projectedAvg = openGroups.length > 0
    ? Math.round(openGroups.reduce((s, rg) => s + rg.annualized_return, 0) / openGroups.length * 100) / 100
    : null

  const today = new Date().toISOString().split('T')[0]
  const latestExp = openGroups.length > 0
    ? openGroups.reduce((latest, rg) => rg.last_expiration > latest ? rg.last_expiration : latest, openGroups[0].last_expiration).slice(0, 10)
    : null

  type ChartPoint = { date: string; label: string; realizado: number | null; proyectado: number | null }
  const pointMap: Record<string, ChartPoint> = {}

  closedGroups.forEach((rg, i) => {
    const slice = closedGroups.slice(0, i + 1)
    const runningAvg = Math.round(slice.reduce((s, x) => s + x.annualized_return, 0) / slice.length * 100) / 100
    const lbl = rg.is_roll_chain ? `${rg.ticker} (roll ${rg.n_rolls}x) ${rg.last_end}` : `${rg.ticker} ${rg.last_end}`
    pointMap[rg.last_end] = { date: rg.last_end, label: lbl, realizado: runningAvg, proyectado: null }
  })

  const lastReal = closedGroups.length > 0
    ? (pointMap[closedGroups[closedGroups.length - 1].last_end]?.realizado ?? null)
    : null

  if (pointMap[today]) {
    pointMap[today].realizado = lastReal
    pointMap[today].proyectado = projectedAvg
    pointMap[today].label = 'Hoy'
  } else {
    pointMap[today] = { date: today, label: 'Hoy', realizado: lastReal, proyectado: projectedAvg }
  }
  if (latestExp && latestExp > today) {
    const expLbl = `${latestExp} (exp.)`
    if (pointMap[latestExp]) {
      pointMap[latestExp].proyectado = projectedAvg
    } else {
      pointMap[latestExp] = { date: latestExp, label: expLbl, realizado: null, proyectado: projectedAvg }
    }
  }
  const chartData = Object.values(pointMap).sort((a, b) => a.date.localeCompare(b.date))

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    const point = chartData.find(p => p.label === label || p.date === label)
    // find matching roll group for context
    const matchRg = roll_groups.find(rg => rg.last_end === point?.date || rg.first_opened === point?.date)
    return (
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-4 text-sm min-w-[230px]">
        <p className="font-bold text-gray-900 dark:text-gray-100 mb-2">{point?.label ?? label}</p>
        {payload.map((entry: any) =>
          entry.value != null ? (
            <p key={entry.name} className="font-semibold" style={{ color: entry.value >= 0 ? entry.color : '#dc2626' }}>
              {entry.name}: {fmtPct(entry.value)}
            </p>
          ) : null
        )}
        {matchRg && (
          <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600 text-xs text-gray-500 space-y-0.5">
            {matchRg.is_roll_chain && <p className="text-amber-500 font-medium">🔄 Cadena de {matchRg.n_rolls + 1} ciclos ({matchRg.n_rolls} roll{matchRg.n_rolls > 1 ? 's' : ''})</p>}
            <p>Prima neta: {fmt(matchRg.total_net_premium)} · {matchRg.total_days}d</p>
            <p>Capital base: {fmt(matchRg.base_capital)}</p>
          </div>
        )}
      </div>
    )
  }

  return (
    <div>
      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        <div className="bg-gradient-to-br from-green-50 to-green-100 dark:from-green-900/20 dark:to-green-800/20 rounded-lg p-4 border border-green-200 dark:border-green-800">
          <p className="text-xs text-green-700 dark:text-green-400 font-medium mb-2">Posiciones abiertas</p>
          {openGroups.length > 0 ? (
            <div className="space-y-1.5">
              {openGroups.map(rg => (
                <div key={rg.ticker} className="flex justify-between items-baseline">
                  <div>
                    <span className="text-sm font-semibold text-green-700 dark:text-green-300">{rg.ticker}</span>
                    {rg.is_roll_chain && <span className="ml-1 text-xs text-amber-500">🔄{rg.n_rolls}x</span>}
                  </div>
                  <span className={`text-base font-bold ${rg.annualized_return >= 0 ? 'text-green-900 dark:text-green-100' : 'text-red-600'}`}>
                    {fmtPct(rg.annualized_return)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-2xl font-bold text-gray-400">—</p>
          )}
          <p className="text-xs text-green-600 dark:text-green-400 mt-2">Anualizado real por cadena</p>
        </div>

        <div className="bg-gradient-to-br from-blue-50 to-blue-100 dark:from-blue-900/20 dark:to-blue-800/20 rounded-lg p-4 border border-blue-200 dark:border-blue-800">
          <p className="text-xs text-blue-700 dark:text-blue-400 font-medium mb-1">Promedio cerrados</p>
          <p className="text-2xl font-bold text-blue-900 dark:text-blue-100">
            {fmtPct(summary.avg_closed_annualized)}
          </p>
          <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">{summary.closed_cycles} ciclo(s) cerrado(s)</p>
        </div>

        <div className="bg-white dark:bg-gray-700 rounded-lg p-4 border border-gray-200 dark:border-gray-600">
          <p className="text-xs text-gray-500 dark:text-gray-400 font-medium mb-1">Prima neta total</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            {fmt(summary.total_net_premium)}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Ingreso acumulado</p>
        </div>

        <div className="bg-white dark:bg-gray-700 rounded-lg p-4 border border-gray-200 dark:border-gray-600">
          <p className="text-xs text-gray-500 dark:text-gray-400 font-medium mb-1">Capital en juego</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">
            {fmt(summary.capital_deployed)}
          </p>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            {summary.open_cycles?.map(oc => oc.ticker).join(' · ') || cycles[0]?.ticker} · Strike × Contratos × 100
          </p>
        </div>
      </div>

      {/* Chart: evolución temporal realizado vs proyectado */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs text-gray-500 dark:text-gray-400">Rendimiento anualizado promedio — evolución en el tiempo</p>
          {projectedAvg != null && (
            <span className="text-xs font-semibold text-green-600 dark:text-green-400">
              Proyectado actual: {fmtPct(projectedAvg)}
            </span>
          )}
        </div>

        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData} margin={{ top: 10, right: 70, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.3} />
            <XAxis dataKey="label" stroke="#6b7280" style={{ fontSize: '11px' }} />
            <YAxis
              tickFormatter={v => `${v}%`}
              stroke="#6b7280"
              style={{ fontSize: '12px' }}
              domain={[(dataMin: number) => Math.floor(Math.min(dataMin, 0) * 1.2), (dataMax: number) => Math.ceil(dataMax * 1.2)]}
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine y={0} stroke="#9ca3af" strokeWidth={1} />
            {projectedAvg != null && (
              <ReferenceLine
                y={projectedAvg}
                stroke="#22c55e"
                strokeDasharray="4 3"
                strokeWidth={1}
                strokeOpacity={0.4}
                label={{ value: `${projectedAvg.toFixed(1)}%`, position: 'right', fill: '#22c55e', fontSize: 11 }}
              />
            )}
            {/* Línea realizado: running avg de ciclos cerrados */}
            <Line
              type="monotone"
              dataKey="realizado"
              name="Realizado"
              stroke="#3b82f6"
              strokeWidth={2.5}
              connectNulls={false}
              dot={(props: any) => {
                const v: number | null = props.payload.realizado
                if (v == null) return <g key={props.key} />
                return (
                  <Dot {...props} r={5}
                    fill={v >= 0 ? '#3b82f6' : '#ef4444'}
                    stroke="#1e293b" strokeWidth={2}
                  />
                )
              }}
              activeDot={{ r: 7 }}
            />
            {/* Línea proyectada: avg de ciclos abiertos, desde hoy hasta expiración */}
            <Line
              type="monotone"
              dataKey="proyectado"
              name="Proyectado"
              stroke="#22c55e"
              strokeWidth={2.5}
              strokeDasharray="7 4"
              connectNulls={false}
              dot={(props: any) => {
                const v: number | null = props.payload.proyectado
                if (v == null) return <g key={props.key} />
                return <Dot {...props} r={5} fill="#22c55e" stroke="#1e293b" strokeWidth={2} />
              }}
              activeDot={{ r: 7 }}
            />
          </LineChart>
        </ResponsiveContainer>

        {/* Legend */}
        <div className="flex gap-6 justify-center mt-2 text-xs text-gray-500 dark:text-gray-400">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-6 border-t-2 border-blue-500"></span> Realizado (cerrados)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-6 border-t-2 border-dashed border-green-500"></span> Proyectado (abiertos)
          </span>
        </div>
      </div>

      {/* Detail table with roll chain grouping */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide border-b border-gray-200 dark:border-gray-700">
              <th className="pb-2 pr-2">#</th>
              <th className="pb-2 pr-3">Ticker</th>
              <th className="pb-2 pr-3">Apertura</th>
              <th className="pb-2 pr-3">Cierre / Vence</th>
              <th className="pb-2 pr-3 text-right">Días</th>
              <th className="pb-2 pr-3 text-right">Capital</th>
              <th className="pb-2 pr-3 text-right">Prima neta</th>
              <th className="pb-2 pr-3 text-right">Yield</th>
              <th className="pb-2 text-right">Anualizado</th>
            </tr>
          </thead>
          <tbody>
            {roll_groups.map(rg => (
              <>
                {/* Individual cycle rows */}
                {cycles
                  .filter(c => rg.cycle_nums.includes(c.cycle_num))
                  .map((c, ci, arr) => {
                    const isLast = ci === arr.length - 1
                    const isFirst = ci === 0
                    return (
                      <tr key={c.cycle_num} className={`border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors ${
                        rg.is_roll_chain ? 'opacity-80' : ''
                      }`}>
                        <td className="py-2 pr-2">
                          <div className="flex items-center gap-1">
                            {rg.is_roll_chain && (
                              <span className="text-gray-400 dark:text-gray-600 text-base leading-none">
                                {isFirst ? '┌' : isLast ? '└' : '├'}
                              </span>
                            )}
                            <span className="font-medium text-gray-600 dark:text-gray-400 text-xs">
                              {c.status === 'OPEN'
                                ? <span className="inline-flex items-center gap-0.5">{c.cycle_num} <span className="text-green-500 font-bold">★</span></span>
                                : c.cycle_num
                              }
                            </span>
                          </div>
                        </td>
                        <td className="py-2 pr-3 font-semibold text-gray-900 dark:text-gray-100">{c.ticker}</td>
                        <td className="py-2 pr-3 text-gray-500 dark:text-gray-400 text-xs">{c.opened_at}</td>
                        <td className="py-2 pr-3 text-gray-500 dark:text-gray-400 text-xs">
                          {c.end_date}{c.status === 'OPEN' && <span className="ml-1 text-green-600">(exp.)</span>}
                        </td>
                        <td className="py-2 pr-3 text-right text-gray-600 dark:text-gray-400 text-xs">{c.duration_days}d</td>
                        <td className="py-2 pr-3 text-right text-gray-600 dark:text-gray-400 text-xs">{fmt(c.capital)}</td>
                        <td className={`py-2 pr-3 text-right text-xs font-medium ${c.net_premium >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                          {fmt(c.net_premium)}
                        </td>
                        <td className="py-2 pr-3 text-right text-gray-500 dark:text-gray-400 text-xs">{c.net_yield.toFixed(3)}%</td>
                        <td className="py-2 text-right text-xs">
                          <span className={c.annualized_return >= summary.avg_annualized_return ? 'text-gray-500' : 'text-gray-500'}>
                            {fmtPct(c.annualized_return)}
                          </span>
                        </td>
                      </tr>
                    )
                  })
                }
                {/* Roll chain summary row */}
                {rg.is_roll_chain && (
                  <tr className="border-b-2 border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700/50">
                    <td className="py-2 pr-2 text-center text-amber-500">🔄</td>
                    <td className="py-2 pr-3">
                      <span className="font-bold text-gray-900 dark:text-gray-100">{rg.ticker}</span>
                      <span className="ml-1.5 text-xs text-amber-600 dark:text-amber-400">roll ×{rg.n_rolls}</span>
                    </td>
                    <td className="py-2 pr-3 text-xs text-gray-500">{rg.first_opened}</td>
                    <td className="py-2 pr-3 text-xs text-gray-500">
                      {rg.last_end}
                      {rg.status === 'OPEN' && <span className="ml-1 text-green-600">(exp.)</span>}
                    </td>
                    <td className="py-2 pr-3 text-right text-xs font-semibold text-gray-700 dark:text-gray-300">{rg.total_days}d</td>
                    <td className="py-2 pr-3 text-right text-xs text-gray-600 dark:text-gray-400">{fmt(rg.base_capital)}</td>
                    <td className={`py-2 pr-3 text-right text-sm font-bold ${rg.total_net_premium >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                      {fmt(rg.total_net_premium)}
                    </td>
                    <td className="py-2 pr-3 text-right text-xs font-semibold text-gray-700 dark:text-gray-300">{rg.net_yield.toFixed(3)}%</td>
                    <td className="py-2 text-right">
                      <span className={`text-sm font-bold ${rg.annualized_return >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                        {fmtPct(rg.annualized_return)}
                      </span>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default CoveredCallCycles
