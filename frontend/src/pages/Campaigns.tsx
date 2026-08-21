import { useCallback, useEffect, useState } from 'react'
import api from '../services/api'
import PageActions from '../components/PageActions'

// ─── Types ────────────────────────────────────────────────────────────────────

interface CampaignMetrics {
  capital: number | null
  days_deployed: number | null
  stock_realized_pnl: number | null
  stock_unrealized_pnl: number | null
  option_realized_pnl: number
  option_open_premium: number
  dividends: number
  commissions: number
  total_realized_pnl: number | null
  total_realized_pnl_reason: string | null
  mark_to_market_pnl: number | null
  return_pct: number | null
  annualized_return_pct: number | null
  premium_per_day: number | null
}

interface Cycle {
  cycle_num: number
  status: string
  ticker: string
  strike: number
  contracts: number
  expiration: string | null
  opened_at: string | null
  closed_at: string | null
  dte: number | null
  days_open: number | null
  entry_premium: number
  exit_premium: number | null
  gross_premium: number | null
  closing_cost: number | null
  commissions: number | null
  realized_pnl: number | null
  open_premium: number | null
  premium_source: string | null
  tp70_price: number | null
  tp75_price: number | null
  tp80_price: number | null
  current_ask: number | null
  captured_pct: number | null
  realized_captured_pct: number | null
}

interface Campaign {
  id: number
  ticker: string
  status: string
  close_reason: string | null
  shares: number
  shares_peak: number
  stock_cost_basis: number | null
  cost_basis_status: string
  opened_at: string | null
  closed_at: string | null
  current_price: number | null
  cycles_count: number
  metrics: CampaignMetrics
  cycles?: Cycle[]
}

interface Summary {
  open_campaigns: number
  closed_campaigns: number
  capital_deployed: number
  stock_realized_pnl: number
  option_realized_pnl: number
  option_open_premium: number
  dividends: number
  commissions: number
  total_realized_pnl: number
  campaigns_with_unknown_cost_basis: string[]
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, decimals = 2): string {
  if (n == null) return '—'
  return n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

function money(n: number | null | undefined): string {
  if (n == null) return '—'
  const sign = n < 0 ? '-' : ''
  return `${sign}$${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function pct(n: number | null | undefined): string {
  return n == null ? '—' : `${n.toFixed(2)}%`
}

function shortDate(s: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return isNaN(d.getTime()) ? '—' : d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short', year: '2-digit' })
}

/** Verde en positivo, rojo en negativo, gris cuando el dato es desconocido. */
function pnlClass(n: number | null | undefined): string {
  if (n == null) return 'text-gray-400 dark:text-gray-500'
  if (n > 0) return 'text-green-600 dark:text-green-400'
  if (n < 0) return 'text-red-600 dark:text-red-400'
  return 'text-gray-600 dark:text-gray-300'
}

const CAMPAIGN_LABEL: Record<string, string> = {
  STOCK_ACQUIRED: 'Acciones compradas',
  STOCK_AVAILABLE: 'Libre para vender call',
  CALL_OPEN: 'Call abierta',
  CLOSED: 'Cerrada',
}

const CAMPAIGN_STYLE: Record<string, string> = {
  STOCK_ACQUIRED: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  STOCK_AVAILABLE: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  CALL_OPEN: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  CLOSED: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
}

const CYCLE_LABEL: Record<string, string> = {
  OPEN: 'Abierta',
  TP_ELIGIBLE: 'TP disponible',
  CLOSED_TP: 'Cerrada TP',
  CLOSED_MANUAL: 'Cerrada manual',
  EXPIRED_OTM: 'Expiró OTM',
  ASSIGNED: 'Asignada',
  ROLLED: 'Roleada',
}

const CYCLE_STYLE: Record<string, string> = {
  OPEN: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  TP_ELIGIBLE: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300',
  CLOSED_TP: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  CLOSED_MANUAL: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  EXPIRED_OTM: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  // El assignment es un resultado normal de la estrategia, no una alerta roja.
  ASSIGNED: 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300',
  ROLLED: 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300',
}

function Badge({ text, className }: { text: string; className: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium ${className}`}>
      {text}
    </span>
  )
}

