import { useEffect, useState, useCallback, useRef } from 'react'
import api from '../services/api'

interface NewsItem {
  id: string
  title: string
  summary: string
  publisher: string
  link: string
  published_at: string
  thumbnail: string | null
  ticker: string
}

type Tab = 'portfolio' | 'market' | 'chile'

const TAB_LABELS: Record<Tab, string> = {
  portfolio: '📊 Mi Portfolio',
  market:    '🌎 Mercado US',
  chile:     '🇨🇱 Mercado CL',
}

// ─── AI Analysis structured types ────────────────────────────────────────────

interface PortfolioImpact {
  ticker: string
  sentiment: 'positive' | 'neutral' | 'negative'
  text: string
}

interface AnalysisData {
  market_summary: string
  market_sentiment: 'bullish' | 'neutral' | 'bearish'
  portfolio_impact: PortfolioImpact[]
  covered_calls: { text: string; recommendation: 'sell' | 'wait' | 'caution' }
  dividends: string
  outlook: { text: string; direction: 'up' | 'flat' | 'down' }
}

const SENTIMENT_LABEL = { bullish: 'ALCISTA', neutral: 'NEUTRAL', bearish: 'BAJISTA' }
const SENTIMENT_COLORS = {
  bullish: 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
  neutral: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-700',
  bearish: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800',
}
const TICKER_SENTIMENT_DOT = {
  positive: 'bg-emerald-400',
  neutral:  'bg-gray-400',
  negative: 'bg-red-400',
}
const TICKER_SENTIMENT_COLORS = {
  positive: 'border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/20',
  neutral:  'border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800',
  negative: 'border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20',
}
const DIRECTION_CONFIG = {
  up:   { label: '▲ SUBE',  cls: 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300' },
  flat: { label: '● LATERAL', cls: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300' },
  down: { label: '▼ BAJA', cls: 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300' },
}
const CC_RECOMMENDATION = {
  sell:    { label: 'VENDER CALLS', cls: 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300' },
  wait:    { label: 'ESPERAR',      cls: 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300' },
  caution: { label: 'CON CAUTELA',  cls: 'bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300' },
}

function AnalysisPanel({ data }: { data: AnalysisData }) {
  return (
    <div className="space-y-3">
      {/* Market Summary */}
      <div className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 p-3">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-bold text-blue-700 dark:text-blue-300 uppercase tracking-wide">🌎 Resumen del Mercado</span>
          <span className={`px-2 py-0.5 rounded-full text-xs font-bold border ${SENTIMENT_COLORS[data.market_sentiment]}`}>
            {SENTIMENT_LABEL[data.market_sentiment]}
          </span>
        </div>
        <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{data.market_summary}</p>
      </div>

      {/* Portfolio Impact */}
      {data.portfolio_impact?.length > 0 && (
        <div className="rounded-lg border border-violet-200 dark:border-violet-800 bg-violet-50 dark:bg-violet-900/20 p-3">
          <span className="text-xs font-bold text-violet-700 dark:text-violet-300 uppercase tracking-wide block mb-2">📊 Impacto en el Portfolio</span>
          <div className="space-y-2">
            {data.portfolio_impact.map((item) => (
              <div key={item.ticker} className={`rounded-lg border p-2.5 ${TICKER_SENTIMENT_COLORS[item.sentiment]}`}>
                <div className="flex items-center gap-2 mb-1">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${TICKER_SENTIMENT_DOT[item.sentiment]}`} />
                  <span className="text-xs font-bold font-mono text-gray-900 dark:text-white">{item.ticker}</span>
                </div>
                <p className="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">{item.text}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Covered Calls */}
      <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-bold text-amber-700 dark:text-amber-300 uppercase tracking-wide">🎯 Covered Calls</span>
          {data.covered_calls?.recommendation && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${CC_RECOMMENDATION[data.covered_calls.recommendation].cls}`}>
              {CC_RECOMMENDATION[data.covered_calls.recommendation].label}
            </span>
          )}
        </div>
        <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{data.covered_calls?.text}</p>
      </div>

      {/* Dividends */}
      <div className="rounded-lg border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20 p-3">
        <span className="text-xs font-bold text-green-700 dark:text-green-300 uppercase tracking-wide block mb-1.5">💰 Dividendos</span>
        <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{data.dividends}</p>
      </div>

      {/* Outlook */}
      <div className="rounded-lg border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-900/20 p-3">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-bold text-indigo-700 dark:text-indigo-300 uppercase tracking-wide">📈 Outlook 2-5 días</span>
          {data.outlook?.direction && (
            <span className={`px-2 py-0.5 rounded-full text-xs font-bold ${DIRECTION_CONFIG[data.outlook.direction].cls}`}>
              {DIRECTION_CONFIG[data.outlook.direction].label}
            </span>
          )}
        </div>
        <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{data.outlook?.text}</p>
      </div>
    </div>
  )
}

function formatDate(raw: string): string {
  if (!raw) return ''
  try {
    const d = new Date(raw)
    if (isNaN(d.getTime())) return raw
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffH = Math.floor(diffMs / 3600000)
    if (diffH < 1) return 'Hace menos de 1h'
    if (diffH < 24) return `Hace ${diffH}h`
    const diffD = Math.floor(diffH / 24)
    if (diffD < 7) return `Hace ${diffD}d`
    return d.toLocaleDateString('es-CL', { day: '2-digit', month: 'short' })
  } catch {
    return raw
  }
}

function NewsCard({ item }: { item: NewsItem }) {
  return (
    <a
      href={item.link}
      target="_blank"
      rel="noopener noreferrer"
      className="flex gap-3 p-4 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 hover:border-blue-400 dark:hover:border-blue-500 hover:shadow-md transition-all group"
    >
      {item.thumbnail && (
        <img
          src={item.thumbnail}
          alt=""
          className="w-20 h-16 object-cover rounded-lg flex-shrink-0 bg-gray-100 dark:bg-gray-700"
          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
        />
      )}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-gray-900 dark:text-white line-clamp-2 group-hover:text-blue-600 dark:group-hover:text-blue-400 leading-snug">
          {item.title}
        </p>
        {item.summary && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-2 leading-relaxed">
            {item.summary}
          </p>
        )}
        <div className="flex items-center gap-2 mt-2 flex-wrap">
          {item.ticker && item.ticker !== 'CL' && (
            <span className="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 text-xs font-mono font-bold">
              {item.ticker}
            </span>
          )}
          {item.publisher && (
            <span className="text-xs text-gray-500 dark:text-gray-400 truncate max-w-[150px]">
              {item.publisher}
            </span>
          )}
          <span className="text-xs text-gray-400 dark:text-gray-500 ml-auto whitespace-nowrap">
            {formatDate(item.published_at)}
          </span>
        </div>
      </div>
    </a>
  )
}

function SkeletonCard() {
  return (
    <div className="flex gap-3 p-4 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 animate-pulse">
      <div className="w-20 h-16 rounded-lg bg-gray-200 dark:bg-gray-700 flex-shrink-0" />
      <div className="flex-1 space-y-2">
        <div className="h-4 bg-gray-200 dark:bg-gray-700 rounded w-full" />
        <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-3/4" />
        <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded w-1/2" />
      </div>
    </div>
  )
}

interface AnalysisResult extends AnalysisData {
  tickers: string[]
  news_count: number
  generated_at: string
  cached: boolean
}

export default function News() {
  const [tab, setTab] = useState<Tab>('portfolio')
  const [news, setNews] = useState<NewsItem[]>([])
  const [tickers, setTickers] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null)
  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisError, setAnalysisError] = useState<string | null>(null)
  const [showAnalysis, setShowAnalysis] = useState(false)
  const analysisRef = useRef<HTMLDivElement>(null)

  const authHeaders = () => {
    const token = localStorage.getItem('token')
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  const fetchNews = useCallback(async (t: Tab) => {
    setLoading(true)
    setError(null)
    try {
      const endpoint =
        t === 'portfolio' ? '/api/news/portfolio'
        : t === 'market'  ? '/api/news/market'
        :                   '/api/news/chile'

      const { data } = await api.get(endpoint, { headers: authHeaders() })
      setNews(data.news || [])
      setTickers(data.tickers || [])
      setLastUpdated(new Date())
    } catch {
      setError('No se pudo cargar las noticias. Intenta nuevamente.')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchAnalysis = useCallback(async () => {
    setAnalysisLoading(true)
    setAnalysisError(null)
    try {
      const { data } = await api.get('/api/news/analysis', { headers: authHeaders(), timeout: 50000 })
      setAnalysis(data)
      setShowAnalysis(true)
      setTimeout(() => analysisRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 100)
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Error al obtener el análisis. Intentá de nuevo.'
      setAnalysisError(msg)
    } finally {
      setAnalysisLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchNews(tab)
  }, [tab, fetchNews])

  return (
    <div className="px-4 sm:px-6 py-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Noticias</h1>
          {lastUpdated && (
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
              Actualizado: {lastUpdated.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' })}
              {' · '}cache 15 min
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => fetchNews(tab)}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
          >
            <svg className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Actualizar
          </button>
          <button
            onClick={fetchAnalysis}
            disabled={analysisLoading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold rounded-lg bg-violet-600 hover:bg-violet-700 text-white transition-colors disabled:opacity-60 shadow-sm"
          >
            {analysisLoading ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                Analizando…
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
                Análisis IA
              </>
            )}
          </button>
        </div>
      </div>

      {/* AI Analysis panel */}
      {(showAnalysis || analysisLoading || analysisError) && (
        <div ref={analysisRef} className="mb-6 rounded-xl border border-violet-200 dark:border-violet-800 bg-violet-50 dark:bg-violet-900/20 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 bg-violet-100 dark:bg-violet-900/40 border-b border-violet-200 dark:border-violet-800">
            <div className="flex items-center gap-2">
              <span className="text-violet-700 dark:text-violet-300 font-semibold text-sm">🤖 Análisis DeepSeek</span>
              {analysis?.cached && (
                <span className="px-1.5 py-0.5 rounded text-xs bg-violet-200 dark:bg-violet-800 text-violet-700 dark:text-violet-300">
                  cache
                </span>
              )}
              {analysis && (
                <span className="text-xs text-violet-500 dark:text-violet-400">
                  {analysis.news_count} noticias · {analysis.generated_at}
                </span>
              )}
            </div>
            <button
              onClick={() => { setShowAnalysis(false); setAnalysisError(null) }}
              className="text-violet-400 hover:text-violet-600 dark:hover:text-violet-200 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="px-4 py-4">
            {analysisLoading && (
              <div className="flex items-center gap-3 text-violet-600 dark:text-violet-400">
                <svg className="w-5 h-5 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                <p className="text-sm">DeepSeek está analizando las noticias del día… puede tomar hasta 30 segundos.</p>
              </div>
            )}
            {analysisError && (
              <p className="text-sm text-red-600 dark:text-red-400">{analysisError}</p>
            )}
            {analysis && !analysisLoading && (
              <AnalysisPanel data={analysis} />
            )}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-5 bg-gray-100 dark:bg-gray-800 rounded-xl p-1">
        {(Object.keys(TAB_LABELS) as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-all ${
              tab === t
                ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm'
                : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
            }`}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* Portfolio tickers badge */}
      {tab === 'portfolio' && tickers.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap mb-4">
          <span className="text-xs text-gray-500 dark:text-gray-400">Siguiendo:</span>
          {tickers.map(t => (
            <span key={t} className="px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 text-xs font-mono font-bold">
              {t}
            </span>
          ))}
        </div>
      )}

      {/* Content */}
      {error ? (
        <div className="text-center py-12 text-red-500 dark:text-red-400">
          <svg className="w-10 h-10 mx-auto mb-3 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-sm">{error}</p>
        </div>
      ) : loading ? (
        <div className="space-y-3">
          {Array.from({ length: 8 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : news.length === 0 ? (
        <div className="text-center py-16 text-gray-400 dark:text-gray-500">
          <svg className="w-12 h-12 mx-auto mb-4 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9a2 2 0 00-2-2h-2m-4-3H9M7 16h6M7 8h6v4H7V8z" />
          </svg>
          <p className="text-sm font-medium">Sin noticias disponibles</p>
          {tab === 'portfolio' && (
            <p className="text-xs mt-1">Agrega acciones a tu portfolio para ver noticias relacionadas</p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {news.map((item, idx) => (
            <NewsCard key={item.id || idx} item={item} />
          ))}
        </div>
      )}
    </div>
  )
}
