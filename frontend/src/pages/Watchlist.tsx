import { useEffect, useRef, useState } from 'react'
import api from '../services/api'
import { WatchlistItem, WatchlistCreate } from '../types'
import TradingViewChart from '../components/TradingViewChart'

interface SearchResult {
  symbol: string
  name: string
  exchange: string
  type: string
  price: number | null
}

const TICKER_CATEGORIES = [
  {
    label: '📈 Índices',
    tickers: [
      { label: 'S&P 500', ticker: 'AMEX:SPY' },
      { label: 'NASDAQ 100', ticker: 'NASDAQ:QQQ' },
      { label: 'Dow Jones', ticker: 'AMEX:DIA' },
      { label: 'Russell 2000', ticker: 'AMEX:IWM' },
      { label: 'Total Market', ticker: 'AMEX:VTI' },
      { label: 'S&P 500 3x', ticker: 'AMEX:UPRO' },
      { label: 'NASDAQ 3x', ticker: 'NASDAQ:TQQQ' },
      { label: 'Bear S&P 3x', ticker: 'AMEX:SPXS' },
    ]
  },
  {
    label: '💻 Tecnología',
    tickers: [
      { label: 'Apple', ticker: 'NASDAQ:AAPL' },
      { label: 'Microsoft', ticker: 'NASDAQ:MSFT' },
      { label: 'NVIDIA', ticker: 'NASDAQ:NVDA' },
      { label: 'Google', ticker: 'NASDAQ:GOOGL' },
      { label: 'Meta', ticker: 'NASDAQ:META' },
      { label: 'Amazon', ticker: 'NASDAQ:AMZN' },
      { label: 'Tesla', ticker: 'NASDAQ:TSLA' },
      { label: 'AMD', ticker: 'NASDAQ:AMD' },
      { label: 'Netflix', ticker: 'NASDAQ:NFLX' },
      { label: 'Palantir', ticker: 'NYSE:PLTR' },
      { label: 'Salesforce', ticker: 'NYSE:CRM' },
      { label: 'Intel', ticker: 'NASDAQ:INTC' },
      { label: 'Broadcom', ticker: 'NASDAQ:AVGO' },
      { label: 'Oracle', ticker: 'NYSE:ORCL' },
    ]
  },
  {
    label: '🏦 Finanzas',
    tickers: [
      { label: 'JPMorgan', ticker: 'NYSE:JPM' },
      { label: 'Bank of America', ticker: 'NYSE:BAC' },
      { label: 'Goldman Sachs', ticker: 'NYSE:GS' },
      { label: 'Visa', ticker: 'NYSE:V' },
      { label: 'Mastercard', ticker: 'NYSE:MA' },
      { label: 'Berkshire B', ticker: 'NYSE:BRK.B' },
      { label: 'Morgan Stanley', ticker: 'NYSE:MS' },
      { label: 'Citi', ticker: 'NYSE:C' },
    ]
  },
  {
    label: '💊 Salud',
    tickers: [
      { label: 'Eli Lilly', ticker: 'NYSE:LLY' },
      { label: 'UnitedHealth', ticker: 'NYSE:UNH' },
      { label: 'Johnson & Johnson', ticker: 'NYSE:JNJ' },
      { label: 'AbbVie', ticker: 'NYSE:ABBV' },
      { label: 'Pfizer', ticker: 'NYSE:PFE' },
      { label: 'Merck', ticker: 'NYSE:MRK' },
      { label: 'Novo Nordisk', ticker: 'NYSE:NVO' },
    ]
  },
  {
    label: '⚡ Energía',
    tickers: [
      { label: 'ExxonMobil', ticker: 'NYSE:XOM' },
      { label: 'Chevron', ticker: 'NYSE:CVX' },
      { label: 'ConocoPhillips', ticker: 'NYSE:COP' },
      { label: 'Energy ETF', ticker: 'AMEX:XLE' },
      { label: 'Shell', ticker: 'NYSE:SHEL' },
    ]
  },
  {
    label: '₿ Crypto',
    tickers: [
      { label: 'Bitcoin', ticker: 'BITSTAMP:BTCUSD' },
      { label: 'Ethereum', ticker: 'BITSTAMP:ETHUSD' },
      { label: 'Solana', ticker: 'COINBASE:SOLUSD' },
      { label: 'BTC ETF (IBIT)', ticker: 'NASDAQ:IBIT' },
      { label: 'ETH ETF (ETHA)', ticker: 'NASDAQ:ETHA' },
    ]
  },
  {
    label: '🪙 Commodities',
    tickers: [
      { label: 'Gold', ticker: 'TVC:GOLD' },
      { label: 'Silver', ticker: 'TVC:SILVER' },
      { label: 'Oil (WTI)', ticker: 'TVC:USOIL' },
      { label: 'Nat Gas', ticker: 'TVC:NATGAS' },
      { label: 'Copper', ticker: 'TVC:COPPER' },
      { label: 'Gold ETF', ticker: 'AMEX:GLD' },
      { label: 'Silver ETF', ticker: 'AMEX:SLV' },
    ]
  },
  {
    label: '🇨🇱 Chile',
    tickers: [
      { label: 'IPSA', ticker: 'SP_IPSA' },
      { label: 'USD/CLP', ticker: 'FX:USDCLP' },
    ]
  },
  {
    label: '💱 Forex',
    tickers: [
      { label: 'EUR/USD', ticker: 'FX:EURUSD' },
      { label: 'USD/JPY', ticker: 'FX:USDJPY' },
      { label: 'GBP/USD', ticker: 'FX:GBPUSD' },
      { label: 'USD/MXN', ticker: 'FX:USDMXN' },
      { label: 'USD/BRL', ticker: 'FX:USDBRL' },
      { label: 'USD/ARS', ticker: 'FX:USDARS' },
    ]
  },
]