// ─── Componentes ─────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, valueClass }: {
  label: string; value: string; sub?: string; valueClass?: string
}) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
      <div className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${valueClass || 'text-gray-900 dark:text-white'}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{sub}</div>}
    </div>
  )
}

/** Stock, opciones y total siempre juntos: una call se juzga por la campaña completa. */
function PnlBreakdown({ m }: { m: CampaignMetrics }) {
  const rows: { label: string; value: number | null; hint?: string }[] = [
    { label: 'P/L acciones (realizado)', value: m.stock_realized_pnl },
    { label: 'P/L acciones (no realizado)', value: m.stock_unrealized_pnl },
    { label: 'P/L opciones (realizado)', value: m.option_realized_pnl },
    { label: 'Prima abierta', value: m.option_open_premium, hint: 'todavía no realizada' },
    { label: 'Dividendos', value: m.dividends },
    { label: 'Comisiones', value: m.commissions == null ? null : -m.commissions },
  ]
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.label} className="flex items-baseline justify-between gap-4 text-sm">
          <span className="text-gray-600 dark:text-gray-400">
            {r.label}
            {r.hint && <span className="ml-1 text-xs text-gray-400 dark:text-gray-500">({r.hint})</span>}
          </span>
          <span className={`font-mono tabular-nums ${pnlClass(r.value)}`}>{money(r.value)}</span>
        </div>
      ))}
      <div className="pt-2 mt-1 border-t border-gray-200 dark:border-gray-700 flex items-baseline justify-between gap-4">
        <span className="text-sm font-medium text-gray-900 dark:text-white">Total realizado</span>
        <span className={`font-mono tabular-nums font-semibold ${pnlClass(m.total_realized_pnl)}`}>
          {money(m.total_realized_pnl)}
        </span>
      </div>
      {m.total_realized_pnl_reason && (
        <div className="text-xs text-amber-600 dark:text-amber-400">{m.total_realized_pnl_reason}</div>
      )}
      {m.mark_to_market_pnl != null && (
        <div className="flex items-baseline justify-between gap-4">
          <span className="text-sm text-gray-600 dark:text-gray-400">Total a precio de mercado</span>
          <span className={`font-mono tabular-nums ${pnlClass(m.mark_to_market_pnl)}`}>
            {money(m.mark_to_market_pnl)}
          </span>
        </div>
      )}
    </div>
  )
}

