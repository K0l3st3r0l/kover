import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts'

interface PremiumTimelineData {
  month: string
  calls: number
  puts: number
  buybacks: number
  total: number
  net: number
}

interface PremiumChartProps {
  data: PremiumTimelineData[]
  height?: number
}

function PremiumChart({ data, height = 300 }: PremiumChartProps) {
  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(Math.abs(value))
  }

  // Buybacks se muestran como negativos en el gráfico
  const chartData = data.map(d => ({ ...d, buybacks_bar: d.buybacks > 0 ? -d.buybacks : 0 }))

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const d = data.find(x => x.month === label)
      if (!d) return null
      return (
        <div className="bg-white p-4 rounded-lg shadow-lg border border-gray-200">
          <p className="text-sm font-bold text-gray-800 mb-2">{label}</p>
          {d.calls > 0 && (
            <p className="text-sm font-medium text-blue-600">Covered Calls: +{formatCurrency(d.calls)}</p>
          )}
          {d.puts > 0 && (
            <p className="text-sm font-medium text-emerald-600">Cash Secured Puts: +{formatCurrency(d.puts)}</p>
          )}
          {d.buybacks > 0 && (
            <p className="text-sm font-medium text-red-500">Cierres/Buybacks: -{formatCurrency(d.buybacks)}</p>
          )}
          <div className="mt-1 pt-1 border-t border-gray-200">
            <p className="text-sm text-gray-500">Bruto cobrado: +{formatCurrency(d.total)}</p>
            <p className="text-sm font-bold text-gray-800">Prima neta: +{formatCurrency(d.net)}</p>
          </div>
        </div>
      )
    }
    return null
  }

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-gray-500">No hay datos de primas</p>
      </div>
    )
  }

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={chartData} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis 
            dataKey="month"
            stroke="#6b7280"
            style={{ fontSize: '12px' }}
          />
          <YAxis 
            tickFormatter={(v) => formatCurrency(v)}
            stroke="#6b7280"
            style={{ fontSize: '12px' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend wrapperStyle={{ paddingTop: '10px' }} />
          <ReferenceLine y={0} stroke="#9ca3af" />
          <Bar dataKey="calls" fill="#3b82f6" name="Covered Calls" stackId="a" />
          <Bar dataKey="puts" fill="#10b981" name="Cash Secured Puts" stackId="a" />
          <Bar dataKey="buybacks_bar" fill="#ef4444" name="Cierres/Buybacks" stackId="b" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default PremiumChart