function Watchlist() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [chartTicker, setChartTicker] = useState('AMEX:SPY')
  const [chartInput, setChartInput] = useState('')
  const [tickerSearch, setTickerSearch] = useState('')
  const [activeCategory, setActiveCategory] = useState(0)
  const [editingItem, setEditingItem] = useState<WatchlistItem | null>(null)
  // Add-form search
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedPreview, setSelectedPreview] = useState<SearchResult | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
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

  // Debounce search for add-form
  useEffect(() => {
    if (!searchQuery || searchQuery.length < 1 || editingItem) {
      setSearchResults([])
      setShowDropdown(false)
      return
    }
    const timer = setTimeout(async () => {
      setSearchLoading(true)
      try {
        const resp = await api.get<SearchResult[]>(`/api/watchlist/search?q=${encodeURIComponent(searchQuery)}`)
        setSearchResults(resp.data)
        setShowDropdown(resp.data.length > 0)
      } catch {
        setSearchResults([])
      } finally {
        setSearchLoading(false)
      }
    }, 350)
    return () => clearTimeout(timer)
  }, [searchQuery, editingItem])

  // Close dropdown on outside click
  useEffect(() => {
    const handleOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleOutside)
    return () => document.removeEventListener('mousedown', handleOutside)
  }, [])

  const handleSelectSearchResult = (result: SearchResult) => {
    setSelectedPreview(result)
    setFormData(prev => ({ ...prev, ticker: result.symbol, company_name: result.name }))
    setSearchQuery(result.name)
    setShowDropdown(false)
  }

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
    setSearchQuery('')
    setSearchResults([])
    setSelectedPreview(null)
    setShowDropdown(false)
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
        <div className="animate-spin rounded-full h-10 w-10 border-2 border-blue-600 border-t-transparent"></div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Watchlist</h1>
          <p className="page-subtitle">Sigue los activos que te interesan</p>
        </div>
        <button
          onClick={() => showForm ? handleCancel() : setShowForm(true)}
          className="btn-primary"
        >
          {showForm ? 'Cancelar' : '+ Agregar ticker'}
        </button>
      </div>

      {/* Form */}
      {showForm && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6 mb-6">
          <h2 className="text-xl font-semibold mb-5 text-gray-800 dark:text-white">
            {editingItem ? '✏️ Editar ticker' : '🔍 Agregar a Watchlist'}
          </h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            {formError && (
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 px-4 py-3 rounded-lg text-sm">
                {formError}
              </div>
            )}

            {/* Search box (only when adding new) */}
            {!editingItem && (
              <div className="relative" ref={dropdownRef}>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Buscar instrumento *
                </label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔍</span>
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={e => { setSearchQuery(e.target.value); setSelectedPreview(null) }}
                    onFocus={() => searchResults.length > 0 && setShowDropdown(true)}
                    placeholder="Nombre o ticker (ej: Apple, NVDA, Bitcoin…)"
                    className="w-full pl-9 pr-10 py-2.5 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-800 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                    autoComplete="off"
                  />
                  {searchLoading && (
                    <span className="absolute right-3 top-1/2 -translate-y-1/2">
                      <div className="animate-spin h-4 w-4 border-2 border-blue-500 border-t-transparent rounded-full" />
                    </span>
                  )}
                </div>
                {/* Results dropdown */}
                {showDropdown && searchResults.length > 0 && (
                  <div className="absolute z-50 top-full mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl shadow-2xl overflow-hidden">
                    {searchResults.map((r, i) => (
                      <button
                        key={i}
                        type="button"
                        onClick={() => handleSelectSearchResult(r)}
                        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-blue-50 dark:hover:bg-gray-700 transition-colors border-b border-gray-100 dark:border-gray-700 last:border-0"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <span className={`flex-shrink-0 text-xs font-bold px-2 py-0.5 rounded ${
                            r.type === 'EQUITY' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/60 dark:text-blue-300' :
                            r.type === 'ETF' ? 'bg-green-100 text-green-700 dark:bg-green-900/60 dark:text-green-300' :
                            r.type === 'CRYPTOCURRENCY' ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/60 dark:text-orange-300' :
                            r.type === 'MUTUALFUND' ? 'bg-purple-100 text-purple-700 dark:bg-purple-900/60 dark:text-purple-300' :
                            'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
                          }`}>{r.type || '—'}</span>
                          <div className="min-w-0">
                            <div className="font-semibold text-sm text-gray-800 dark:text-white">{r.symbol}</div>
                            <div className="text-xs text-gray-500 dark:text-gray-400 truncate">{r.name}</div>
                          </div>
                        </div>
                        <div className="text-right flex-shrink-0 ml-3">
                          <div className="text-sm font-semibold text-gray-800 dark:text-white">
                            {r.price != null ? `$${r.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
                          </div>
                          <div className="text-xs text-gray-400">{r.exchange}</div>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Selected preview card */}
            {selectedPreview && !editingItem && (
              <div className="flex items-center gap-4 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-lg font-bold text-blue-700 dark:text-blue-300">{selectedPreview.symbol}</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                      selectedPreview.type === 'EQUITY' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/60 dark:text-blue-300' :
                      selectedPreview.type === 'ETF' ? 'bg-green-100 text-green-700 dark:bg-green-900/60 dark:text-green-300' :
                      selectedPreview.type === 'CRYPTOCURRENCY' ? 'bg-orange-100 text-orange-700' :
                      'bg-gray-100 text-gray-600'
                    }`}>{selectedPreview.type}</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">{selectedPreview.exchange}</span>
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-400 mt-0.5 truncate">{selectedPreview.name}</div>
                </div>
                <div className="text-right flex-shrink-0">
                  <div className="text-xl font-bold text-gray-800 dark:text-white">
                    {selectedPreview.price != null
                      ? `$${selectedPreview.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                      : '—'}
                  </div>
                  <div className="text-xs text-gray-400">Precio actual</div>
                </div>
                <button
                  type="button"
                  onClick={() => { setSelectedPreview(null); setSearchQuery(''); setFormData(prev => ({ ...prev, ticker: '', company_name: '' })) }}
                  className="flex-shrink-0 text-gray-400 hover:text-red-500 transition-colors text-xl leading-none"
                >✕</button>
              </div>
            )}

            {/* Editing: show ticker readonly */}
            {editingItem && (
              <div className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                <span className="font-bold text-blue-600 dark:text-blue-400 text-lg">{editingItem.ticker}</span>
                {editingItem.company_name && (
                  <span className="text-sm text-gray-500 dark:text-gray-400">{editingItem.company_name}</span>
                )}
              </div>
            )}

            {/* Target price + Notes */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  🔔 Precio objetivo (alarma)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={formData.target_price || ''}
                  onChange={e => setFormData({ ...formData, target_price: e.target.value ? parseFloat(e.target.value) : undefined })}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-800 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  placeholder="ej: 150.00"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  📝 Notas
                </label>
                <input
                  type="text"
                  value={formData.notes}
                  onChange={e => setFormData({ ...formData, notes: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-800 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                  placeholder="Notas opcionales…"
                />
              </div>
            </div>

            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={handleCancel}
                className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={!editingItem && !selectedPreview}
                className="px-5 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {editingItem ? 'Guardar cambios' : '+ Agregar a Watchlist'}
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
        <div className="mt-6 bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-blue-800 dark:text-blue-300 font-medium">
                Tracking {watchlist.length} ticker{watchlist.length !== 1 ? 's' : ''}
              </p>
              <p className="text-xs text-blue-600 dark:text-blue-400 mt-1">
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

      {/* ── TradingView Chart ── */}
      <div className="mt-8 bg-white dark:bg-gray-800 rounded-xl shadow p-5">
        <div className="flex flex-col gap-4 mb-4">

          {/* Header */}
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
              📊 <span className="text-blue-500">{chartTicker}</span>
            </h2>
            {/* Custom ticker input */}
            <form
              onSubmit={e => { e.preventDefault(); if (chartInput.trim()) { setChartTicker(chartInput.trim().toUpperCase()); setChartInput(''); setTickerSearch('') } }}
              className="flex gap-1"
            >
              <input
                type="text"
                value={chartInput}
                onChange={e => setChartInput(e.target.value.toUpperCase())}
                placeholder="Ticker manual…"
                className="w-32 px-2 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded-l-md bg-white dark:bg-gray-700 text-gray-800 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <button type="submit" className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-r-md hover:bg-blue-700 transition-colors">
                Ver
              </button>
            </form>
          </div>

          {/* Search bar */}
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">🔍</span>
            <input
              type="text"
              value={tickerSearch}
              onChange={e => setTickerSearch(e.target.value)}
              placeholder="Buscar instrumento (ej: Apple, Gold, BTC…)"
              className="w-full pl-9 pr-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-700 text-gray-800 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            {tickerSearch && (
              <button onClick={() => setTickerSearch('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xs">✕</button>
            )}
          </div>

          {/* Category tabs (hidden when searching) */}
          {!tickerSearch && (
            <div className="flex gap-1 overflow-x-auto scrollbar-hide pb-1">
              {TICKER_CATEGORIES.map((cat, i) => (
                <button
                  key={cat.label}
                  onClick={() => setActiveCategory(i)}
                  className={`flex-shrink-0 px-3 py-1.5 text-xs font-medium rounded-full transition-colors ${
                    activeCategory === i
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                  }`}
                >
                  {cat.label}
                </button>
              ))}
            </div>
          )}

          {/* Ticker grid */}
          <div className="flex flex-wrap gap-2">
            {tickerSearch
              ? TICKER_CATEGORIES.flatMap(cat => cat.tickers)
                  .filter(t => t.label.toLowerCase().includes(tickerSearch.toLowerCase()) || t.ticker.toLowerCase().includes(tickerSearch.toLowerCase()))
                  .map(t => (
                    <button
                      key={t.ticker}
                      onClick={() => { setChartTicker(t.ticker); setTickerSearch('') }}
                      className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${
                        chartTicker === t.ticker
                          ? 'bg-blue-600 border-blue-600 text-white'
                          : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:border-blue-400 hover:text-blue-600 dark:hover:text-blue-400'
                      }`}
                    >
                      {t.label}
                      <span className="ml-1 opacity-50 font-normal">{t.ticker.split(':')[1] ?? t.ticker}</span>
                    </button>
                  ))
              : TICKER_CATEGORIES[activeCategory].tickers.map(t => (
                  <button
                    key={t.ticker}
                    onClick={() => setChartTicker(t.ticker)}
                    className={`px-3 py-1.5 text-xs font-semibold rounded-lg border transition-colors ${
                      chartTicker === t.ticker
                        ? 'bg-blue-600 border-blue-600 text-white'
                        : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:border-blue-400 hover:text-blue-600 dark:hover:text-blue-400'
                    }`}
                  >
                    {t.label}
                    <span className="ml-1 opacity-40 font-normal">{t.ticker.split(':')[1] ?? t.ticker}</span>
                  </button>
                ))
            }
          </div>

          {/* Watchlist tickers */}
          {watchlist.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-1 border-t border-gray-200 dark:border-gray-700">
              <span className="text-xs text-gray-400 dark:text-gray-500 self-center">Mi Watchlist:</span>
              {watchlist.map(item => (
                <button
                  key={item.ticker}
                  onClick={() => setChartTicker(item.ticker)}
                  className={`px-2.5 py-1 text-xs font-bold rounded-md transition-colors ${
                    chartTicker === item.ticker
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-blue-100 dark:hover:bg-gray-600'
                  }`}
                >
                  {item.ticker}
                </button>
              ))}
            </div>
          )}
        </div>

        <TradingViewChart ticker={chartTicker} height={580} />
      </div>
    </div>
  )
}

export default Watchlist