function CycleTable({ cycles }: { cycles: Cycle[] }) {
  if (!cycles.length) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400 py-3">
        Esta campaña no tiene calls vendidas.
      </p>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-gray-700">
            <th className="py-2 pr-3 font-medium">#</th>
            <th className="py-2 pr-3 font-medium">Estado</th>
            <th className="py-2 pr-3 font-medium text-right">Strike</th>
            <th className="py-2 pr-3 font-medium text-right">Contratos</th>
            <th className="py-2 pr-3 font-medium">Abierta</th>
            <th className="py-2 pr-3 font-medium">Expira</th>
            <th className="py-2 pr-3 font-medium text-right">Prima entrada</th>
            <th className="py-2 pr-3 font-medium text-right">TP75</th>
            <th className="py-2 pr-3 font-medium text-right">TP80</th>
            <th className="py-2 pr-3 font-medium text-right">Capturado</th>
            <th className="py-2 pr-3 font-medium text-right">Resultado</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-700/60">
          {cycles.map((c) => (
            <tr key={c.cycle_num} className="hover:bg-gray-50 dark:hover:bg-gray-700/40">
              <td className="py-2 pr-3 text-gray-500 dark:text-gray-400">{c.cycle_num}</td>
              <td className="py-2 pr-3">
                <Badge
                  text={CYCLE_LABEL[c.status] || c.status}
                  className={CYCLE_STYLE[c.status] || CYCLE_STYLE.CLOSED_MANUAL}
                />
              </td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums">${fmt(c.strike)}</td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums">{fmt(c.contracts, 0)}</td>
              <td className="py-2 pr-3 whitespace-nowrap text-gray-600 dark:text-gray-300">{shortDate(c.opened_at)}</td>
              <td className="py-2 pr-3 whitespace-nowrap text-gray-600 dark:text-gray-300">
                {shortDate(c.expiration)}
                {c.dte != null && <span className="ml-1 text-xs text-gray-400">({c.dte}d)</span>}
              </td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums">${fmt(c.entry_premium, 3)}</td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums text-gray-500 dark:text-gray-400">
                {c.tp75_price == null ? '—' : `$${fmt(c.tp75_price)}`}
              </td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums text-gray-500 dark:text-gray-400">
                {c.tp80_price == null ? '—' : `$${fmt(c.tp80_price)}`}
              </td>
              <td className="py-2 pr-3 text-right font-mono tabular-nums text-gray-600 dark:text-gray-300">
                {pct(c.captured_pct ?? c.realized_captured_pct)}
              </td>
              <td className={`py-2 pr-3 text-right font-mono tabular-nums ${pnlClass(c.status === 'OPEN' ? c.open_premium : c.realized_pnl)}`}>
                {money(c.status === 'OPEN' ? c.open_premium : c.realized_pnl)}
                {c.status === 'OPEN' && <span className="ml-1 text-xs text-gray-400">abierta</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function CampaignCard({ campaign, expanded, onToggle }: {
  campaign: Campaign; expanded: boolean; onToggle: () => void
}) {
  const [detail, setDetail] = useState<Campaign | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!expanded || detail) return
    setLoading(true)
    api.get(`/api/campaigns/${campaign.id}`)
      .then((r) => setDetail(r.data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false))
  }, [expanded, detail, campaign.id])

  const m = campaign.metrics

  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full text-left px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2 hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors"
      >
        <div className="flex items-center gap-2 min-w-[9rem]">
          <span className="text-lg font-semibold text-gray-900 dark:text-white">{campaign.ticker}</span>
          <Badge
            text={CAMPAIGN_LABEL[campaign.status] || campaign.status}
            className={CAMPAIGN_STYLE[campaign.status] || CAMPAIGN_STYLE.CLOSED}
          />
          {campaign.close_reason === 'ASSIGNED' && (
            <Badge text="Asignada" className="bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300" />
          )}
        </div>

        <div className="text-sm text-gray-600 dark:text-gray-300">
          {fmt(campaign.shares_peak, 0)} acc @ ${fmt(campaign.stock_cost_basis, 4)}
        </div>

        <div className="text-sm text-gray-500 dark:text-gray-400">
          {campaign.cycles_count} {campaign.cycles_count === 1 ? 'call' : 'calls'}
        </div>

        <div className="text-sm text-gray-500 dark:text-gray-400">
          {shortDate(campaign.opened_at)} → {campaign.closed_at ? shortDate(campaign.closed_at) : 'hoy'}
          {m.days_deployed != null && <span className="ml-1">({m.days_deployed}d)</span>}
        </div>

        <div className="ml-auto flex items-center gap-4">
          {campaign.current_price != null && (
            <span className="text-sm text-gray-500 dark:text-gray-400">${fmt(campaign.current_price)}</span>
          )}
          <span className={`font-mono tabular-nums font-semibold ${pnlClass(m.mark_to_market_pnl ?? m.total_realized_pnl)}`}>
            {money(m.mark_to_market_pnl ?? m.total_realized_pnl)}
          </span>
          <span className="text-gray-400 dark:text-gray-500">{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-200 dark:border-gray-700 pt-4">
          <div className="grid gap-6 md:grid-cols-[minmax(0,20rem)_1fr]">
            <div>
              <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">Resultado de la campaña</h4>
              <PnlBreakdown m={m} />
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Capital</div>
                  <div className="font-mono tabular-nums text-gray-900 dark:text-white">{money(m.capital)}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Retorno</div>
                  <div className={`font-mono tabular-nums ${pnlClass(m.return_pct)}`}>{pct(m.return_pct)}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Anualizado simple</div>
                  <div className={`font-mono tabular-nums ${pnlClass(m.annualized_return_pct)}`}>
                    {pct(m.annualized_return_pct)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">Prima por día</div>
                  <div className="font-mono tabular-nums text-gray-900 dark:text-white">
                    {m.premium_per_day == null ? '—' : money(m.premium_per_day)}
                  </div>
                </div>
              </div>
            </div>

            <div>
              <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-3">Ciclos</h4>
              {loading && <p className="text-sm text-gray-500 dark:text-gray-400">Cargando ciclos…</p>}
              {!loading && detail && <CycleTable cycles={detail.cycles || []} />}
              {!loading && !detail && (
                <p className="text-sm text-red-600 dark:text-red-400">No se pudieron cargar los ciclos.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Página ──────────────────────────────────────────────────────────────────

type Filter = 'OPEN' | 'CLOSED' | 'ALL'

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [rebuilding, setRebuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('OPEN')
  const [expanded, setExpanded] = useState<number | null>(null)

  const load = useCallback(async (f: Filter) => {
    setLoading(true)
    setError(null)
    try {
      const params = f === 'ALL' ? {} : { status: f }
      const { data } = await api.get('/api/campaigns', { params })
      setCampaigns(data.campaigns)
      setSummary(data.summary)
      if (f === 'OPEN' && data.campaigns.length === 1) setExpanded(data.campaigns[0].id)
    } catch {
      setError('No se pudieron cargar las campañas.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(filter) }, [filter, load])

  const rebuild = async () => {
    setRebuilding(true)
    try {
      await api.post('/api/campaigns/rebuild')
      await load(filter)
    } catch {
      setError('El rebuild falló.')
    } finally {
      setRebuilding(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageActions>
        <button
          onClick={rebuild}
          disabled={rebuilding}
          className="px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors"
        >
          {rebuilding ? 'Reconstruyendo…' : 'Reconstruir desde transacciones'}
        </button>
      </PageActions>

      {summary && (
        <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Capital desplegado"
            value={money(summary.capital_deployed)}
            sub={`${summary.open_campaigns} ${summary.open_campaigns === 1 ? 'campaña abierta' : 'campañas abiertas'}`}
          />
          <StatCard
            label="P/L acciones"
            value={money(summary.stock_realized_pnl)}
            sub="realizado"
            valueClass={pnlClass(summary.stock_realized_pnl)}
          />
          <StatCard
            label="P/L opciones"
            value={money(summary.option_realized_pnl)}
            sub={`${money(summary.option_open_premium)} en primas abiertas`}
            valueClass={pnlClass(summary.option_realized_pnl)}
          />
          <StatCard
            label="Total realizado"
            value={money(summary.total_realized_pnl)}
            sub={`neto de ${money(summary.commissions)} en comisiones`}
            valueClass={pnlClass(summary.total_realized_pnl)}
          />
        </div>
      )}

      {summary && summary.campaigns_with_unknown_cost_basis.length > 0 && (
        <div className="rounded-lg border border-amber-300 dark:border-amber-700/60 bg-amber-50 dark:bg-amber-900/20 px-4 py-3 text-sm text-amber-800 dark:text-amber-300">
          Sin costo base para {summary.campaigns_with_unknown_cost_basis.join(', ')}: el histórico
          importado no cubre la compra original, así que su P/L de acciones queda fuera de los totales.
        </div>
      )}

      <div className="flex gap-2">
        {(['OPEN', 'CLOSED', 'ALL'] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              filter === f
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
            }`}
          >
            {f === 'OPEN' ? 'Abiertas' : f === 'CLOSED' ? 'Cerradas' : 'Todas'}
          </button>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-red-300 dark:border-red-700/60 bg-red-50 dark:bg-red-900/20 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : campaigns.length === 0 ? (
        <div className="text-center py-12 text-gray-500 dark:text-gray-400">
          No hay campañas {filter === 'OPEN' ? 'abiertas' : filter === 'CLOSED' ? 'cerradas' : ''}.
        </div>
      ) : (
        <div className="space-y-3">
          {campaigns.map((c) => (
            <CampaignCard
              key={c.id}
              campaign={c}
              expanded={expanded === c.id}
              onToggle={() => setExpanded(expanded === c.id ? null : c.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
