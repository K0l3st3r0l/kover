import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { format, parseISO } from 'date-fns'
import { es } from 'date-fns/locale'
import api from '../services/api'

const FUND_COLORS: Record<string, string> = {
  A: '#ef4444',
  B: '#f97316',
  C: '#3b82f6',
  D: '#22c55e',
  E: '#a855f7',
}

const FUND_NAMES: Record<string, string> = {
  A: 'Fondo A',
  B: 'Fondo B',
  C: 'Fondo C',
  D: 'Fondo D',
  E: 'Fondo E',
}

function modelLabel(id: string) {
  if (!id) return '—'
  if (id.includes('gpt-5.6-luna')) return 'Luna'
  if (id.includes('deepseek-v4.1-flash')) return 'DeepSeek V4.1'
  if (id.includes('mimo-v2.6-pro')) return 'MiMo V2.6 Pro'
  if (id.includes('deepseek-v4-pro')) return 'DeepSeek'
  if (id.includes('glm-5.3-flash')) return 'GLM 5.3 Flash'
  if (id.includes('glm-5.1')) return 'GLM 5.1'
  if (id.includes('minimax')) return 'MiniMax'
  return id
}

function fmtDay(dateStr: string) {
  try {
    return format(parseISO(dateStr), 'dd MMM yy', { locale: es })
  } catch {
    return dateStr
  }
}

function fmtPct(v: number | null | undefined) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

function pctClass(v: number | null | undefined) {
  if (v === null || v === undefined) return 'text-gray-400'
  if (v > 0) return 'text-green-600 dark:text-green-400'
  if (v < 0) return 'text-red-500 dark:text-red-400'
  return 'text-gray-500'
}

function AllocationChips({ items }: { items: { fondo: string; pct: number }[] }) {
  if (!items?.length) return <span className="text-gray-400">—</span>
  return (
    <span className="inline-flex flex-wrap gap-1">
      {items.map(d => (
        <span
          key={d.fondo}
          className="text-xs font-bold px-2 py-0.5 rounded-full"
          style={{ backgroundColor: `${FUND_COLORS[d.fondo] ?? '#888'}22`, color: FUND_COLORS[d.fondo] ?? '#888' }}
        >
          {d.pct}% {FUND_NAMES[d.fondo] ?? d.fondo}
        </span>
      ))}
    </span>
  )
}

interface TrackPayload {
  snapshots: any[]
  series: any[]
  summary: any
  source?: string
}

