import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts'

interface BenchmarkData {
  date: string
  portfolio_return: number
  sp500_return: number
  outperformance: number
}

interface BenchmarkChartProps {
  data: BenchmarkData[]
  height?: number
}

function BenchmarkChart({ data, height = 400 }: BenchmarkChartProps) {
  const formatPercent = (value: number) => {
    return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white dark:bg-gray-800 p-4 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700">
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">
            {new Date(label).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
          </p>
          {payload.map((entry: any, index: number) => (
            <p key={index} className="text-sm font-medium" style={{ color: entry.color }}>
              {entry.name}: {formatPercent(entry.value)}
            </p>
          ))}
        </div>
      )
    }
    return null
  }

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-gray-500 dark:text-gray-400">No data available</p>
      </div>
    )
  }

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" className="dark:stroke-gray-700" />
          <XAxis 
            dataKey="date" 
            tickFormatter={formatDate}
            stroke="#6b7280"
            className="dark:stroke-gray-400"
            style={{ fontSize: '12px' }}
          />
          <YAxis 
            tickFormatter={formatPercent}
            stroke="#6b7280"
            className="dark:stroke-gray-400"
            style={{ fontSize: '12px' }}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend 
            wrapperStyle={{ paddingTop: '20px' }}
            iconType="line"
          />
          <Line 
            type="monotone" 
            dataKey="portfolio_return" 
            stroke="#3b82f6" 
            strokeWidth={3}
            name="Your Portfolio"
            dot={false}
            activeDot={{ r: 6 }}
          />
          <Line 
            type="monotone" 
            dataKey="sp500_return" 
            stroke="#f59e0b" 
            strokeWidth={2}
            name="S&P 500"
            dot={false}
            strokeDasharray="5 5"
          />
          <Line 
            type="monotone" 
            dataKey="outperformance" 
            stroke="#10b981" 
            strokeWidth={2}
            name="Outperformance"
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export default BenchmarkChart
