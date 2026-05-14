import { useEffect, useState, useCallback } from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import api from '../services/api'

// ─── Types ────────────────────────────────────────────────────────────────────

interface DividendPosition {
  ticker: string
  company_name: string
  shares: number
  dividend_yield: number | null
  dividend_rate: number | null
  trailing_annual_dividend_rate: number | null
  ex_dividend_date: string | null
  payout_ratio: number | null
  five_year_avg_yield: number | null
  annual_income_projection: number
  pays_dividend: boolean
  stock_id: number
  recent_dividends: { date: string; amount: number }[]
}

interface PortfolioData {
  positions: DividendPosition[]
  total_annual_income: number
  payers_count: number
}

interface HistoryItem {
  id: number
  ticker: string
  amount: number
  shares: number
  price_per_share: number
  date: string
  notes: string | null
}

interface HistoryData {
  history: HistoryItem[]
  total_received: number
  by_ticker: { ticker: string; total: number }[]
  by_year: { year: string; total: number }[]
  by_month: { month: string; total: number }[]
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—'
  return (n * 100).toFixed(2) + '%'
}

function fmtCurrency(n: number): string {
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function daysUntil(dateStr: string | null): number | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return null
  return Math.ceil((d.getTime() - Date.now()) / 86400000)
}

function ExDateBadge({ dateStr }: { dateStr: string | null }) {
  if (!dateStr) return <span className="text-gray-400 dark:text-gray-500">—</span>
  const days = daysUntil(dateStr)
  if (days === null) return <span className="text-gray-500 dark:text-gray-400 text-xs">{dateStr}</span>

  let color = 'text-gray-500 dark:text-gray-400'
  let bg = ''
  if (days <= 0) { color = 'text-gray-400'; bg = '' }
  else if (days <= 7)  { color = 'text-red-700 dark:text-red-300';    bg = 'bg-red-50 dark:bg-red-900/30 font-semibold' }
  else if (days <= 21) { color = 'text-amber-700 dark:text-amber-300'; bg = 'bg-amber-50 dark:bg-amber-900/30' }

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${bg} ${color}`}>
      {dateStr}
      {days > 0 && <span className="ml-1 opacity-70">({days}d)</span>}
    </span>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

type Tab = 'portfolio' | 'history'

export default function Dividends() {
  const [tab, setTab] = useState<Tab>('portfolio')
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null)
  const [history, setHistory] = useState<HistoryData | null>(null)
  const [loadingP, setLoadingP] = useState(false)
  const [loadingH, setLoadingH] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)

  const authHeaders = () => {
    const token = localStorage.getItem('token')
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  const fetchPortfolio = useCallback(async () => {
    setLoadingP(true)
    try {
      const { data } = await api.get('/api/dividends/portfolio', { headers: authHeaders() })
      setPortfolio(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoadingP(false)
    }
  }, [])

  const fetchHistory = useCallback(async () => {
    if (history) return
    setLoadingH(true)
    try {
      const { data } = await api.get('/api/dividends/history', { headers: authHeaders() })
      setHistory(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoadingH(false)
    }
  }, [history])

  useEffect(() => { fetchPortfolio() }, [fetchPortfolio])
  useEffect(() => { if (tab === 'history') fetchHistory() }, [tab, fetchHistory])

  // ─── Tab: Portfolio ─────────────────────────────────────────────────────

  function renderPortfolio() {
    if (loadingP) return <LoadingSkeleton />
    if (!portfolio) return null

    const { positions, total_annual_income, payers_count } = portfolio
    const monthly_income = total_annual_income / 12
    const payers = positions.filter(p => p.pays_dividend)

    return (
      <div className="space-y-6">

        {/* Summary cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <SummaryCard
            label="Ingreso Anual Proyectado"
            value={fmtCurrency(total_annual_income)}
            sub="dividendos estimados/año"
            accent="blue"
          />
          <SummaryCard
            label="Ingreso Mensual"
            value={fmtCurrency(monthly_income)}
            sub="promedio mensual"
            accent="green"
          />
          <SummaryCard
            label="Acciones con Dividendo"
            value={`${payers_count} / ${positions.length}`}
            sub="del portfolio"
            accent="purple"
          />
          <SummaryCard
            label="Yield Promedio Portf."
            value={payers.length > 0
              ? fmtPct(payers.reduce((s, p) => s + (p.dividend_yield ?? 0), 0) / payers.length)
              : '—'}
            sub="de posiciones pagadoras"
            accent="amber"
          />
        </div>

        {/* Strategy note */}
        <div className="flex gap-3 p-4 rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
          <span className="text-2xl">💡</span>
          <div>
            <p className="text-sm font-semibold text-blue-800 dark:text-blue-200">Estrategia Triple Yield</p>
            <p className="text-xs text-blue-700 dark:text-blue-300 mt-0.5 leading-relaxed">
              Maximizás rendimiento combinando <strong>dividendos</strong> + <strong>primas de covered calls</strong> + <strong>apreciación del capital</strong>.
              Ej. Ford (F): dividendo trimestral + primas vendiendo calls cada ciclo.
              Vigilá las fechas ex-dividendo para asegurarte de mantener las acciones antes de ese corte.
            </p>
          </div>
        </div>

        {/* Upcoming ex-dates */}
        {(() => {
          const upcoming = positions
            .filter(p => {
              const d = daysUntil(p.ex_dividend_date)
              return d !== null && d > 0 && d <= 30
            })
            .sort((a, b) => (daysUntil(a.ex_dividend_date) ?? 999) - (daysUntil(b.ex_dividend_date) ?? 999))

          if (!upcoming.length) return null
          return (
            <div className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-4">
              <p className="text-sm font-semibold text-amber-800 dark:text-amber-200 mb-3">
                ⚠️ Ex-Dividend próximos (30 días)
              </p>
              <div className="space-y-2">
                {upcoming.map(p => (
                  <div key={p.ticker} className="flex items-center justify-between text-sm">
                    <span className="font-mono font-bold text-amber-800 dark:text-amber-300">{p.ticker}</span>
                    <span className="text-gray-700 dark:text-gray-300 text-xs">{p.company_name}</span>
                    <ExDateBadge dateStr={p.ex_dividend_date} />
                    <span className="text-amber-700 dark:text-amber-300 font-medium">
                      {p.dividend_rate ? `$${fmt(p.dividend_rate / 4, 4)}/acc` : ''}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )
        })()}

        {/* Positions table */}
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <div className="px-4 py-3 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Posiciones — Detalle Dividendos</h2>
          </div>
          <div className="divide-y divide-gray-100 dark:divide-gray-700/60">
            {positions.map(pos => (
              <div key={pos.ticker}>
                <button
                  onClick={() => setExpanded(expanded === pos.ticker ? null : pos.ticker)}
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors text-left"
                >
                  {/* Ticker */}
                  <span className="w-16 font-mono font-bold text-gray-900 dark:text-white text-sm flex-shrink-0">
                    {pos.ticker}
                  </span>

                  {/* Yield pill */}
                  <span className={`px-2 py-0.5 rounded-full text-xs font-semibold flex-shrink-0 ${
                    pos.pays_dividend
                      ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400'
                  }`}>
                    {pos.pays_dividend ? fmtPct(pos.dividend_yield) : 'Sin div.'}
                  </span>

                  {/* Annual income */}
                  <span className="flex-1 text-right text-sm font-semibold text-gray-900 dark:text-white">
                    {pos.annual_income_projection > 0 ? fmtCurrency(pos.annual_income_projection) : '—'}
                    {pos.annual_income_projection > 0 && <span className="text-xs text-gray-400 font-normal ml-1">/año</span>}
                  </span>

                  {/* Ex date */}
                  <div className="w-36 text-right flex-shrink-0">
                    <ExDateBadge dateStr={pos.ex_dividend_date} />
                  </div>

                  {/* Chevron */}
                  <svg className={`w-4 h-4 text-gray-400 flex-shrink-0 transition-transform ${expanded === pos.ticker ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {expanded === pos.ticker && (
                  <div className="px-4 pb-4 bg-gray-50 dark:bg-gray-800/50 border-t border-gray-100 dark:border-gray-700/60">
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-3 mb-4">
                      <Detail label="Empresa" value={pos.company_name} />
                      <Detail label="Acciones" value={fmt(pos.shares, 0)} />
                      <Detail label="Dividendo Anual/Acc" value={pos.dividend_rate ? `$${fmt(pos.dividend_rate, 4)}` : '—'} />
                      <Detail label="Payout Ratio" value={fmtPct(pos.payout_ratio)} />
                      <Detail label="Yield 5 años avg" value={pos.five_year_avg_yield ? `${fmt(pos.five_year_avg_yield, 2)}%` : '—'} />
                      <Detail label="Ingreso mensual proj." value={pos.annual_income_projection > 0 ? fmtCurrency(pos.annual_income_projection / 12) : '—'} />
                      <Detail label="Ex-Dividend Date" value={pos.ex_dividend_date ?? '—'} />
                      <Detail label="Ingreso anual proj." value={pos.annual_income_projection > 0 ? fmtCurrency(pos.annual_income_projection) : '—'} accent />
                    </div>

                    {pos.recent_dividends.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">Últimos pagos</p>
                        <div className="flex flex-wrap gap-2">
                          {pos.recent_dividends.map((d, i) => (
                            <div key={i} className="px-3 py-1.5 rounded-lg bg-white dark:bg-gray-700 border border-gray-200 dark:border-gray-600 text-xs">
                              <span className="text-gray-500 dark:text-gray-400">{d.date}: </span>
                              <span className="font-semibold text-gray-900 dark:text-white">${fmt(d.amount, 4)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }

  // ─── Tab: History ────────────────────────────────────────────────────────

  function renderHistory() {
    if (loadingH) return <LoadingSkeleton />
    if (!history) return null

    const { history: txs, total_received, by_ticker, by_month } = history

    return (
      <div className="space-y-6">

        {/* Summary */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <SummaryCard label="Total Cobrado" value={fmtCurrency(total_received)} sub="histórico registrado" accent="green" />
          <SummaryCard label="Pagos Registrados" value={String(txs.length)} sub="transacciones tipo DIVIDEND" accent="blue" />
          <SummaryCard label="Acciones pagadoras" value={String(by_ticker.length)} sub="tickers distintos" accent="purple" />
        </div>

        {/* Monthly chart */}
        {by_month.length > 0 && (
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-800">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">Dividendos por Mes</h3>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={by_month} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(156,163,175,0.2)" />
                <XAxis dataKey="month" tick={{ fontSize: 10 }} tickFormatter={m => m.slice(5)} />
                <YAxis tick={{ fontSize: 10 }} tickFormatter={v => `$${v}`} width={50} />
                <Tooltip
                  formatter={(v: number) => [fmtCurrency(v), 'Dividendo']}
                  contentStyle={{ background: 'var(--tooltip-bg, #1f2937)', border: 'none', borderRadius: 8, fontSize: 12 }}
                />
                <Bar dataKey="total" fill="#22c55e" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* By ticker */}
        {by_ticker.length > 0 && (
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="px-4 py-3 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Por Ticker</h3>
            </div>
            <div className="divide-y divide-gray-100 dark:divide-gray-700/60">
              {by_ticker.map(row => (
                <div key={row.ticker} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="font-mono font-bold text-gray-900 dark:text-white text-sm w-16">{row.ticker}</span>
                  <div className="flex-1 bg-gray-100 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden">
                    <div
                      className="h-full bg-green-500 rounded-full"
                      style={{ width: `${(row.total / by_ticker[0].total) * 100}%` }}
                    />
                  </div>
                  <span className="text-sm font-semibold text-gray-900 dark:text-white w-24 text-right">
                    {fmtCurrency(row.total)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Transaction list */}
        {txs.length > 0 && (
          <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div className="px-4 py-3 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Historial de Pagos</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800/60">
                  <tr>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">Fecha</th>
                    <th className="px-4 py-2 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">Ticker</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">$/Acc</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">Acciones</th>
                    <th className="px-4 py-2 text-right text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-700/60">
                  {txs.map(tx => (
                    <tr key={tx.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors">
                      <td className="px-4 py-2.5 text-gray-600 dark:text-gray-400 tabular-nums">
                        {new Date(tx.date).toLocaleDateString('es-CL')}
                      </td>
                      <td className="px-4 py-2.5 font-mono font-bold text-gray-900 dark:text-white">{tx.ticker}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-gray-700 dark:text-gray-300">${fmt(tx.price_per_share, 4)}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-gray-700 dark:text-gray-300">{fmt(tx.shares, 0)}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums font-semibold text-green-600 dark:text-green-400">
                        {fmtCurrency(tx.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {txs.length === 0 && (
          <div className="text-center py-14 text-gray-400 dark:text-gray-500">
            <svg className="w-12 h-12 mx-auto mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-sm font-medium">No hay dividendos registrados</p>
            <p className="text-xs mt-1">Registrá los cobros en Historial usando el tipo "DIVIDEND"</p>
          </div>
        )}
      </div>
    )
  }

  // ─── Layout ──────────────────────────────────────────────────────────────

  return (
    <div className="px-4 sm:px-6 py-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Dividendos</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Rendimiento pasivo — dividendos + covered calls + apreciación
          </p>
        </div>
        {tab === 'portfolio' && (
          <button
            onClick={fetchPortfolio}
            disabled={loadingP}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
          >
            <svg className={`w-3.5 h-3.5 ${loadingP ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Actualizar
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-100 dark:bg-gray-800 rounded-xl p-1 w-fit">
        {(['portfolio', 'history'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`py-2 px-4 rounded-lg text-sm font-medium transition-all ${
              tab === t
                ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
            }`}
          >
            {t === 'portfolio' ? '📈 Portfolio' : '📋 Historial'}
          </button>
        ))}
      </div>

      {tab === 'portfolio' ? renderPortfolio() : renderHistory()}
    </div>
  )
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SummaryCard({ label, value, sub, accent }: { label: string; value: string; sub: string; accent: string }) {
  const colors: Record<string, string> = {
    blue:   'bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800',
    green:  'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800',
    purple: 'bg-purple-50 dark:bg-purple-900/20 border-purple-200 dark:border-purple-800',
    amber:  'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800',
  }
  const text: Record<string, string> = {
    blue:   'text-blue-800 dark:text-blue-200',
    green:  'text-green-800 dark:text-green-200',
    purple: 'text-purple-800 dark:text-purple-200',
    amber:  'text-amber-800 dark:text-amber-200',
  }
  return (
    <div className={`rounded-xl border p-4 ${colors[accent]}`}>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">{label}</p>
      <p className={`text-xl font-bold ${text[accent]}`}>{value}</p>
      <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">{sub}</p>
    </div>
  )
}

function Detail({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{label}</p>
      <p className={`text-sm font-semibold ${accent ? 'text-green-600 dark:text-green-400' : 'text-gray-900 dark:text-white'}`}>
        {value}
      </p>
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 rounded-xl bg-gray-200 dark:bg-gray-700" />
        ))}
      </div>
      <div className="h-48 rounded-xl bg-gray-200 dark:bg-gray-700" />
      <div className="h-64 rounded-xl bg-gray-200 dark:bg-gray-700" />
    </div>
  )
}
