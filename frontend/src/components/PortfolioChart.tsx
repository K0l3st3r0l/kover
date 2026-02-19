import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

interface PortfolioHistoryData {
  date: string
  portfolio_value: number
  invested: number
  pnl: number
}

interface PortfolioChartProps {
  data: PortfolioHistoryData[]
  height?: number
}

function PortfolioChart({ data, height = 400 }: PortfolioChartProps) {
  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(value)
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white p-4 rounded-lg shadow-lg border border-gray-200">
          <p className="text-sm text-gray-600 mb-2">{new Date(label).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}</p>
          {payload.map((entry: any, index: number) => (
            <p key={index} className="text-sm font-medium" style={{ color: entry.color }}>
              {entry.name}: {formatCurrency(entry.value)}
            </p>
          ))}
        </div>
      )
    }
    return null
  }

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis 
            dataKey="date" 
            tickFormatter={formatDate}
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
            wrapperStyle={{ paddingTop: '20px' }}
            iconType="line"
          />
          <Line 
            type="monotone" 
            dataKey="portfolio_value" 
            stroke="#3b82f6" 
            strokeWidth={3}
            name="Portfolio Value"
            dot={false}
            activeDot={{ r: 6 }}
          />
          <Line 
            type="monotone" 
            dataKey="invested" 
            stroke="#ef4444" 
            strokeWidth={2}
            strokeDasharray="5 5"
            name="Invested"
            dot={false}
          />
          <Line 
            type="monotone" 
            dataKey="pnl" 
            stroke="#10b981" 
            strokeWidth={2}
            name="P&L"
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default PortfolioChart
