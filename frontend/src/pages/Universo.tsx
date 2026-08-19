import { useCallback, useEffect, useState } from 'react'
import api from '../services/api'

// ─── Types ────────────────────────────────────────────────────────────────────

interface FunnelCounts {
  listed_total: number
  excluded_etf: number
  excluded_test_issue: number
  excluded_not_common: number
  listing_passed: number
  price_checked: number
  price_no_data: number
  price_out_of_range: number
  price_in_range: number
  low_volume: number
  optionable_checked: number
  not_optionable: number
  optionable_check_failed: number
  qualified: number
}

interface LastRun {
  status: string
  started_at: string
  duration_seconds: number
  funnel: FunnelCounts
  market_risk: { computed: number; failed: string[] }
}

interface UniverseItem {
  symbol: string
  name: string | null
  exchange: string | null
  is_optionable: boolean | null
  universe_stage: string
  rejected_reason: string | null
  qualified: boolean
  checked_at: string | null
  price: number | null
  avg_dollar_volume_20: number | null
  market_safety_score: number | null
  market_risk_as_of: string | null
  financial_safety_score: number | null
  financial_score_status: string
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const REASON_LABEL: Record<string, string> = {
  LOW_VOLUME: 'volumen diario insuficiente',
  LOW_DOLLAR_VOLUME: 'volumen en dólares insuficiente',
  NOT_OPTIONABLE: 'sin opciones listadas',
  OPTIONABLE_CHECK_FAILED: 'no se pudo verificar (reintenta la próxima corrida)',
}

const STAGE_LABEL: Record<string, string> = {
  PRICE_RANGE: 'En banda de precio',
  LIQUIDITY: 'Liquidez evaluada',
  OPTIONABLE: 'Optionabilidad evaluada',
}

function scoreColor(score: number | null): string {
  if (score == null) return 'text-gray-400 dark:text-gray-500'
  if (score >= 70) return 'text-green-600 dark:text-green-400'
  if (score >= 45) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

function money(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`
  return `$${n.toFixed(0)}`
}

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return 'recién'
  if (mins < 60) return `hace ${mins} min`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `hace ${hours} h`
  return `hace ${Math.round(hours / 24)} d`
}

// ─── Funnel visual ───────────────────────────────────────────────────────────

function FunnelStep({ label, value, of, hint }: { label: string; value: number; of: number; hint?: string }) {
  const pct = of > 0 ? (value / of) * 100 : 0
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm mb-1">
        <span className="text-gray-700 dark:text-gray-300">{label}</span>
        <span className="font-mono tabular-nums text-gray-900 dark:text-white">
          {value.toLocaleString('en-US')}
          {hint && <span className="ml-1.5 text-xs text-gray-400 dark:text-gray-500">{hint}</span>}
        </span>
      </div>
      <div className="h-2 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
        <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.max(pct, value > 0 ? 1.5 : 0)}%` }} />
      </div>
    </div>
  )
}

function Funnel({ run }: { run: LastRun }) {
  const f = run.funnel
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Embudo del universo</h2>
        <span className="text-xs text-gray-400 dark:text-gray-500">
          última corrida {timeAgo(run.started_at)} · {run.duration_seconds.toFixed(0)}s
        </span>
      </div>
      <div className="space-y-3">
        <FunnelStep label="Listados (NYSE + NASDAQ + AMEX)" value={f.listed_total} of={f.listed_total} />
        <FunnelStep
          label="Acción común (sin ETF/test/warrants/preferentes)"
          value={f.listing_passed}
          of={f.listed_total}
          hint={`−${f.excluded_etf} ETF, −${f.excluded_test_issue} test, −${f.excluded_not_common} otros`}
        />
        <FunnelStep
          label="Precio US$5–20"
          value={f.price_in_range}
          of={f.listing_passed}
          hint={`−${f.price_out_of_range} fuera de banda, −${f.price_no_data} sin datos`}
        />
        <FunnelStep
          label="Liquidez suficiente"
          value={f.price_in_range - f.low_volume}
          of={f.price_in_range}
          hint={`−${f.low_volume} volumen bajo`}
        />
        <FunnelStep
          label="Optionable"
          value={f.qualified}
          of={f.price_in_range - f.low_volume || 1}
          hint={
            f.optionable_check_failed > 0
              ? `${f.optionable_check_failed} pendientes de verificar`
              : `−${f.not_optionable} sin opciones (según directorio CBOE)`
          }
        />
      </div>
      {f.optionable_check_failed > 0 && (
        <div className="flex items-start gap-2 bg-amber-50 dark:bg-amber-900/20 text-amber-800 dark:text-amber-300 rounded-lg px-3 py-2.5 text-sm">
          <span className="mt-0.5">⚠️</span>
          <span>
            <strong>No se pudo descargar el directorio de símbolos de CBOE en esta corrida</strong> — los{' '}
            {f.optionable_check_failed.toLocaleString('en-US')} candidatos con liquidez suficiente quedaron sin
            verificar. No están descartados: se reintenta solo en la próxima corrida (job diario 05:45 ET) o con
            "Correr ahora" más tarde.
          </span>
        </div>
      )}
      <div className="pt-2 border-t border-gray-100 dark:border-gray-700 flex items-center justify-between text-sm">
        <span className="text-gray-500 dark:text-gray-400">Riesgo de mercado calculado</span>
        <span className="font-mono text-gray-900 dark:text-white">
          {run.market_risk.computed}
          {run.market_risk.failed.length > 0 && (
            <span className="text-amber-600 dark:text-amber-400 ml-1.5">({run.market_risk.failed.length} sin datos)</span>
          )}
        </span>
      </div>
    </div>
  )
}

