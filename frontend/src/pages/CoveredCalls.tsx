import { Fragment, useCallback, useEffect, useState } from 'react'
import api from '../services/api'

// ─── Types ────────────────────────────────────────────────────────────────────

interface LiquidityComponent {
  name: string
  normalized: number | null
  weight: number
  contribution: number
  note: string
}

interface Candidate {
  symbol: string
  name: string | null
  occ_symbol: string
  expiration: string
  strike: number
  dte: number
  underlying_price: number
  stock_ask: number
  call_bid: number
  call_ask: number
  spread_pct: number | null
  delta: number | null
  implied_volatility: number | null
  volume: number | null
  open_interest: number | null
  premium_total: number
  premium_yield: number
  annualized_premium_yield: number
  return_if_assigned: number
  annualized_return_if_assigned: number
  downside_protection: number
  breakeven: number
  moneyness: number
  liquidity_score: number | null
  liquidity_components: LiquidityComponent[] | null
  financial_safety_score: number | null
  market_safety_score: number | null
  quote_as_of: string | null
  scanned_at: string | null
}

interface LastRun {
  started_at: string
  duration_seconds: number
  symbols_scanned: number
  symbols_with_candidates: number
  symbols_without_candidates: number
  failed_count: number
  rejections: Record<string, number>
}

const PICK_LABELS: Record<string, { title: string; help: string }> = {
  BALANCED: {
    title: 'Balanceado',
    help: 'Mejor rendimiento anualizado ponderado por liquidez. Es el punto de partida razonable: una prima excelente en un contrato que no puedes cerrar no es una oportunidad.',
  },
  PREMIUM: {
    title: 'Máxima prima',
    help: 'El mayor rendimiento anualizado, sin ponderar por liquidez. Sirve cuando piensas llevar la call hasta expiración y no te importa el spread de salida.',
  },
  UPSIDE: {
    title: 'Máximo recorrido',
    help: 'El mayor retorno si te asignan: prima más la ganancia hasta el strike. Para cuando te da lo mismo que te ejerzan porque el precio de salida te acomoda.',
  },
}

const pct = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`
const usd = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? '—' : `$${v.toFixed(digits)}`

function ScoreBadge({ value, label }: { value: number | null; label: string }) {
  if (value === null || value === undefined) {
    // Sin dato es "pendiente", nunca 0: un cero acá se leería como "empresa
    // frágil" y es exactamente lo contrario de lo que significa una ausencia.
    return (
      <span
        className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400"
        title={`${label}: sin snapshot todavía`}
      >
        pendiente
      </span>
    )
  }
  const tone =
    value >= 70
      ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300'
      : value >= 45
        ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300'
        : 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300'
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${tone}`} title={label}>
      {value.toFixed(0)}
    </span>
  )
}

