import { useState, useMemo } from 'react'
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, ReferenceLine
} from 'recharts'

interface GrowthEvent {
  date: string
  cumulative_invested: number
  cumulative_sells: number
  net_cash_deployed: number
  cumulative_realized_pnl: number
  cumulative_premiums: number
  total_realized_net: number
  roi_realized_pct: number
  roi_net_cash_pct: number
}

interface PortfolioGrowthData {
  events: GrowthEvent[]
  current_unrealized: number
  total_pnl: number
  roi_total_pct: number
  roi_net_cash_total_pct: number
  cumulative_invested: number
  net_cash_deployed: number
}

interface Props {
  data: PortfolioGrowthData
}

const formatCurrency = (v: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(v)

const formatPct = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`

const formatDate = (d: string) => {
  const dt = new Date(d + 'T00:00:00')
  return dt.toLocaleDateString('es-CL', { month: 'short', year: '2-digit' })
}

export default function PortfolioGrowthChart({ data }: Props) {
  const [mode, setMode] = useState<'usd' | 'pct'>('usd')

  // Build chart data: one point per event, plus a "today" point with unrealized included
  const chartData = useMemo(() => {
    const points = data.events.map(e => ({
      date: e.date,
      invested: e.cumulative_invested,
      net_cash: e.net_cash_deployed,
      realizado: e.total_realized_net,
      roi_realizado: e.roi_realized_pct,
      roi_net_cash: e.roi_net_cash_pct,
      // total (realized + unrealized) is only meaningful at the last point
      total: null as number | null,
      roi_total: null as number | null,
      roi_total_net: null as number | null,
    }))

    // Patch last point to also include total
    if (points.length > 0) {
      const last = { ...points[points.length - 1] }
      last.total = data.total_pnl
      last.roi_total = data.roi_total_pct
      last.roi_total_net = data.roi_net_cash_total_pct
      points[points.length - 1] = last
    }
    return points
  }, [data])

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    const d = new Date(label + 'T00:00:00').toLocaleDateString('es-CL', { day: 'numeric', month: 'long', year: 'numeric' })
    return (
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg p-3 text-sm">
        <p className="font-semibold text-gray-700 dark:text-gray-200 mb-2">{d}</p>
        {payload.map((entry: any) => {
          if (entry.value === null || entry.value === undefined) return null
          return (
            <p key={entry.dataKey} style={{ color: entry.color }} className="font-medium">
              {entry.name}: {mode === 'usd' ? formatCurrency(entry.value) : formatPct(entry.value)}
            </p>
          )
        })}
      </div>
    )
  }

  const pnlColor = data.total_pnl >= 0 ? '#16a34a' : '#dc2626'

  return (
    <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-5">
        <div>
          <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">📈 Crecimiento Histórico del Portafolio</h3>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">Desde primera transacción hasta hoy</p>
        </div>
        <div className="flex items-center gap-3">
          {/* Summary pills */}
          <div className="flex gap-2 text-xs">
            <span className="bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 px-2 py-1 rounded">
              Capital bruto: {formatCurrency(data.cumulative_invested)}
            </span>
            <span className="bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 px-2 py-1 rounded">
              Neto bolsillo: {formatCurrency(data.net_cash_deployed)}
            </span>
            <span className={`px-2 py-1 rounded font-semibold ${data.total_pnl >= 0 ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400' : 'bg-red-100 text-red-700'}`}>
              ROI neto: {formatPct(data.roi_net_cash_total_pct)}
            </span>
          </div>
          {/* Toggle */}
          <div className="flex rounded-lg border border-gray-200 dark:border-gray-600 overflow-hidden text-xs font-medium">
            <button
              onClick={() => setMode('usd')}
              className={`px-3 py-1.5 transition-colors ${mode === 'usd' ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700'}`}
            >$ USD</button>
            <button
              onClick={() => setMode('pct')}
              className={`px-3 py-1.5 transition-colors ${mode === 'pct' ? 'bg-blue-600 text-white' : 'text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700'}`}
            >% ROI</button>
          </div>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={380}>
        <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            stroke="#9ca3af"
            style={{ fontSize: '11px' }}
            interval="preserveStartEnd"
            minTickGap={50}
          />
          <YAxis
            tickFormatter={mode === 'usd' ? (v: number) => `$${(v / 1000).toFixed(0)}k` : (v: number) => `${v.toFixed(0)}%`}
            stroke="#9ca3af"
            style={{ fontSize: '11px' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '12px' }} iconType="line" />
          <ReferenceLine y={0} stroke="#6b7280" strokeDasharray="4 4" />

          {mode === 'usd' ? (
            <>
              <Area
                type="monotone"
                dataKey="invested"
                name="Capital bruto acumulado"
                stroke="#94a3b8"
                fill="#f1f5f9"
                strokeWidth={1.5}
                dot={false}
                activeDot={false}
                fillOpacity={0.6}
              />
              <Area
                type="monotone"
                dataKey="net_cash"
                name="Neto de bolsillo (compras − ventas)"
                stroke="#f59e0b"
                fill="#fef3c7"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5 }}
                fillOpacity={0.5}
              />
              <Area
                type="stepAfter"
                dataKey="realizado"
                name="P&L Realizado neto"
                stroke="#3b82f6"
                fill="#dbeafe"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5 }}
                fillOpacity={0.5}
              />
              <Line
                type="stepAfter"
                dataKey="total"
                name="P&L Total (+ unrealized)"
                stroke={pnlColor}
                strokeWidth={2.5}
                dot={(props: any) => {
                  if (props.payload.total === null) return <g key={props.key} />
                  return <circle key={props.key} cx={props.cx} cy={props.cy} r={5} fill={pnlColor} stroke="white" strokeWidth={2} />
                }}
                activeDot={{ r: 6 }}
                connectNulls={false}
              />
            </>
          ) : (
            <>
              <ReferenceLine y={0} stroke="#6b7280" />
              <Area
                type="stepAfter"
                dataKey="roi_realizado"
                name="ROI Realizado (vs capital bruto)"
                stroke="#3b82f6"
                fill="#dbeafe"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5 }}
                fillOpacity={0.4}
              />
              <Area
                type="stepAfter"
                dataKey="roi_net_cash"
                name="ROI vs neto de bolsillo"
                stroke="#f59e0b"
                fill="#fef3c7"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5 }}
                fillOpacity={0.4}
              />
              <Line
                type="stepAfter"
                dataKey="roi_total_net"
                name="ROI Total vs neto bolsillo (+ unrealized)"
                stroke={pnlColor}
                strokeWidth={2.5}
                dot={(props: any) => {
                  if (props.payload.roi_total_net === null) return <g key={props.key} />
                  return <circle key={props.key} cx={props.cx} cy={props.cy} r={5} fill={pnlColor} stroke="white" strokeWidth={2} />
                }}
                activeDot={{ r: 6 }}
                connectNulls={false}
              />
            </>
          )}
        </ComposedChart>
      </ResponsiveContainer>

      {/* Desglose inferior */}
      <div className="mt-4 grid grid-cols-2 sm:grid-cols-5 gap-3 text-center text-xs">
        <div className="bg-gray-50 dark:bg-gray-700 rounded p-2">
          <p className="text-gray-500 dark:text-gray-400">Capital bruto acumulado</p>
          <p className="font-bold text-gray-800 dark:text-gray-100 text-sm">{formatCurrency(data.cumulative_invested)}</p>
        </div>
        <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded p-2">
          <p className="text-gray-500 dark:text-gray-400">Neto de bolsillo</p>
          <p className="font-bold text-yellow-700 dark:text-yellow-300 text-sm">{formatCurrency(data.net_cash_deployed)}</p>
          <p className="text-gray-400 text-[10px]">compras − ventas</p>
        </div>
        <div className="bg-blue-50 dark:bg-blue-900/30 rounded p-2">
          <p className="text-gray-500 dark:text-gray-400">P&L Realizado neto</p>
          {(() => {
            const last = data.events[data.events.length - 1]
            return (
              <p className={`font-bold text-sm ${last?.total_realized_net >= 0 ? 'text-blue-700 dark:text-blue-300' : 'text-red-600'}`}>
                {formatCurrency(last?.total_realized_net ?? 0)}
              </p>
            )
          })()}
        </div>
        <div className="bg-gray-50 dark:bg-gray-700 rounded p-2">
          <p className="text-gray-500 dark:text-gray-400">Unrealized actual</p>
          <p className={`font-bold text-sm ${data.current_unrealized >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
            {formatCurrency(data.current_unrealized)}
          </p>
        </div>
        <div className={`rounded p-2 ${data.total_pnl >= 0 ? 'bg-green-50 dark:bg-green-900/30' : 'bg-red-50 dark:bg-red-900/30'}`}>
          <p className="text-gray-500 dark:text-gray-400">ROI total vs bolsillo</p>
          <p className={`font-bold text-sm ${data.total_pnl >= 0 ? 'text-green-700 dark:text-green-300' : 'text-red-600'}`}>
            {formatCurrency(data.total_pnl)}
          </p>
          <p className={`font-bold text-sm ${data.roi_net_cash_total_pct >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
            {formatPct(data.roi_net_cash_total_pct)}
          </p>
        </div>
      </div>
    </div>
  )
}
