import { useEffect, useState } from 'react'
import api from '../services/api'
import ExpirationAlerts from '../components/ExpirationAlerts'
import AllocationChart from '../components/AllocationChart'
import PremiumChart from '../components/PremiumChart'
import CoveredCallCycles from '../components/CoveredCallCycles'
import PortfolioGrowthChart from '../components/PortfolioGrowthChart'
import TWRChart from '../components/TWRChart'
import PositionsPnLChart, { PositionPnL } from '../components/PositionsPnLChart'
import { AllocationResponse, PremiumTimelineData, PerformanceMetrics } from '../types'

interface DashboardSummary {
  total_stocks: number
  total_invested: number
  total_capital_deployed: number
  current_portfolio_value: number
  total_premium_earned: number
  open_options: number
  realized_pnl: number
  realized_stock_pnl: number
  unrealized_pnl: number
  total_pnl: number
  total_pnl_pct: number
  roi_historical_pct: number
  roi_current_pct: number
}

interface YearlySummary {
  year: number
  invested: number
  sold: number
  premium_income: number
  dividends: number
  commissions: number
  realized_stock_pnl: number
  total_income: number
  n_buys: number
  n_sells: number
  n_options: number
}

interface TWRData {
  twr_series: Array<{ date: string; twr_pct: number }>
  twr_final: number
  benchmark_series: Array<{ date: string; pct: number }>  // NASDAQ
  sp500_series: Array<{ date: string; pct: number }>      // S&P 500
  error: string | null
}

interface PortfolioGrowthEvent {  date: string
  cumulative_invested: number
  cumulative_sells: number
  net_cash_deployed: number
  cumulative_realized_pnl: number
  cumulative_premiums: number
  total_realized_net: number
  roi_realized_pct: number
  roi_net_cash_pct: number
}

interface PortfolioGrowthData {
  events: PortfolioGrowthEvent[]
  current_unrealized: number
  total_pnl: number
  roi_total_pct: number
  roi_net_cash_total_pct: number
  cumulative_invested: number
  net_cash_deployed: number
}

interface CCByTicker {
  by_ticker: Array<{
    ticker: string
    primas_cobradas: number
    cierres: number
    prima_neta: number
    n_ventas: number
    n_cierres: number
    shares: number
    avg_cost: number
    capital: number
    yield_pct: number
  }>
  total_primas_cobradas: number
  total_cierres: number
  total_prima_neta: number
}

interface AdvancedMetrics {
  period_days: number
  total_trades: number
  option_trades: number
  stock_trades: number
  winning_trades: number
  losing_trades: number
  breakeven_trades: number
  win_rate: number
  avg_win: number
  avg_loss: number
  expectancy: number
  profit_factor: number | null
  total_realized_pnl: number
  option_pnl: number
  stock_pnl: number
  best_trade: { ticker: string; pnl: number; type: string } | null
  worst_trade: { ticker: string; pnl: number; type: string } | null
  avg_duration_days: number | null
  max_consec_wins: number
  max_consec_losses: number
  error: string | null
}

