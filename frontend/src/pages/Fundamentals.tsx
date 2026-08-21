import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import api from '../services/api'
import PageActions from '../components/PageActions'

// ─── Types ────────────────────────────────────────────────────────────────────

interface Metrics {
  revenue_ttm: number | null
  revenue_growth_yoy: number | null
  operating_income_ttm: number | null
  net_income_ttm: number | null
  operating_margin: number | null
  cash: number | null
  total_debt: number | null
  net_debt: number | null
  operating_cf_ttm: number | null
  capex_ttm: number | null
  fcf_ttm: number | null
  fcf_margin: number | null
  current_ratio: number | null
  debt_to_equity: number | null
  shares_outstanding: number | null
  dilution_yoy: number | null
  cash_runway_quarters: number | null
  stockholders_equity: number | null
  total_assets: number | null
  total_liabilities: number | null
}

interface ScoreComponent {
  name: string
  raw_value: number | null
  normalized: number | null
  weight: number
  contribution: number
  note: string
}

interface RiskFlagItem {
  flag: string
  severity: string
  origin: string
  section: string | null
  text_excerpt: string | null
  detail: Record<string, unknown> | null
  detected_at: string | null
}

interface Fundamentals {
  symbol: string
  name: string | null
  cik: string | null
  sec_url: string | null
  as_of_date: string | null
  accepted_at: string | null
  profile: string
  profile_label: string
  score_status: string
  financial_safety_score: number | null
  metrics: Metrics
  missing_metrics: Record<string, string>
  score_breakdown: {
    score: number | null
    status: string
    coverage: number
    note: string
    components: ScoreComponent[]
    penalties: { flag: string; severity: string; effect: unknown }[]
  }
  source_filing: { form: string; filing_date: string; accession_no: string } | null
  risk_flags: RiskFlagItem[]
  has_reject_flag: boolean
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function big(n: number | null | undefined): string {
  if (n == null) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`
  return `${sign}$${abs.toFixed(0)}`
}

function pct(n: number | null | undefined): string {
  return n == null ? '—' : `${(n * 100).toFixed(2)}%`
}

function num(n: number | null | undefined, d = 2): string {
  return n == null ? '—' : n.toFixed(d)
}

function shares(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`
  return n.toLocaleString('en-US')
}

/** Verde sobre 70, ámbar sobre 45, rojo bajo eso. Gris si no hay score. */
function scoreColor(score: number | null): string {
  if (score == null) return 'text-gray-400 dark:text-gray-500'
  if (score >= 70) return 'text-green-600 dark:text-green-400'
  if (score >= 45) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

function barColor(score: number | null): string {
  if (score == null) return 'bg-gray-300 dark:bg-gray-600'
  if (score >= 70) return 'bg-green-500'
  if (score >= 45) return 'bg-amber-500'
  return 'bg-red-500'
}

const SEVERITY_STYLE: Record<string, string> = {
  REJECT: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
  PENALIZE: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  INFO: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
}

const FLAG_LABEL: Record<string, string> = {
  GOING_CONCERN: 'Duda sobre continuidad',
  BANKRUPTCY: 'Quiebra',
  RESTRUCTURING: 'Reestructuración',
  DELISTING_RISK: 'Riesgo de deslistado',
  SEVERE_LIQUIDITY_RISK: 'Liquidez crítica',
  EXTREME_DILUTION: 'Dilución extrema',
  NEGATIVE_EQUITY: 'Patrimonio negativo',
  COVENANT_BREACH: 'Incumplimiento de covenants',
  AUDITOR_WARNING: 'Debilidad de control interno',
  STALE_FILINGS: 'Filings atrasados',
}

const COMPONENT_LABEL: Record<string, string> = {
  liquidity: 'Liquidez',
  solvency: 'Solvencia',
  cash: 'Caja',
  cash_flow: 'Flujo de caja',
  profitability: 'Rentabilidad',
  revenue_trend: 'Tendencia de ingresos',
  dilution: 'Dilución',
  filing_risk: 'Riesgo en filings',
}

// ─── Componentes ─────────────────────────────────────────────────────────────

function Metric({ label, value, hint, missing }: {
  label: string; value: string; hint?: string; missing?: string
}) {
  return (
    <div>
      <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
      <div className={`font-mono tabular-nums ${missing ? 'text-gray-400 dark:text-gray-500' : 'text-gray-900 dark:text-white'}`}>
        {value}
      </div>
      {hint && <div className="text-xs text-gray-400 dark:text-gray-500">{hint}</div>}
      {missing && <div className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">{missing}</div>}
    </div>
  )
}

/** El desglose que responde "¿por qué este score?" sin recalcular nada. */
function ScoreBreakdown({ breakdown }: { breakdown: Fundamentals['score_breakdown'] }) {
  const maxContribution = Math.max(...breakdown.components.map((c) => c.weight))
  return (
    <div className="space-y-2">
      {breakdown.components.map((c) => {
        const available = c.normalized != null
        const width = available ? (c.contribution / maxContribution) * 100 : 0
        return (
          <div key={c.name}>
            <div className="flex items-baseline justify-between text-sm gap-3">
              <span className="text-gray-700 dark:text-gray-300">
                {COMPONENT_LABEL[c.name] || c.name}
                <span className="ml-1.5 text-xs text-gray-400 dark:text-gray-500">
                  peso {(c.weight * 100).toFixed(0)}%
                </span>
              </span>
              <span className={`font-mono tabular-nums text-xs ${available ? 'text-gray-700 dark:text-gray-300' : 'text-gray-400 dark:text-gray-500'}`}>
                {available ? `+${(c.contribution * 100).toFixed(1)}` : 'sin dato'}
              </span>
            </div>
            <div className="h-1.5 mt-1 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
              <div
                className={available ? 'h-full bg-blue-500' : 'h-full bg-gray-300 dark:bg-gray-600'}
                style={{ width: `${Math.max(width, available ? 2 : 0)}%` }}
              />
            </div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{c.note}</div>
          </div>
        )
      })}
      {breakdown.penalties.length > 0 && (
        <div className="pt-2 mt-2 border-t border-gray-200 dark:border-gray-700 space-y-1">
          {breakdown.penalties.map((p, i) => (
            <div key={i} className="flex justify-between text-sm">
              <span className="text-red-600 dark:text-red-400">
                {FLAG_LABEL[p.flag] || p.flag}
              </span>
              <span className="font-mono tabular-nums text-red-600 dark:text-red-400">
                {typeof p.effect === 'number' ? p.effect.toFixed(1) : String(p.effect)}
              </span>
            </div>
          ))}
        </div>
      )}
      <div className="pt-2 text-xs text-gray-500 dark:text-gray-400">
        {breakdown.note} · cobertura de datos {(breakdown.coverage * 100).toFixed(0)}%
      </div>
    </div>
  )
}

// ─── Página ──────────────────────────────────────────────────────────────────

export default function Fundamentals() {
  const [params, setParams] = useSearchParams()
  const [symbol, setSymbol] = useState(params.get('symbol') || 'F')
  const [input, setInput] = useState(symbol)
  const [data, setData] = useState<Fundamentals | null>(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (sym: string) => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await api.get(`/api/instruments/${sym}/fundamentals`)
      setData(data)
    } catch (err: any) {
      setData(null)
      setError(err?.response?.data?.detail || `No hay fundamentales para ${sym}.`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(symbol) }, [symbol, load])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const sym = input.trim().toUpperCase()
    if (!sym) return
    setSymbol(sym)
    setParams({ symbol: sym })
  }

  const refresh = async () => {
    setRefreshing(true)
    setError(null)
    try {
      await api.post(`/api/instruments/${symbol}/fundamentals/refresh`, null, {
        params: { recompute: true },
      })
      await load(symbol)
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'La descarga desde SEC falló.')
    } finally {
      setRefreshing(false)
    }
  }

  const m = data?.metrics
  const missing = data?.missing_metrics || {}

  return (
    <div className="space-y-6">
      <PageActions>
        <form onSubmit={submit} className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ticker"
            className="w-32 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white uppercase"
          />
          <button type="submit" className="px-3 py-2 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 transition-colors">
            Buscar
          </button>
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing}
            className="px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors"
          >
            {refreshing ? 'Descargando…' : 'Actualizar desde SEC'}
          </button>
        </form>
      </PageActions>

      {error && (
        <div className="rounded-lg border border-amber-300 dark:border-amber-700/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-300">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-blue-600 border-t-transparent" />
        </div>
      )}

      {!loading && data && m && (
        <>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-xl font-semibold text-gray-900 dark:text-white">{data.symbol}</h2>
                  <span className="text-sm text-gray-500 dark:text-gray-400">{data.name}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
                  <span className="px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 text-xs">
                    {data.profile_label}
                  </span>
                  <span>datos al {data.as_of_date}</span>
                  {data.source_filing && (
                    <span>
                      · {data.source_filing.form} del {data.source_filing.filing_date}
                    </span>
                  )}
                  {data.sec_url && (
                    <a href={data.sec_url} target="_blank" rel="noreferrer"
                       className="text-blue-600 dark:text-blue-400 hover:underline">
                      ver en SEC
                    </a>
                  )}
                </div>
              </div>

              <div className="text-right">
                <div className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Financial Safety
                </div>
                <div className={`text-4xl font-semibold ${scoreColor(data.financial_safety_score)}`}>
                  {data.financial_safety_score == null ? '—' : data.financial_safety_score.toFixed(0)}
                </div>
                {data.score_status !== 'OK' && (
                  <div className="text-xs text-amber-600 dark:text-amber-400 max-w-[16rem]">
                    {data.score_status === 'UNSUPPORTED_PROFILE'
                      ? 'Perfil sin métricas sectoriales implementadas: no se le asigna score'
                      : 'Datos insuficientes para puntuar'}
                  </div>
                )}
              </div>
            </div>

            {data.financial_safety_score != null && (
              <div className="mt-3 h-2 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
                <div className={`h-full ${barColor(data.financial_safety_score)}`}
                     style={{ width: `${data.financial_safety_score}%` }} />
              </div>
            )}
          </div>

          {data.risk_flags.length > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">
                Señales de riesgo
                {data.has_reject_flag && (
                  <span className="ml-2 px-2 py-0.5 rounded-md bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300 text-xs">
                    veto activo
                  </span>
                )}
              </h3>
              <div className="space-y-3">
                {data.risk_flags.map((f, i) => (
                  <div key={i} className="text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`px-2 py-0.5 rounded-md text-xs font-medium ${SEVERITY_STYLE[f.severity] || SEVERITY_STYLE.INFO}`}>
                        {f.severity}
                      </span>
                      <span className="text-gray-900 dark:text-white font-medium">
                        {FLAG_LABEL[f.flag] || f.flag}
                      </span>
                      <span className="text-xs text-gray-400 dark:text-gray-500">
                        {f.origin === 'FILING_TEXT' ? `texto de ${f.section}` : 'métrica'}
                      </span>
                    </div>
                    {f.text_excerpt && (
                      // La evidencia es obligatoria: ningún flag de texto sin su cita.
                      <blockquote className="mt-1 pl-3 border-l-2 border-gray-300 dark:border-gray-600 text-xs text-gray-600 dark:text-gray-400 italic">
                        …{f.text_excerpt}…
                      </blockquote>
                    )}
                    {f.origin === 'METRIC' && f.detail && (
                      <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 font-mono">
                        {JSON.stringify(f.detail)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid gap-6 lg:grid-cols-2">
            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Métricas</h3>
              <div className="grid grid-cols-2 gap-4">
                <Metric label="Ingresos TTM" value={big(m.revenue_ttm)}
                        hint={m.revenue_growth_yoy != null ? `${pct(m.revenue_growth_yoy)} interanual` : undefined}
                        missing={missing.revenue_ttm} />
                <Metric label="Resultado operacional" value={big(m.operating_income_ttm)}
                        hint={m.operating_margin != null ? `margen ${pct(m.operating_margin)}` : undefined}
                        missing={missing.operating_income_ttm} />
                <Metric label="Caja" value={big(m.cash)} missing={missing.cash} />
                <Metric label="Deuda total" value={big(m.total_debt)}
                        hint={m.net_debt != null ? `neta ${big(m.net_debt)}` : undefined}
                        missing={missing.total_debt} />
                <Metric label="Flujo operacional" value={big(m.operating_cf_ttm)} missing={missing.operating_cf_ttm} />
                <Metric label="Flujo de caja libre" value={big(m.fcf_ttm)}
                        hint={m.fcf_margin != null ? `margen ${pct(m.fcf_margin)}` : undefined}
                        missing={missing.fcf_ttm} />
                <Metric label="Current ratio" value={num(m.current_ratio)} missing={missing.current_ratio} />
                <Metric label="Deuda / Patrimonio" value={num(m.debt_to_equity)} missing={missing.debt_to_equity} />
                <Metric label="Acciones en circulación" value={shares(m.shares_outstanding)}
                        hint={m.dilution_yoy != null ? `${pct(m.dilution_yoy)} en 12 meses` : undefined}
                        missing={missing.shares_outstanding} />
                <Metric label="Cash runway"
                        value={m.cash_runway_quarters == null ? '—' : `${m.cash_runway_quarters.toFixed(1)} trimestres`}
                        hint={m.cash_runway_quarters == null && m.fcf_ttm != null && m.fcf_ttm > 0
                          ? 'genera caja: no aplica' : undefined}
                        missing={missing.cash_runway_quarters} />
              </div>
            </div>

            <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-5">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">
                ¿Por qué este score?
              </h3>
              {data.score_breakdown?.components?.length ? (
                <ScoreBreakdown breakdown={data.score_breakdown} />
              ) : (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Sin desglose: este perfil no recibe score en la versión actual.
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
