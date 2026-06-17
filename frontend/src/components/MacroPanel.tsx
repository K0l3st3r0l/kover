import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'

export interface MacroIndicator {
  key: string
  name: string
  country: 'CL' | 'US'
  format: 'currency' | 'percent' | 'commodity' | 'index'
  value: number | null
  previous: number | null
  change_pct: number | null
  as_of: string
}

interface MacroResponse {
  cl: MacroIndicator[]
  us: MacroIndicator[]
  generated_at: string
}

export interface MacroEvent {
  id: string
  name: string
  country: 'CL' | 'US'
  impact: 1 | 2 | 3
  category: string
  date: string
  hour_cl: string
  when: string
  actual?: number | null
  actual_previous?: number | null
  actual_change_pct?: number | null
  actual_date?: string | null
  actual_format?: MacroIndicator['format'] | null
  actual_source?: string | null
}

export interface CalendarResponse {
  events: MacroEvent[]
  from: string
  to: string
  generated_at: string
}

export function formatValue(i: { value: number | null; format: MacroIndicator['format'] }): string {
  if (i.value === null || i.value === undefined) return '—'
  if (i.format === 'currency') return `$${i.value.toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  if (i.format === 'percent') return `${i.value.toFixed(2)}%`
  if (i.format === 'commodity') return `$${i.value.toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  return i.value.toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function ChangeBadge({ pct }: { pct: number | null | undefined }) {
  if (pct === null || pct === undefined) return <span className="text-xs text-gray-400">—</span>
  const isUp = pct >= 0
  return (
    <span className={`text-xs font-semibold ${isUp ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
      {isUp ? '▲' : '▼'} {Math.abs(pct).toFixed(2)}%
    </span>
  )
}

function IndicatorCard({ i }: { i: MacroIndicator }) {
  return (
    <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 min-w-0">
      <div className="flex items-center justify-between gap-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 truncate">
          {i.name}
        </span>
        <span className={`text-[9px] font-bold px-1 rounded ${i.country === 'US' ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300' : 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300'}`}>
          {i.country}
        </span>
      </div>
      <div className="flex items-baseline justify-between gap-2 mt-0.5">
        <span className="text-sm font-bold text-gray-900 dark:text-white tabular-nums truncate">
          {formatValue(i)}
        </span>
        <ChangeBadge pct={i.change_pct} />
      </div>
    </div>
  )
}

export function ImpactDots({ impact }: { impact: 1 | 2 | 3 }) {
  return (
    <span className="text-amber-500 dark:text-amber-400 tracking-tight" title={`Impacto ${impact}/3`}>
      {'★'.repeat(impact)}<span className="text-gray-300 dark:text-gray-600">{'★'.repeat(3 - impact)}</span>
    </span>
  )
}

function eventDateLabel(d: string, hour: string): string {
  try {
    const dt = new Date(`${d}T${hour || '09:00'}:00`)
    return dt.toLocaleDateString('es-CL', { weekday: 'short', day: '2-digit' })
  } catch {
    return d
  }
}

const WHEN_STYLES: Record<string, string> = {
  hoy:    'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300',
  mañana: 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300',
}

export default function MacroPanel() {
  const [macro, setMacro] = useState<MacroResponse | null>(null)
  const [calendar, setCalendar] = useState<CalendarResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [m, c] = await Promise.all([
        api.get<MacroResponse>('/api/news/macro', { timeout: 30000 }),
        api.get<CalendarResponse>('/api/news/macro-calendar', { params: { days_back: 3 }, timeout: 10000 }),
      ])
      setMacro(m.data)
      setCalendar(c.data)
    } catch (err: any) {
      setError('No se pudieron cargar los indicadores macro.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAll() }, [])

  const isRecentPast = (when: string) => {
    const m = when.match(/^hace (\d+)d$/)
    return m ? parseInt(m[1], 10) <= 3 : false
  }
  const upcoming = (calendar?.events || [])
    .filter(e => e.when === 'hoy' || e.when === 'mañana' || e.when.startsWith('en ') || isRecentPast(e.when))
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(0, 6)
  const cl = (macro?.cl || []).filter(i => i.value !== null)
  const us = (macro?.us || []).filter(i => i.value !== null)

  return (
    <div className="rounded-xl border border-indigo-200 dark:border-indigo-800 bg-gradient-to-br from-indigo-50/50 to-blue-50/30 dark:from-indigo-900/20 dark:to-blue-900/10 p-4 mb-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-base">🌐</span>
          <h2 className="text-sm font-bold text-indigo-900 dark:text-indigo-200 uppercase tracking-wide">
            Contexto Macro
          </h2>
          <span className="text-xs text-indigo-500 dark:text-indigo-400">
            · alimenta al Análisis IA
          </span>
        </div>
        <button
          onClick={fetchAll}
          disabled={loading}
          className="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-200 disabled:opacity-50 flex items-center gap-1"
        >
          <svg className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Actualizar
        </button>
      </div>

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : loading && !macro ? (
        <div className="space-y-2">
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-14 rounded-lg bg-gray-200 dark:bg-gray-700 animate-pulse" />
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Indicadores CL + US */}
          {(cl.length > 0 || us.length > 0) && (
            <div>
              {cl.length > 0 && (
                <div className="mb-2">
                  <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                    🇨🇱 Chile
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
                    {cl.map(i => <IndicatorCard key={i.key} i={i} />)}
                  </div>
                </div>
              )}
              {us.length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                    🇺🇸 Internacional
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
                    {us.map(i => <IndicatorCard key={i.key} i={i} />)}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Próximos eventos */}
          {upcoming.length > 0 && (
            <div className="pt-2 border-t border-indigo-200/60 dark:border-indigo-800/60">
              <div className="text-[10px] font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">
                📅 Próximos eventos macro
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-2">
                {upcoming.map(e => {
                  const past = isRecentPast(e.when)
                  const whenCls = past
                    ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300'
                    : (WHEN_STYLES[e.when] || 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300')
                  const hasResult = e.actual !== undefined && e.actual !== null
                  return (
                    <div key={`${e.id}-${e.date}`} className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
                      <div className="flex flex-col items-center min-w-[42px]">
                        <span className="text-[10px] font-bold text-gray-700 dark:text-gray-300 uppercase">
                          {eventDateLabel(e.date, e.hour_cl).split(' ')[0]}
                        </span>
                        <span className="text-sm font-bold text-gray-900 dark:text-white tabular-nums">
                          {eventDateLabel(e.date, e.hour_cl).split(' ')[1]}
                        </span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className={`text-[9px] font-bold px-1 rounded ${e.country === 'US' ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300' : 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300'}`}>
                            {e.country}
                          </span>
                          <ImpactDots impact={e.impact} />
                        </div>
                        <p className="text-xs font-medium text-gray-800 dark:text-gray-200 truncate" title={e.name}>
                          {e.name}
                        </p>
                        {hasResult ? (
                          <p className="text-[10px] font-semibold text-gray-700 dark:text-gray-300 truncate">
                            Resultado: {formatValue({ value: e.actual ?? null, format: e.actual_format || 'index' })}
                            {e.actual_change_pct !== undefined && e.actual_change_pct !== null && (
                              <span className="ml-1"><ChangeBadge pct={e.actual_change_pct} /></span>
                            )}
                          </p>
                        ) : (
                          <p className="text-[10px] text-gray-500 dark:text-gray-400">
                            {e.hour_cl} CL
                            {!past && e.when !== 'hoy' && e.when !== 'mañana' && ` · ${e.when}`}
                          </p>
                        )}
                      </div>
                      {(e.when === 'hoy' || e.when === 'mañana') && (
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${whenCls}`}>
                          {e.when}
                        </span>
                      )}
                      {past && (
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${whenCls}`}>
                          salió
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
              <Link
                to="/noticias/calendario"
                className="inline-block mt-2 text-[11px] font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-200"
              >
                Ver calendario completo →
              </Link>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
