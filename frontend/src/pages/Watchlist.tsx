import { useEffect, useState } from 'react'
import api from '../services/api'
import { WatchlistItem, WatchlistCreate } from '../types'

function Watchlist() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingItem, setEditingItem] = useState<WatchlistItem | null>(null)
  const [formData, setFormData] = useState<WatchlistCreate>({
    ticker: '',
    company_name: '',
    target_price: undefined,
    notes: ''
  })
  const [formError, setFormError] = useState('')

  useEffect(() => {
    fetchWatchlist()
    // Actualizar cada 30 segundos
    const interval = setInterval(fetchWatchlist, 30000)
    return () => clearInterval(interval)
  }, [])

  const fetchWatchlist = async () => {
    try {
      const response = await api.get<WatchlistItem[]>('/api/watchlist')
      setWatchlist(response.data)
    } catch (error) {
      console.error('Error fetching watchlist:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError('')

    try {
      if (editingItem) {
        // Actualizar
        await api.put(`/api/watchlist/${editingItem.id}`, {
          company_name: formData.company_name,
          target_price: formData.target_price || null,
          notes: formData.notes
        })
      } else {
        // Crear nuevo
        await api.post('/api/watchlist', {
          ...formData,
          ticker: formData.ticker.toUpperCase(),
          target_price: formData.target_price || null
        })
      }

      // Reset form
      setFormData({
        ticker: '',
        company_name: '',
        target_price: undefined,
        notes: ''
      })
      setShowForm(false)
      setEditingItem(null)
      fetchWatchlist()
    } catch (error: any) {
      setFormError(error.response?.data?.detail || 'Error al guardar el ticker')
    }
  }

  const handleEdit = (item: WatchlistItem) => {
    setEditingItem(item)
    setFormData({
      ticker: item.ticker,
      company_name: item.company_name || '',
      target_price: item.target_price,
      notes: item.notes || ''
    })
    setShowForm(true)
  }

  const handleDelete = async (id: number) => {
    if (!confirm('¿Estás seguro de eliminar este ticker de la watchlist?')) return

    try {
      await api.delete(`/api/watchlist/${id}`)
      fetchWatchlist()
    } catch (error) {
      console.error('Error deleting watchlist item:', error)
    }
  }

  const handleCancel = () => {
    setShowForm(false)
    setEditingItem(null)
    setFormData({
      ticker: '',
      company_name: '',
      target_price: undefined,
      notes: ''
    })
    setFormError('')
  }

  const formatCurrency = (value?: number) => {
    if (value === undefined || value === null) return '-'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value)
  }

  const formatPercent = (value?: number) => {
    if (value === undefined || value === null) return '-'
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  return (
    <div className="container mx-auto p-6 max-w-7xl">
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-800 mb-2">Watchlist</h1>
          <p className="text-gray-600">Track tickers you're interested in</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
        >
          {showForm ? 'Cancel' : '+ Add Ticker'}
        </button>
      </div>

      {/* Form */}
      {showForm && (
        <div className="bg-white rounded-lg shadow p-6 mb-6">
          <h2 className="text-xl font-semibold mb-4">
            {editingItem ? 'Edit Ticker' : 'Add New Ticker'}
          </h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            {formError && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
                {formError}
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Ticker *
                </label>
                <input
                  type="text"
                  required
                  disabled={!!editingItem}
                  value={formData.ticker}
                  onChange={(e) => setFormData({ ...formData, ticker: e.target.value.toUpperCase() })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
                  placeholder="e.g., AAPL"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Company Name
                </label>
                <input
                  type="text"
                  value={formData.company_name}
                  onChange={(e) => setFormData({ ...formData, company_name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g., Apple Inc."
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Target Price
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={formData.target_price || ''}
                  onChange={(e) => setFormData({ ...formData, target_price: e.target.value ? parseFloat(e.target.value) : undefined })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="150.00"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Notes
                </label>
                <input
                  type="text"
                  value={formData.notes}
                  onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Your notes..."
                />
              </div>
            </div>

            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={handleCancel}
                className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
              >
                {editingItem ? 'Update' : 'Add to Watchlist'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Watchlist Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {watchlist.length === 0 ? (
          <div className="text-center py-12">
            <svg className="mx-auto h-12 w-12 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            <h3 className="mt-2 text-sm font-medium text-gray-900">No tickers in watchlist</h3>
            <p className="mt-1 text-sm text-gray-500">Get started by adding a ticker to track.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Ticker
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Company
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Current Price
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Target Price
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Distance to Target
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Notes
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {watchlist.map((item) => (
                  <tr key={item.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm font-bold text-blue-600">{item.ticker}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-900">{item.company_name || '-'}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <span className="text-sm font-medium text-gray-900">
                        {formatCurrency(item.current_price)}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <span className="text-sm text-gray-900">
                        {formatCurrency(item.target_price)}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      {item.distance_to_target !== undefined && item.distance_to_target !== null ? (
                        <div>
                          <span className={`text-sm font-medium ${item.distance_to_target >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                            {formatCurrency(Math.abs(item.distance_to_target))}
                          </span>
                          <br />
                          <span className={`text-xs ${item.distance_to_target_pct && item.distance_to_target_pct >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                            ({formatPercent(item.distance_to_target_pct)})
                          </span>
                        </div>
                      ) : (
                        <span className="text-sm text-gray-500">-</span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-gray-500 truncate max-w-xs block">
                        {item.notes || '-'}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button
                        onClick={() => handleEdit(item)}
                        className="text-blue-600 hover:text-blue-900 mr-3"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => handleDelete(item.id)}
                        className="text-red-600 hover:text-red-900"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Summary */}
      {watchlist.length > 0 && (
        <div className="mt-6 bg-blue-50 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-blue-800 font-medium">
                Tracking {watchlist.length} ticker{watchlist.length !== 1 ? 's' : ''}
              </p>
              <p className="text-xs text-blue-600 mt-1">
                Prices update automatically every 30 seconds
              </p>
            </div>
            <button
              onClick={fetchWatchlist}
              className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              Refresh Now
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default Watchlist
