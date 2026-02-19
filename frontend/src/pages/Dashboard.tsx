import { useEffect, useState } from 'react'
import api from '../services/api'
import ExpirationAlerts from '../components/ExpirationAlerts'
import PortfolioChart from '../components/PortfolioChart'
import AllocationChart from '../components/AllocationChart'
import PremiumChart from '../components/PremiumChart'
import BenchmarkChart from '../components/BenchmarkChart'
import { PortfolioHistory, AllocationResponse, PremiumTimelineData, PerformanceMetrics, BenchmarkComparison } from '../types'

interface DashboardSummary {
  total_stocks: number
  total_invested: number
  current_portfolio_value: number
  total_premium_earned: number
  open_options: number
  realized_pnl: number
  unrealized_pnl: number
  total_pnl: number
  total_pnl_pct: number
}

interface AdvancedMetrics {
  period_days: number
  total_return: number
  annual_return: number
  volatility: number
  sharpe_ratio: number
  sortino_ratio: number
  max_drawdown: number
  max_drawdown_pct: number
  calmar_ratio: number
  win_rate: number
  avg_win: number
  avg_loss: number
  profit_factor: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  risk_free_rate: number
  error?: string
}

function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [portfolioHistory, setPortfolioHistory] = useState<PortfolioHistory[]>([])
  const [allocation, setAllocation] = useState<AllocationResponse | null>(null)
  const [premiumTimeline, setPremiumTimeline] = useState<PremiumTimelineData[]>([])
  const [metrics, setMetrics] = useState<PerformanceMetrics | null>(null)
  const [benchmark, setBenchmark] = useState<BenchmarkComparison | null>(null)
  const [advancedMetrics, setAdvancedMetrics] = useState<AdvancedMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [chartDays, setChartDays] = useState(30)
  const [metricsDays, setMetricsDays] = useState(365)

  useEffect(() => {
    fetchSummary()
    fetchAnalytics()
    // Actualizar cada 30 segundos
    const interval = setInterval(() => {
      fetchSummary()
      fetchAnalytics()
    }, 30000)
    return () => clearInterval(interval)
  }, [chartDays])

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
    const [historyRes, allocationRes, premiumRes, metricsRes, benchmarkRes, advancedRes] = await Promise.allSettled([
      api.get<PortfolioHistory[]>(`/api/analytics/portfolio-history?days=${chartDays}`),
      api.get<AllocationResponse>('/api/analytics/allocation'),
      api.get<PremiumTimelineData[]>('/api/analytics/premium-timeline?days=90'),
      api.get<PerformanceMetrics>('/api/analytics/performance-metrics'),
      api.get<BenchmarkComparison>(`/api/analytics/benchmark-comparison?days=${chartDays}`),
      api.get<AdvancedMetrics>(`/api/analytics/advanced-metrics?days=${metricsDays}`)
    ])

    if (historyRes.status === 'fulfilled') setPortfolioHistory(historyRes.value.data)
    else console.error('portfolio-history error:', historyRes.reason)

    if (allocationRes.status === 'fulfilled') setAllocation(allocationRes.value.data)
    else console.error('allocation error:', allocationRes.reason)

    if (premiumRes.status === 'fulfilled') setPremiumTimeline(premiumRes.value.data)
    else console.error('premium-timeline error:', premiumRes.reason)

    if (metricsRes.status === 'fulfilled') setMetrics(metricsRes.value.data)
    else console.error('performance-metrics error:', metricsRes.reason)

    if (benchmarkRes.status === 'fulfilled') setBenchmark(benchmarkRes.value.data)
    else console.error('benchmark-comparison error:', benchmarkRes.reason)

    if (advancedRes.status === 'fulfilled') setAdvancedMetrics(advancedRes.value.data)
    else console.error('advanced-metrics error:', advancedRes.reason)
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
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="flex justify-between items-center mb-6">
        <h2 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Dashboard</h2>
        <div className="flex gap-2">
          <button 
            onClick={handleExportPortfolio}
            className="text-sm px-3 py-2 bg-green-600 text-white rounded hover:bg-green-700 dark:bg-green-700 dark:hover:bg-green-800 font-medium flex items-center gap-1"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export Portfolio
          </button>
          <button 
            onClick={handleExportTaxReport}
            className="text-sm px-3 py-2 bg-purple-600 text-white rounded hover:bg-purple-700 dark:bg-purple-700 dark:hover:bg-purple-800 font-medium flex items-center gap-1"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Tax Report
          </button>
          <button 
            onClick={fetchSummary}
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

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-1">
                <dt className="text-sm font-medium text-gray-500 truncate">Primas Ganadas</dt>
                <dd className="mt-1 text-3xl font-semibold text-green-600">
                  {formatCurrency(summary?.total_premium_earned)}
                </dd>
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg">
          <div className="p-5">
            <div className="flex items-center">
              <div className="flex-1">
                <dt className="text-sm font-medium text-gray-500 truncate">P&L Total</dt>
                <dd className={`mt-1 text-3xl font-semibold ${(summary?.total_pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {formatCurrency(summary?.total_pnl)}
                </dd>
                <dd className={`text-sm ${(summary?.total_pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {summary?.total_pnl_pct !== undefined ? `${summary.total_pnl_pct >= 0 ? '+' : ''}${summary.total_pnl_pct.toFixed(2)}%` : '0.00%'}
                </dd>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Additional Stats */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-3 mb-8">
        <div className="bg-white overflow-hidden shadow rounded-lg p-5">
          <dt className="text-sm font-medium text-gray-500">Posiciones Activas</dt>
          <dd className="mt-1 text-2xl font-semibold text-gray-900">{summary?.total_stocks || 0}</dd>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg p-5">
          <dt className="text-sm font-medium text-gray-500">Opciones Abiertas</dt>
          <dd className="mt-1 text-2xl font-semibold text-gray-900">{summary?.open_options || 0}</dd>
        </div>

        <div className="bg-white overflow-hidden shadow rounded-lg p-5">
          <dt className="text-sm font-medium text-gray-500">P&L Realizado</dt>
          <dd className={`mt-1 text-2xl font-semibold ${(summary?.realized_pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
            {formatCurrency(summary?.realized_pnl)}
          </dd>
        </div>
      </div>

      {/* Performance Metrics */}
      {metrics && (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 mb-8">
          <div className="bg-gradient-to-br from-blue-50 to-blue-100 overflow-hidden shadow rounded-lg p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">ROI Total</h3>
            <div className="text-4xl font-bold text-blue-600 mb-2">
              {metrics.roi >= 0 ? '+' : ''}{metrics.roi.toFixed(2)}%
            </div>
            <p className="text-sm text-gray-600">
              {formatCurrency(metrics.total_pnl)} de ganancia/pérdida
            </p>
          </div>

          <div className="bg-white overflow-hidden shadow rounded-lg p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">Mejor y Peor Posición</h3>
            {metrics.best_position && (
              <div className="mb-3">
                <p className="text-sm text-gray-600">Mejor:</p>
                <p className="text-lg font-bold text-green-600">
                  {metrics.best_position.ticker} +{metrics.best_position.pnl_pct.toFixed(2)}%
                </p>
                <p className="text-sm text-gray-500">{formatCurrency(metrics.best_position.pnl)}</p>
              </div>
            )}
            {metrics.worst_position && (
              <div>
                <p className="text-sm text-gray-600">Peor:</p>
                <p className="text-lg font-bold text-red-600">
                  {metrics.worst_position.ticker} {metrics.worst_position.pnl_pct.toFixed(2)}%
                </p>
                <p className="text-sm text-gray-500">{formatCurrency(metrics.worst_position.pnl)}</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Portfolio Performance Chart */}
      <div className="bg-white shadow rounded-lg p-6 mb-8">
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-xl font-bold text-gray-900">Portfolio Performance</h3>
          <div className="flex gap-2">
            <button
              onClick={() => setChartDays(7)}
              className={`px-3 py-1 text-sm rounded ${chartDays === 7 ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
            >
              7D
            </button>
            <button
              onClick={() => setChartDays(30)}
              className={`px-3 py-1 text-sm rounded ${chartDays === 30 ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
            >
              30D
            </button>
            <button
              onClick={() => setChartDays(90)}
              className={`px-3 py-1 text-sm rounded ${chartDays === 90 ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
            >
              90D
            </button>
            <button
              onClick={() => setChartDays(365)}
              className={`px-3 py-1 text-sm rounded ${chartDays === 365 ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}
            >
              1Y
            </button>
          </div>
        </div>
        {portfolioHistory.length > 0 ? (
          <PortfolioChart data={portfolioHistory} height={400} />
        ) : (
          <div className="flex items-center justify-center h-64 text-gray-500">
            No hay datos suficientes para mostrar el gráfico
          </div>
        )}
      </div>

      {/* Benchmark Comparison */}
      {benchmark && (
        <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">Performance vs S&P 500</h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                Benchmark comparison over {benchmark.period_days} days
              </p>
            </div>
            <div className={`px-4 py-2 rounded-lg ${benchmark.summary.beat_market ? 'bg-green-100 dark:bg-green-900' : 'bg-red-100 dark:bg-red-900'}`}>
              <p className="text-xs font-medium text-gray-600 dark:text-gray-300">Outperformance</p>
              <p className={`text-2xl font-bold ${benchmark.summary.beat_market ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                {benchmark.summary.outperformance >= 0 ? '+' : ''}{benchmark.summary.outperformance.toFixed(2)}%
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4">
              <p className="text-sm text-gray-600 dark:text-gray-400">Your Portfolio</p>
              <p className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                {benchmark.summary.portfolio_total_return >= 0 ? '+' : ''}{benchmark.summary.portfolio_total_return.toFixed(2)}%
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {formatCurrency(benchmark.summary.portfolio_final_value)}
              </p>
            </div>
            <div className="bg-amber-50 dark:bg-amber-900/20 rounded-lg p-4">
              <p className="text-sm text-gray-600 dark:text-gray-400">S&P 500</p>
              <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">
                {benchmark.summary.sp500_total_return >= 0 ? '+' : ''}{benchmark.summary.sp500_total_return.toFixed(2)}%
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {formatCurrency(benchmark.summary.sp500_final_value)}
              </p>
            </div>
            <div className={`rounded-lg p-4 ${benchmark.summary.beat_market ? 'bg-green-50 dark:bg-green-900/20' : 'bg-gray-50 dark:bg-gray-700'}`}>
              <p className="text-sm text-gray-600 dark:text-gray-400">Status</p>
              <p className={`text-lg font-bold ${benchmark.summary.beat_market ? 'text-green-600 dark:text-green-400' : 'text-gray-600 dark:text-gray-400'}`}>
                {benchmark.summary.beat_market ? '🎉 Beating Market' : '📉 Underperforming'}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {benchmark.summary.beat_market ? 'Keep it up!' : 'Stay focused'}
              </p>
            </div>
          </div>

          {benchmark.data.length > 0 ? (
            <BenchmarkChart data={benchmark.data} height={350} />
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-500 dark:text-gray-400">
              No hay datos suficientes para comparación
            </div>
          )}
        </div>
      )}

      {/* Advanced Metrics Section */}
      {advancedMetrics && !advancedMetrics.error && (
        <div className="bg-white dark:bg-gray-800 shadow rounded-lg p-6 mb-8">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-xl font-bold text-gray-900 dark:text-gray-100">Advanced Metrics</h3>
            <select
              value={metricsDays}
              onChange={(e) => setMetricsDays(parseInt(e.target.value))}
              className="px-3 py-1 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded text-sm"
            >
              <option value="30">30 days</option>
              <option value="90">90 days</option>
              <option value="180">6 months</option>
              <option value="365">1 year</option>
              <option value="730">2 years</option>
            </select>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {/* Risk-Adjusted Returns */}
            <div className="bg-gradient-to-br from-blue-50 to-blue-100 dark:from-blue-900/20 dark:to-blue-800/20 rounded-lg p-4 border border-blue-200 dark:border-blue-800">
              <p className="text-sm text-blue-700 dark:text-blue-400 font-medium mb-1">Sharpe Ratio</p>
              <p className="text-3xl font-bold text-blue-900 dark:text-blue-100">{advancedMetrics.sharpe_ratio.toFixed(2)}</p>
              <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
                {advancedMetrics.sharpe_ratio > 1 ? '✅ Excellent' : advancedMetrics.sharpe_ratio > 0.5 ? '👍 Good' : '⚠️ Poor'}
              </p>
            </div>

            <div className="bg-gradient-to-br from-purple-50 to-purple-100 dark:from-purple-900/20 dark:to-purple-800/20 rounded-lg p-4 border border-purple-200 dark:border-purple-800">
              <p className="text-sm text-purple-700 dark:text-purple-400 font-medium mb-1">Sortino Ratio</p>
              <p className="text-3xl font-bold text-purple-900 dark:text-purple-100">{advancedMetrics.sortino_ratio.toFixed(2)}</p>
              <p className="text-xs text-purple-600 dark:text-purple-400 mt-1">Downside risk adjusted</p>
            </div>

            <div className="bg-gradient-to-br from-red-50 to-red-100 dark:from-red-900/20 dark:to-red-800/20 rounded-lg p-4 border border-red-200 dark:border-red-800">
              <p className="text-sm text-red-700 dark:text-red-400 font-medium mb-1">Max Drawdown</p>
              <p className="text-3xl font-bold text-red-900 dark:text-red-100">-{advancedMetrics.max_drawdown_pct.toFixed(1)}%</p>
              <p className="text-xs text-red-600 dark:text-red-400 mt-1">{formatCurrency(advancedMetrics.max_drawdown)}</p>
            </div>

            <div className="bg-gradient-to-br from-amber-50 to-amber-100 dark:from-amber-900/20 dark:to-amber-800/20 rounded-lg p-4 border border-amber-200 dark:border-amber-800">
              <p className="text-sm text-amber-700 dark:text-amber-400 font-medium mb-1">Calmar Ratio</p>
              <p className="text-3xl font-bold text-amber-900 dark:text-amber-100">{advancedMetrics.calmar_ratio.toFixed(2)}</p>
              <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">Return/Drawdown</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {/* Performance Stats */}
            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Total Return</p>
              <p className={`text-2xl font-bold ${advancedMetrics.total_return >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                {advancedMetrics.total_return >= 0 ? '+' : ''}{advancedMetrics.total_return.toFixed(2)}%
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{advancedMetrics.period_days} days</p>
            </div>

            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Annual Return</p>
              <p className={`text-2xl font-bold ${advancedMetrics.annual_return >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                {advancedMetrics.annual_return >= 0 ? '+' : ''}{advancedMetrics.annual_return.toFixed(2)}%
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Annualized</p>
            </div>

            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Volatility</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">{advancedMetrics.volatility.toFixed(1)}%</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">Annual volatility</p>
            </div>

            <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-4">
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-1">Win Rate</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">{advancedMetrics.win_rate.toFixed(1)}%</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                {advancedMetrics.winning_trades}W / {advancedMetrics.losing_trades}L
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4 border border-green-200 dark:border-green-800">
              <p className="text-sm text-green-700 dark:text-green-400 mb-1">Avg Win</p>
              <p className="text-xl font-bold text-green-900 dark:text-green-100">{formatCurrency(advancedMetrics.avg_win)}</p>
            </div>

            <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-4 border border-red-200 dark:border-red-800">
              <p className="text-sm text-red-700 dark:text-red-400 mb-1">Avg Loss</p>
              <p className="text-xl font-bold text-red-900 dark:text-red-100">{formatCurrency(advancedMetrics.avg_loss)}</p>
            </div>

            <div className="bg-indigo-50 dark:bg-indigo-900/20 rounded-lg p-4 border border-indigo-200 dark:border-indigo-800">
              <p className="text-sm text-indigo-700 dark:text-indigo-400 mb-1">Profit Factor</p>
              <p className="text-xl font-bold text-indigo-900 dark:text-indigo-100">{advancedMetrics.profit_factor.toFixed(2)}x</p>
              <p className="text-xs text-indigo-600 dark:text-indigo-400 mt-1">
                {advancedMetrics.profit_factor > 2 ? '🔥 Excellent' : advancedMetrics.profit_factor > 1 ? '✅ Profitable' : '⚠️ Needs work'}
              </p>
            </div>
          </div>

          <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
            <p className="text-xs text-blue-700 dark:text-blue-400">
              <span className="font-semibold">Note:</span> Sharpe & Sortino ratios use {advancedMetrics.risk_free_rate}% risk-free rate. 
              Total trades analyzed: {advancedMetrics.total_trades}. Metrics based on {advancedMetrics.period_days} days of data.
            </p>
          </div>
        </div>
      )}

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        {/* Allocation Chart */}
        <div className="bg-white shadow rounded-lg p-6">
          <h3 className="text-xl font-bold text-gray-900 mb-4">Portfolio Allocation</h3>
          {allocation && allocation.allocation.length > 0 ? (
            <>
              <AllocationChart data={allocation.allocation} height={350} />
              <div className="mt-4 pt-4 border-t border-gray-200">
                <p className="text-sm text-gray-600">
                  Total Portfolio Value: <span className="font-semibold text-gray-900">{formatCurrency(allocation.total_value)}</span>
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
        <div className="bg-white shadow rounded-lg p-6">
          <h3 className="text-xl font-bold text-gray-900 mb-4">Premium Income Timeline</h3>
          {premiumTimeline.length > 0 ? (
            <>
              <PremiumChart data={premiumTimeline} height={350} />
              <div className="mt-4 pt-4 border-t border-gray-200">
                <p className="text-sm text-gray-600">
                  Total Premium (Last 3 months): <span className="font-semibold text-green-600">
                    {formatCurrency(premiumTimeline.reduce((sum, item) => sum + item.total, 0))}
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
    </div>
  )
}

export default Dashboard
