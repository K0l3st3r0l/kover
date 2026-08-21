import { Fragment, useCallback, useEffect, useState } from 'react'
import api from '../services/api'
import PageActions from '../components/PageActions'

// ─── Types ────────────────────────────────────────────────────────────────────

interface LiquidityComponent {
  name: string
  normalized: number | null
  weight: number
  contribution: number
  note: string
}

interface ScoreComponent {
  name: string
  raw_value: number | null
  normalized: number | null
  weight: number
  contribution: number
  note: string
}

interface Candidate {
  symbol: string
  gate_passed: boolean
  gate_reasons: string[]
  cc_opportunity_score: number | null
  cc_score_components: ScoreComponent[] | null
  final_score: number | null
  final_score_status: string | null
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

interface HoldingCandidate {
  occ_symbol: string
  strike: number
  expiration: string
  dte: number
  call_bid: number
  spread_pct: number | null
  delta: number | null
  open_interest: number | null
  contracts: number
  position_premium_total: number
  gain_if_assigned: number
  total_if_assigned: number
  below_cost_basis: boolean
  net_loss_if_assigned: boolean
  assignment_probability: number | null
  annualized_premium_on_cost: number | null
}

interface HoldingPosition {
  ticker: string
  shares: number
  contracts: number
  uncovered_shares: number
  cost_basis: number
  cost_basis_source: string
  gross_cost: number | null
  premium_collected: number
  market_price: number
  vs_cost_basis: number
  quote_as_of: string
  candidates: HoldingCandidate[]
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

const GATE_LABELS: Record<string, string> = {
  VETO_HARD_FLAG: 'Veto por hard flag en sus filings',
  BAJO_FINANCIAL_SAFETY: 'Financial Safety bajo el umbral del perfil',
  BAJO_MARKET_SAFETY: 'Market Safety bajo el umbral del perfil',
  SPREAD_ANCHO: 'Spread más ancho de lo que tolera el perfil',
  DELTA_FUERA_DE_PERFIL: 'Delta fuera de la banda del perfil',
  DTE_FUERA_DE_PERFIL: 'Vencimiento fuera de la ventana del perfil',
  SIN_FUNDAMENTALES: 'Sin fundamentales: no hay con qué evaluar la puerta',
}

const FINAL_STATUS_LABELS: Record<string, string> = {
  MISSING_FUNDAMENTAL: 'Sin Financial Safety — no se puntúa por omisión',
  MISSING_MARKET: 'Sin Market Safety — no se puntúa por omisión',
  MISSING_BOTH: 'Sin ninguno de los dos scores de seguridad',
  MISSING_CC_OPPORTUNITY: 'Sin CC Opportunity: datos insuficientes del contrato',
}

const pct = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`
const usd = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? '—' : `$${v.toFixed(digits)}`

function ScoreBadge({ value, label }: { value: number | null; label: string }) {
  // Un Financial Safety de exactamente 0 no es "puntaje muy bajo": es el veto
  // de un hard flag (going concern, patrimonio negativo, runway bajo 2
  // trimestres). El score se fuerza a 0 a propósito para que no se promedie
  // con nada. Mostrarlo como un número más lo escondería justo en la fila que
  // más importa no operar.
  if (value === 0 && label === 'Financial Safety') {
    return (
      <span
        className="text-xs px-2 py-0.5 rounded-full font-bold bg-red-600 text-white"
        title="Veto por hard flag: la empresa tiene una señal de fragilidad crítica en sus filings"
      >
        VETO
      </span>
    )
  }
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
  const [mode, setMode] = useState<'universo' | 'posiciones'>('posiciones')
  const [holdings, setHoldings] = useState<HoldingPosition[]>([])
  const [holdingsLoading, setHoldingsLoading] = useState(false)
  const [pickType, setPickType] = useState('BALANCED')
  const [profile, setProfile] = useState('')
  const [includeRejected, setIncludeRejected] = useState(false)
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
  const [orderBy, setOrderBy] = useState('final_score')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: Record<string, string | number | boolean> = { pick_type: pickType, order_by: orderBy, limit: 200 }
      if (profile) {
        params.profile = profile
        params.include_rejected = includeRejected
      }
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
  }, [pickType, profile, includeRejected, orderBy, minFinancial, minMarket, minLiquidity, maxDte])

  const loadHoldings = useCallback(async () => {
    setHoldingsLoading(true)
    setError('')
    try {
      const res = await api.get('/api/scanner/covered-calls/holdings')
      setHoldings(res.data.positions || [])
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'No se pudieron cargar las posiciones.')
    } finally {
      setHoldingsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (mode === 'posiciones') loadHoldings()
  }, [mode, loadHoldings])

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
    if (mode === 'universo') load()
  }, [mode, load])

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
    <div className="space-y-6">
      <PageActions>
        <button
          onClick={runScan}
          disabled={running}
          className="flex-shrink-0 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold px-5 py-2.5 rounded-lg transition"
        >
          {running ? '⏳ Escaneando...' : '🔄 Escanear ahora'}
        </button>
      </PageActions>

      <div className="flex gap-2">
        {[
          { key: 'posiciones' as const, label: '📦 Sobre lo que ya tengo' },
          { key: 'universo' as const, label: '🌎 Buscar en el universo' },
        ].map(m => (
          <button
            key={m.key}
            onClick={() => setMode(m.key)}
            className={`px-4 py-2 rounded-lg text-sm font-semibold transition ${
              mode === m.key
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {mode === 'posiciones' && (
        <HoldingsView positions={holdings} loading={holdingsLoading} onReload={loadHoldings} />
      )}

      {mode === 'universo' && lastRun && (
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

      {mode === 'universo' && (
      <>
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

        <div className="pt-3 border-t border-gray-100 dark:border-gray-700 space-y-2">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="text-sm font-semibold text-gray-700 dark:text-gray-200">Perfil:</span>
            {[
              { key: '', label: 'Sin puerta' },
              { key: 'CONSERVADOR', label: 'Conservador' },
              { key: 'BALANCEADO', label: 'Balanceado' },
              { key: 'AGRESIVO', label: 'Agresivo' },
            ].map(p => (
              <button
                key={p.key}
                onClick={() => setProfile(p.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                  profile === p.key
                    ? 'bg-green-600 text-white'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                {p.label}
              </button>
            ))}
            {profile && (
              <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 cursor-pointer ml-2">
                <input type="checkbox" checked={includeRejected}
                  onChange={e => setIncludeRejected(e.target.checked)} className="w-3.5 h-3.5 rounded" />
                Mostrar también los rechazados, con su motivo
              </label>
            )}
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            {profile
              ? 'Con perfil elegido se aplica la puerta: primero se descarta lo inadmisible, después se ordena. Para cada papel se muestra el mejor contrato que pasa ESE perfil, no el mejor absoluto — el strike que maximiza el score suele quedar fuera de la banda de delta conservadora.'
              : 'Sin perfil no hay puerta: es el ranking crudo, incluidas las filas con veto. Elige un perfil para que se aplique el criterio de admisión antes del orden.'}
          </p>
        </div>

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
              <option value="final_score">Final Score</option>
              <option value="cc_opportunity_score">CC Opportunity</option>
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

      {/* Cómo leer esta tabla sin caerse en las dos trampas obvias */}
      <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-700 rounded-xl p-5 space-y-2 text-sm">
        <p className="font-semibold text-amber-800 dark:text-amber-300">Antes de operar cualquiera de estas filas</p>
        <p className="text-amber-700 dark:text-amber-400">
          <strong>Esto es un ranking, no una recomendación.</strong> Ordena por rendimiento; no aplica
          la puerta fundamental. Una fila marcada <span className="px-1.5 py-0.5 rounded bg-red-600 text-white text-xs font-bold">VETO</span>{' '}
          tiene un hard flag crítico en sus filings — no debería operarse por buena que se vea la prima.
          Cruzar el ranking con los dos scores de seguridad es lo que hace el Final Score, que todavía
          no está construido.
        </p>
        <p className="text-amber-700 dark:text-amber-400">
          <strong>El anualizado engaña en vencimientos cortos.</strong> Un contrato a 8 días con 2,9% de
          prima se anualiza sobre 130%, pero eso supone repetir la operación 45 veces al año con la
          misma prima y sin que te asignen nunca. Mira la columna <em>Rend.</em> —el retorno real del
          período— y usa el anualizado solo para comparar plazos entre sí.
        </p>
        <p className="text-amber-700 dark:text-amber-400">
          <strong>El colchón es delgado arriba del ranking.</strong> Las primas más gordas vienen de los
          papeles más volátiles: un colchón de 3% no protege de una caída del 15%, que en estos nombres
          pasa en un día.
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
                  <th className="px-3 py-2 text-right" title="0,45 CC Opportunity + 0,35 Financial Safety + 0,20 Market Safety">Final</th>
                  <th className="px-3 py-2 text-right" title="Oportunidad del contrato, normalizada contra el resto de la corrida">CC Opp.</th>
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
                      <td className="px-3 py-2 font-bold">
                        {c.symbol}
                        {!c.gate_passed && (
                          <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 font-semibold">
                            rechazado
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-bold">
                        {c.final_score !== null ? (
                          c.final_score.toFixed(0)
                        ) : (
                          <span className="text-xs text-gray-400" title={FINAL_STATUS_LABELS[c.final_score_status || ''] || c.final_score_status || ''}>
                            —
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">{c.cc_opportunity_score?.toFixed(0) ?? '—'}</td>
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
                        <td colSpan={17} className="px-4 py-4">
                          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-6 text-xs text-gray-600 dark:text-gray-300">
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
                              <p className="font-semibold text-gray-800 dark:text-gray-100">
                                Final Score {c.final_score?.toFixed(0) ?? '—'}
                              </p>
                              {c.final_score === null && c.final_score_status && (
                                <p className="text-amber-600 dark:text-amber-400">
                                  {FINAL_STATUS_LABELS[c.final_score_status] || c.final_score_status}
                                </p>
                              )}
                              <p>CC Opportunity {c.cc_opportunity_score?.toFixed(0) ?? '—'} (peso 45%)</p>
                              <p>Financial Safety {c.financial_safety_score?.toFixed(0) ?? 'pendiente'} (peso 35%)</p>
                              <p>Market Safety {c.market_safety_score?.toFixed(0) ?? 'pendiente'} (peso 20%)</p>
                              {!c.gate_passed && c.gate_reasons.length > 0 && (
                                <div className="pt-2">
                                  <p className="font-semibold text-red-600 dark:text-red-400">No pasa la puerta:</p>
                                  {c.gate_reasons.map(r => (
                                    <p key={r} className="text-red-600 dark:text-red-400">• {GATE_LABELS[r] || r}</p>
                                  ))}
                                </div>
                              )}
                            </div>
                            <div className="space-y-1">
                              <p className="font-semibold text-gray-800 dark:text-gray-100">Desglose CC Opportunity</p>
                              {(c.cc_score_components || []).map(comp => (
                                <p key={comp.name} title={comp.note}>
                                  {comp.name}: {comp.normalized === null ? 'sin dato' : `${(comp.normalized * 100).toFixed(0)}%`}
                                  <span className="text-gray-400"> × {(comp.weight * 100).toFixed(0)}%</span>
                                </p>
                              ))}
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
      </>
      )}
    </div>
  )
}

// ─── Vista sobre posiciones abiertas ─────────────────────────────────────────

function HoldingsView({
  positions, loading, onReload,
}: { positions: HoldingPosition[]; loading: boolean; onReload: () => void }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center gap-3 py-10">
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" />
        <span className="text-gray-600 dark:text-gray-300">Consultando cadenas en vivo...</span>
      </div>
    )
  }
  if (!positions.length) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-8 text-center text-gray-500 dark:text-gray-400">
        No tienes posiciones de 100 acciones o más. Un covered call necesita al menos 100.
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <button onClick={onReload}
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
          🔄 Actualizar cotizaciones
        </button>
      </div>

      {positions.map(p => (
        <div key={p.ticker} className="bg-white dark:bg-gray-800 rounded-xl shadow overflow-hidden">
          <div className="p-5 border-b border-gray-100 dark:border-gray-700">
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">{p.ticker}</h2>
              <span className="text-sm text-gray-600 dark:text-gray-300">
                {p.shares} acciones → <strong>{p.contracts} contratos</strong>
                {p.uncovered_shares > 0 && (
                  <span className="text-gray-400"> ({p.uncovered_shares} sin cubrir)</span>
                )}
              </span>
              <span className="text-sm text-gray-600 dark:text-gray-300">
                Mercado <strong>{usd(p.market_price)}</strong>
              </span>
              <span className="text-sm text-gray-600 dark:text-gray-300">
                Costo real <strong>{usd(p.cost_basis)}</strong>
                {p.cost_basis_source === 'GROSS' && (
                  <span className="ml-1 text-xs text-amber-600 dark:text-amber-400">(bruto, sin ajuste por primas)</span>
                )}
              </span>
              <span className={`text-sm font-semibold ${p.vs_cost_basis >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                {p.vs_cost_basis >= 0 ? '+' : ''}{(p.vs_cost_basis * 100).toFixed(1)}% sobre tu costo
              </span>
            </div>
            {p.gross_cost !== null && p.cost_basis_source === 'ADJUSTED' && (
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-2">
                Costo bruto {usd(p.gross_cost)} menos {usd(p.premium_collected, 0)} de primas cobradas en este ciclo.
                Los strikes se comparan contra el costo real, que es lo que decide si te deja ganancia.
              </p>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 dark:bg-gray-700/50 text-xs uppercase text-gray-500 dark:text-gray-400">
                <tr>
                  <th className="px-3 py-2 text-right">Strike</th>
                  <th className="px-3 py-2 text-right">Vence</th>
                  <th className="px-3 py-2 text-right">DTE</th>
                  <th className="px-3 py-2 text-right">Bid</th>
                  <th className="px-3 py-2 text-right" title="Por los {p.contracts} contratos">Prima</th>
                  <th className="px-3 py-2 text-right" title="Prima sobre tu costo real, anualizada">Anual</th>
                  <th className="px-3 py-2 text-right" title="Delta como aproximación de terminar dentro del dinero">P(asig)</th>
                  <th className="px-3 py-2 text-right" title="Solo el capital: (strike - costo real) x acciones">Capital</th>
                  <th className="px-3 py-2 text-right" title="Capital + prima: lo que cierras si te ejercen">Total ciclo</th>
                  <th className="px-3 py-2 text-right">Spread</th>
                  <th className="px-3 py-2 text-right">OI</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {p.candidates.slice(0, 12).map(c => (
                  <tr key={c.occ_symbol}
                    className={`text-gray-700 dark:text-gray-200 ${c.net_loss_if_assigned ? 'bg-red-50 dark:bg-red-900/20' : ''}`}>
                    <td className="px-3 py-2 text-right font-semibold">
                      {usd(c.strike)}
                      {c.below_cost_basis && (
                        <span className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300"
                          title="Bajo tu costo real: la asignación realiza una pérdida de capital">
                          bajo costo
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">{c.expiration}</td>
                    <td className="px-3 py-2 text-right">{c.dte}d</td>
                    <td className="px-3 py-2 text-right">{usd(c.call_bid)}</td>
                    <td className="px-3 py-2 text-right font-semibold text-green-600 dark:text-green-400">
                      {usd(c.position_premium_total, 0)}
                    </td>
                    <td className="px-3 py-2 text-right font-bold">{pct(c.annualized_premium_on_cost, 0)}</td>
                    <td className="px-3 py-2 text-right">{pct(c.assignment_probability, 0)}</td>
                    <td className={`px-3 py-2 text-right ${c.gain_if_assigned < 0 ? 'text-red-600 dark:text-red-400' : ''}`}>
                      {c.gain_if_assigned >= 0 ? '+' : ''}{usd(c.gain_if_assigned, 0).replace('$', '$')}
                    </td>
                    <td className={`px-3 py-2 text-right font-semibold ${c.net_loss_if_assigned ? 'text-red-600 dark:text-red-400' : 'text-green-700 dark:text-green-300'}`}>
                      {c.total_if_assigned >= 0 ? '+' : ''}{usd(c.total_if_assigned, 0)}
                    </td>
                    <td className="px-3 py-2 text-right">{pct(c.spread_pct, 1)}</td>
                    <td className="px-3 py-2 text-right">{c.open_interest ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="p-4 bg-amber-50 dark:bg-amber-900/20 text-xs text-amber-700 dark:text-amber-400 space-y-1">
            <p>
              <strong>El orden es por prima anualizada</strong>, no por "total ciclo". La apreciación hasta
              un strike lejano es de la acción que ya tienes — la call no la crea, así que ordenar por ahí
              premiaría strikes que casi nunca se ejercen y nunca te devuelven el capital.
            </p>
            <p>
              Tú decides el canje: más strike es más capital de vuelta si te asignan, menos strike es más
              prima ahora y más probabilidad de cerrar el ciclo. Las dos columnas están para eso.
            </p>
          </div>
        </div>
      ))}
    </div>
  )
}
