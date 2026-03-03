import { useEffect, useState } from 'react'
import api from '../services/api'
import { Transaction, TransactionsResponse, TransactionSummary } from '../types'

function Transactions() {
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [summary, setSummary] = useState<TransactionSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({
    ticker: '',
    transaction_type: '',
    start_date: '',
    end_date: ''
  })
  const [pagination, setPagination] = useState({
    skip: 0,
    limit: 50,
    total: 0
  })

  useEffect(() => {
    fetchTransactions()
    fetchSummary()
  }, [pagination.skip, filters])

  const fetchTransactions = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams({
        skip: pagination.skip.toString(),
        limit: pagination.limit.toString(),
        ...(filters.ticker && { ticker: filters.ticker }),
        ...(filters.transaction_type && { transaction_type: filters.transaction_type }),
        ...(filters.start_date && { start_date: filters.start_date }),
        ...(filters.end_date && { end_date: filters.end_date })
      })

      const response = await api.get<TransactionsResponse>(`/api/transactions?${params}`)
      setTransactions(response.data.transactions)
      setPagination(prev => ({ ...prev, total: response.data.total }))
    } catch (error) {
      console.error('Error fetching transactions:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchSummary = async () => {
    try {
      const response = await api.get<TransactionSummary>('/api/transactions/summary')
      setSummary(response.data)
    } catch (error) {
      console.error('Error fetching summary:', error)
    }
  }

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value)
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const getTransactionTypeLabel = (type: string) => {
    const labels: { [key: string]: string } = {
      'BUY_STOCK': 'Buy Stock',
      'SELL_STOCK': 'Sell Stock',
      'SELL_CALL': 'Sell Call',
      'BUY_CALL': 'Buy Call',
      'SELL_PUT': 'Sell Put',
      'BUY_PUT': 'Buy Put',
      'ASSIGNMENT': 'Assignment',
      'DIVIDEND': 'Dividend'
    }
    return labels[type] || type
  }

  const getTransactionTypeColor = (type: string) => {
    const colors: { [key: string]: string } = {
      'BUY_STOCK': 'text-red-600 bg-red-50',
      'SELL_STOCK': 'text-green-600 bg-green-50',
      'SELL_CALL': 'text-green-600 bg-green-50',
      'BUY_CALL': 'text-red-600 bg-red-50',
      'SELL_PUT': 'text-green-600 bg-green-50',
      'BUY_PUT': 'text-red-600 bg-red-50',
      'ASSIGNMENT': 'text-purple-600 bg-purple-50',
      'DIVIDEND': 'text-blue-600 bg-blue-50'
    }
    return colors[type] || 'text-gray-600 bg-gray-50'
  }

  const handleFilterChange = (field: string, value: string) => {
    setFilters(prev => ({ ...prev, [field]: value }))
    setPagination(prev => ({ ...prev, skip: 0 })) // Reset pagination
  }

  const clearFilters = () => {
    setFilters({
      ticker: '',
      transaction_type: '',
      start_date: '',
      end_date: ''
    })
  }

  const handleExportCSV = async () => {
    try {
      const params = new URLSearchParams({
        ...(filters.start_date && { start_date: filters.start_date }),
        ...(filters.end_date && { end_date: filters.end_date })
      })

      const response = await api.get(`/api/exports/transactions/csv?${params}`, {
        responseType: 'blob'
      })

      // Crear un enlace temporal para descargar
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `kover_transactions_${new Date().toISOString().split('T')[0]}.csv`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Error exporting CSV:', error)
      alert('Error al exportar CSV. Por favor intenta de nuevo.')
    }
  }

  const nextPage = () => {
    if (pagination.skip + pagination.limit < pagination.total) {
      setPagination(prev => ({ ...prev, skip: prev.skip + prev.limit }))
    }
  }

  const prevPage = () => {
    if (pagination.skip > 0) {
      setPagination(prev => ({ ...prev, skip: Math.max(0, prev.skip - prev.limit) }))
    }
  }

  if (loading && transactions.length === 0) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <div className="text-xl text-gray-600">Loading transactions...</div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Historial de Transacciones</h1>
          <p className="page-subtitle">Registro completo de tu actividad de trading</p>
        </div>
        <button
          onClick={handleExportCSV}
          className="btn btn-sm bg-green-600 hover:bg-green-700 text-white"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          Export CSV
        </button>
      </div>

      {summary && (
        <div className="space-y-4 mb-6">
          {/* Fila 1: Vista actual (igual que dashboard) */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Total Operaciones</p>
              <p className="text-2xl font-bold text-gray-800 dark:text-gray-100">{summary.total_transactions}</p>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Capital Activo</p>
              <p className="text-sm text-gray-400 mb-1">Posiciones abiertas actuales</p>
              <p className="text-2xl font-bold text-blue-600">{formatCurrency(summary.current_invested)}</p>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Primas Netas</p>
              <p className="text-sm text-gray-400 mb-1">
                Cobradas {formatCurrency(summary.premium_collected)} &minus; Pagadas {formatCurrency(summary.premium_paid)}
              </p>
              <p className="text-2xl font-bold text-green-600">{formatCurrency(summary.net_premium)}</p>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Comisiones Totales</p>
              <p className="text-2xl font-bold text-orange-600">{formatCurrency(summary.total_commissions)}</p>
            </div>
          </div>
          {/* Fila 2: Flujos históricos */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-white rounded-lg shadow p-4">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Total Comprado (Histórico)</p>
              <p className="text-xs text-gray-400 mb-1">Suma de todas las compras, incl. ya vendidas</p>
              <p className="text-2xl font-bold text-red-600">{formatCurrency(summary.stock_buys)}</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Total Vendido (Histórico)</p>
              <p className="text-xs text-gray-400 mb-1">Proceeds de todas las ventas</p>
              <p className="text-2xl font-bold text-green-600">{formatCurrency(summary.stock_sells)}</p>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Flujo Neto de Caja</p>
              <p className="text-xs text-gray-400 mb-1">Lo que salió de tu bolsillo en total</p>
              <p className={`text-2xl font-bold ${summary.stock_buys - summary.stock_sells >= 0 ? 'text-red-600' : 'text-green-600'}`}>
                {formatCurrency(summary.stock_buys - summary.stock_sells)}
              </p>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">Dividendos Cobrados</p>
              <p className="text-2xl font-bold text-blue-500">{formatCurrency(summary.dividends)}</p>
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="bg-white rounded-lg shadow p-4 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Ticker</label>
            <input
              type="text"
              value={filters.ticker}
              onChange={(e) => handleFilterChange('ticker', e.target.value.toUpperCase())}
              placeholder="e.g., AAPL"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
            <select
              value={filters.transaction_type}
              onChange={(e) => handleFilterChange('transaction_type', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All Types</option>
              <option value="BUY_STOCK">Buy Stock</option>
              <option value="SELL_STOCK">Sell Stock</option>
              <option value="SELL_CALL">Sell Call</option>
              <option value="BUY_CALL">Buy Call</option>
              <option value="SELL_PUT">Sell Put</option>
              <option value="BUY_PUT">Buy Put</option>
              <option value="ASSIGNMENT">Assignment</option>
              <option value="DIVIDEND">Dividend</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Start Date</label>
            <input
              type="date"
              value={filters.start_date}
              onChange={(e) => handleFilterChange('start_date', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">End Date</label>
            <input
              type="date"
              value={filters.end_date}
              onChange={(e) => handleFilterChange('end_date', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={clearFilters}
            className="px-4 py-2 text-sm text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors"
          >
            Clear Filters
          </button>
        </div>
      </div>

      {/* Transactions Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Date
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Ticker
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Type
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Quantity
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Price
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Total Amount
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Commission
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Notes
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {transactions.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-6 py-12 text-center text-gray-500">
                    No transactions found. Try adjusting your filters.
                  </td>
                </tr>
              ) : (
                transactions.map((transaction) => (
                  <tr key={transaction.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                      {formatDate(transaction.transaction_date)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm font-medium text-gray-900">{transaction.ticker}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`px-2 py-1 inline-flex text-xs leading-5 font-semibold rounded-full ${getTransactionTypeColor(transaction.transaction_type)}`}>
                        {getTransactionTypeLabel(transaction.transaction_type)}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-900">
                      {transaction.quantity}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-900">
                      {formatCurrency(transaction.price)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right">
                      <span className={transaction.total_amount >= 0 ? 'text-green-600 font-medium' : 'text-red-600 font-medium'}>
                        {formatCurrency(Math.abs(transaction.total_amount))}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-500">
                      {formatCurrency(transaction.commission)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-500">
                      {transaction.notes || '-'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {pagination.total > pagination.limit && (
          <div className="bg-gray-50 px-6 py-4 flex items-center justify-between border-t border-gray-200">
            <div className="text-sm text-gray-700">
              Showing {pagination.skip + 1} to {Math.min(pagination.skip + pagination.limit, pagination.total)} of {pagination.total} transactions
            </div>
            <div className="flex gap-2">
              <button
                onClick={prevPage}
                disabled={pagination.skip === 0}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Previous
              </button>
              <button
                onClick={nextPage}
                disabled={pagination.skip + pagination.limit >= pagination.total}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default Transactions