// ─── Página ──────────────────────────────────────────────────────────────────

type StageFilter = 'ALL' | 'QUALIFIED' | 'PRICE_RANGE' | 'LIQUIDITY' | 'OPTIONABLE'

export default function Universo() {
  const [lastRun, setLastRun] = useState<LastRun | null>(null)
  const [items, setItems] = useState<UniverseItem[]>([])
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [stageFilter, setStageFilter] = useState<StageFilter>('ALL')
  const [search, setSearch] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const params: Record<string, string> = {}
      if (stageFilter === 'QUALIFIED') params.qualified_only = 'true'
      else if (stageFilter !== 'ALL') params.stage = stageFilter
      if (search.trim()) params.search = search.trim()
      const res = await api.get('/api/scanner/universe', { params })
      setItems(res.data.instruments)
      setLastRun(res.data.last_run)
      setError(null)
    } catch (e) {
      setError('No se pudo cargar el universo.')
    } finally {
      setLoading(false)
    }
  }, [stageFilter, search])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!running) return
    const interval = setInterval(async () => {
      const res = await api.get('/api/scanner/universe/status')
      if (!res.data.running) {
        setRunning(false)
        load()
      }
    }, 4000)
    return () => clearInterval(interval)
  }, [running, load])

  const triggerRun = async () => {
    setRunning(true)
    try {
      await api.post('/api/scanner/universe/run')
    } catch {
      setRunning(false)
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">🔭 Universo</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Acciones US$5–20, optionables y con liquidez — Stage 1-3 del scanner de covered calls.
          </p>
        </div>
        <button
          onClick={triggerRun}
          disabled={running}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium transition-colors"
        >
          {running ? 'Corriendo… (puede tardar varios minutos)' : 'Correr ahora'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 rounded-lg p-3 text-sm">{error}</div>
      )}

      {lastRun ? (
        <Funnel run={lastRun} />
      ) : (
        !loading && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-5 text-sm text-gray-500 dark:text-gray-400">
            Todavía no hay ninguna corrida registrada. Usa "Correr ahora" o espera al job diario (05:45 ET).
          </div>
        )
      )}

      <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
        <div className="p-4 border-b border-gray-100 dark:border-gray-700 flex flex-wrap items-center gap-3">
          <div className="flex gap-1.5 flex-wrap">
            {(['ALL', 'QUALIFIED', 'PRICE_RANGE', 'LIQUIDITY', 'OPTIONABLE'] as StageFilter[]).map((s) => (
              <button
                key={s}
                onClick={() => setStageFilter(s)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                  stageFilter === s
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                {s === 'ALL' ? 'Todos' : s === 'QUALIFIED' ? 'Calificados' : STAGE_LABEL[s]}
              </button>
            ))}
          </div>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar símbolo…"
            className="ml-auto px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-900 text-gray-900 dark:text-white w-40"
          />
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-400 dark:text-gray-500 border-b border-gray-100 dark:border-gray-700">
                <th className="px-4 py-2">Símbolo</th>
                <th className="px-4 py-2">Precio</th>
                <th className="px-4 py-2">Vol. US$ (20d)</th>
                <th className="px-4 py-2">Market Safety</th>
                <th className="px-4 py-2">Financial Safety</th>
                <th className="px-4 py-2">Estado</th>
                <th className="px-4 py-2">Actualizado</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                    Cargando…
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-400">
                    Sin resultados.
                  </td>
                </tr>
              ) : (
                items.map((it) => (
                  <tr key={it.symbol} className="border-b border-gray-50 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                    <td className="px-4 py-2.5">
                      <div className="font-medium text-gray-900 dark:text-white">{it.symbol}</div>
                      {it.name && <div className="text-xs text-gray-400 dark:text-gray-500 truncate max-w-[220px]">{it.name}</div>}
                    </td>
                    <td className="px-4 py-2.5 font-mono tabular-nums text-gray-700 dark:text-gray-300">
                      {it.price != null ? `$${it.price.toFixed(2)}` : '—'}
                    </td>
                    <td className="px-4 py-2.5 font-mono tabular-nums text-gray-700 dark:text-gray-300">
                      {money(it.avg_dollar_volume_20)}
                    </td>
                    <td className={`px-4 py-2.5 font-mono tabular-nums font-medium ${scoreColor(it.market_safety_score)}`}>
                      {it.market_safety_score != null ? it.market_safety_score.toFixed(0) : '—'}
                    </td>
                    <td className={`px-4 py-2.5 font-mono tabular-nums font-medium ${scoreColor(it.financial_safety_score)}`}>
                      {it.financial_score_status === 'PENDING' ? (
                        <span className="text-xs text-gray-400 dark:text-gray-500 font-sans">pendiente</span>
                      ) : it.financial_safety_score != null ? (
                        it.financial_safety_score.toFixed(0)
                      ) : (
                        <span className="text-xs text-gray-400 dark:text-gray-500 font-sans">{it.financial_score_status}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      {it.qualified ? (
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300">
                          Calificado
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                          {REASON_LABEL[it.rejected_reason || ''] || STAGE_LABEL[it.universe_stage] || it.universe_stage}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-400 dark:text-gray-500">{timeAgo(it.checked_at)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