export default function CoveredCalls() {
  const [pickType, setPickType] = useState('BALANCED')
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [lastRun, setLastRun] = useState<LastRun | null>(null)
  const [running, setRunning] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  const [minFinancial, setMinFinancial] = useState('')
  const [minMarket, setMinMarket] = useState('')
  const [minLiquidity, setMinLiquidity] = useState('')
  const [maxDte, setMaxDte] = useState('')
  const [orderBy, setOrderBy] = useState('annualized_premium_yield')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number> = { pick_type: pickType, order_by: orderBy, limit: 200 }
      if (minFinancial) params.min_financial_safety = Number(minFinancial)
      if (minMarket) params.min_market_safety = Number(minMarket)
      if (minLiquidity) params.min_liquidity = Number(minLiquidity)
      if (maxDte) params.max_dte = Number(maxDte)
      const res = await api.get('/api/scanner/covered-calls', { params })
      setCandidates(res.data.candidates || [])
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'No se pudieron cargar los candidatos.')
    } finally {
      setLoading(false)
    }
  }, [pickType, orderBy, minFinancial, minMarket, minLiquidity, maxDte])

  const loadStatus = useCallback(async () => {
    try {
      const res = await api.get('/api/scanner/covered-calls/status')
      setRunning(res.data.running)
      setLastRun(res.data.last_run)
      return res.data.running as boolean
    } catch {
      return false
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  // Mientras corre el scan se pollea; al terminar se recargan los candidatos
  // una sola vez. Sin esto la tabla queda mostrando la corrida anterior sin
  // ninguna señal de que hay datos nuevos.
  useEffect(() => {
    if (!running) return
    const id = setInterval(async () => {
      const stillRunning = await loadStatus()
      if (!stillRunning) {
        clearInterval(id)
        load()
      }
    }, 4000)
    return () => clearInterval(id)
  }, [running, loadStatus, load])

  const runScan = async () => {
    setError('')
    try {
      await api.post('/api/scanner/covered-calls/run')
      setRunning(true)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'No se pudo iniciar el escaneo.')
    }
  }

  const pick = PICK_LABELS[pickType]

  return (
    <div className="max-w-[1600px] mx-auto px-4 py-8 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">🎯 Covered Calls</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Cadenas reales de CBOE sobre el universo calificado. Se compra la acción al ask y se vende
            la call al bid — el peor lado de ambos spreads, para que el número no prometa más de lo
            que se puede ejecutar.
          </p>
        </div>
        <button
          onClick={runScan}
          disabled={running}
          className="flex-shrink-0 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold px-5 py-2.5 rounded-lg transition"
        >
          {running ? '⏳ Escaneando...' : '🔄 Escanear ahora'}
        </button>
      </div>

      {lastRun && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4 text-sm text-gray-600 dark:text-gray-300 flex flex-wrap gap-x-6 gap-y-2">
          <span>Última corrida: <strong>{new Date(lastRun.started_at).toLocaleString('es-CL')}</strong></span>
          <span>{lastRun.symbols_scanned} papeles en {lastRun.duration_seconds}s</span>
          <span className="text-green-600 dark:text-green-400">{lastRun.symbols_with_candidates} con candidatos</span>
          <span className="text-gray-400">{lastRun.symbols_without_candidates} sin nada vendible</span>
          {lastRun.failed_count > 0 && (
            <span className="text-red-600 dark:text-red-400">{lastRun.failed_count} fallidos</span>
          )}
        </div>
      )}

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg p-4 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Selector de lectura */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-5 space-y-4">
        <div className="flex gap-2 flex-wrap">
          {Object.entries(PICK_LABELS).map(([key, meta]) => (
            <button
              key={key}
              onClick={() => setPickType(key)}
              className={`px-4 py-2 rounded-lg text-sm font-semibold transition ${
                pickType === key
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
              }`}
            >
              {meta.title}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400">{pick.help}</p>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 pt-2 border-t border-gray-100 dark:border-gray-700">
          <label className="text-xs text-gray-500 dark:text-gray-400">
            Financial Safety ≥
            <input type="number" value={minFinancial} onChange={e => setMinFinancial(e.target.value)}
              placeholder="sin filtro"
              className="mt-1 w-full px-2 py-1.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white" />
          </label>
          <label className="text-xs text-gray-500 dark:text-gray-400">
            Market Safety ≥
            <input type="number" value={minMarket} onChange={e => setMinMarket(e.target.value)}
              placeholder="sin filtro"
              className="mt-1 w-full px-2 py-1.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white" />
          </label>
          <label className="text-xs text-gray-500 dark:text-gray-400">
            Liquidez ≥
            <input type="number" value={minLiquidity} onChange={e => setMinLiquidity(e.target.value)}
              placeholder="sin filtro"
              className="mt-1 w-full px-2 py-1.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white" />
          </label>
          <label className="text-xs text-gray-500 dark:text-gray-400">
            DTE máximo
            <input type="number" value={maxDte} onChange={e => setMaxDte(e.target.value)}
              placeholder="sin filtro"
              className="mt-1 w-full px-2 py-1.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white" />
          </label>
          <label className="text-xs text-gray-500 dark:text-gray-400">
            Ordenar por
            <select value={orderBy} onChange={e => setOrderBy(e.target.value)}
              className="mt-1 w-full px-2 py-1.5 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white">
              <option value="annualized_premium_yield">Prima anualizada</option>
              <option value="annualized_return_if_assigned">Retorno si asignan</option>
              <option value="liquidity_score">Liquidez</option>
            </select>
          </label>
        </div>

        <p className="text-xs text-amber-600 dark:text-amber-400">
          ⚠️ Los filtros de seguridad dejan fuera los papeles sin snapshot (los que muestran
          "pendiente"), porque un umbral no puede evaluar un dato que no existe. Sin filtro, aparecen
          todos.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center gap-3 py-10">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" />
          <span className="text-gray-600 dark:text-gray-300">Cargando candidatos...</span>
        </div>
      ) : candidates.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-8 text-center text-gray-500 dark:text-gray-400">
          Sin candidatos. Corre un escaneo o afloja los filtros.
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-700/50 text-xs uppercase text-gray-500 dark:text-gray-400">
                <tr>
                  <th className="px-3 py-2 text-left">Papel</th>
                  <th className="px-3 py-2 text-right">Precio</th>
                  <th className="px-3 py-2 text-right">Strike</th>
                  <th className="px-3 py-2 text-right">Vence</th>
                  <th className="px-3 py-2 text-right">DTE</th>
                  <th className="px-3 py-2 text-right">Bid</th>
                  <th className="px-3 py-2 text-right">Prima</th>
                  <th className="px-3 py-2 text-right" title="Prima sobre el capital comprometido">Rend.</th>
                  <th className="px-3 py-2 text-right" title="El mismo rendimiento llevado a un año">Anualiz.</th>
                  <th className="px-3 py-2 text-right" title="Prima + ganancia hasta el strike, si te ejercen">Si asignan</th>
                  <th className="px-3 py-2 text-right" title="Cuánto puede caer el papel antes de perder plata">Colchón</th>
                  <th className="px-3 py-2 text-right">Δ</th>
                  <th className="px-3 py-2 text-right">Spread</th>
                  <th className="px-3 py-2 text-right">Liquidez</th>
                  <th className="px-3 py-2 text-center" title="Financial Safety / Market Safety">FSS / MSS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {candidates.map(c => (
                  <Fragment key={c.occ_symbol}>
                    <tr
                      onClick={() => setExpanded(expanded === c.occ_symbol ? null : c.occ_symbol)}
                      className="hover:bg-gray-50 dark:hover:bg-gray-700/40 cursor-pointer text-gray-700 dark:text-gray-200"
                    >
                      <td className="px-3 py-2 font-bold">{c.symbol}</td>
                      <td className="px-3 py-2 text-right">{usd(c.underlying_price)}</td>
                      <td className="px-3 py-2 text-right font-semibold">{usd(c.strike)}</td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">{c.expiration}</td>
                      <td className="px-3 py-2 text-right">{c.dte}d</td>
                      <td className="px-3 py-2 text-right">{usd(c.call_bid)}</td>
                      <td className="px-3 py-2 text-right font-semibold text-green-600 dark:text-green-400">
                        {usd(c.premium_total, 0)}
                      </td>
                      <td className="px-3 py-2 text-right">{pct(c.premium_yield)}</td>
                      <td className="px-3 py-2 text-right font-bold text-green-700 dark:text-green-300">
                        {pct(c.annualized_premium_yield, 1)}
                      </td>
                      <td className="px-3 py-2 text-right">{pct(c.return_if_assigned)}</td>
                      <td className="px-3 py-2 text-right">{pct(c.downside_protection)}</td>
                      <td className="px-3 py-2 text-right">{c.delta?.toFixed(2) ?? '—'}</td>
                      <td className="px-3 py-2 text-right">{pct(c.spread_pct, 1)}</td>
                      <td className="px-3 py-2 text-right">{c.liquidity_score?.toFixed(0) ?? '—'}</td>
                      <td className="px-3 py-2 text-center whitespace-nowrap">
                        <ScoreBadge value={c.financial_safety_score} label="Financial Safety" />{' '}
                        <ScoreBadge value={c.market_safety_score} label="Market Safety" />
                      </td>
                    </tr>
                    {expanded === c.occ_symbol && (
                      <tr className="bg-gray-50 dark:bg-gray-900/40">
                        <td colSpan={15} className="px-4 py-4">
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs text-gray-600 dark:text-gray-300">
                            <div className="space-y-1">
                              <p className="font-semibold text-gray-800 dark:text-gray-100">La operación</p>
                              <p>Contrato: <code className="text-blue-600 dark:text-blue-400">{c.occ_symbol}</code></p>
                              <p>Compras 100 acciones a {usd(c.stock_ask)} = {usd(c.stock_ask * 100, 0)}</p>
                              <p>Vendes 1 call {usd(c.strike)} y cobras {usd(c.premium_total, 0)}</p>
                              <p>Break-even: <strong>{usd(c.breakeven)}</strong> — bajo eso pierdes plata</p>
                              <p>Si te asignan cobras {usd(c.strike * 100 + c.premium_total, 0)} en total</p>
                            </div>
                            <div className="space-y-1">
                              <p className="font-semibold text-gray-800 dark:text-gray-100">Liquidez {c.liquidity_score?.toFixed(0) ?? '—'}</p>
                              {(c.liquidity_components || []).map(comp => (
                                <p key={comp.name}>
                                  {comp.name}: {comp.normalized === null ? 'sin dato' : `${(comp.normalized * 100).toFixed(0)}%`}
                                  <span className="text-gray-400"> (peso {(comp.weight * 100).toFixed(0)}%)</span>
                                </p>
                              ))}
                              <p>Volumen hoy: {c.volume ?? '—'} · OI: {c.open_interest ?? '—'}</p>
                            </div>
                            <div className="space-y-1">
                              <p className="font-semibold text-gray-800 dark:text-gray-100">Contexto</p>
                              <p>IV del contrato: {pct(c.implied_volatility, 1)}</p>
                              <p>Moneyness: {pct(c.moneyness, 1)} sobre el precio</p>
                              <p>Ask de la call: {usd(c.call_ask)} (lo que cuesta recomprarla)</p>
                              <p className="text-gray-400">
                                Cotización de {c.quote_as_of ? new Date(c.quote_as_of).toLocaleString('es-CL') : '—'} · CBOE difiere ~15 min
                              </p>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
