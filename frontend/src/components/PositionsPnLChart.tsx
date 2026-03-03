import { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, ReferenceLine, Legend
} from 'recharts'

export interface PositionPnL {
  ticker: string
  shares: number
  cost_basis_raw: number
  adjusted_cost_basis: number
  current_price: number
  current_value: number
  total_invested: number
  unrealized_pnl: number
  unrealized_pct: number
  premium_earned: number
  total_pnl: number
  total_pct: number
}

interface Props {
  data: PositionPnL[]
}

const fmt = (v: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(v)

const fmtPct = (v: number) => `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`

type Mode = 'dollars' | 'percent'

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null
  const d: PositionPnL = payload[0]?.payload
  if (!d) return null
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-4 text-sm min-w-[220px]">
      <p className="font-bold text-gray-900 text-base mb-2">{d.ticker}</p>
      <div className="space-y-1 text-xs text-gray-600">
        <div className="flex justify-between gap-4">
          <span>Acciones</span><span className="font-medium text-gray-800">{d.shares}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span>Precio compra (promedio)</span><span className="font-medium text-gray-800">{fmt(d.cost_basis_raw)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span>Costo ajustado (neto premiums)</span><span className="font-medium text-blue-600">{fmt(d.adjusted_cost_basis)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span>Precio actual</span><span className="font-medium text-gray-800">{fmt(d.current_price)}</span>
        </div>
        <hr className="my-2" />
        <div className="flex justify-between gap-4">
          <span>P&L no realizado</span>
          <span className={`font-semibold ${d.unrealized_pnl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
            {fmt(d.unrealized_pnl)} ({fmtPct(d.unrealized_pct)})
          </span>
        </div>
        <div className="flex justify-between gap-4">
          <span>Premiums cobrados</span>
          <span className="font-semibold text-green-600">+{fmt(d.premium_earned)}</span>
        </div>
        <div className="flex justify-between gap-4 text-sm pt-1 border-t border-gray-100">
          <span className="font-semibold text-gray-700">P&L total</span>
          <span className={`font-bold ${d.total_pnl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
            {fmt(d.total_pnl)} ({fmtPct(d.total_pct)})
          </span>
        </div>
      </div>
    </div>
  )
}

export default function PositionsPnLChart({ data }: Props) {
  const [mode, setMode] = useState<Mode>('dollars')

  const chartData = [...data].sort((a, b) => {
    const va = mode === 'dollars' ? b.total_pnl : b.total_pct
    const vb = mode === 'dollars' ? a.total_pnl : a.total_pct
    return va - vb
  })

  const getValue = (d: PositionPnL, key: 'unrealized' | 'premium') => {
    if (mode === 'dollars') return key === 'unrealized' ? d.unrealized_pnl : d.premium_earned
    // percent: both components as % of total_invested
    if (key === 'unrealized') return d.unrealized_pct
    return d.total_invested > 0 ? (d.premium_earned / d.total_invested) * 100 : 0
  }

  return (
    <div className="bg-white shadow rounded-lg p-6 mb-8">
      <div className="flex justify-between items-start mb-6">
        <div>
          <h3 className="text-xl font-bold text-gray-900">P&amp;L por Posición</h3>
          <p className="text-sm text-gray-500 mt-1">
            P&amp;L no realizado + premiums cobrados, ordenado de mejor a peor
          </p>
        </div>
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          {(['dollars', 'percent'] as Mode[]).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors font-medium ${
                mode === m ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {m === 'dollars' ? '$ USD' : '% ROI'}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f0f0f0" />
          <XAxis dataKey="ticker" tick={{ fontSize: 13, fontWeight: 600 }} />
          <YAxis
            tickFormatter={v => mode === 'dollars'
              ? (Math.abs(v) >= 1000 ? `$${(v/1000).toFixed(1)}k` : `$${v.toFixed(0)}`)
              : `${v.toFixed(0)}%`
            }
            tick={{ fontSize: 11 }}
            width={60}
          />
          <Tooltip content={<CustomTooltip mode={mode} />} />
          <ReferenceLine y={0} stroke="#9ca3af" strokeWidth={1.5} />
          <Legend
            verticalAlign="bottom"
            height={32}
            formatter={(value) => value === 'unrealized' ? 'No realizado' : 'Premiums'}
          />
          <Bar dataKey={(d: PositionPnL) => getValue(d, 'unrealized')} name="unrealized" stackId="a" radius={[0, 0, 0, 0]}>
            {chartData.map((d) => (
              <Cell
                key={d.ticker}
                fill={d.unrealized_pnl >= 0 ? '#4ade80' : '#f87171'}
                opacity={0.85}
              />
            ))}
          </Bar>
          <Bar dataKey={(d: PositionPnL) => getValue(d, 'premium')} name="premium" stackId="a" fill="#60a5fa" opacity={0.85} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>

      {/* Summary table */}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-400 uppercase border-b border-gray-100">
              <th className="text-left py-2 pr-4">Ticker</th>
              <th className="text-right pr-4">Acciones</th>
              <th className="text-right pr-4">Costo ajustado</th>
              <th className="text-right pr-4">Precio actual</th>
              <th className="text-right pr-4">No realizado</th>
              <th className="text-right pr-4">Premiums</th>
              <th className="text-right font-semibold">P&amp;L total</th>
            </tr>
          </thead>
          <tbody>
            {chartData.map(d => (
              <tr key={d.ticker} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                <td className="py-2.5 pr-4 font-bold text-gray-900">{d.ticker}</td>
                <td className="text-right pr-4 text-gray-600">{d.shares}</td>
                <td className="text-right pr-4 text-gray-600">{fmt(d.adjusted_cost_basis)}</td>
                <td className="text-right pr-4 text-gray-600">{fmt(d.current_price)}</td>
                <td className={`text-right pr-4 font-medium ${d.unrealized_pnl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                  {fmt(d.unrealized_pnl)}<span className="text-xs text-gray-400 ml-1">({fmtPct(d.unrealized_pct)})</span>
                </td>
                <td className="text-right pr-4 text-blue-600 font-medium">+{fmt(d.premium_earned)}</td>
                <td className={`text-right font-bold ${d.total_pnl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                  {fmt(d.total_pnl)}<span className="text-xs ml-1">({fmtPct(d.total_pct)})</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
