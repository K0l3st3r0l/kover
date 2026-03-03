import React, { useEffect, useState } from 'react';
import api from '../services/api';

interface Stock {
  id: number;
  ticker: string;
  company_name: string;
}

interface Option {
  id: number;
  stock_id: number;
  ticker: string;
  option_type: 'CALL' | 'PUT';
  strategy: 'COVERED_CALL' | 'CASH_SECURED_PUT';
  strike_price: number;
  contracts: number;
  premium_per_contract: number;
  total_premium: number;
  expiration_date: string;
  status: 'OPEN' | 'CLOSED' | 'EXPIRED' | 'ASSIGNED';
  opened_at: string;
  closed_at?: string;
  realized_pnl?: number;
  days_to_expiration?: number;
  notes?: string;
  premium_yield?: number;
  annualized_return?: number;
}

interface OptionForm {
  stock_id: string;
  option_type: 'CALL' | 'PUT';
  strategy: 'COVERED_CALL' | 'CASH_SECURED_PUT';
  strike_price: string;
  contracts: string;
  premium_per_contract: string;
  expiration_date: string;
  opened_at: string;
  notes: string;
}

function Options() {
  const [options, setOptions] = useState<Option[]>([]);
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState<OptionForm>({
    stock_id: '',
    option_type: 'CALL',
    strategy: 'COVERED_CALL',
    strike_price: '',
    contracts: '',
    premium_per_contract: '',
    expiration_date: '',
    opened_at: '',
    notes: ''
  });
  const [formError, setFormError] = useState('');
  const [formLoading, setFormLoading] = useState(false);
  const [filter, setFilter] = useState<'ALL' | 'OPEN' | 'CLOSED'>('ALL');

  // Roll modal
  const [rollTarget, setRollTarget] = useState<Option | null>(null);
  const [rollForm, setRollForm] = useState({
    closing_premium: '',
    new_strike_price: '',
    new_expiration_date: '',
    new_premium_per_contract: '',
    new_contracts: '',
    notes: ''
  });
  const [rollLoading, setRollLoading] = useState(false);
  const [rollError, setRollError] = useState('');

  // Edit modal
  const [editTarget, setEditTarget] = useState<Option | null>(null);
  const [editForm, setEditForm] = useState({
    strike_price: '',
    contracts: '',
    premium_per_contract: '',
    expiration_date: '',
    opened_at: '',
    strategy: 'COVERED_CALL' as 'COVERED_CALL' | 'CASH_SECURED_PUT',
    status: 'OPEN' as Option['status'],
    notes: '',
    realized_pnl: ''
  });
  const [editLoading, setEditLoading] = useState(false);
  const [editError, setEditError] = useState('');

  const fetchData = async () => {
    try {
      const [optionsRes, stocksRes] = await Promise.all([
        api.get('/api/options'),
        api.get('/api/stocks')
      ]);
      setOptions(optionsRes.data);
      setStocks(stocksRes.data);
    } catch (error) {
      console.error('Error fetching data:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError('');
    setFormLoading(true);

    try {
      await api.post('/api/options', {
        stock_id: parseInt(formData.stock_id),
        option_type: formData.option_type,
        strategy: formData.strategy,
        strike_price: parseFloat(formData.strike_price),
        contracts: parseInt(formData.contracts),
        premium_per_contract: parseFloat(formData.premium_per_contract),
        expiration_date: new Date(formData.expiration_date + 'T12:00:00').toISOString(),
        notes: formData.notes || null,
        opened_at: formData.opened_at ? new Date(formData.opened_at + 'T12:00:00').toISOString() : null
      });

      // Reset form
      setFormData({
        stock_id: '',
        option_type: 'CALL',
        strategy: 'COVERED_CALL',
        strike_price: '',
        contracts: '',
        premium_per_contract: '',
        expiration_date: '',
        opened_at: '',
        notes: ''
      });
      setShowForm(false);
      fetchData();
    } catch (error: any) {
      setFormError(error.response?.data?.detail || 'Error al crear la opción');
    } finally {
      setFormLoading(false);
    }
  };

  const handleClose = async (id: number, closingPremium: number) => {
    try {
      await api.post(`/api/options/${id}/close`, {
        closing_premium: closingPremium
      });
      fetchData();
    } catch (error) {
      console.error('Error closing option:', error);
    }
  };

  const openRollModal = (option: Option) => {
    setRollTarget(option);
    setRollForm({
      closing_premium: '',
      new_strike_price: String(option.strike_price),
      new_expiration_date: '',
      new_premium_per_contract: '',
      new_contracts: String(option.contracts),
      notes: ''
    });
    setRollError('');
  };

  const handleRoll = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rollTarget) return;
    setRollError('');
    setRollLoading(true);
    try {
      await api.post(`/api/options/${rollTarget.id}/roll`, {
        closing_premium: parseFloat(rollForm.closing_premium),
        new_strike_price: parseFloat(rollForm.new_strike_price),
        new_expiration_date: new Date(rollForm.new_expiration_date + 'T12:00:00').toISOString(),
        new_premium_per_contract: parseFloat(rollForm.new_premium_per_contract),
        new_contracts: rollForm.new_contracts ? parseInt(rollForm.new_contracts) : undefined,
        notes: rollForm.notes || null
      });
      setRollTarget(null);
      fetchData();
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      setRollError(Array.isArray(detail) ? detail.map((e: any) => e.msg).join(' | ') : (detail || 'Error al hacer roll'));
    } finally {
      setRollLoading(false);
    }
  };

  const handleDelete = async (option: Option) => {
    const label = `${option.ticker} Covered Call $${option.strike_price} (${option.status})`;
    if (!window.confirm(`¿Eliminar permanentemente la opción ${label}?\n\nSe revertirá su impacto en el portafolio.`)) return;
    try {
      await api.delete(`/api/options/${option.id}`);
      fetchData();
    } catch (error: any) {
      alert(error.response?.data?.detail || 'Error al eliminar la opción');
    }
  };

  const openEditModal = (option: Option) => {
    setEditTarget(option);
    setEditError('');
    setEditForm({
      strike_price: String(option.strike_price),
      contracts: String(option.contracts),
      premium_per_contract: String(option.premium_per_contract),
      expiration_date: option.expiration_date.split('T')[0],
      opened_at: option.opened_at.split('T')[0],
      strategy: option.strategy,
      status: option.status,
      notes: option.notes || '',
      realized_pnl: option.realized_pnl != null ? String(option.realized_pnl) : ''
    });
  };

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editTarget) return;
    setEditError('');
    setEditLoading(true);
    try {
      await api.put(`/api/options/${editTarget.id}`, {
        strike_price: parseFloat(editForm.strike_price),
        contracts: parseInt(editForm.contracts),
        premium_per_contract: parseFloat(editForm.premium_per_contract),
        expiration_date: new Date(editForm.expiration_date + 'T12:00:00').toISOString(),
        strategy: editForm.strategy,
        status: editForm.status,
        notes: editForm.notes || null,
        realized_pnl: editForm.realized_pnl !== '' ? parseFloat(editForm.realized_pnl) : null,
        opened_at: editForm.opened_at ? new Date(editForm.opened_at + 'T12:00:00').toISOString() : null
      });
      setEditTarget(null);
      fetchData();
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      setEditError(Array.isArray(detail) ? detail.map((e: any) => e.msg).join(' | ') : (detail || 'Error al guardar'));
    } finally {
      setEditLoading(false);
    }
  };

  const formatCurrency = (value?: number) => {
    if (value === undefined || value === null) return '-';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD'
    }).format(value);
  };

  const formatDate = (dateString: string) => {
    // Parsear solo la parte de fecha para evitar desfase por zona horaria
    const [year, month, day] = dateString.split('T')[0].split('-').map(Number);
    return new Date(year, month - 1, day).toLocaleDateString('es-CL', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  const getStatusBadge = (status: string) => {
    const styles = {
      OPEN: 'bg-blue-100 text-blue-800',
      CLOSED: 'bg-gray-100 text-gray-800',
      EXPIRED: 'bg-green-100 text-green-800',
      ASSIGNED: 'bg-yellow-100 text-yellow-800'
    };
    return styles[status as keyof typeof styles] || 'bg-gray-100 text-gray-800';
  };

  const handleExportCSV = async () => {
    try {
      const params = filter !== 'ALL' ? `?status=${filter === 'OPEN' ? 'OPEN' : 'CLOSED'}` : '';
      const response = await api.get(`/api/exports/options/csv${params}`, {
        responseType: 'blob'
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `kover_options_${new Date().toISOString().split('T')[0]}.csv`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Error exporting CSV:', error);
      alert('Error al exportar CSV. Por favor intenta de nuevo.');
    }
  };

  const filteredOptions = options.filter(opt => {
    if (filter === 'ALL') return true;
    if (filter === 'OPEN') return opt.status === 'OPEN';
    return opt.status !== 'OPEN';
  });

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-2 border-blue-600 border-t-transparent"></div>
      </div>
    );
  }

  return (
    <>
    <div className="page space-y-6">
      <div className="page-header">
        <div>
          <h1 className="page-title">Mis Opciones</h1>
          <p className="page-subtitle">Covered Calls y Cash Secured Puts</p>
        </div>
        <div className="flex gap-2">
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
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition disabled:opacity-50"
            disabled={stocks.length === 0}
          >
            {showForm ? 'Cancelar' : '+ Registrar Opción'}
          </button>
        </div>
      </div>

      {stocks.length === 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-yellow-800">
            Primero debes agregar posiciones de acciones antes de registrar opciones.
          </p>
        </div>
      )}

      {showForm && stocks.length > 0 && (
        <div className="bg-white rounded-lg shadow-md p-6">
          <h2 className="text-xl font-semibold mb-4">Nueva Opción</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            {formError && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
                {formError}
              </div>
            )}
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Acción *
                </label>
                <select
                  required
                  value={formData.stock_id}
                  onChange={(e) => setFormData({ ...formData, stock_id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="">Seleccionar...</option>
                  {stocks.map(stock => (
                    <option key={stock.id} value={stock.id}>
                      {stock.ticker} - {stock.company_name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Estrategia *
                </label>
                <select
                  required
                  value={formData.strategy}
                  onChange={(e) => {
                    const strategy = e.target.value as 'COVERED_CALL' | 'CASH_SECURED_PUT';
                    setFormData({ 
                      ...formData, 
                      strategy,
                      option_type: strategy === 'COVERED_CALL' ? 'CALL' : 'PUT'
                    });
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="COVERED_CALL">Covered Call</option>
                  <option value="CASH_SECURED_PUT">Cash Secured Put</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Strike Price *
                </label>
                <input
                  type="number"
                  required
                  step="0.01"
                  min="0"
                  value={formData.strike_price}
                  onChange={(e) => setFormData({ ...formData, strike_price: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="100.00"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Contratos *
                </label>
                <input
                  type="number"
                  required
                  min="1"
                  value={formData.contracts}
                  onChange={(e) => setFormData({ ...formData, contracts: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="1"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Prima por Contrato *
                </label>
                <input
                  type="number"
                  required
                  step="0.01"
                  min="0"
                  value={formData.premium_per_contract}
                  onChange={(e) => setFormData({ ...formData, premium_per_contract: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="2.50"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Fecha de Expiración *
                </label>
                <input
                  type="date"
                  required
                  value={formData.expiration_date}
                  onChange={(e) => setFormData({ ...formData, expiration_date: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Fecha de Apertura <span className="text-gray-400 font-normal">(opcional — si fue antes de hoy)</span>
                </label>
                <input
                  type="date"
                  value={formData.opened_at}
                  onChange={(e) => setFormData({ ...formData, opened_at: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>

            {formData.contracts && formData.premium_per_contract && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <p className="text-sm text-blue-800">
                  Prima Total: <span className="font-bold">
                    ${(parseInt(formData.contracts || '0') * parseFloat(formData.premium_per_contract || '0') * 100).toFixed(2)}
                  </span>
                </p>
              </div>
            )}

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

      <div className="flex space-x-2">
        <button
          onClick={() => setFilter('ALL')}
          className={`px-4 py-2 rounded-lg transition ${
            filter === 'ALL' 
              ? 'bg-blue-600 text-white' 
              : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
          }`}
        >
          Todas
        </button>
        <button
          onClick={() => setFilter('OPEN')}
          className={`px-4 py-2 rounded-lg transition ${
            filter === 'OPEN' 
              ? 'bg-blue-600 text-white' 
              : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
          }`}
        >
          Abiertas
        </button>
        <button
          onClick={() => setFilter('CLOSED')}
          className={`px-4 py-2 rounded-lg transition ${
            filter === 'CLOSED' 
              ? 'bg-blue-600 text-white' 
              : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
          }`}
        >
          Cerradas
        </button>
      </div>

      {filteredOptions.length === 0 ? (
        <div className="bg-white rounded-lg shadow-md p-12 text-center">
          <p className="text-gray-500 text-lg">No hay opciones registradas</p>
          {stocks.length > 0 && (
            <button
              onClick={() => setShowForm(true)}
              className="mt-4 text-blue-600 hover:text-blue-700 font-medium"
            >
              Registrar tu primera opción →
            </button>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow-md overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Ticker
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Estrategia
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Strike
                  </th>
                  <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Contratos
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Prima Total
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Rendimiento
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Expiración
                  </th>
                  <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Estado
                  </th>
                  <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Acciones
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredOptions.map((option) => (
                  <tr key={option.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm font-medium text-gray-900">{option.ticker}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm text-gray-900">
                        {option.strategy === 'COVERED_CALL' ? 'Covered Call' : 'Cash Secured Put'}
                      </div>
                      <div className="text-xs text-gray-500">{option.option_type}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-900">
                      {formatCurrency(option.strike_price)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-center text-gray-900">
                      {option.contracts}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right font-medium text-green-600">
                      {formatCurrency(option.total_premium)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      {option.premium_yield != null ? (
                        <div>
                          <div className="text-sm font-medium text-blue-600">
                            {option.premium_yield.toFixed(2)}%
                          </div>
                          {option.annualized_return != null && (
                            <div className="text-xs text-gray-500">
                              {option.annualized_return.toFixed(1)}% anual
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-sm text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center space-x-2">
                        <div>
                          <div className="text-sm text-gray-900">{formatDate(option.expiration_date)}</div>
                          {option.days_to_expiration !== undefined && option.days_to_expiration >= 0 && (
                            <div className={`text-xs font-medium ${
                              option.days_to_expiration <= 2 ? 'text-red-600' : 
                              option.days_to_expiration <= 5 ? 'text-orange-600' : 
                              option.days_to_expiration <= 7 ? 'text-yellow-600' : 
                              'text-gray-500'
                            }`}>
                              {option.days_to_expiration === 0 ? '⚠️ HOY' : 
                               option.days_to_expiration === 1 ? '⚠️ MAÑANA' : 
                               option.days_to_expiration <= 7 ? `⏰ ${option.days_to_expiration} días` :
                               `${option.days_to_expiration} días`}
                            </div>
                          )}
                        </div>
                        {option.status === 'OPEN' && option.days_to_expiration !== undefined && option.days_to_expiration <= 2 && (
                          <span className="text-lg animate-pulse">🚨</span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-center">
                      <span className={`px-2 py-1 text-xs font-medium rounded-full ${getStatusBadge(option.status)}`}>
                        {option.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-center text-sm font-medium">
                      <div className="flex items-center justify-center gap-2">
                        {option.status === 'OPEN' && (
                          <>
                            <button
                              onClick={() => openRollModal(option)}
                              className="text-purple-600 hover:text-purple-800 font-medium transition"
                              title="Hacer roll de la opción"
                            >
                              Roll
                            </button>
                            <span className="text-gray-300">|</span>
                            <button
                              onClick={() => {
                                const premium = prompt('Prima de cierre (0 si expiró sin valor):');
                                if (premium !== null) handleClose(option.id, parseFloat(premium));
                              }}
                              className="text-blue-600 hover:text-blue-800 transition"
                            >
                              Cerrar
                            </button>
                            <span className="text-gray-300">|</span>
                          </>
                        )}
                        <button
                          onClick={() => openEditModal(option)}
                          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
                          title="Editar opción"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                        </button>
                        <button
                          onClick={() => handleDelete(option)}
                          className="text-red-400 hover:text-red-600 transition"
                          title="Eliminar opción"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                      {option.realized_pnl !== undefined && option.realized_pnl !== null && (
                        <div className={`text-xs mt-1 ${option.realized_pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                          P&L: {formatCurrency(option.realized_pnl)}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>

      {/* Roll Modal */}
      {rollTarget && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-lg">
            <div className="p-6">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Roll de Opción</h2>
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                    {rollTarget.ticker} · {rollTarget.strategy === 'COVERED_CALL' ? 'Covered Call' : 'Cash Secured Put'} ·
                    Strike ${rollTarget.strike_price} · Exp {formatDate(rollTarget.expiration_date)}
                  </p>
                </div>
                <button onClick={() => setRollTarget(null)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-2xl leading-none">&times;</button>
              </div>

              {rollError && (
                <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 text-red-700 dark:text-red-300 px-4 py-3 rounded mb-4 text-sm">
                  {rollError}
                </div>
              )}

              <form onSubmit={handleRoll} className="space-y-4">
                {/* Pata 1: cierre */}
                <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-red-800 dark:text-red-300 mb-3">① Buy to Close (pata de cierre)</h3>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                      Prima de recompra por contrato *
                    </label>
                    <input
                      type="number" required step="0.01" min="0"
                      value={rollForm.closing_premium}
                      onChange={e => setRollForm({ ...rollForm, closing_premium: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-red-400 focus:border-transparent"
                      placeholder="ej: 0.15"
                    />
                    {rollForm.closing_premium && (
                      <p className="text-xs text-red-600 dark:text-red-400 mt-1">
                        Costo: ${(parseFloat(rollForm.closing_premium || '0') * rollTarget.contracts * 100).toFixed(2)}
                      </p>
                    )}
                  </div>
                </div>

                {/* Pata 2: nueva opción */}
                <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4">
                  <h3 className="text-sm font-semibold text-green-800 dark:text-green-300 mb-3">② Sell to Open (nueva pata)</h3>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Nuevo Strike *</label>
                      <input
                        type="number" required step="0.01" min="0"
                        value={rollForm.new_strike_price}
                        onChange={e => setRollForm({ ...rollForm, new_strike_price: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-green-400 focus:border-transparent"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Nueva Expiración *</label>
                      <input
                        type="date" required
                        value={rollForm.new_expiration_date}
                        onChange={e => setRollForm({ ...rollForm, new_expiration_date: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-green-400 focus:border-transparent"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Nueva Prima por Contrato *</label>
                      <input
                        type="number" required step="0.01" min="0"
                        value={rollForm.new_premium_per_contract}
                        onChange={e => setRollForm({ ...rollForm, new_premium_per_contract: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-green-400 focus:border-transparent"
                        placeholder="ej: 0.30"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Contratos (opcional)</label>
                      <input
                        type="number" min="1"
                        value={rollForm.new_contracts}
                        onChange={e => setRollForm({ ...rollForm, new_contracts: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-green-400 focus:border-transparent"
                        placeholder={String(rollTarget.contracts)}
                      />
                    </div>
                  </div>
                  {rollForm.new_premium_per_contract && (
                    <p className="text-xs text-green-600 dark:text-green-400 mt-2">
                      Ingreso: ${(parseFloat(rollForm.new_premium_per_contract || '0') * (parseInt(rollForm.new_contracts || String(rollTarget.contracts)) || rollTarget.contracts) * 100).toFixed(2)}
                    </p>
                  )}
                </div>

                {/* Resumen neto */}
                {rollForm.closing_premium && rollForm.new_premium_per_contract && (
                  <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 text-sm">
                    {(() => {
                      const closeCost = parseFloat(rollForm.closing_premium) * rollTarget.contracts * 100;
                      const newIncome = parseFloat(rollForm.new_premium_per_contract) * (parseInt(rollForm.new_contracts || String(rollTarget.contracts)) || rollTarget.contracts) * 100;
                      const net = newIncome - closeCost;
                      return (
                        <div className="flex justify-between items-center">
                          <span className="text-gray-600 dark:text-gray-300 font-medium">Prima neta del roll:</span>
                          <span className={`font-bold text-base ${net >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                            {net >= 0 ? '+' : ''}{formatCurrency(net)}
                            <span className="text-xs font-normal ml-1">{net >= 0 ? '(crédito)' : '(débito)'}</span>
                          </span>
                        </div>
                      );
                    })()}
                  </div>
                )}

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Notas</label>
                  <input
                    type="text"
                    value={rollForm.notes}
                    onChange={e => setRollForm({ ...rollForm, notes: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    placeholder="Opcional..."
                  />
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <button
                    type="button" onClick={() => setRollTarget(null)}
                    className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition dark:text-gray-300"
                  >
                    Cancelar
                  </button>
                  <button
                    type="submit" disabled={rollLoading}
                    className="bg-purple-600 hover:bg-purple-700 text-white px-5 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50"
                  >
                    {rollLoading ? 'Ejecutando...' : 'Confirmar Roll'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {editTarget && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-lg">
            <div className="p-6">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">Editar Opción</h2>
                <button onClick={() => setEditTarget(null)} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-2xl leading-none">&times;</button>
              </div>

              {editError && (
                <div className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 text-red-700 dark:text-red-300 px-4 py-3 rounded mb-4 text-sm">
                  {editError}
                </div>
              )}

              <form onSubmit={handleEdit} className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Strike Price *</label>
                    <input type="number" required step="0.01" min="0"
                      value={editForm.strike_price}
                      onChange={e => setEditForm({...editForm, strike_price: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Contratos *</label>
                    <input type="number" required min="1"
                      value={editForm.contracts}
                      onChange={e => setEditForm({...editForm, contracts: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Prima por Contrato *</label>
                    <input type="number" required step="0.01" min="0"
                      value={editForm.premium_per_contract}
                      onChange={e => setEditForm({...editForm, premium_per_contract: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Fecha de Expiración *</label>
                    <input type="date" required
                      value={editForm.expiration_date}
                      onChange={e => setEditForm({...editForm, expiration_date: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Fecha de Apertura</label>
                    <input type="date"
                      value={editForm.opened_at}
                      onChange={e => setEditForm({...editForm, opened_at: e.target.value})}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Estrategia *</label>
                    <select
                      value={editForm.strategy}
                      onChange={e => setEditForm({...editForm, strategy: e.target.value as any})}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                    >
                      <option value="COVERED_CALL">Covered Call</option>
                      <option value="CASH_SECURED_PUT">Cash Secured Put</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Estado *</label>
                    <select
                      value={editForm.status}
                      onChange={e => setEditForm({...editForm, status: e.target.value as any})}
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100 focus:ring-2 focus:ring-blue-400 focus:border-transparent"
                    >
                      <option value="OPEN">OPEN</option>
                      <option value="CLOSED">CLOSED</option>
                      <option value="EXPIRED">EXPIRED</option>
                      <option value="ASSIGNED">ASSIGNED</option>
                    </select>
                  </div>
                </div>

                {editForm.status !== 'OPEN' && (
                  <div>
                    <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">P&L Realizado</label>
                    <input type="number" step="0.01"
                      value={editForm.realized_pnl}
                      onChange={e => setEditForm({...editForm, realized_pnl: e.target.value})}
                      placeholder="Dejar vacío para calcular automáticamente"
                      className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    />
                  </div>
                )}

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Notas</label>
                  <input type="text"
                    value={editForm.notes}
                    onChange={e => setEditForm({...editForm, notes: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-gray-700 dark:text-gray-100"
                    placeholder="Opcional..."
                  />
                </div>

                {editForm.contracts && editForm.premium_per_contract && (
                  <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-3 text-sm">
                    <span className="text-gray-600 dark:text-gray-300">Prima total: </span>
                    <span className="font-bold text-blue-700 dark:text-blue-300">
                      ${(parseInt(editForm.contracts) * parseFloat(editForm.premium_per_contract) * 100).toFixed(2)}
                    </span>
                  </div>
                )}

                <div className="flex justify-end gap-3 pt-2">
                  <button type="button" onClick={() => setEditTarget(null)}
                    className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition dark:text-gray-300"
                  >
                    Cancelar
                  </button>
                  <button type="submit" disabled={editLoading}
                    className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-lg text-sm font-medium transition disabled:opacity-50"
                  >
                    {editLoading ? 'Guardando...' : 'Guardar cambios'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default Options;