function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [allocation, setAllocation] = useState<AllocationResponse | null>(null)
  const [premiumTimeline, setPremiumTimeline] = useState<PremiumTimelineData[]>([])
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null)
  const [advancedMetrics, setAdvancedMetrics] = useState<AdvancedMetrics | null>(null)
  const [yearlySummary, setYearlySummary] = useState<YearlySummary[]>([])
  const [selectedYear, setSelectedYear] = useState<number | null>(null)
  const [ccByTicker, setCcByTicker] = useState<CCByTicker | null>(null)
  const [portfolioGrowth, setPortfolioGrowth] = useState<PortfolioGrowthData | null>(null)
  const [positionsPnL, setPositionsPnL] = useState<PositionPnL[]>([])
  const [twrData, setTwrData] = useState<TWRData | null>(null)
  const [twrLoading, setTwrLoading] = useState(false)
  const [cashBalance, setCashBalance] = useState<number>(0)
  const [editingCash, setEditingCash] = useState(false)
  const [cashInput, setCashInput] = useState('')
  const [cashSaving, setCashSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [metricsDays, setMetricsDays] = useState(365)

  useEffect(() => {
    fetchSummary()
    fetchAnalytics()
    fetchCash()
    // Actualizar cada 30 segundos
    const interval = setInterval(() => {
      fetchSummary()
      fetchAnalytics()
    }, 30000)
    return () => clearInterval(interval)
  }, [])

  const fetchCash = async () => {
    try {
      const res = await api.get<{ cash_balance: number }>('/api/auth/cash')
      setCashBalance(res.data.cash_balance ?? 0)
    } catch { /* ignorar */ }
  }

  const saveCash = async () => {
    const val = parseFloat(cashInput.replace(/,/g, '.'))
    if (isNaN(val) || val < 0) return
    setCashSaving(true)
    try {
      const res = await api.put<{ cash_balance: number }>('/api/auth/cash', { cash_balance: val })
      setCashBalance(res.data.cash_balance)
      setEditingCash(false)
    } catch { alert('Error al guardar el saldo') }
    finally { setCashSaving(false) }
  }

  const fetchSummary = async () => {
    try {
      const response = await api.get('/api/dashboard/summary')
      setSummary(response.data)
    } catch (error) {
      console.error('Error fetching summary:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchAnalytics = async () => {
    const [allocationRes, premiumRes, metricsRes, advancedRes, yearlyRes, ccRes, growthRes, positionsRes] = await Promise.allSettled([
      api.get<AllocationResponse>('/api/analytics/allocation'),
      api.get<PremiumTimelineData[]>('/api/analytics/premium-timeline?days=90'),
      api.get<PerformanceMetrics>('/api/analytics/performance-metrics'),
      api.get<AdvancedMetrics>(`/api/analytics/advanced-metrics?days=${metricsDays}`),
      api.get<YearlySummary[]>('/api/analytics/yearly-summary'),
      api.get<CCByTicker>('/api/analytics/cc-by-ticker'),
      api.get<PortfolioGrowthData>('/api/analytics/portfolio-growth'),
      api.get<PositionPnL[]>('/api/analytics/positions-pnl')
    ])

    if (allocationRes.status === 'fulfilled') setAllocation(allocationRes.value.data)
    else console.error('allocation error:', allocationRes.reason)

    if (premiumRes.status === 'fulfilled') setPremiumTimeline(premiumRes.value.data)
    else console.error('premium-timeline error:', premiumRes.reason)

    if (metricsRes.status === 'fulfilled') setMetrics(metricsRes.value.data)
    else console.error('performance-metrics error:', metricsRes.reason)

    if (advancedRes.status === 'fulfilled') setAdvancedMetrics(advancedRes.value.data)
    else console.error('advanced-metrics error:', advancedRes.reason)

    if (yearlyRes.status === 'fulfilled') {
      const data = yearlyRes.value.data
      setYearlySummary(data)
      if (data.length > 0) setSelectedYear(data[data.length - 1].year)
    } else console.error('yearly-summary error:', yearlyRes.reason)

    if (ccRes.status === 'fulfilled') setCcByTicker(ccRes.value.data)
    else console.error('cc-by-ticker error:', ccRes.reason)

    if (growthRes.status === 'fulfilled') setPortfolioGrowth(growthRes.value.data)
    else console.error('portfolio-growth error:', growthRes.reason)

    if (positionsRes.status === 'fulfilled') setPositionsPnL(positionsRes.value.data)
    else console.error('positions-pnl error:', positionsRes.reason)

    // TWR se carga por separado (puede ser lento — descarga precios históricos)
    setTwrLoading(true)
    api.get<TWRData>('/api/analytics/twr')
      .then(r => setTwrData(r.data))
      .catch(e => console.error('twr error:', e))
      .finally(() => setTwrLoading(false))
  }

  const formatCurrency = (value?: number) => {
    if (value === undefined || value === null) return '$0.00';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value);
  };

  const handleExportTaxReport = async () => {
    const year = prompt('Enter the year for tax report (e.g., 2025):', new Date().getFullYear().toString());
    if (!year) return;

    try {
      const response = await api.get(`/api/exports/tax-report/csv?year=${year}`, {
        responseType: 'blob'
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `kover_tax_report_${year}.csv`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Error exporting tax report:', error);
      alert('Error al exportar reporte de impuestos. Por favor intenta de nuevo.');
    }
  };

  const handleExportPortfolio = async () => {
    try {
      const response = await api.get('/api/exports/portfolio/csv', {
        responseType: 'blob'
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `kover_portfolio_${new Date().toISOString().split('T')[0]}.csv`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Error exporting portfolio:', error);
      alert('Error al exportar portafolio. Por favor intenta de nuevo.');
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-2 border-blue-600 border-t-transparent"></div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Resumen general de tu portafolio</p>
        </div>
        <div className="flex gap-2">
          <button 
            onClick={handleExportPortfolio}
            className="btn btn-sm bg-green-600 hover:bg-green-700 text-white"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export Portfolio
          </button>
          <button 
            onClick={handleExportTaxReport}
            className="btn btn-sm bg-purple-600 hover:bg-purple-700 text-white"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Tax Report
          </button>
          <button 
            onClick={() => { fetchSummary(); fetchAnalytics(); fetchCash(); }}
            className="text-sm px-3 py-2 text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 font-medium"
          >
            🔄 Actualizar
          </button>
        </div>
      </div>

      {/* Alertas de Expiración */}
      <ExpirationAlerts />
      
      {/* Stats Grid */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4 mb-6">
        <div className="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-1">
                <dt className="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Total Invertido</dt>
                <dd className="mt-1 text-3xl font-semibold text-gray-900 dark:text-gray-100">
                  {formatCurrency(summary?.total_invested)}
                </dd>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-1">
                <dt className="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Valor Actual</dt>
                <dd className="mt-1 text-3xl font-semibold text-gray-900 dark:text-gray-100">
                  {formatCurrency(summary?.current_portfolio_value)}
                </dd>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-1">
                <dt className="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">Primas Ganadas</dt>
                <dd className="mt-1 text-3xl font-semibold text-green-600 dark:text-green-400">
                  {formatCurrency(summary?.total_premium_earned)}
                </dd>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-1">
                <dt className="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">P&L Total</dt>
                <dd className={`mt-1 text-3xl font-semibold ${(summary?.total_pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {formatCurrency(summary?.total_pnl)}
                </dd>
                <div className="mt-1 space-y-0.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-400">ROI histórico</span>
                    <span className={`font-medium ${(summary?.roi_historical_pct || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {summary?.roi_historical_pct !== undefined ? `${summary.roi_historical_pct >= 0 ? '+' : ''}${summary.roi_historical_pct.toFixed(2)}%` : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-400">ROI posición actual</span>
                    <span className={`font-medium ${(summary?.roi_current_pct || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {summary?.roi_current_pct !== undefined ? `${summary.roi_current_pct >= 0 ? '+' : ''}${summary.roi_current_pct.toFixed(2)}%` : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs pt-0.5 border-t border-gray-100">
                    <span className="text-gray-400">Capital desplegado</span>
                    <span className="text-gray-500 font-medium">{formatCurrency(summary?.total_capital_deployed)}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Additional Stats */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4 mb-8">
        <div className="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg p-5">
          <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Posiciones Activas</dt>
          <dd className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{summary?.total_stocks || 0}</dd>
        </div>

        <div className="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg p-5">
          <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Opciones Abiertas</dt>
          <dd className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{summary?.open_options || 0}</dd>
        </div>

        <div className="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg p-5">
          <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">P&L Realizado</dt>
          <dd className={`mt-1 text-2xl font-semibold ${((summary?.realized_pnl || 0) + (summary?.realized_stock_pnl || 0)) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
            {formatCurrency((summary?.realized_pnl || 0) + (summary?.realized_stock_pnl || 0))}
          </dd>
          <dd className="text-xs text-gray-400 dark:text-gray-500 mt-1">
            Opciones: {formatCurrency(summary?.realized_pnl)} · Acciones: {formatCurrency(summary?.realized_stock_pnl)}
          </dd>
        </div>

        {/* Cash disponible — editable manualmente */}
        <div className="bg-white dark:bg-gray-800 overflow-hidden shadow rounded-lg p-5">
          <div className="flex items-center justify-between mb-1">
            <dt className="text-sm font-medium text-gray-500 dark:text-gray-400">Cash Disponible</dt>
            {!editingCash && (
              <button
                onClick={() => { setCashInput(cashBalance.toFixed(2)); setEditingCash(true) }}
                className="text-gray-400 hover:text-blue-500 transition-colors"
                title="Editar saldo"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536M9 13l6.586-6.586a2 2 0 112.828 2.828L11.828 15.828a2 2 0 01-1.414.586H9v-2a2 2 0 01.586-1.414z" />
                </svg>
              </button>
            )}
          </div>
          {editingCash ? (
            <div className="mt-1">
              <div className="flex items-center gap-1">
                <span className="text-gray-400 text-sm">$</span>
                <input
                  autoFocus
                  type="number"
                  step="0.01"
                  min="0"
                  value={cashInput}
                  onChange={e => setCashInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') saveCash(); if (e.key === 'Escape') setEditingCash(false) }}
                  className="w-full border border-blue-300 rounded px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-blue-400"
                />
              </div>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={saveCash}
                  disabled={cashSaving}
                  className="flex-1 text-xs bg-blue-600 text-white rounded py-1 hover:bg-blue-700 disabled:opacity-50"
                >
                  {cashSaving ? 'Guardando…' : 'Guardar'}
                </button>
                <button
                  onClick={() => setEditingCash(false)}
                  className="flex-1 text-xs bg-gray-100 text-gray-600 rounded py-1 hover:bg-gray-200"
                >
                  Cancelar
                </button>
              </div>
            </div>
          ) : (
            <>
              <dd className="mt-1 text-2xl font-semibold text-blue-600 dark:text-blue-400">
                {formatCurrency(cashBalance)}
              </dd>
              <dd className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                Valor de mercado + cash:{' '}
                <span className="font-medium text-gray-600 dark:text-gray-300">
                  {formatCurrency((summary?.current_portfolio_value || 0) + cashBalance)}
                </span>
              </dd>
            </>
          )}
        </div>
      </div>

      {/* ── TWR Chart ─────────────────────────────────────────────── */}
      {twrLoading && (
        <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8 flex items-center gap-3">
          <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-green-600"></div>
          <span className="text-sm text-gray-500 dark:text-gray-400">Calculando TWR — descargando precios históricos…</span>
        </div>
      )}
      {!twrLoading && twrData && <TWRChart data={twrData} />}

      {/* ── Crecimiento Histórico ─────────────────────────────────────── */}
      {portfolioGrowth && portfolioGrowth.events.length > 0 && (
        <PortfolioGrowthChart data={portfolioGrowth} />
      )}

      {/* ── Resumen por Año Fiscal ─────────────────────────────────────── */}
      {yearlySummary.length > 0 && (() => {
        const yr = yearlySummary.find(y => y.year === selectedYear)
        return (
          <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-5">
              <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">📅 Resumen por Año Fiscal</h3>
              <select
                value={selectedYear ?? ''}
                onChange={e => setSelectedYear(Number(e.target.value))}
                className="text-sm border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {yearlySummary.map(y => (
                  <option key={y.year} value={y.year}>Año {y.year}</option>
                ))}
              </select>
            </div>
            {yr && (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
                <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3">
                  <p className="text-gray-500 dark:text-gray-400 mb-1">Compras</p>
                  <p className="font-semibold text-gray-800 dark:text-gray-200">{formatCurrency(yr.invested)}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{yr.n_buys} transacciones</p>
                </div>
                <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3">
                  <p className="text-gray-500 dark:text-gray-400 mb-1">Ventas</p>
                  <p className="font-semibold text-gray-800 dark:text-gray-200">{formatCurrency(yr.sold)}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{yr.n_sells} transacciones</p>
                </div>
                <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3">
                  <p className="text-gray-500 dark:text-gray-400 mb-1">P&L Acciones</p>
                  <p className={`font-semibold ${yr.realized_stock_pnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                    {yr.realized_stock_pnl >= 0 ? '+' : ''}{formatCurrency(yr.realized_stock_pnl)}
                  </p>
                </div>
                <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3">
                  <p className="text-gray-500 dark:text-gray-400 mb-1">Primas Netas</p>
                  <p className={`font-semibold ${yr.premium_income >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                    {yr.premium_income >= 0 ? '+' : ''}{formatCurrency(yr.premium_income)}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">{yr.n_options} contratos</p>
                </div>
                <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3">
                  <p className="text-gray-500 dark:text-gray-400 mb-1">Dividendos</p>
                  <p className="font-semibold text-green-600 dark:text-green-400">{formatCurrency(yr.dividends)}</p>
                </div>
                <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3">
                  <p className="text-gray-500 dark:text-gray-400 mb-1">Comisiones</p>
                  <p className="font-semibold text-red-500">-{formatCurrency(yr.commissions)}</p>
                </div>
                <div className="col-span-2 sm:col-span-3 bg-blue-50 dark:bg-blue-900/30 rounded-lg p-4 flex justify-between items-center">
                  <span className="font-medium text-gray-700 dark:text-gray-300">Ingreso total neto</span>
                  <span className={`text-xl font-bold ${yr.total_income >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                    {yr.total_income >= 0 ? '+' : ''}{formatCurrency(yr.total_income)}
                  </span>
                </div>
              </div>
            )}
          </div>
        )
      })()}

      {/* Performance Metrics */}
      {metrics && (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 mb-8">
          {/* ── P&L Resumen ─────────────────────────────────────────────── */}
          <div className="bg-gradient-to-br from-blue-50 to-blue-100 overflow-hidden shadow rounded-lg p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-1">P&amp;L Portafolio</h3>
            <p className="text-xs text-gray-500 mb-4">Posiciones actuales + historial completo</p>

            {/* Unrealized */}
            <div className="mb-3 pb-3 border-b border-blue-200">
              <div className="flex justify-between items-baseline">
                <span className="text-sm text-gray-600">No realizado (posiciones abiertas)</span>
                <span className={`text-base font-bold ${metrics.unrealized_pnl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                  {metrics.unrealized_pnl >= 0 ? '+' : ''}{formatCurrency(metrics.unrealized_pnl)}
                </span>
              </div>
              <div className="flex justify-between items-baseline mt-1">
                <span className="text-xs text-gray-400">
                  {formatCurrency(metrics.current_value)} valor actual · {formatCurrency(metrics.total_invested)} invertido
                </span>
                <span className={`text-xs font-medium ${metrics.roi_unrealized >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                  {metrics.roi_unrealized >= 0 ? '+' : ''}{metrics.roi_unrealized.toFixed(2)}%
                </span>
              </div>
            </div>

            {/* Premiums */}
            <div className="mb-3 pb-3 border-b border-blue-200">
              <div className="flex justify-between items-baseline">
                <span className="text-sm text-gray-600">Premiums netos (opciones)</span>
                <span className={`text-base font-bold ${metrics.total_premium >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                  {metrics.total_premium >= 0 ? '+' : ''}{formatCurrency(metrics.total_premium)}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-1">Todas las posiciones, históricas y actuales</p>
            </div>

            {/* Realized stocks */}
            <div className="mb-4 pb-3 border-b border-blue-200">
              <div className="flex justify-between items-baseline">
                <span className="text-sm text-gray-600">Realizado en acciones (ventas)</span>
                <span className={`text-base font-bold ${metrics.realized_stock_pnl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                  {metrics.realized_stock_pnl >= 0 ? '+' : ''}{formatCurrency(metrics.realized_stock_pnl)}
                </span>
              </div>
              <p className="text-xs text-gray-400 mt-1">Ganancias/pérdidas de acciones vendidas</p>
            </div>

            {/* Net total */}
            <div className="bg-white rounded-lg px-4 py-3 flex justify-between items-center">
              <div>
                <p className="text-sm font-semibold text-gray-700">P&amp;L Neto Total</p>
                <p className="text-xs text-gray-400">
                  ROI sobre {formatCurrency(metrics.total_capital_deployed)} capital desplegado
                </p>
              </div>
              <div className="text-right">
                <p className={`text-xl font-bold ${metrics.net_total_pnl >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                  {metrics.net_total_pnl >= 0 ? '+' : ''}{formatCurrency(metrics.net_total_pnl)}
                </p>
                <p className={`text-sm font-semibold ${metrics.roi_net_total >= 0 ? 'text-green-600' : 'text-red-500'}`}>
                  {metrics.roi_net_total >= 0 ? '+' : ''}{metrics.roi_net_total.toFixed(2)}%
                </p>
              </div>
            </div>
          </div>

          {/* ── Mejor y Peor Posición ────────────────────────────────────── */}
          <div className="bg-white overflow-hidden shadow rounded-lg p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-1">Mejor y Peor Posición</h3>
            <p className="text-xs text-gray-500 mb-4">Rendimiento vs. costo base ajustado por premiums recibidos</p>
            {metrics.best_position && (
              <div className="mb-4 pb-4 border-b border-gray-100">
                <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Mejor</p>
                <p className="text-lg font-bold text-green-600">
                  {metrics.best_position.ticker} +{metrics.best_position.pnl_pct.toFixed(2)}%
                </p>
                <p className="text-sm text-gray-500">{formatCurrency(metrics.best_position.pnl)} no realizado</p>
                <p className="text-xs text-gray-400 mt-1">
                  {metrics.best_position.shares} acc · precio actual {formatCurrency(metrics.best_position.current_price)} · costo ajustado {formatCurrency(metrics.best_position.adjusted_cost_basis)}
                </p>
              </div>
            )}
            {metrics.worst_position && (
              <div>
                <p className="text-xs uppercase tracking-wide text-gray-400 mb-1">Peor</p>
                <p className="text-lg font-bold text-red-600">
                  {metrics.worst_position.ticker} {metrics.worst_position.pnl_pct.toFixed(2)}%
                </p>
                <p className="text-sm text-gray-500">{formatCurrency(metrics.worst_position.pnl)} no realizado</p>
                <p className="text-xs text-gray-400 mt-1">
                  {metrics.worst_position.shares} acc · precio actual {formatCurrency(metrics.worst_position.current_price)} · costo ajustado {formatCurrency(metrics.worst_position.adjusted_cost_basis)}
                </p>
              </div>
            )}
            <div className="mt-6 pt-4 border-t border-gray-100 grid grid-cols-2 gap-3">
              <div className="bg-gray-50 rounded p-3 text-center">
                <p className="text-xs text-gray-500">Posiciones activas</p>
                <p className="text-xl font-bold text-gray-800">{metrics.total_positions}</p>
              </div>
              <div className="bg-gray-50 rounded p-3 text-center">
                <p className="text-xs text-gray-500">Opciones abiertas</p>
                <p className="text-xl font-bold text-gray-800">{metrics.active_options}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* P&L por Posición */}
      {positionsPnL.length > 0 && <PositionsPnLChart data={positionsPnL} />}

      {/* Advanced Metrics Section */}
      {advancedMetrics && !advancedMetrics.error && (
        <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">Estadísticas de Trading</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
                Basado en {advancedMetrics.total_trades} trades cerrados ({advancedMetrics.option_trades} opciones · {advancedMetrics.stock_trades} acciones)
              </p>
            </div>
            <select
              value={metricsDays}
              onChange={(e) => setMetricsDays(parseInt(e.target.value))}
              className="px-3 py-1 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded text-sm"
            >
              <option value="30">30 días</option>
              <option value="90">90 días</option>
              <option value="180">6 meses</option>
              <option value="365">1 año</option>
              <option value="730">2 años</option>
              <option value="1825">5 años</option>
            </select>
          </div>

          {/* Row 1: main stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Win Rate</p>
              <p className={`text-3xl font-bold ${advancedMetrics.win_rate >= 50 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                {advancedMetrics.win_rate.toFixed(1)}%
              </p>
              <p className="text-xs text-gray-400 mt-1">
                {advancedMetrics.winning_trades}G · {advancedMetrics.losing_trades}P
                {advancedMetrics.breakeven_trades > 0 && ` · ${advancedMetrics.breakeven_trades}E`}
              </p>
            </div>

            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">P&L Realizado Total</p>
              <p className={`text-3xl font-bold ${advancedMetrics.total_realized_pnl >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                {formatCurrency(advancedMetrics.total_realized_pnl)}
              </p>
              <p className="text-xs text-gray-400 mt-1">
                Opc: {formatCurrency(advancedMetrics.option_pnl)} · Acc: {formatCurrency(advancedMetrics.stock_pnl)}
              </p>
            </div>

            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Expectancy por Trade</p>
              <p className={`text-3xl font-bold ${advancedMetrics.expectancy >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                {formatCurrency(advancedMetrics.expectancy)}
              </p>
              <p className="text-xs text-gray-400 mt-1">Promedio de ganancia esperada</p>
            </div>

            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Profit Factor</p>
              <p className={`text-3xl font-bold ${(advancedMetrics.profit_factor ?? 0) > 1 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                {advancedMetrics.profit_factor !== null ? `${advancedMetrics.profit_factor.toFixed(2)}x` : '—'}
              </p>
              <p className="text-xs text-gray-400 mt-1">
                {advancedMetrics.profit_factor === null ? 'Sin pérdidas' :
                  advancedMetrics.profit_factor > 2 ? '🔥 Excelente (>2)' :
                  advancedMetrics.profit_factor > 1 ? '✅ Rentable (>1)' : '⚠️ Por mejorar'}
              </p>
            </div>
          </div>

          {/* Row 2: avg win/loss + streaks */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4 border border-green-100 dark:border-green-800">
              <p className="text-xs text-green-700 dark:text-green-400 mb-1">Ganancia promedio</p>
              <p className="text-2xl font-bold text-green-700 dark:text-green-300">+{formatCurrency(advancedMetrics.avg_win)}</p>
              <p className="text-xs text-green-600 dark:text-green-500 mt-1">{advancedMetrics.winning_trades} trades ganadores</p>
            </div>

            <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-4 border border-red-100 dark:border-red-800">
              <p className="text-xs text-red-700 dark:text-red-400 mb-1">Pérdida promedio</p>
              <p className="text-2xl font-bold text-red-700 dark:text-red-300">{formatCurrency(advancedMetrics.avg_loss)}</p>
              <p className="text-xs text-red-600 dark:text-red-500 mt-1">{advancedMetrics.losing_trades} trades perdedores</p>
            </div>

            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">Duración promedio</p>
              <p className="text-2xl font-bold text-gray-800 dark:text-gray-100">
                {advancedMetrics.avg_duration_days !== null ? `${advancedMetrics.avg_duration_days}d` : '—'}
              </p>
              <p className="text-xs text-gray-400 mt-1">Por trade cerrado</p>
            </div>

            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Rachas máximas</p>
              <div className="flex justify-between">
                <div>
                  <p className="text-xs text-green-500">Ganadoras</p>
                  <p className="text-xl font-bold text-green-600 dark:text-green-400">{advancedMetrics.max_consec_wins}</p>
                </div>
                <div className="text-right">
                  <p className="text-xs text-red-500">Perdedoras</p>
                  <p className="text-xl font-bold text-red-500">{advancedMetrics.max_consec_losses}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Row 3: best / worst trade */}
          {(advancedMetrics.best_trade || advancedMetrics.worst_trade) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {advancedMetrics.best_trade && (
                <div className="flex items-center gap-4 bg-green-50 dark:bg-green-900/20 rounded-lg p-4 border border-green-100 dark:border-green-800">
                  <div className="text-2xl">🏆</div>
                  <div>
                    <p className="text-xs text-green-700 dark:text-green-400 uppercase tracking-wide mb-0.5">Mejor trade</p>
                    <p className="font-bold text-green-800 dark:text-green-200">
                      {advancedMetrics.best_trade.ticker}
                      <span className="text-xs font-normal text-green-600 ml-2">({advancedMetrics.best_trade.type})</span>
                    </p>
                    <p className="text-lg font-bold text-green-700 dark:text-green-300">+{formatCurrency(advancedMetrics.best_trade.pnl)}</p>
                  </div>
                </div>
              )}
              {advancedMetrics.worst_trade && (
                <div className="flex items-center gap-4 bg-red-50 dark:bg-red-900/20 rounded-lg p-4 border border-red-100 dark:border-red-800">
                  <div className="text-2xl">📉</div>
                  <div>
                    <p className="text-xs text-red-700 dark:text-red-400 uppercase tracking-wide mb-0.5">Peor trade</p>
                    <p className="font-bold text-red-800 dark:text-red-200">
                      {advancedMetrics.worst_trade.ticker}
                      <span className="text-xs font-normal text-red-600 ml-2">({advancedMetrics.worst_trade.type})</span>
                    </p>
                    <p className="text-lg font-bold text-red-700 dark:text-red-300">{formatCurrency(advancedMetrics.worst_trade.pnl)}</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Allocation Chart */}
        <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
          <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-4">Portfolio Allocation</h3>
          {allocation && allocation.allocation.length > 0 ? (
            <>
              <AllocationChart data={allocation.allocation} height={350} />
              <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  Total Portfolio Value: <span className="font-semibold text-gray-900 dark:text-gray-100">{formatCurrency(allocation.total_value)}</span>
                </p>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-500">
              No hay posiciones en el portafolio
            </div>
          )}
        </div>

        {/* Premium Timeline Chart */}
        <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6">
          <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100 mb-4">Timeline de Primas</h3>
          {premiumTimeline.length > 0 ? (
            <>
              <PremiumChart data={premiumTimeline} height={350} />
              <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 flex justify-between">
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Bruto cobrado: <span className="font-semibold text-gray-700 dark:text-gray-200">
                    {formatCurrency(premiumTimeline.reduce((sum, item) => sum + item.total, 0))}
                  </span>
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Prima neta (últimos 3 meses): <span className="font-semibold text-green-600 dark:text-green-400">
                    {formatCurrency(premiumTimeline.reduce((sum, item) => sum + item.net, 0))}
                  </span>
                </p>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-500">
              No hay datos de premiums
            </div>
          )}
        </div>
      </div>

      {/* ── Covered Calls por Ticker ───────────────────────────────── */}
      {ccByTicker && ccByTicker.by_ticker.length > 0 && (
        <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">🎯 Covered Calls por Ticker</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Primas cobradas vs cierres por subyacente</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-400 uppercase tracking-wide">Prima neta total</p>
              <p className="text-2xl font-bold text-green-600 dark:text-green-400">
                {formatCurrency(ccByTicker.total_prima_neta)}
              </p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 text-xs uppercase tracking-wide">
                  <th className="text-left py-2 pr-4">Ticker</th>
                  <th className="text-right py-2 px-3">Primas cobradas</th>
                  <th className="text-right py-2 px-3">Cierres</th>
                  <th className="text-right py-2 px-3">Prima neta</th>
                  <th className="text-right py-2 px-3">Capital</th>
                  <th className="text-right py-2 px-3">Yield</th>
                  <th className="text-right py-2 pl-3">Trades</th>
                </tr>
              </thead>
              <tbody>
                {ccByTicker.by_ticker.map(row => (
                  <tr key={row.ticker} className="border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                    <td className="py-3 pr-4 font-bold text-gray-900 dark:text-gray-100">{row.ticker}</td>
                    <td className="py-3 px-3 text-right text-green-600 dark:text-green-400">{formatCurrency(row.primas_cobradas)}</td>
                    <td className="py-3 px-3 text-right text-red-500">{row.cierres > 0 ? `-${formatCurrency(row.cierres)}` : '—'}</td>
                    <td className={`py-3 px-3 text-right font-semibold ${row.prima_neta >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500'}`}>
                      {formatCurrency(row.prima_neta)}
                    </td>
                    <td className="py-3 px-3 text-right text-gray-600 dark:text-gray-300">
                      {row.capital > 0 ? formatCurrency(row.capital) : '—'}
                    </td>
                    <td className={`py-3 px-3 text-right font-semibold ${row.yield_pct >= 0 ? 'text-blue-600 dark:text-blue-400' : 'text-red-500'}`}>
                      {row.capital > 0 ? `${row.yield_pct.toFixed(1)}%` : '—'}
                    </td>
                    <td className="py-3 pl-3 text-right text-gray-500 dark:text-gray-400">
                      {row.n_ventas}v / {row.n_cierres}c
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-gray-300 dark:border-gray-600 font-semibold">
                  <td className="py-2 pr-4 text-gray-700 dark:text-gray-300">Total</td>
                  <td className="py-2 px-3 text-right text-green-600 dark:text-green-400">{formatCurrency(ccByTicker.total_primas_cobradas)}</td>
                  <td className="py-2 px-3 text-right text-red-500">{ccByTicker.total_cierres > 0 ? `-${formatCurrency(ccByTicker.total_cierres)}` : '—'}</td>
                  <td className="py-2 px-3 text-right text-green-600 dark:text-green-400">{formatCurrency(ccByTicker.total_prima_neta)}</td>
                  <td colSpan={3} />
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}

      {/* Covered Call Cycles — rendimiento anualizado por ciclo */}
      <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">Rendimiento por Ciclo de Covered Call</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Rendimiento anualizado capturado en cada apertura / roll de opción vendida
            </p>
          </div>
          <span className="text-2xl">📈</span>
        </div>
        <CoveredCallCycles />
      </div>
    </div>
  )
}

export default Dashboard
