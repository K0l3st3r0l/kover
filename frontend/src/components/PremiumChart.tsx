import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

interface PremiumTimelineData {
  month: string
  calls: number
  puts: number
  total: number
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
    }).format(value)
  }

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white p-4 rounded-lg shadow-lg border border-gray-200">
          <p className="text-sm font-bold text-gray-800 mb-2">{label}</p>
          {payload.map((entry: any, index: number) => (
            <p key={index} className="text-sm font-medium" style={{ color: entry.color }}>
              {entry.name}: {formatCurrency(entry.value)}
            </p>
          ))}
          <p className="text-sm font-bold text-gray-800 mt-1 pt-1 border-t border-gray-200">
            Total: {formatCurrency(payload.reduce((sum: number, entry: any) => sum + entry.value, 0))}
          </p>
        </div>
      )
    }
    return null
  }

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-gray-500">No premium data available</p>
      </div>
    )
  }

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis 
            dataKey="month"
            stroke="#6b7280"
            style={{ fontSize: '12px' }}
          />
          <YAxis 
            tickFormatter={formatCurrency}
            stroke="#6b7280"
            style={{ fontSize: '12px' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend 
            wrapperStyle={{ paddingTop: '10px' }}
          />
          <Bar dataKey="calls" fill="#3b82f6" name="Covered Calls" stackId="a" />
          <Bar dataKey="puts" fill="#10b981" name="Cash Secured Puts" stackId="a" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default PremiumChart
