import { useEffect, useRef, memo, useId } from 'react'
import { useTheme } from '../contexts/ThemeContext'

interface TradingViewChartProps {
  ticker: string
  height?: number
  interval?: string
}

function TradingViewChart({ ticker, height = 500, interval = 'D' }: TradingViewChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const { isDark } = useTheme()
  const uid = useId().replace(/:/g, '_')
  const containerId = `tv_${ticker.replace(/[^a-zA-Z0-9]/g, '_')}_${uid}`

  useEffect(() => {
    if (!containerRef.current) return

    // Clear previous widget
    containerRef.current.innerHTML = ''

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/tv.js'
    script.async = true
    script.onload = () => {
      if (typeof (window as any).TradingView !== 'undefined') {
        new (window as any).TradingView.widget({
          autosize: true,
          symbol: ticker,
          interval: interval,
          timezone: 'America/Santiago',
          theme: isDark ? 'dark' : 'light',
          style: '1', // 1 = Candlestick
          locale: 'es',
          toolbar_bg: isDark ? '#1F2937' : '#f1f3f6',
          enable_publishing: false,
          allow_symbol_change: true,
          container_id: containerId,
          hide_side_toolbar: false,
          studies: [
            'MASimple@tv-basicstudies',
            'RSI@tv-basicstudies'
          ],
          show_popup_button: true,
          popup_width: '1000',
          popup_height: '650'
        })
      }
    }

    containerRef.current.appendChild(script)

    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = ''
      }
    }
  }, [ticker, isDark, interval, containerId])

  return (
    <div className="tradingview-widget-container">
      <div 
        id={containerId}
        ref={containerRef} 
        style={{ height: `${height}px`, width: '100%' }}
      />
    </div>
  )
}

export default memo(TradingViewChart)
