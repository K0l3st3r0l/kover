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
    if (days <= 2) return 'bg-red-50 border-red-200'
    if (days <= 5) return 'bg-orange-50 border-orange-200'
    return 'bg-yellow-50 border-yellow-200'
  }

  const getUrgencyTextColor = (days: number) => {
    if (days <= 2) return 'text-red-800'
    if (days <= 5) return 'text-orange-800'
    return 'text-yellow-800'
  }

  const getUrgencyIcon = (days: number) => {
    if (days <= 2) return '🚨'
    if (days <= 5) return '⚠️'
    return '⏰'
  }

  return (
    <div className={`border rounded-lg p-4 mb-6 ${getUrgencyColor(Math.min(...expiringOptions.map(o => o.days_to_expiration)))}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h3 className={`text-lg font-semibold mb-2 ${getUrgencyTextColor(Math.min(...expiringOptions.map(o => o.days_to_expiration)))}`}>
            {getUrgencyIcon(Math.min(...expiringOptions.map(o => o.days_to_expiration)))} Opciones Próximas a Vencer
          </h3>
          <p className="text-sm text-gray-600 mb-3">
            Tienes {expiringOptions.length} {expiringOptions.length === 1 ? 'opción' : 'opciones'} que {expiringOptions.length === 1 ? 'vence' : 'vencen'} en los próximos 7 días
          </p>
          
          <div className="space-y-2">
            {expiringOptions.map((option) => (
              <div 
                key={option.id} 
                className="bg-white rounded-md p-3 shadow-sm flex items-center justify-between"
              >
                <div className="flex items-center space-x-4">
                  <span className="text-2xl">{getUrgencyIcon(option.days_to_expiration)}</span>
                  <div>
                    <div className="font-semibold text-gray-900">
                      {option.ticker} - ${option.strike_price} {option.option_type}
                    </div>
                    <div className="text-sm text-gray-600">
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
                  <div className="text-sm text-gray-500">
                    {(() => {
                      const [y, m, d] = option.expiration_date.split('T')[0].split('-').map(Number);
                      return new Date(y, m - 1, d).toLocaleDateString('es-CL', { month: 'short', day: 'numeric' });
                    })()}
                  </div>
                </div>
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
