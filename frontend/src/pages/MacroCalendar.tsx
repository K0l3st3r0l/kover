import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import { formatValue, ChangeBadge, ImpactDots, type MacroEvent, type CalendarResponse } from '../components/MacroPanel'

type CountryFilter = 'all' | 'CL' | 'US'

function eventDateLabel(d: string): string {
  try {
    const dt = new Date(`${d}T12:00:00`)
    return dt.toLocaleDateString('es-CL', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })
  } catch {
    return d
  }
}

export default function MacroCalendar() {
  const [calendar, setCalendar] = useState<CalendarResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [country, setCountry] = useState<CountryFilter>('all')
  const [minImpact, setMinImpact] = useState<1 | 2 | 3>(1)

  const fetchAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<CalendarResponse>('/api/news/macro-calendar', {
        params: { days: 45, days_back: 60 },
        timeout: 15000,
      })
      setCalendar(res.data)
    } catch {
      setError('No se pudo cargar el calendario económico.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAll() }, [])

  const events = (calendar?.events || [])
    .filter(e => country === 'all' || e.country === country)
    .filter(e => e.impact >= minImpact)
    .sort((a, b) => a.date.localeCompare(b.date))

  const isPast = (e: MacroEvent) => e.when.startsWith('hace ')
  const hasResult = (e: MacroEvent) => e.actual !== undefined && e.actual !== null

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <Link to="/noticias" className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">← Volver a Noticias</Link>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white mt-1 flex items-center gap-2">
            📅 Calendario Económico
          </h1>
        </div>
        <button
          onClick={fetchAll}
          disabled={loading}
          className="text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-200 disabled:opacity-50"
        >
          {loading ? 'Actualizando…' : 'Actualizar'}
        </button>
      </div>

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="flex rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          {(['all', 'CL', 'US'] as CountryFilter[]).map(c => (
            <button
              key={c}
              onClick={() => setCountry(c)}
              className={`px-3 py-1.5 text-xs font-semibold ${country === c ? 'bg-indigo-600 text-white' : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300'}`}
            >
              {c === 'all' ? 'Todos' : c === 'CL' ? '🇨🇱 Chile' : '🇺🇸 EE.UU.'}
            </button>
          ))}
        </div>
        <div className="flex rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          {[1, 2, 3].map(n => (
            <button
              key={n}
              onClick={() => setMinImpact(n as 1 | 2 | 3)}
              className={`px-3 py-1.5 text-xs font-semibold ${minImpact === n ? 'bg-amber-500 text-white' : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-300'}`}
              title={`Impacto mínimo ${n}/3`}
            >
              {'★'.repeat(n)}+
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : loading && !calendar ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-16 rounded-lg bg-gray-200 dark:bg-gray-700 animate-pulse" />
          ))}
        </div>
      ) : events.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">No hay eventos para el filtro seleccionado.</p>
      ) : (
        <div className="space-y-2">
          {events.map(e => {
            const past = isPast(e)
            const result = hasResult(e)
            return (
              <div
                key={`${e.id}-${e.date}`}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${
                  past
                    ? 'bg-gray-50 dark:bg-gray-800/60 border-gray-200 dark:border-gray-700'
                    : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700'
                }`}
              >
                <div className="flex flex-col items-center min-w-[64px]">
                  <span className="text-[10px] font-bold text-gray-500 dark:text-gray-400 uppercase">
                    {eventDateLabel(e.date).split(',')[0]}
                  </span>
                  <span className="text-sm font-bold text-gray-900 dark:text-white tabular-nums">
                    {e.date.slice(8, 10)}/{e.date.slice(5, 7)}
                  </span>
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className={`text-[9px] font-bold px-1 rounded ${e.country === 'US' ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300' : 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300'}`}>
                      {e.country}
                    </span>
                    <ImpactDots impact={e.impact} />
                    <span className="text-[10px] text-gray-400 dark:text-gray-500">{e.hour_cl} CL</span>
                  </div>
                  <p className="text-sm font-medium text-gray-800 dark:text-gray-200">{e.name}</p>
                  {result && (
                    <p className="text-xs text-gray-600 dark:text-gray-300 mt-0.5">
                      Resultado: <span className="font-semibold">{formatValue({ value: e.actual ?? null, format: e.actual_format || 'index' })}</span>
                      {e.actual_previous !== undefined && e.actual_previous !== null && (
                        <span className="text-gray-400 dark:text-gray-500"> (anterior {formatValue({ value: e.actual_previous, format: e.actual_format || 'index' })})</span>
                      )}
                      {e.actual_change_pct !== undefined && e.actual_change_pct !== null && (
                        <span className="ml-1"><ChangeBadge pct={e.actual_change_pct} /></span>
                      )}
                      {e.actual_date && (
                        <span className="text-gray-400 dark:text-gray-500"> · dato del {e.actual_date}</span>
                      )}
                    </p>
                  )}
                </div>

                <div className="flex-shrink-0">
                  {past ? (
                    result ? (
                      <span className="text-[10px] font-bold px-2 py-1 rounded bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300">
                        salió
                      </span>
                    ) : (
                      <span className="text-[10px] font-bold px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
                        sin dato
                      </span>
                    )
                  ) : (
                    <span className="text-[10px] font-bold px-2 py-1 rounded bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300">
                      {e.when}
                    </span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-4">
        Calendario curado por reglas de recurrencia (no oficial). Resultados: mindicador.cl para Chile, Alpha Vantage para EE.UU. cuando hay key configurada.
      </p>
    </div>
  )
}