export default function AfpCommitteeTrack({
  currentAllocation,
}: {
  currentAllocation: Record<string, number>
}) {
  const [data, setData] = useState<TrackPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [hidden, setHidden] = useState<Set<string>>(new Set())

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<TrackPayload>('/api/market/ai-committee-track')
      setData(res.data)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'No se pudo cargar el seguimiento')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const userWeights = useMemo(() => {
    const w: Record<string, number> = {}
    let total = 0
    ;(['A', 'B', 'C', 'D', 'E'] as const).forEach(f => {
      const v = currentAllocation[f] ?? 0
      w[f] = v
      total += v
    })
    if (total !== 100) return null
    return { A: w.A / 100, B: w.B / 100, C: w.C / 100, D: w.D / 100, E: w.E / 100 }
  }, [currentAllocation])

  const chartData = useMemo(() => {
    const series = data?.series
    if (!series?.length) return []
    return series.map(row => {
      const next = { ...row }
      if (userWeights) {
        let v = 0
        let ok = true
        ;(['A', 'B', 'C', 'D', 'E'] as const).forEach(f => {
          if (!userWeights[f]) return
          if (row[f] == null) ok = false
          else v += userWeights[f] * row[f]
        })
        next.user = ok ? Math.round(v * 10000) / 10000 : null
      }
      return next
    })
  }, [data?.series, userWeights])

  const lines = useMemo(() => {
    const list = [
      { key: 'committee', label: 'Comité (rebalance)', color: '#6366f1' },
      { key: 'A', label: 'Fondo A', color: FUND_COLORS.A },
      { key: 'C', label: 'Fondo C', color: FUND_COLORS.C },
      { key: 'E', label: 'Fondo E', color: FUND_COLORS.E },
    ]
    if (userWeights) list.splice(1, 0, { key: 'user', label: 'Tu posición', color: '#64748b' })
    return list
  }, [userWeights])

  const toggle = (key: string) => {
    setHidden(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else if (next.size < lines.length - 1) next.add(key)
      return next
    })
  }

  const snapshots = [...(data?.snapshots ?? [])].reverse()
  const summary = data?.summary

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
          Seguimiento de recomendaciones
        </h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
          Si hubieras rebalanceado a la distribución del árbitro en cada veredicto. Base 100 al primer veredicto.
          Valor cuota promedio del sistema.
        </p>
      </div>

      {loading && (
        <div className="flex items-center justify-center h-40">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-indigo-600" />
        </div>
      )}

      {error && !loading && (
        <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-3 text-sm text-red-700 dark:text-red-300">
          {error}
          <button type="button" onClick={load} className="ml-2 underline">Reintentar</button>
        </div>
      )}

      {!loading && !error && (
        <>
          {summary && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
              {[
                { label: 'Comité', value: summary.committee_pct, color: '#6366f1' },
                { label: 'Fondo A', value: summary.A_pct, color: FUND_COLORS.A },
                { label: 'Fondo C', value: summary.C_pct, color: FUND_COLORS.C },
                { label: 'Fondo E', value: summary.E_pct, color: FUND_COLORS.E },
              ].map(card => (
                <div key={card.label} className="rounded-lg border border-gray-100 dark:border-gray-700 px-3 py-2">
                  <p className="text-xs text-gray-400">{card.label}</p>
                  <p className={`text-sm font-bold font-mono ${pctClass(card.value)}`}>{fmtPct(card.value)}</p>
                </div>
              ))}
            </div>
          )}

          {summary?.from && summary?.to && (
            <p className="text-xs text-gray-400 mb-3">
              {fmtDay(summary.from)} → {fmtDay(summary.to)}
            </p>
          )}

          {chartData.length > 1 && (
            <>
              <div className="flex flex-wrap gap-2 mb-3">
                {lines.map(l => {
                  const on = !hidden.has(l.key)
                  return (
                    <button
                      key={l.key}
                      type="button"
                      onClick={() => toggle(l.key)}
                      className={`px-2.5 py-1 rounded-full text-xs font-semibold border-2 ${on ? 'text-white' : 'bg-transparent text-gray-400'}`}
                      style={on ? { backgroundColor: l.color, borderColor: l.color } : { borderColor: l.color, color: l.color }}
                    >
                      {l.label}
                    </button>
                  )
                })}
              </div>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                  <XAxis dataKey="date" tickFormatter={fmtDay} tick={{ fontSize: 11 }} minTickGap={28} />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    domain={['auto', 'auto']}
                    tickFormatter={(v: number) => v.toFixed(0)}
                    width={36}
                  />
                  <Tooltip
                    labelFormatter={(l) => fmtDay(String(l))}
                    formatter={(value: any, name: string) => [value != null ? Number(value).toFixed(2) : '—', name]}
                  />
                  <Legend />
                  {lines.filter(l => !hidden.has(l.key)).map(l => (
                    <Line
                      key={l.key}
                      type="monotone"
                      dataKey={l.key}
                      name={l.label}
                      stroke={l.color}
                      strokeWidth={l.key === 'committee' ? 2.5 : 1.5}
                      dot={false}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </>
          )}

          <div className="overflow-x-auto mt-5">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="text-gray-500 dark:text-gray-400 border-b border-gray-100 dark:border-gray-700">
                  <th className="text-left py-1.5 pr-3 font-medium">Veredicto</th>
                  <th className="text-left pr-3 font-medium">Árbitro</th>
                  <th className="text-left pr-3 font-medium">Analistas</th>
                  <th className="text-right pr-3 font-medium">Hold árbitro</th>
                  <th className="text-right pr-3 font-medium">vs C</th>
                  <th className="text-right font-medium">vs E</th>
                </tr>
              </thead>
              <tbody>
                {snapshots.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-4 text-gray-400 italic">Aún no hay veredictos guardados.</td>
                  </tr>
                )}
                {snapshots.map(s => (
                  <tr key={s.as_of_date} className="border-b border-gray-50 dark:border-gray-800 align-top">
                    <td className="py-2 pr-3 whitespace-nowrap">
                      <div className="font-semibold text-gray-700 dark:text-gray-200">{fmtDay(s.as_of_date)}</div>
                      <div className="text-gray-400">{s.from && s.to ? `${fmtDay(s.from)} → ${fmtDay(s.to)}` : ''}</div>
                    </td>
                    <td className="py-2 pr-3">
                      <div className="text-gray-400 mb-1">{modelLabel(s.arbiter?.model)}</div>
                      <AllocationChips items={s.arbiter?.allocation ?? []} />
                    </td>
                    <td className="py-2 pr-3">
                      <div className="space-y-1.5">
                        {(s.analysts ?? []).map((a: any) => (
                          <div key={a.model}>
                            <span className="text-gray-400 mr-1">{modelLabel(a.model)}</span>
                            <AllocationChips items={a.allocation ?? []} />
                            <span className={`ml-1 font-mono ${pctClass(a.hold_pct)}`}>{fmtPct(a.hold_pct)}</span>
                          </div>
                        ))}
                      </div>
                    </td>
                    <td className={`py-2 pr-3 text-right font-mono font-semibold ${pctClass(s.arbiter?.hold_pct)}`}>
                      {fmtPct(s.arbiter?.hold_pct)}
                    </td>
                    <td className={`py-2 pr-3 text-right font-mono ${pctClass(s.vs?.C)}`}>{fmtPct(s.vs?.C)}</td>
                    <td className={`py-2 text-right font-mono ${pctClass(s.vs?.E)}`}>{fmtPct(s.vs?.E)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-xs text-gray-400 dark:text-gray-600">
            Hold = comprar esa mezcla el día del veredicto y no tocar. El gráfico rebalancea en cada veredicto nuevo.
            Fuente: {data?.source ?? 'Superintendencia de Pensiones'}. No constituye asesoría financiera.
          </p>
        </>
      )}
    </div>
  )
}
