import React, { useEffect, useState } from 'react';
import api from '../services/api';
import TradingViewChart from '../components/TradingViewChart';

interface Stock {
  id: number;
  ticker: string;
  company_name: string;
  shares: number;
  average_cost: number;
  total_invested: number;
  total_premium_earned: number;
  adjusted_cost_basis: number;
  current_price?: number;
  current_value?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  is_active: boolean;
  created_at: string;
}

interface StockForm {
  ticker: string;
  shares: string;
  purchase_price: string;
  purchase_date: string;
  notes: string;
}

interface SearchFilters {
  ticker: string;
  minPrice: string;
  maxPrice: string;
  minShares: string;
  maxShares: string;
  minPnlPct: string;
  maxPnlPct: string;
  profitableOnly: boolean;
  losingOnly: boolean;
  sortBy: string;
  sortOrder: string;
}

function Stocks() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [selectedStock, setSelectedStock] = useState<string | null>(null);
  const [formData, setFormData] = useState<StockForm>({
    ticker: '',
    shares: '',
    purchase_price: '',
    purchase_date: new Date().toISOString().split('T')[0],
    notes: ''
  });
  const [filters, setFilters] = useState<SearchFilters>({
    ticker: '',
    minPrice: '',
    maxPrice: '',
    minShares: '',
    maxShares: '',
    minPnlPct: '',
    maxPnlPct: '',
    profitableOnly: false,
    losingOnly: false,
    sortBy: 'ticker',
    sortOrder: 'asc'
  });
  const [formError, setFormError] = useState('');
  const [formLoading, setFormLoading] = useState(false);

  const fetchStocks = async (useFilters = false) => {
    setLoading(true);
    try {
      let url = '/api/stocks';
      
      if (useFilters) {
        const params = new URLSearchParams();
        if (filters.ticker) params.append('ticker', filters.ticker);
        if (filters.minPrice) params.append('min_price', filters.minPrice);
        if (filters.maxPrice) params.append('max_price', filters.maxPrice);
        if (filters.minShares) params.append('min_shares', filters.minShares);
        if (filters.maxShares) params.append('max_shares', filters.maxShares);
        if (filters.minPnlPct) params.append('min_pnl_pct', filters.minPnlPct);
        if (filters.maxPnlPct) params.append('max_pnl_pct', filters.maxPnlPct);
        if (filters.profitableOnly) params.append('profitable_only', 'true');
        if (filters.losingOnly) params.append('losing_only', 'true');
        params.append('sort_by', filters.sortBy);
        params.append('sort_order', filters.sortOrder);
        
        url = `/api/stocks/search/advanced?${params.toString()}`;
      }
      
      const { data } = await api.get(url);
      setStocks(data);
    } catch (error) {
      console.error('Error fetching stocks:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStocks();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    setFormLoading(true);

    const shares = parseFloat(formData.shares);
    const purchase_price = parseFloat(formData.purchase_price);

    if (!formData.ticker.trim()) {
      setFormError('El ticker es requerido');
      setFormLoading(false);
      return;
    }
    if (isNaN(shares) || shares <= 0) {
      setFormError('Ingresa un número válido de acciones');
      setFormLoading(false);
      return;
    }
    if (isNaN(purchase_price) || purchase_price <= 0) {
      setFormError('Ingresa un precio de compra válido');
      setFormLoading(false);
      return;
    }

    try {
      await api.post('/api/stocks/', {
        ticker: formData.ticker.toUpperCase(),
        shares,
        purchase_price,
        purchase_date: new Date(formData.purchase_date + 'T12:00:00').toISOString(),
        notes: formData.notes || null
      });

      // Reset form
      setFormData({
        ticker: '',
        shares: '',
        purchase_price: '',
        purchase_date: new Date().toISOString().split('T')[0],
        notes: ''
      });
      setShowForm(false);
      fetchStocks(showFilters);
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      if (Array.isArray(detail)) {
        // FastAPI Pydantic V2 validation error: array of {loc, msg, type, ...}
        const messages = detail.map((e: any) => {
          const field = Array.isArray(e.loc) ? e.loc.filter((l: any) => l !== 'body').join('.') : '';
          return field ? `${field}: ${e.msg}` : e.msg;
        });
        setFormError(messages.join(' | '));
      } else if (typeof detail === 'string') {
        setFormError(detail);
      } else {
        setFormError('Error al crear la posición');
      }
    } finally {
      setFormLoading(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('¿Estás seguro de eliminar esta posición?')) return;

    try {
      await api.delete(`/api/stocks/${id}`);
      fetchStocks(showFilters);
    } catch (error) {
      console.error('Error deleting stock:', error);
    }
  };

  const handleSearch = () => {
    fetchStocks(true);
  };

  const handleClearFilters = () => {
    setFilters({
      ticker: '',
      minPrice: '',
      maxPrice: '',
      minShares: '',
      maxShares: '',
      minPnlPct: '',
      maxPnlPct: '',
      profitableOnly: false,
      losingOnly: false,
      sortBy: 'ticker',
      sortOrder: 'asc'
    });
    setShowFilters(false);
    fetchStocks(false);
  };

  const formatCurrency = (value?: number) => {
    if (value === undefined || value === null) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD'
    }).format(value);
  };

  const formatPercent = (value?: number) => {
    if (value === undefined || value === null) return '-';
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;
  };

  const handleExportCSV = async () => {
    try {
      const response = await api.get('/api/exports/stocks/csv', {
        responseType: 'blob'
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `kover_stocks_${new Date().toISOString().split('T')[0]}.csv`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Error exporting CSV:', error);
      alert('Error al exportar CSV. Por favor intenta de nuevo.');
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
    <div className="page space-y-6">
      <div className="page-header">
        <div>
          <h1 className="page-title">Mis Acciones</h1>
          <p className="page-subtitle">Posiciones activas en renta variable</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="btn btn-secondary"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
            </svg>
            {showFilters ? 'Ocultar Filtros' : 'Filtros Avanzados'}
          </button>
          <button
            onClick={handleExportCSV}
            className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg transition flex items-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export CSV
          </button>
          <button
            onClick={() => setShowForm(!showForm)}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition"
          >
            {showForm ? 'Cancelar' : '+ Agregar Posición'}
          </button>
        </div>
      </div>

      {/* Advanced Filters */}
      {showFilters && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
          <h2 className="text-xl font-semibold mb-4 text-gray-900 dark:text-gray-100">Búsqueda Avanzada</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Ticker
              </label>
              <input
                type="text"
                value={filters.ticker}
                onChange={(e) => setFilters({ ...filters, ticker: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="AAPL"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Precio Mín
              </label>
              <input
                type="number"
                step="0.01"
                value={filters.minPrice}
                onChange={(e) => setFilters({ ...filters, minPrice: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="0"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Precio Máx
              </label>
              <input
                type="number"
                step="0.01"
                value={filters.maxPrice}
                onChange={(e) => setFilters({ ...filters, maxPrice: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="1000"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Shares Mín
              </label>
              <input
                type="number"
                step="1"
                value={filters.minShares}
                onChange={(e) => setFilters({ ...filters, minShares: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="0"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Shares Máx
              </label>
              <input
                type="number"
                step="1"
                value={filters.maxShares}
                onChange={(e) => setFilters({ ...filters, maxShares: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="1000"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                P&L % Mín
              </label>
              <input
                type="number"
                step="0.1"
                value={filters.minPnlPct}
                onChange={(e) => setFilters({ ...filters, minPnlPct: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="-50"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                P&L % Máx
              </label>
              <input
                type="number"
                step="0.1"
                value={filters.maxPnlPct}
                onChange={(e) => setFilters({ ...filters, maxPnlPct: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="100"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Ordenar por
              </label>
              <select
                value={filters.sortBy}
                onChange={(e) => setFilters({ ...filters, sortBy: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="ticker">Ticker</option>
                <option value="shares">Shares</option>
                <option value="current_price">Precio</option>
                <option value="pnl_pct">P&L %</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-4 mt-4">
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
              <input
                type="checkbox"
                checked={filters.profitableOnly}
                onChange={(e) => setFilters({ ...filters, profitableOnly: e.target.checked, losingOnly: false })}
                className="rounded text-blue-600"
              />
              Solo Rentables
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
              <input
                type="checkbox"
                checked={filters.losingOnly}
                onChange={(e) => setFilters({ ...filters, losingOnly: e.target.checked, profitableOnly: false })}
                className="rounded text-blue-600"
              />
              Solo Pérdidas
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
              <input
                type="radio"
                checked={filters.sortOrder === 'asc'}
                onChange={() => setFilters({ ...filters, sortOrder: 'asc' })}
                name="sortOrder"
              />
              Ascendente
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
              <input
                type="radio"
                checked={filters.sortOrder === 'desc'}
                onChange={() => setFilters({ ...filters, sortOrder: 'desc' })}
                name="sortOrder"
              />
              Descendente
            </label>
          </div>

          <div className="flex gap-2 mt-4">
            <button
              onClick={handleSearch}
              className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-lg transition"
            >
              Buscar
            </button>
            <button
              onClick={handleClearFilters}
              className="bg-gray-500 hover:bg-gray-600 text-white px-6 py-2 rounded-lg transition"
            >
              Limpiar Filtros
            </button>
          </div>
        </div>
      )}

      {showForm && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-xl font-semibold mb-4">Nueva Posición</h2>
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
                  value={formData.ticker}
                  onChange={(e) => setFormData({ ...formData, ticker: e.target.value.toUpperCase() })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="AAPL"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Acciones *
                </label>
                <input
                  type="number"
                  required
                  step="0.01"
                  min="0"
                  value={formData.shares}
                  onChange={(e) => setFormData({ ...formData, shares: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="100"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Precio de Compra *
                </label>
                <input
                  type="number"
                  required
                  step="0.01"
                  min="0"
                  value={formData.purchase_price}
                  onChange={(e) => setFormData({ ...formData, purchase_price: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="150.00"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Fecha de Compra *
                </label>
                <input
                  type="date"
                  required
                  value={formData.purchase_date}
                  onChange={(e) => setFormData({ ...formData, purchase_date: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Notas
              </label>
              <textarea
                value={formData.notes}
                onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                rows={3}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="Notas adicionales..."
              />
            </div>

            <div className="flex justify-end space-x-3">
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={formLoading}
                className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition disabled:opacity-50"
              >
                {formLoading ? 'Guardando...' : 'Guardar'}
              </button>
            </div>
          </form>
        </div>
      )}

      {stocks.length === 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-12 text-center">
          <p className="text-gray-500 dark:text-gray-400 text-lg">No tienes posiciones aún</p>
          <button
            onClick={() => setShowForm(true)}
            className="mt-4 text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 font-medium"
          >
            Agregar tu primera posición →
          </button>
        </div>
      ) : (
        <>
          {/* TradingView Chart Modal */}
          {selectedStock && (
            <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
              <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-6xl max-h-[90vh] overflow-hidden">
                <div className="flex justify-between items-center p-4 border-b border-gray-200 dark:border-gray-700">
                  <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">{selectedStock} - Candlestick Chart</h2>
                  <button
                    onClick={() => setSelectedStock(null)}
                    className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                  >
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <div className="p-4">
                  <TradingViewChart ticker={selectedStock} height={600} />
                </div>
              </div>
            </div>
          )}

          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Ticker
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Acciones
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Costo Prom.
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Precio Actual
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Valor Actual
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      P&L
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Primas
                    </th>
                    <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                      Acciones
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                  {stocks.map((stock) => (
                    <tr key={stock.id} className="hover:bg-gray-50 dark:hover:bg-gray-700">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div>
                          <div className="text-sm font-medium text-gray-900 dark:text-gray-100">{stock.ticker}</div>
                          <div className="text-sm text-gray-500 dark:text-gray-400">{stock.company_name}</div>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
                        {stock.shares}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-900 dark:text-gray-100">
                        {formatCurrency(stock.adjusted_cost_basis)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-900 dark:text-gray-100">
                        {formatCurrency(stock.current_price)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-right font-medium text-gray-900 dark:text-gray-100">
                        {formatCurrency(stock.current_value)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right">
                        <div className={`text-sm font-medium ${
                          (stock.unrealized_pnl || 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                        }`}>
                          {formatCurrency(stock.unrealized_pnl)}
                        </div>
                        <div className={`text-xs ${
                          (stock.unrealized_pnl_pct || 0) >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
                        }`}>
                          {formatPercent(stock.unrealized_pnl_pct)}
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-green-600 dark:text-green-400 font-medium">
                        {formatCurrency(stock.total_premium_earned)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-center text-sm font-medium">
                        <div className="flex justify-center gap-2">
                          <button
                            onClick={() => setSelectedStock(stock.ticker)}
                            className="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 transition"
                            title="Ver gráfico"
                          >
                            📊
                          </button>
                          <button
                            onClick={() => handleDelete(stock.id)}
                            className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300 transition"
                          >
                            Eliminar
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default Stocks
