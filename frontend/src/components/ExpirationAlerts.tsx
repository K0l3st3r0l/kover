import { useEffect, useState } from 'react'
import api from '../services/api'
import { Link } from 'react-router-dom'

interface ExpiringOption {
  id: number
  ticker: string
  option_type: string
  strategy: string
  strike_price: number
  contracts: number
  expiration_date: string
  days_to_expiration: number
  total_premium: number
  current_price?: number
}

function ExpirationAlerts() {
  const [expiringOptions, setExpiringOptions] = useState<ExpiringOption[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchExpiringOptions()
  }, [])

  const fetchExpiringOptions = async () => {
    try {
      const response = await api.get('/api/options/expiring-soon?days=7')
      setExpiringOptions(response.data)
    } catch (error) {
      console.error('Error fetching expiring options:', error)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return null

  if (expiringOptions.length === 0) return null

  const getUrgencyColor = (days: number) => {
    if (days <= 2) return 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-700'
    if (days <= 5) return 'bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-700'
    return 'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-700'
  }

  const getUrgencyTextColor = (days: number) => {
    if (days <= 2) return 'text-red-800 dark:text-red-300'
    if (days <= 5) return 'text-orange-800 dark:text-orange-300'
    return 'text-yellow-800 dark:text-yellow-300'
  }

  const getUrgencyIcon = (days: number) => {
    if (days <= 2) return '🚨'
    if (days <= 5) return '⚠️'
    return '⏰'
  }

  const renderSuggestion = (option: ExpiringOption) => {
    if (option.current_price === undefined || option.current_price === null) return null;

    const { strategy, strike_price, current_price, ticker } = option;
    
    // Para Covered Calls
    if (strategy === 'COVERED_CALL') {
      if (current_price < strike_price) {
        return (
          <div className="pt-3 border-t border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50 p-3">
            <div className="flex items-start">
              <span className="text-blue-500 mr-2">🤖</span>
              <div>
                <span className="text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Sugerencia (OTM):</span>
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                  {ticker} cotiza a <strong>${current_price.toFixed(2)}</strong>, por debajo de tu strike (${strike_price}). <strong>Recomendación: Dejar expirar.</strong> Ahorrarás comisiones, conservarás tus acciones y tu prima total.
                </p>
              </div>
            </div>
          </div>
        );
      } else {
        return (
          <div className="pt-3 border-t border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50 p-3">
            <div className="flex items-start">
              <span className="text-blue-500 mr-2">🤖</span>
              <div>
                <span className="text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Sugerencia (ITM):</span>
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                  {ticker} cotiza a <strong>${current_price.toFixed(2)}</strong>, por encima de tu strike (${strike_price}). Si deseas conservar tus acciones, considera <strong>hacer un Roll</strong>. Si estás conforme con la ganancia, no hagas nada (se venderán a ${strike_price}).
                </p>
              </div>
            </div>
          </div>
        );
      }
    }

    // Para Cash Secured Puts
    if (strategy === 'CASH_SECURED_PUT') {
      if (current_price > strike_price) {
        return (
          <div className="pt-3 border-t border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50 p-3">
            <div className="flex items-start">
              <span className="text-blue-500 mr-2">🤖</span>
              <div>
                <span className="text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Sugerencia (OTM):</span>
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                  {ticker} cotiza a <strong>${current_price.toFixed(2)}</strong>, por encima de tu strike (${strike_price}). <strong>Recomendación: Dejar expirar.</strong> Conservarás el 100% de la prima y no serás asignado.
                </p>
              </div>
            </div>
          </div>
        );
      } else {
        return (
          <div className="pt-3 border-t border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50 p-3">
            <div className="flex items-start">
              <span className="text-blue-500 mr-2">🤖</span>
              <div>
                <span className="text-xs font-bold text-gray-700 dark:text-gray-300 uppercase tracking-wider">Sugerencia (ITM):</span>
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                  {ticker} cotiza a <strong>${current_price.toFixed(2)}</strong>, por debajo de tu strike (${strike_price}). Serás asignado (comprarás 100 acciones x contrato a ${strike_price}). Considera <strong>hacer un Roll</strong> si prefieres evitar la asignación.
                </p>
              </div>
            </div>
          </div>
        );
      }
    }

    return null;
  }

  return (
    <div className={`border rounded-lg p-4 mb-6 ${getUrgencyColor(Math.min(...expiringOptions.map(o => o.days_to_expiration)))}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h3 className={`text-lg font-semibold mb-2 ${getUrgencyTextColor(Math.min(...expiringOptions.map(o => o.days_to_expiration)))}`}>
            {getUrgencyIcon(Math.min(...expiringOptions.map(o => o.days_to_expiration)))} Opciones Próximas a Vencer
          </h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
            Tienes {expiringOptions.length} {expiringOptions.length === 1 ? 'opción' : 'opciones'} que {expiringOptions.length === 1 ? 'vence' : 'vencen'} en los próximos 7 días
          </p>
          
          <div className="space-y-3">
            {expiringOptions.map((option) => (
              <div
                key={option.id}
                className="bg-white dark:bg-gray-800 rounded-md shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden flex flex-col"
              >
                <div className="p-3 flex items-center justify-between">
                  <div className="flex items-center space-x-4">
                    <span className="text-2xl">{getUrgencyIcon(option.days_to_expiration)}</span>
                    <div>
                      <div className="font-semibold text-gray-900 dark:text-gray-100">
                        {option.ticker} - ${option.strike_price} {option.option_type}
                      </div>
                      <div className="text-sm text-gray-600 dark:text-gray-400">
                        {option.contracts} {option.contracts === 1 ? 'contrato' : 'contratos'} •
                        {option.strategy === 'COVERED_CALL' ? ' Covered Call' : ' Cash Secured Put'}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className={`text-lg font-bold ${getUrgencyTextColor(option.days_to_expiration)}`}>
                      {option.days_to_expiration === 0 ? 'HOY' :
                       option.days_to_expiration === 1 ? 'MAÑANA' :
                       `${option.days_to_expiration} días`}
                    </div>
                    <div className="text-sm text-gray-500 dark:text-gray-400">
                      {(() => {
                        const [y, m, d] = option.expiration_date.split('T')[0].split('-').map(Number);
                        return new Date(y, m - 1, d).toLocaleDateString('es-CL', { month: 'short', day: 'numeric' });
                      })()}
                    </div>
                  </div>
                </div>
                {renderSuggestion(option)}
              </div>
            ))}
          </div>
        </div>
      </div>
      
      <div className="mt-4 flex justify-end">
        <Link 
          to="/options" 
          className="text-sm font-medium text-blue-600 hover:text-blue-800 transition"
        >
          Ver todas las opciones →
        </Link>
      </div>
    </div>
  )
}

export default ExpirationAlerts
