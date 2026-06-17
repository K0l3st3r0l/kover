import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import {
  LineChart,
  BarChart,
  Bar,
  Line,
  ReferenceDot,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { format, parseISO } from 'date-fns'
import { es } from 'date-fns/locale'
import TradingViewChart from '../components/TradingViewChart'
import api from '../services/api'

// ─── Types ────────────────────────────────────────────────────────────────────

interface FundDataPoint {
  date: string
  value: number      // normalised (base 100)
  raw_value: number
  patrimonio: number // total system patrimonio (MM CLP)
  obv: number        // on-balance volume
}

interface FundSeries {
  color: string
  risk_label: string
  data: FundDataPoint[]
}

interface AFPResponse {
  funds: Record<string, FundSeries>
  period_days: number
  errors: string[]
  source: string
}

// ─── Period options ────────────────────────────────────────────────────────────

const PERIODS: { label: string; days: number }[] = [
  { label: '1M',  days: 30   },
  { label: '3M',  days: 90   },
  { label: '6M',  days: 180  },
  { label: '1A',  days: 365  },
  { label: '3A',  days: 1095 },
  { label: '5A',  days: 1825 },
  { label: 'Max', days: 5000 },
]

const FUND_NAMES: Record<string, string> = {
  A: 'Fondo A',
  B: 'Fondo B',
  C: 'Fondo C',
  D: 'Fondo D',
  E: 'Fondo E',
}

// ─── AFP Chart ────────────────────────────────────────────────────────────────

function formatDate(dateStr: string) {
  try {
    return format(parseISO(dateStr), 'dd MMM yy', { locale: es })
  } catch {
    return dateStr
  }
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ChileanMarkets() {
  const [afpData, setAfpData] = useState<AFPResponse | null>(null)
  const [afpLoading, setAfpLoading] = useState(false)
  const [afpError, setAfpError] = useState<string | null>(null)
  const [selectedDays, setSelectedDays] = useState(365)
  const [chartData, setChartData] = useState<any[]>([])
  const [activeFunds, setActiveFunds] = useState<Set<string>>(new Set(['A', 'B', 'C', 'D', 'E']))
  const [patrimonioChartData, setPatrimonioChartData] = useState<any[]>([])
  const [showPatrimonio, setShowPatrimonio] = useState(true)
  const [showOBV, setShowOBV] = useState(true)
  const [showDivergences, setShowDivergences] = useState(true)
  // 'rent' | 'pat' | 'obv' | null
  const [maximized, setMaximized] = useState<'rent' | 'pat' | 'obv' | null>(null)
  const [signalChartData, setSignalChartData] = useState<any[]>([])
  const [macroData, setMacroData] = useState<any>(null)
  const [aiCommittee, setAiCommittee] = useState<any>(null)
  const [currentAllocation, setCurrentAllocation] = useState<Record<string, number>>(() => {
    try {
      const saved = localStorage.getItem('afp-current-allocation')
      return saved ? JSON.parse(saved) : { A: 0, B: 0, C: 0, D: 0, E: 100 }
    } catch { return { A: 0, B: 0, C: 0, D: 0, E: 100 } }
  })
  const [editingAllocation, setEditingAllocation] = useState(false)
  const saveAllocationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastSavedRef = useRef<string>(JSON.stringify(currentAllocation))

  const fetchAFP = useCallback(async (days: number) => {
    setAfpLoading(true)
    setAfpError(null)
    try {
      const res = await api.get<AFPResponse>(`/api/market/afp-funds?days=${days}`)
      setAfpData(res.data)

      // Build unified rentabilidad chart data: one row per date (includes obv_X keys)
      const dateMap = new Map<string, any>()
      // Build patrimonio chart data
      const patDateMap = new Map<string, any>()
      for (const [fund, series] of Object.entries(res.data.funds)) {
        for (const point of series.data) {
          if (!dateMap.has(point.date)) {
            dateMap.set(point.date, { date: point.date })
          }
          dateMap.get(point.date)[fund] = point.value
          dateMap.get(point.date)[`obv_${fund}`] = point.obv

          if (!patDateMap.has(point.date)) {
            patDateMap.set(point.date, { date: point.date })
          }
          patDateMap.get(point.date)[fund] = point.patrimonio
        }
      }
      const sorted = Array.from(dateMap.values()).sort(
        (a, b) => a.date.localeCompare(b.date)
      )
      setChartData(sorted)
      const sortedPat = Array.from(patDateMap.values()).sort(
        (a, b) => a.date.localeCompare(b.date)
      )
      setPatrimonioChartData(sortedPat)
    } catch (e: any) {
      setAfpError(e?.response?.data?.detail ?? 'Error al cargar datos AFP')
    } finally {
      setAfpLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAFP(selectedDays)
  }, [selectedDays, fetchAFP])

  useEffect(() => {
    try { localStorage.setItem('afp-current-allocation', JSON.stringify(currentAllocation)) } catch {}

    // Persistir en backend (debounced 600ms) — fuente de verdad para que la posición
    // se mantenga entre dispositivos y sesiones de login.
    const serialized = JSON.stringify(currentAllocation)
    if (serialized === lastSavedRef.current) return
    if (saveAllocationTimerRef.current) clearTimeout(saveAllocationTimerRef.current)
    saveAllocationTimerRef.current = setTimeout(async () => {
      try {
        await api.put('/api/auth/afp-allocation', { allocation: currentAllocation })
        lastSavedRef.current = serialized
      } catch {
        // silencioso: si falla (no auth, red), localStorage sigue siendo cache
      }
    }, 600)
    return () => {
      if (saveAllocationTimerRef.current) clearTimeout(saveAllocationTimerRef.current)
    }
  }, [currentAllocation])

  // Cargar desde backend al montar — el backend pisa localStorage si tiene valor.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await api.get<{ allocation: Record<string, number> | null }>('/api/auth/afp-allocation')
        if (cancelled) return
        if (res.data?.allocation && Object.keys(res.data.allocation).length > 0) {
          setCurrentAllocation(res.data.allocation)
          lastSavedRef.current = JSON.stringify(res.data.allocation)
        }
      } catch {
        // sin token o sin backend: mantener lo que haya en localStorage
      }
    })()
    return () => { cancelled = true }
  }, [])

  // Full-history data for signal computation (independent of display period)
  const fetchSignalData = useCallback(async () => {
    try {
      const res = await api.get<AFPResponse>('/api/market/afp-funds?days=5000')
      const dateMap = new Map<string, any>()
      for (const [fund, series] of Object.entries(res.data.funds)) {
        for (const point of series.data) {
          if (!dateMap.has(point.date)) dateMap.set(point.date, { date: point.date })
          dateMap.get(point.date)[fund] = point.value
          dateMap.get(point.date)[`obv_${fund}`] = point.obv
        }
      }
      setSignalChartData(Array.from(dateMap.values()).sort((a, b) => a.date.localeCompare(b.date)))
    } catch {}
  }, [])

  const fetchMacro = useCallback(async () => {
    try {
      const res = await api.get('/api/market/macro-cl')
      setMacroData(res.data)
    } catch {}
  }, [])

  const fetchAiCommittee = useCallback(async () => {
    try {
      const res = await api.get('/api/market/ai-committee')
      setAiCommittee(res.data)
    } catch {}
  }, [])

  useEffect(() => {
    fetchSignalData()
    fetchMacro()
    fetchAiCommittee()
  }, [fetchSignalData, fetchMacro, fetchAiCommittee])

  const toggleFund = (fund: string) => {
    setActiveFunds(prev => {
      const next = new Set(prev)
      if (next.has(fund)) {
        if (next.size > 1) next.delete(fund)
      } else {
        next.add(fund)
      }
      return next
    })
  }

  const handleDoubleClick = (pane: 'rent' | 'pat' | 'obv') => {
    setMaximized(prev => (prev === pane ? null : pane))
  }

  const paneHeight = (pane: 'rent' | 'pat' | 'obv', defaultH: number) => {
    if (maximized === null) return defaultH
    return maximized === pane ? 560 : 0
  }

  const paneVisible = (pane: 'rent' | 'pat' | 'obv') => {
    if (maximized !== null) return maximized === pane
    if (pane === 'pat') return showPatrimonio
    if (pane === 'obv') return showOBV
    return true
  }

  const fmtBig = (v: number) => {
    const abs = Math.abs(v)
    if (abs >= 1e12) return `${(v / 1e12).toFixed(1)}T`
    if (abs >= 1e9)  return `${(v / 1e9).toFixed(1)}B`
    if (abs >= 1e6)  return `${(v / 1e6).toFixed(1)}M`
    return v.toFixed(0)
  }

  const funds = afpData?.funds ?? {}
  const fundKeys = Object.keys(funds).sort()

  // OBV extremes for the display period (chart markers)
  const obvExtremes = useMemo(() => {
    if (!chartData.length) return []
    const result: { fund: string; maxDate: string; maxVal: number; minDate: string; minVal: number }[] = []
    for (const fund of fundKeys.filter(f => activeFunds.has(f))) {
      const key = `obv_${fund}`
      let maxVal = -Infinity, minVal = Infinity
      let maxDate = '', minDate = ''
      for (const row of chartData) {
        const v = row[key]
        if (v === undefined || v === null) continue
        if (v > maxVal) { maxVal = v; maxDate = row.date }
        if (v < minVal) { minVal = v; minDate = row.date }
      }
      if (maxDate) result.push({ fund, maxDate, maxVal, minDate, minVal })
    }
    return result
  }, [chartData, fundKeys, activeFunds])

  // OBV extremes over full history (for signal scoring)
  const signalObvExtremes = useMemo(() => {
    const data = signalChartData.length ? signalChartData : chartData
    if (!data.length) return []
    const result: { fund: string; maxVal: number; minVal: number }[] = []
    for (const fund of fundKeys) {
      const key = `obv_${fund}`
      let maxVal = -Infinity, minVal = Infinity
      for (const row of data) {
        const v = row[key]
        if (v === undefined || v === null) continue
        if (v > maxVal) maxVal = v
        if (v < minVal) minVal = v
      }
      if (maxVal !== -Infinity) result.push({ fund, maxVal, minVal })
    }
    return result
  }, [signalChartData, chartData, fundKeys])

  // Divergence detection (hidden + regular, bearish + bullish)
  type DivType = 'hidden_bearish' | 'hidden_bullish' | 'regular_bearish' | 'regular_bullish'
  interface Divergence { type: DivType; fund: string; date: string; obv: number }

  const divergences = useMemo((): Divergence[] => {
    const data = signalChartData.length ? signalChartData : chartData
    if (!data.length) return []
    const WIN = Math.max(5, Math.floor(data.length / 20))
    const result: Divergence[] = []

    for (const fund of fundKeys.filter(f => activeFunds.has(f))) {
      const priceKey = fund
      const obvKey = `obv_${fund}`

      const swingHighs: { date: string; price: number; obv: number }[] = []
      for (let i = WIN; i < data.length - WIN; i++) {
        const price = data[i][priceKey]
        const obv   = data[i][obvKey]
        if (price == null || obv == null) continue
        let isHigh = true
        for (let j = i - WIN; j <= i + WIN; j++) {
          if (j !== i && (data[j][priceKey] ?? -Infinity) >= price) { isHigh = false; break }
        }
        if (isHigh) swingHighs.push({ date: data[i].date, price, obv })
      }

      const swingLows: { date: string; price: number; obv: number }[] = []
      for (let i = WIN; i < data.length - WIN; i++) {
        const price = data[i][priceKey]
        const obv   = data[i][obvKey]
        if (price == null || obv == null) continue
        let isLow = true
        for (let j = i - WIN; j <= i + WIN; j++) {
          if (j !== i && (data[j][priceKey] ?? Infinity) <= price) { isLow = false; break }
        }
        if (isLow) swingLows.push({ date: data[i].date, price, obv })
      }

      for (let i = 1; i < swingHighs.length; i++) {
        const prev = swingHighs[i - 1], curr = swingHighs[i]
        if (curr.price < prev.price && curr.obv > prev.obv)
          result.push({ type: 'hidden_bearish',  fund, date: curr.date, obv: curr.obv })
        if (curr.price > prev.price && curr.obv < prev.obv)
          result.push({ type: 'regular_bearish', fund, date: curr.date, obv: curr.obv })
      }

      for (let i = 1; i < swingLows.length; i++) {
        const prev = swingLows[i - 1], curr = swingLows[i]
        if (curr.price > prev.price && curr.obv < prev.obv)
          result.push({ type: 'hidden_bullish',  fund, date: curr.date, obv: curr.obv })
        if (curr.price < prev.price && curr.obv > prev.obv)
          result.push({ type: 'regular_bullish', fund, date: curr.date, obv: curr.obv })
      }
    }
    return result
  }, [signalChartData, chartData, fundKeys, activeFunds])

  // Only divergences within the displayed date range (for OBV chart markers)
  const displayDivergences = useMemo(() => {
    if (!chartData.length || !divergences.length) return []
    const minDate = chartData[0].date
    const maxDate = chartData[chartData.length - 1].date
    return divergences.filter(d => d.date >= minDate && d.date <= maxDate)
  }, [divergences, chartData])

  const DIV_META: Record<DivType, { color: string; label: string; pos: 'top' | 'bottom' }> = {
    hidden_bearish:  { color: '#f97316', label: '▼ Div.O.Baj', pos: 'bottom' },
    hidden_bullish:  { color: '#22c55e', label: '▲ Div.O.Alc', pos: 'top'    },
    regular_bearish: { color: '#ef4444', label: '▼ Div.Baj',   pos: 'bottom' },
    regular_bullish: { color: '#3b82f6', label: '▲ Div.Alc',   pos: 'top'    },
  }

  // ─── Signal computation ────────────────────────────────────────────────────
  type SignalLevel = 'alcista' | 'neutro' | 'bajista'
  interface FundSignal {
    fund: string
    mom30d: number
    drawdown: number
    obvPos: 'alto' | 'medio' | 'bajo'
    lastDivType: DivType | null
    signal: SignalLevel
    score: number
  }

  const fundSignals = useMemo((): FundSignal[] => {
    const sData = signalChartData.length ? signalChartData : chartData
    if (!sData.length || !fundKeys.length) return []
    return fundKeys.map(fund => {
      const prices = sData.map((d: any) => d[fund]).filter((v: any) => v != null)
      if (prices.length < 2) return null
      const last = prices[prices.length - 1]
      const p30  = prices[Math.max(0, prices.length - 31)]
      const mom30d = last - p30
      const maxP   = Math.max(...prices)
      const drawdown = ((last - maxP) / maxP) * 100

      const extreme = signalObvExtremes.find(e => e.fund === fund)
      let obvPos: 'alto' | 'medio' | 'bajo' = 'medio'
      if (extreme) {
        const range = extreme.maxVal - extreme.minVal
        if (range > 0) {
          const lastObv = (sData[sData.length - 1]?.[`obv_${fund}`] as number) ?? 0
          const pct = (lastObv - extreme.minVal) / range
          if (pct > 0.7) obvPos = 'alto'
          else if (pct < 0.3) obvPos = 'bajo'
        }
      }

      const fundDivs = divergences.filter(d => d.fund === fund)
      const lastDiv  = fundDivs.length ? fundDivs[fundDivs.length - 1] : null

      let score = 50
      if      (mom30d >  5) score += 15
      else if (mom30d >  2) score += 8
      else if (mom30d >  0) score += 3
      else if (mom30d < -5) score -= 15
      else if (mom30d < -2) score -= 8
      else                  score -= 3
      if (obvPos === 'alto') score += 12
      else if (obvPos === 'bajo') score -= 12
      if      (lastDiv?.type === 'regular_bullish') score += 15
      else if (lastDiv?.type === 'hidden_bullish')  score += 8
      else if (lastDiv?.type === 'regular_bearish') score -= 15
      else if (lastDiv?.type === 'hidden_bearish')  score -= 8
      if      (drawdown < -5) score -= 10
      else if (drawdown < -2) score -= 5
      score = Math.max(0, Math.min(100, score))
      const signal: SignalLevel = score >= 60 ? 'alcista' : score <= 40 ? 'bajista' : 'neutro'
      return { fund, mom30d, drawdown, obvPos, lastDivType: lastDiv?.type ?? null, signal, score }
    }).filter(Boolean) as FundSignal[]
  }, [signalChartData, chartData, fundKeys, signalObvExtremes, divergences])

  const macroScore = useMemo(() => {
    if (!macroData?.indicators) return null
    const tpmSeries: { date: string; value: number }[] = macroData.indicators.tpm?.data ?? []
    const ipcSeries: { date: string; value: number }[] = macroData.indicators.ipc?.data ?? []
    const cobreSeries: { date: string; value: number }[] = macroData.indicators.libra_cobre?.data ?? []

    // TPM trend: rate cuts = bullish for equities
    const tpmLast = tpmSeries[tpmSeries.length - 1]?.value ?? null
    const tpm3mAgo = tpmSeries[Math.max(0, tpmSeries.length - 90)]?.value ?? tpmLast
    const tpmTrend = tpmLast !== null && tpm3mAgo !== null ? tpmLast - tpm3mAgo : 0

    // Copper 30d momentum
    const cobreLast = cobreSeries[cobreSeries.length - 1]?.value ?? 0
    const cobreP30  = cobreSeries[Math.max(0, cobreSeries.length - 30)]?.value ?? cobreLast
    const cobreMom  = cobreP30 > 0 ? ((cobreLast - cobreP30) / cobreP30) * 100 : 0

    // IPC: average last 3 months
    const ipcRecent = ipcSeries.slice(-3).map(d => d.value)
    const ipcAvg    = ipcRecent.length ? ipcRecent.reduce((a, b) => a + b, 0) / ipcRecent.length : 0

    let score = 50
    // TPM: bajando = bancos centrales expansivos = favorable para activos de riesgo
    if (tpmTrend < -0.5) score += 15
    else if (tpmTrend < 0) score += 7
    else if (tpmTrend > 0.5) score -= 12
    else if (tpmTrend > 0) score -= 5
    // Cobre: proxy de crecimiento Chile — sube junto con A históricamente
    if (cobreMom > 5)  score += 12
    else if (cobreMom > 2)  score += 6
    else if (cobreMom < -5) score -= 12
    else if (cobreMom < -2) score -= 6
    // IPC alto = inflación presiona a Banco Central → sube tasas → E/D mejor relativo
    if (ipcAvg > 0.8) score -= 8
    else if (ipcAvg < 0) score += 5

    score = Math.max(0, Math.min(100, score))
    return { tpmLast, tpmTrend, cobreLast, cobreMom, ipcAvg, score }
  }, [macroData])

  const aiDecision = aiCommittee?.status === 'ready' ? aiCommittee.arbiter?.parsed?.decision_final : null

  const aiAllocation = useMemo(() => {
    const dist = aiDecision?.distribucion
    if (!Array.isArray(dist) || !dist.length) return null
    const items = dist
      .map((d: any) => ({ fund: d.fondo, pct: d.pct }))
      .filter((d: any) => d.fund && d.pct > 0)
    return items.length ? items : null
  }, [aiDecision])

  const rotationPlan = useMemo(() => {
    if (!aiAllocation) return null
    const ALL_FUNDS = ['A', 'B', 'C', 'D', 'E']
    const current: Record<string, number> = {}
    ALL_FUNDS.forEach(f => { current[f] = currentAllocation[f] ?? 0 })
    const suggested: Record<string, number> = {}
    ALL_FUNDS.forEach(f => { suggested[f] = 0 })
    aiAllocation.forEach(item => { suggested[item.fund] = item.pct })

    const diffs = ALL_FUNDS.map(f => ({ fund: f, diff: suggested[f] - current[f] })).filter(d => Math.abs(d.diff) >= 1)

    const srcQ = diffs.filter(d => d.diff < 0).map(d => ({ fund: d.fund, amount: -d.diff }))
    const tgtQ = diffs.filter(d => d.diff > 0).map(d => ({ fund: d.fund, amount: d.diff }))

    const steps: { from: string; to: string; pct: number }[] = []
    let si = 0, ti = 0
    while (si < srcQ.length && ti < tgtQ.length) {
      const move = Math.min(srcQ[si].amount, tgtQ[ti].amount)
      if (move >= 1) steps.push({ from: srcQ[si].fund, to: tgtQ[ti].fund, pct: Math.round(move) })
      srcQ[si].amount -= move
      tgtQ[ti].amount -= move
      if (srcQ[si].amount < 1) si++
      if (tgtQ[ti].amount < 1) ti++
    }

    if (!steps.length) return { aligned: true, steps, urgency: 'gradual' as const, timingReason: '' }

    // ── Urgency (juicio del comité de IA, combinado con la dirección del movimiento) ──
    type Urgency = 'inmediato' | 'gradual' | 'esperar'
    const RISKY = new Set(['A', 'B'])
    const allConservative = steps.every(s => !RISKY.has(s.from) && !RISKY.has(s.to))
    const movingIntoRiskOn  = steps.some(s => RISKY.has(s.to))
    const movingOutOfRiskOn = steps.some(s => RISKY.has(s.from))
    const urgenciaReducirRiesgo = aiDecision?.urgencia_reducir_riesgo
    const confirmacionEntrada = aiDecision?.confirmacion_entrada_riesgo
    const motivo = aiDecision?.urgencia_motivo as string | undefined

    let urgency: Urgency = 'gradual'
    let timingReason = ''

    if (movingOutOfRiskOn && urgenciaReducirRiesgo === 'alta') {
      urgency = 'inmediato'
      timingReason = motivo || 'El comité de IA califica como alta la urgencia de reducir exposición en fondos riesgosos (A/B).'
    } else if (movingIntoRiskOn && confirmacionEntrada !== 'confirmada') {
      urgency = 'esperar'
      timingReason = motivo || 'El comité de IA aún no confirma técnicamente el punto de entrada en fondos riesgosos (A/B).'
    } else if (movingIntoRiskOn && confirmacionEntrada === 'confirmada') {
      urgency = 'gradual'
      timingReason = motivo || 'El comité de IA confirma la señal de entrada. Puedes entrar ahora o escalonar el traspaso para promediar el precio.'
    } else if (allConservative) {
      urgency = 'gradual'
      timingReason = motivo || 'Movimiento entre fondos conservadores. La diferencia de rendimiento en días o semanas es mínima con 15 años de horizonte — puedes ejecutarlo cuando quieras.'
    } else {
      urgency = 'gradual'
      timingReason = motivo || 'Señal clara pero sin urgencia inmediata. Ejecutar en las próximas 1–2 semanas.'
    }

    return { aligned: false, steps, urgency, timingReason }
  }, [currentAllocation, aiAllocation, aiDecision])

  return (
    <div className="page space-y-8">
      {/* ── Header ── */}
      <div className="page-header">
        <div>
          <h1 className="page-title">🇨🇱 Mercado Chileno</h1>
          <p className="page-subtitle">IPSA · USD/CLP · Fondos AFP A–E</p>
        </div>
      </div>

      {/* ── TradingView charts ── */}
      <div className="grid grid-cols-1 gap-6">
        {/* IPSA */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
          <div className="mb-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
              📈 IPSA Chile
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Índice de Precio Selectivo de Acciones · Bolsa de Santiago
            </p>
          </div>
          <TradingViewChart ticker="SP_IPSA" height={560} />
        </div>

        {/* USDCLP */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-4">
          <div className="mb-3">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
              💵 USD / CLP
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Tipo de cambio Dólar Estadounidense · Peso Chileno
            </p>
          </div>
          <TradingViewChart ticker="FX:USDCLP" height={560} />
        </div>
      </div>

      {/* ── AFP Funds ── */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
        {/* Title + period selector */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
              🏦 Fondos AFP — Rentabilidad Histórica
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Valor cuota promedio · normalizado a base 100 · Fuente: Superintendencia de Pensiones
            </p>
          </div>
          {/* Period buttons */}
          <div className="flex gap-1 flex-wrap">
            {PERIODS.map(p => (
              <button
                key={p.label}
                onClick={() => setSelectedDays(p.days)}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors ${
                  selectedDays === p.days
                    ? 'bg-blue-600 text-white shadow'
                    : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Fund toggle pills + indicator toggles */}
        {fundKeys.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4 items-center">
            {fundKeys.map(fund => {
              const isActive = activeFunds.has(fund)
              const color = funds[fund].color
              return (
                <button
                  key={fund}
                  onClick={() => toggleFund(fund)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium border-2 transition-all ${
                    isActive ? 'text-white shadow-md' : 'bg-transparent text-gray-400 dark:text-gray-500 border-gray-200 dark:border-gray-600'
                  }`}
                  style={isActive ? { backgroundColor: color, borderColor: color } : { borderColor: color, color: color }}
                >
                  <span>{FUND_NAMES[fund]}</span>
                  <span className="text-xs opacity-70">({funds[fund].risk_label})</span>
                </button>
              )
            })}
            <div className="ml-auto flex gap-2">
              <button
                onClick={() => setShowPatrimonio(v => !v)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border-2 transition-all ${
                  showPatrimonio
                    ? 'bg-slate-600 text-white border-slate-600'
                    : 'bg-transparent text-gray-400 border-gray-300 dark:border-gray-600'
                }`}
              >
                🏦 Patrimonio
              </button>
              <button
                onClick={() => setShowOBV(v => !v)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border-2 transition-all ${
                  showOBV
                    ? 'bg-slate-600 text-white border-slate-600'
                    : 'bg-transparent text-gray-400 border-gray-300 dark:border-gray-600'
                }`}
              >
                📊 OBV
              </button>
              <button
                onClick={() => setShowDivergences(v => !v)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border-2 transition-all ${
                  showDivergences
                    ? 'bg-orange-500 text-white border-orange-500'
                    : 'bg-transparent text-gray-400 border-gray-300 dark:border-gray-600'
                }`}
              >
                🔀 Divergencias
              </button>
            </div>
          </div>
        )}

        {/* Chart area */}
        {afpLoading && (
          <div className="flex items-center justify-center h-64">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
          </div>
        )}

        {afpError && !afpLoading && (
          <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300">
            <p className="font-semibold">No se pudieron cargar los datos AFP</p>
            <p className="mt-1 text-xs">{afpError}</p>
            <button
              onClick={() => fetchAFP(selectedDays)}
              className="mt-3 px-3 py-1.5 bg-red-100 dark:bg-red-900/40 hover:bg-red-200 dark:hover:bg-red-900/60 rounded-lg text-xs font-medium transition-colors"
            >
              Reintentar
            </button>
          </div>
        )}

        {!afpLoading && !afpError && chartData.length > 0 && (
          <>
            {/* ── Rentabilidad ─────────────────────────────────────────── */}
            <div
              className="relative cursor-pointer select-none"
              onDoubleClick={() => handleDoubleClick('rent')}
              title="Doble clic para maximizar / restaurar"
            >
              {maximized === 'rent' && (
                <span className="absolute top-1 right-2 text-xs text-gray-400 dark:text-gray-500 z-10">doble clic para restaurar</span>
              )}
              <p className="text-xs text-gray-400 dark:text-gray-500 mb-1 ml-1 select-none">
                Valor cuota (base 100){maximized === null ? ' · doble clic para maximizar' : ''}
              </p>
              <ResponsiveContainer width="100%" height={paneHeight('rent', 320)}>
                <LineChart syncId="afp-sync" data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                  <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 11 }} tickLine={false} minTickGap={40} hide />
                  <YAxis domain={['auto', 'auto']} tick={{ fontSize: 11 }} tickLine={false} tickFormatter={v => v.toFixed(0)} width={50} />
                  <Tooltip
                    content={({ active, payload, label }: any) => {
                      if (!active || !payload?.length) return null
                      return (
                        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-3 shadow-lg text-sm">
                          <p className="font-semibold text-gray-700 dark:text-gray-200 mb-2">{formatDate(label)}</p>
                          {payload.map((e: any) => (
                            <p key={e.dataKey} style={{ color: e.color }} className="font-medium">
                              {FUND_NAMES[e.dataKey] ?? e.dataKey}: {e.value?.toFixed(2)}
                            </p>
                          ))}
                        </div>
                      )
                    }}
                  />
                  <Legend formatter={v => FUND_NAMES[v] ?? v} wrapperStyle={{ fontSize: '12px' }} />
                  {fundKeys.filter(f => activeFunds.has(f)).map(fund => (
                    <Line key={fund} type="monotone" dataKey={fund} name={fund}
                      stroke={funds[fund].color} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* ── Patrimonio (barras de volumen) ────────────────────────── */}
            {paneVisible('pat') && patrimonioChartData.length > 0 && (
              <div
                className="mt-1 cursor-pointer select-none"
                onDoubleClick={() => handleDoubleClick('pat')}
                title="Doble clic para maximizar / restaurar"
              >
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-1 ml-1 select-none">Patrimonio total (CLP)</p>
                <ResponsiveContainer width="100%" height={paneHeight('pat', 90)}>
                  <BarChart syncId="afp-sync" data={patrimonioChartData} margin={{ top: 0, right: 16, left: 0, bottom: 0 }} barCategoryGap="0%">
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10 }} tickLine={false} minTickGap={40}
                      hide={paneVisible('obv')} />
                    <YAxis tick={{ fontSize: 10 }} tickLine={false} width={50} tickFormatter={fmtBig} />
                    <Tooltip
                      content={({ active, payload, label }: any) => {
                        if (!active || !payload?.length) return null
                        return (
                          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-2 shadow-lg text-xs">
                            <p className="font-semibold text-gray-700 dark:text-gray-200 mb-1">{formatDate(label)}</p>
                            {payload.map((e: any) => (
                              <p key={e.dataKey} style={{ color: e.color }}>
                                {FUND_NAMES[e.dataKey] ?? e.dataKey}: {fmtBig(e.value)} CLP
                              </p>
                            ))}
                          </div>
                        )
                      }}
                    />
                    {fundKeys.filter(f => activeFunds.has(f)).map(fund => (
                      <Bar key={fund} dataKey={fund} name={fund} fill={funds[fund]?.color} fillOpacity={0.6} isAnimationActive={false} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* ── OBV ──────────────────────────────────────────────────── */}
            {paneVisible('obv') && (
              <div
                className="mt-1 cursor-pointer select-none"
                onDoubleClick={() => handleDoubleClick('obv')}
                title="Doble clic para maximizar / restaurar"
              >
                <p className="text-xs text-gray-400 dark:text-gray-500 mb-1 ml-1 select-none">OBV — On-Balance Volume (CLP)</p>
                <div className="[&_svg]:overflow-visible">
                <ResponsiveContainer width="100%" height={paneHeight('obv', 220)}>
                  <LineChart syncId="afp-sync" data={chartData} margin={{ top: 22, right: 16, left: 0, bottom: 22 }}>
                    <CartesianGrid strokeDasharray="3 3" className="opacity-20" />
                    <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 10 }} tickLine={false} minTickGap={40} />
                    <YAxis tick={{ fontSize: 10 }} tickLine={false} width={55} tickFormatter={fmtBig} domain={['auto', 'auto']} />
                    <Tooltip
                      content={({ active, payload, label }: any) => {
                        if (!active || !payload?.length) return null
                        return (
                          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-2 shadow-lg text-xs">
                            <p className="font-semibold text-gray-700 dark:text-gray-200 mb-1">{formatDate(label)}</p>
                            {payload.map((e: any) => {
                              const fund = String(e.dataKey).replace('obv_', '')
                              return (
                                <p key={e.dataKey} style={{ color: e.color }}>
                                  {FUND_NAMES[fund] ?? fund}: {fmtBig(e.value)} CLP
                                </p>
                              )
                            })}
                          </div>
                        )
                      }}
                    />
                    <Legend formatter={v => `OBV ${FUND_NAMES[v.replace('obv_', '')] ?? v}`} wrapperStyle={{ fontSize: '11px' }} />
                    {fundKeys.filter(f => activeFunds.has(f)).map(fund => (
                      <Line key={`obv_${fund}`} type="monotone" dataKey={`obv_${fund}`} name={`obv_${fund}`}
                        stroke={funds[fund]?.color} strokeWidth={1.5} dot={false} activeDot={{ r: 3 }} />
                    ))}
                    {/* Max/min markers — círculo hueco con borde del color del fondo */}
                    {obvExtremes.map(({ fund, maxDate, maxVal, minDate, minVal }) => {
                      const color = funds[fund]?.color
                      return [
                        <ReferenceDot key={`max_${fund}`} x={maxDate} y={maxVal}
                          r={6} fill="transparent" stroke={color} strokeWidth={2} strokeDasharray="3 2"
                          label={{ value: `MAX ${fmtBig(maxVal)}`, position: 'top', fontSize: 8, fill: '#9ca3af', fontWeight: 600 }} />,
                        <ReferenceDot key={`min_${fund}`} x={minDate} y={minVal}
                          r={6} fill="transparent" stroke={color} strokeWidth={2} strokeDasharray="3 2"
                          label={{ value: `MIN ${fmtBig(minVal)}`, position: 'bottom', fontSize: 8, fill: '#9ca3af', fontWeight: 600 }} />,
                      ]
                    })}
                    {/* Divergence markers — only within the displayed period */}
                    {showDivergences && displayDivergences.map((d, i) => {
                      const meta = DIV_META[d.type]
                      return (
                        <ReferenceDot key={`div_${i}`} x={d.date} y={d.obv}
                          r={5} fill={meta.color} stroke="#fff" strokeWidth={1.5} opacity={0.9}
                          label={{ value: meta.label, position: meta.pos, fontSize: 8, fill: meta.color, fontWeight: 'bold' }}
                        />
                      )
                    })}
                  </LineChart>
                </ResponsiveContainer>
                </div>
                {showDivergences && (
                  <div className="mt-2 flex flex-wrap gap-3 text-xs ml-1 items-center">
                    {(Object.entries(DIV_META) as [DivType, typeof DIV_META[DivType]][]).map(([type, meta]) => (
                      <span key={type} className="flex items-center gap-1">
                        <span style={{ color: meta.color }} className="font-bold text-base leading-none">●</span>
                        <span className="text-gray-500 dark:text-gray-400">{meta.label.replace('▼ ', '').replace('▲ ', '')}</span>
                      </span>
                    ))}
                    <span className="flex items-center gap-1 ml-1">
                      <span className="inline-block w-3 h-3 rounded-full border-2 border-gray-400 border-dashed bg-transparent"></span>
                      <span className="text-gray-500 dark:text-gray-400">MAX / MIN período</span>
                    </span>
                    <span className="text-gray-400 dark:text-gray-600">
                      · Div.O = Oculta (continuación) · Div. = Regular (reversión)
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Return summary cards */}
            <div className="mt-6 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {fundKeys.map(fund => {
                const series = funds[fund].data
                if (!series.length) return null
                const first = series[0].value
                const last = series[series.length - 1].value
                const change = last - first  // base 100 → change%
                const positive = change >= 0
                return (
                  <div
                    key={fund}
                    className="rounded-xl border-2 p-3 transition-all"
                    style={{
                      borderColor: funds[fund].color,
                      opacity: activeFunds.has(fund) ? 1 : 0.45,
                    }}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span
                        className="text-sm font-bold"
                        style={{ color: funds[fund].color }}
                      >
                        {FUND_NAMES[fund]}
                      </span>
                      <span
                        className={`text-sm font-bold ${
                          positive ? 'text-green-500' : 'text-red-500'
                        }`}
                      >
                        {positive ? '+' : ''}
                        {change.toFixed(2)}%
                      </span>
                    </div>
                    <p className="text-xs text-gray-400 dark:text-gray-500">
                      {funds[fund].risk_label}
                    </p>
                    <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                      Val. cuota: {series[series.length - 1].raw_value.toLocaleString('es-CL')}
                    </p>
                    {series[series.length - 1].patrimonio > 0 && (
                      <p className="text-xs text-gray-400 dark:text-gray-500">
                        Patrimonio: {series[series.length - 1].patrimonio >= 1e9
                          ? `${(series[series.length - 1].patrimonio / 1e9).toFixed(1)}B`
                          : `${(series[series.length - 1].patrimonio / 1e6).toFixed(0)}M`} CLP
                      </p>
                    )}
                  </div>
                )
              })}
            </div>

            {/* ── Señal de mercado ─────────────────────────────── */}
            {fundSignals.length > 0 && (
              <div className="mt-6 border-t border-gray-100 dark:border-gray-700 pt-5">
                <div className="flex items-center gap-2 mb-3">
                  <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                    🎯 Señal de mercado AFP
                  </h3>
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    · momentum, OBV y divergencias del período seleccionado
                  </span>
                </div>

                {/* Signal table */}
                <div className="overflow-x-auto mb-4">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="text-gray-500 dark:text-gray-400 border-b border-gray-100 dark:border-gray-700">
                        <th className="text-left py-1.5 pr-3 font-medium">Fondo</th>
                        <th className="text-right pr-3 font-medium">Mom. 30d</th>
                        <th className="text-center pr-3 font-medium">OBV</th>
                        <th className="text-center pr-3 font-medium">Últ. divergencia</th>
                        <th className="text-right pr-3 font-medium">DD máx.</th>
                        <th className="text-center font-medium">Señal</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fundSignals.map(s => {
                        const color = funds[s.fund]?.color
                        const sigCls: Record<SignalLevel, string> = {
                          alcista: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
                          neutro:  'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400',
                          bajista: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
                        }
                        const obvCls = {
                          alto:  'text-green-600 dark:text-green-400',
                          medio: 'text-gray-400 dark:text-gray-500',
                          bajo:  'text-red-500 dark:text-red-400',
                        }
                        const divLabel: Record<DivType, string> = {
                          regular_bearish: '▼ Baj.R',
                          hidden_bearish:  '▼ Baj.O',
                          regular_bullish: '▲ Alc.R',
                          hidden_bullish:  '▲ Alc.O',
                        }
                        return (
                          <tr key={s.fund} className="border-b border-gray-50 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors">
                            <td className="py-2 pr-3">
                              <span className="font-bold" style={{ color }}>{FUND_NAMES[s.fund]}</span>
                              <span className="ml-1.5 text-gray-400 opacity-70">({funds[s.fund]?.risk_label})</span>
                            </td>
                            <td className={`text-right pr-3 font-mono font-semibold ${s.mom30d >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>
                              {s.mom30d >= 0 ? '+' : ''}{s.mom30d.toFixed(2)}
                            </td>
                            <td className={`text-center pr-3 font-medium ${obvCls[s.obvPos]}`}>
                              {s.obvPos === 'alto' ? '↑ Alto' : s.obvPos === 'bajo' ? '↓ Bajo' : '→ Med.'}
                            </td>
                            <td className="text-center pr-3">
                              {s.lastDivType ? (
                                <span style={{ color: DIV_META[s.lastDivType].color }} className="font-semibold">
                                  {divLabel[s.lastDivType]}
                                </span>
                              ) : (
                                <span className="text-gray-300 dark:text-gray-600">—</span>
                              )}
                            </td>
                            <td className={`text-right pr-3 font-mono ${s.drawdown < -2 ? 'text-red-500' : 'text-gray-400 dark:text-gray-500'}`}>
                              {s.drawdown.toFixed(2)}%
                            </td>
                            <td className="text-center py-1.5">
                              <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${sigCls[s.signal]}`}>
                                {s.signal === 'alcista' ? '🟢 Alcista' : s.signal === 'bajista' ? '🔴 Bajista' : '🟡 Neutro'}
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                <p className="text-xs text-gray-400 dark:text-gray-600">
                  ⚠️ Señales basadas en historial completo desde {signalChartData[0]?.date ?? '…'}. No constituye asesoría financiera.
                </p>

                {/* Tu posición actual */}
                {fundKeys.length > 0 && (
                  <div className="mb-4 rounded-xl border border-gray-200 dark:border-gray-600 overflow-hidden">
                    <button
                      onClick={() => setEditingAllocation(v => !v)}
                      className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-left"
                    >
                      <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">📍 Tu posición actual</span>
                      <span className="text-xs text-gray-400 dark:text-gray-500">{editingAllocation ? '▲ cerrar' : '▼ editar'}</span>
                    </button>
                    {/* Barra de posición actual — siempre visible */}
                    <div className="px-4 pt-3 pb-3">
                      {['A','B','C','D','E'].some(f => (currentAllocation[f] ?? 0) > 0) ? (
                        <>
                          <div className="flex rounded-lg overflow-hidden h-8 mb-2 shadow-inner bg-gray-100 dark:bg-gray-800">
                            {['A','B','C','D','E'].filter(f => (currentAllocation[f] ?? 0) > 0).map(f => (
                              <div
                                key={f}
                                style={{ width: `${currentAllocation[f]}%`, backgroundColor: funds[f]?.color ?? '#888' }}
                                className="flex items-center justify-center transition-all duration-300"
                              >
                                {(currentAllocation[f] ?? 0) >= 15 && (
                                  <span className="text-white text-xs font-bold drop-shadow">{currentAllocation[f]}%</span>
                                )}
                              </div>
                            ))}
                          </div>
                          <div className="flex flex-wrap gap-x-4 gap-y-1">
                            {['A','B','C','D','E'].filter(f => (currentAllocation[f] ?? 0) > 0).map(f => (
                              <span key={f} className="flex items-center gap-1 text-xs">
                                <span className="w-2.5 h-2.5 rounded-sm flex-none" style={{ backgroundColor: funds[f]?.color ?? '#888' }} />
                                <span className="font-bold" style={{ color: funds[f]?.color ?? '#888' }}>{currentAllocation[f]}%</span>
                                <span className="text-gray-500 dark:text-gray-400">{FUND_NAMES[f]}</span>
                              </span>
                            ))}
                          </div>
                        </>
                      ) : (
                        <p className="text-xs text-gray-400 italic">Sin posición ingresada — haz clic en "editar" para ingresar tu distribución actual.</p>
                      )}
                    </div>
                    {/* Inputs (colapsables) */}
                    {editingAllocation && (
                      <div className="px-4 pb-4 pt-1 border-t border-gray-100 dark:border-gray-700">
                        <div className="grid grid-cols-5 gap-2 mb-2 mt-2">
                          {['A','B','C','D','E'].map(f => (
                            <div key={f} className="flex flex-col items-center gap-1">
                              <label className="text-xs font-bold" style={{ color: funds[f]?.color ?? '#888' }}>
                                {FUND_NAMES[f]}
                              </label>
                              <input
                                type="number"
                                min={0}
                                max={100}
                                value={currentAllocation[f] ?? 0}
                                onChange={e => {
                                  const val = Math.max(0, Math.min(100, parseInt(e.target.value) || 0))
                                  setCurrentAllocation(prev => ({ ...prev, [f]: val }))
                                }}
                                className="w-full text-center text-sm font-mono border rounded-lg py-1.5 bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-gray-200"
                              />
                            </div>
                          ))}
                        </div>
                        {(() => {
                          const total = ['A','B','C','D','E'].reduce((s, f) => s + (currentAllocation[f] ?? 0), 0)
                          return (
                            <div className={`text-xs font-semibold text-right mt-1 ${total === 100 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>
                              Total: {total}%{total === 100 ? ' ✓' : ` — ${total < 100 ? `faltan ${100 - total}%` : `sobran ${total - 100}%`}`}
                            </div>
                          )
                        })()}
                      </div>
                    )}
                  </div>
                )}

                {/* Distribución sugerida por el comité de IA */}
                {aiCommittee?.status === 'ready' && aiAllocation ? (
                  <div className="rounded-xl bg-gray-50 dark:bg-gray-700/50 border border-gray-100 dark:border-gray-700 px-4 py-4">
                    {/* Header row: regimen badge */}
                    <div className="flex items-center gap-2 mb-3">
                      <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300">
                        🤖 {aiDecision?.regimen || 'Veredicto del comité de IA'}
                      </span>
                    </div>

                    {/* Justificación del comité */}
                    {aiDecision?.justificacion && (
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-4">{aiDecision.justificacion}</p>
                    )}

                    {/* Allocation bar */}
                    <div>
                      <p className="text-xs font-semibold text-gray-700 dark:text-gray-200 mb-2">
                        📊 Distribución sugerida
                      </p>
                      {/* Stacked bar */}
                      <div className="flex rounded-lg overflow-hidden h-10 mb-3 shadow-inner">
                        {aiAllocation.map(item => (
                          <div
                            key={item.fund}
                            style={{ width: `${item.pct}%`, backgroundColor: funds[item.fund]?.color ?? '#888' }}
                            className="flex items-center justify-center transition-all duration-500"
                          >
                            {item.pct >= 18 && (
                              <span className="text-white text-xs font-bold drop-shadow">{item.pct}%</span>
                            )}
                          </div>
                        ))}
                      </div>
                      {/* Legend */}
                      <div className="flex flex-wrap gap-x-5 gap-y-1.5 mb-2">
                        {aiAllocation.map(item => (
                          <div key={item.fund} className="flex items-center gap-1.5">
                            <span
                              className="w-3 h-3 rounded-sm flex-none"
                              style={{ backgroundColor: funds[item.fund]?.color ?? '#888' }}
                            />
                            <span className="text-xs font-bold" style={{ color: funds[item.fund]?.color ?? '#888' }}>
                              {item.pct}% {FUND_NAMES[item.fund]}
                            </span>
                            <span className="text-xs text-gray-400 dark:text-gray-500">
                              ({funds[item.fund]?.risk_label})
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Comparación y plan de rotación */}
                    {rotationPlan && (
                      <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-600">
                        <p className="text-xs font-semibold text-gray-700 dark:text-gray-200 mb-3">
                          🔄 Comparación con tu posición actual
                        </p>
                        <div className="space-y-2 mb-3">
                          <div>
                            <p className="text-xs text-gray-400 dark:text-gray-500 mb-1">Tu posición:</p>
                            <div className="flex rounded-md overflow-hidden h-7 bg-gray-200 dark:bg-gray-700">
                              {['A','B','C','D','E'].filter(f => (currentAllocation[f] ?? 0) > 0).map(f => (
                                <div
                                  key={f}
                                  style={{ width: `${currentAllocation[f]}%`, backgroundColor: funds[f]?.color ?? '#888' }}
                                  className="flex items-center justify-center"
                                >
                                  {(currentAllocation[f] ?? 0) >= 15 && (
                                    <span className="text-white text-xs font-bold drop-shadow">{currentAllocation[f]}%</span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                          <div>
                            <p className="text-xs text-gray-400 dark:text-gray-500 mb-1">Distribución sugerida:</p>
                            <div className="flex rounded-md overflow-hidden h-7">
                              {aiAllocation.map(item => (
                                <div
                                  key={item.fund}
                                  style={{ width: `${item.pct}%`, backgroundColor: funds[item.fund]?.color ?? '#888' }}
                                  className="flex items-center justify-center"
                                >
                                  {item.pct >= 15 && (
                                    <span className="text-white text-xs font-bold drop-shadow">{item.pct}%</span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                        {rotationPlan.aligned ? (
                          <div className="flex items-center gap-2 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 px-3 py-2">
                            <span className="text-base">✅</span>
                            <span className="text-xs text-green-700 dark:text-green-300 font-medium">
                              Tu posición está alineada con la distribución sugerida. No se requieren cambios.
                            </span>
                          </div>
                        ) : (
                          <div className="rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 px-3 py-2.5">
                            <div className="flex items-center justify-between mb-2">
                              <p className="text-xs font-semibold text-amber-700 dark:text-amber-300">
                                📋 Movimientos sugeridos
                              </p>
                              {rotationPlan.urgency === 'inmediato' && (
                                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300">
                                  🔴 Actuar ahora
                                </span>
                              )}
                              {rotationPlan.urgency === 'gradual' && (
                                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300">
                                  🟠 Sin urgencia
                                </span>
                              )}
                              {rotationPlan.urgency === 'esperar' && (
                                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300">
                                  ⏳ Esperar señal
                                </span>
                              )}
                            </div>
                            <div className="space-y-1.5 mb-2">
                              {rotationPlan.steps.map((step, i) => (
                                <div key={i} className="flex items-center gap-2 text-xs">
                                  <span className="inline-flex items-center gap-1">
                                    <span className="w-2.5 h-2.5 rounded-sm flex-none" style={{ backgroundColor: funds[step.from]?.color ?? '#888' }} />
                                    <span className="font-bold" style={{ color: funds[step.from]?.color }}>{FUND_NAMES[step.from]}</span>
                                  </span>
                                  <span className="text-gray-400">→</span>
                                  <span className="inline-flex items-center gap-1">
                                    <span className="w-2.5 h-2.5 rounded-sm flex-none" style={{ backgroundColor: funds[step.to]?.color ?? '#888' }} />
                                    <span className="font-bold" style={{ color: funds[step.to]?.color }}>{FUND_NAMES[step.to]}</span>
                                  </span>
                                  <span className="ml-auto font-mono font-semibold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-900/40 px-2 py-0.5 rounded">
                                    mover {step.pct}%
                                  </span>
                                </div>
                              ))}
                            </div>
                            {rotationPlan.timingReason && (
                              <p className="text-xs text-amber-600 dark:text-amber-400 border-t border-amber-200 dark:border-amber-700 pt-2 mt-1">
                                {rotationPlan.timingReason}
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="rounded-xl bg-gray-50 dark:bg-gray-700/50 border border-gray-100 dark:border-gray-700 px-4 py-4 text-xs text-gray-400 dark:text-gray-500 italic">
                    {aiCommittee?.status === 'generating' ? 'Comité de IA generando veredicto...' : 'Distribución sugerida del comité de IA no disponible aún.'}
                  </div>
                )}
              </div>
            )}

            {/* Source footnote */}
            {afpData && (
              <p className="mt-4 text-xs text-gray-400 dark:text-gray-600 text-right">
                Fuente: {afpData.source}
                {afpData.errors.length > 0 && (
                  <span className="ml-2 text-yellow-500">
                    · Fondos sin datos: {afpData.errors.join(', ')}
                  </span>
                )}
              </p>
            )}
          </>
        )}

        {!afpLoading && !afpError && chartData.length === 0 && !afpData && (
          <div className="flex items-center justify-center h-40 text-gray-400 dark:text-gray-600 text-sm">
            Cargando datos...
          </div>
        )}
      </div>

      {/* ── Comité de IA Multi-Modelo ── */}
      {aiCommittee && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
              🤖 Comité de IA Multi-Modelo
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Dos analistas (DeepSeek, MiniMax) analizan los datos en paralelo y un árbitro independiente (GLM) contrasta ambos veredictos.
              {aiCommittee.generated_at && ` Generado: ${new Date(aiCommittee.generated_at).toLocaleString('es-CL')}.`}
            </p>
          </div>

          {aiCommittee.status === 'generating' && (
            <div className="text-sm text-gray-500 dark:text-gray-400">
              Generando el primer análisis del comité (puede tardar unos minutos)… refresca la página más tarde.
            </div>
          )}

          {aiCommittee.status === 'ready' && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {aiCommittee.analysts.map((a: any) => (
                  <div key={a.model} className="rounded-lg border border-gray-100 dark:border-gray-700 p-3">
                    <p className="text-xs font-bold text-gray-600 dark:text-gray-300 mb-1">{a.model}</p>
                    {a.parsed ? (
                      <>
                        <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">{a.parsed.regimen}</p>
                        <div className="flex gap-1.5 mb-2">
                          {a.parsed.distribucion?.map((d: any) => (
                            <span key={d.fondo} className="text-xs font-bold px-2 py-0.5 rounded-full" style={{ backgroundColor: `${funds[d.fondo]?.color ?? '#888'}22`, color: funds[d.fondo]?.color ?? '#888' }}>
                              {d.pct}% {FUND_NAMES[d.fondo] ?? d.fondo}
                            </span>
                          ))}
                        </div>
                        <p className="text-xs text-gray-500 dark:text-gray-400">{a.parsed.analisis}</p>
                      </>
                    ) : (
                      <p className="text-xs text-gray-400 italic">No se pudo interpretar la respuesta de este modelo.</p>
                    )}
                  </div>
                ))}
              </div>

              {aiCommittee.arbiter?.parsed && (
                <div className="rounded-lg border-2 border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 p-4">
                  <p className="text-xs font-bold text-blue-700 dark:text-blue-300 mb-2">⚖️ Veredicto del árbitro ({aiCommittee.arbiter.model})</p>

                  <div className="flex gap-1.5 mb-3">
                    {aiCommittee.arbiter.parsed.decision_final?.distribucion?.map((d: any) => (
                      <span key={d.fondo} className="text-sm font-bold px-2.5 py-1 rounded-full text-white" style={{ backgroundColor: funds[d.fondo]?.color ?? '#888' }}>
                        {d.pct}% {FUND_NAMES[d.fondo] ?? d.fondo}
                      </span>
                    ))}
                  </div>

                  <p className="text-xs text-gray-600 dark:text-gray-300 mb-3">{aiCommittee.arbiter.parsed.decision_final?.justificacion}</p>

                  <details className="text-xs text-gray-500 dark:text-gray-400">
                    <summary className="cursor-pointer font-semibold mb-1">Ver evaluación crítica completa</summary>
                    <p className="mb-2"><strong>Evaluación crítica:</strong> {aiCommittee.arbiter.parsed.evaluacion_critica}</p>
                    {aiCommittee.arbiter.parsed.coincidencias?.length > 0 && (
                      <div className="mb-2">
                        <strong>Coincidencias:</strong>
                        <ul className="list-disc list-inside">
                          {aiCommittee.arbiter.parsed.coincidencias.map((c: string, i: number) => <li key={i}>{c}</li>)}
                        </ul>
                      </div>
                    )}
                    {aiCommittee.arbiter.parsed.diferencias?.length > 0 && (
                      <div className="mb-2">
                        <strong>Diferencias:</strong>
                        <ul className="list-disc list-inside">
                          {aiCommittee.arbiter.parsed.diferencias.map((d: string, i: number) => <li key={i}>{d}</li>)}
                        </ul>
                      </div>
                    )}
                    {aiCommittee.arbiter.parsed.riesgos_a_vigilar?.length > 0 && (
                      <div>
                        <strong>Riesgos a vigilar:</strong>
                        <ul className="list-disc list-inside">
                          {aiCommittee.arbiter.parsed.riesgos_a_vigilar.map((r: string, i: number) => <li key={i}>{r}</li>)}
                        </ul>
                      </div>
                    )}
                  </details>
                </div>
              )}

              <p className="text-xs text-gray-400 dark:text-gray-600">
                ⚠️ Análisis generado por modelos de IA, se actualiza 1 vez al día. No constituye asesoría financiera.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── Contexto Macroeconómico Chile ── */}
      {macroData?.indicators && (
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-white">
              🏛️ Contexto Macroeconómico Chile
            </h2>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              Indicadores que influyen en la rentabilidad de los fondos AFP · Fuente: mindicador.cl / Banco Central
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
            {/* TPM */}
            {macroData.indicators.tpm && (() => {
              const series = macroData.indicators.tpm.data.slice(-60)
              const latest = macroData.indicators.tpm.latest
              const trend  = macroScore?.tpmTrend ?? 0
              return (
                <div className="rounded-xl border border-gray-100 dark:border-gray-700 p-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">📊 TPM Banco Central</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${trend < -0.1 ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300' : trend > 0.1 ? 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'}`}>
                      {trend < -0.1 ? '↘ Bajando' : trend > 0.1 ? '↗ Subiendo' : '→ Estable'}
                    </span>
                  </div>
                  <p className="text-2xl font-bold text-gray-800 dark:text-white mb-0.5">{latest?.value?.toFixed(2)}%</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">Tasa de Política Monetaria</p>
                  <ResponsiveContainer width="100%" height={60}>
                    <LineChart data={series}>
                      <Line type="stepAfter" dataKey="value" stroke="#3b82f6" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                  <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">
                    {trend < -0.1 ? '✅ Política expansiva — favorable para renta variable' : trend > 0.1 ? '⚠️ Política restrictiva — presiona a A/B' : '→ Sin cambio reciente de política'}
                  </p>
                </div>
              )
            })()}

            {/* Cobre */}
            {macroData.indicators.libra_cobre && (() => {
              const series = macroData.indicators.libra_cobre.data.slice(-90)
              const latest = macroData.indicators.libra_cobre.latest
              const mom    = macroScore?.cobreMom ?? 0
              return (
                <div className="rounded-xl border border-gray-100 dark:border-gray-700 p-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">🟤 Cobre (USD/lb)</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${mom > 2 ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300' : mom < -2 ? 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'}`}>
                      {mom >= 0 ? '+' : ''}{mom.toFixed(1)}% 30d
                    </span>
                  </div>
                  <p className="text-2xl font-bold text-gray-800 dark:text-white mb-0.5">${latest?.value?.toFixed(2)}</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">Precio libra · COMEX</p>
                  <ResponsiveContainer width="100%" height={60}>
                    <LineChart data={series}>
                      <Line type="monotone" dataKey="value" stroke="#f97316" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                  <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">
                    {mom > 3 ? '✅ Cobre al alza — señal positiva para economía chilena y Fondo A' : mom < -3 ? '⚠️ Cobre a la baja — presión sobre economía y renta variable local' : '→ Sin tendencia fuerte en cobre'}
                  </p>
                </div>
              )
            })()}

            {/* IPC */}
            {macroData.indicators.ipc && (() => {
              const series = macroData.indicators.ipc.data.slice(-24)
              const latest = macroData.indicators.ipc.latest
              const avg    = macroScore?.ipcAvg ?? 0
              return (
                <div className="rounded-xl border border-gray-100 dark:border-gray-700 p-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">📈 IPC (var. mensual)</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${avg > 0.8 ? 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300' : avg < 0.1 ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'}`}>
                      Prom 3m: {avg.toFixed(2)}%
                    </span>
                  </div>
                  <p className="text-2xl font-bold text-gray-800 dark:text-white mb-0.5">{latest?.value?.toFixed(1)}%</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">Último mes · INE Chile</p>
                  <ResponsiveContainer width="100%" height={60}>
                    <BarChart data={series}>
                      <Bar dataKey="value" fill={avg > 0.8 ? '#ef4444' : '#22c55e'} radius={[2,2,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                  <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">
                    {avg > 0.8 ? '⚠️ Inflación elevada — Banco Central podría subir tasas' : avg < 0 ? '✅ Deflación — espacio para bajar tasas' : '✅ Inflación controlada — sin presión sobre tasas'}
                  </p>
                </div>
              )
            })()}
            {/* UF */}
            {macroData.indicators.uf && (() => {
              const series  = macroData.indicators.uf.data.slice(-60)
              const latest  = macroData.indicators.uf.latest
              const p30val  = macroData.indicators.uf.data[Math.max(0, macroData.indicators.uf.data.length - 30)]?.value ?? latest?.value
              const mom     = latest && p30val ? ((latest.value - p30val) / p30val) * 100 : 0
              const fmtUF   = (v: number) => `$${v.toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
              return (
                <div className="rounded-xl border border-gray-100 dark:border-gray-700 p-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">🪙 UF</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${mom > 0.3 ? 'bg-yellow-100 dark:bg-yellow-900/40 text-yellow-700 dark:text-yellow-300' : 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300'}`}>
                      {mom >= 0 ? '+' : ''}{mom.toFixed(2)}% 30d
                    </span>
                  </div>
                  <p className="text-2xl font-bold text-gray-800 dark:text-white mb-0.5">{latest ? fmtUF(latest.value) : '—'}</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">Valor diario · Banco Central</p>
                  <ResponsiveContainer width="100%" height={60}>
                    <LineChart data={series}>
                      <Line type="monotone" dataKey="value" stroke="#8b5cf6" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                  <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">
                    {mom > 0.3 ? '⚠️ UF al alza — inflación activa, deuda UF más cara' : '✅ UF estable — inflación contenida'}
                  </p>
                </div>
              )
            })()}

            {/* Tasa Desempleo */}
            {macroData.indicators.tasa_desempleo && (() => {
              const series = macroData.indicators.tasa_desempleo.data.slice(-12)
              const latest = macroData.indicators.tasa_desempleo.latest
              const change = macroData.indicators.tasa_desempleo.change ?? 0
              return (
                <div className="rounded-xl border border-gray-100 dark:border-gray-700 p-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">👷 Desempleo</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${change > 0.2 ? 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300' : change < -0.2 ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'}`}>
                      {change >= 0 ? '+' : ''}{change.toFixed(1)}pp vs ant.
                    </span>
                  </div>
                  <p className="text-2xl font-bold text-gray-800 dark:text-white mb-0.5">{latest?.value?.toFixed(1)}%</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">Último trimestre · INE Chile</p>
                  <ResponsiveContainer width="100%" height={60}>
                    <LineChart data={series}>
                      <Line type="monotone" dataKey="value" stroke="#ec4899" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                  <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">
                    {change > 0.3 ? '⚠️ Desempleo al alza — consumo bajo presión' : change < -0.3 ? '✅ Desempleo cayendo — consumo favorable' : '→ Mercado laboral estable'}
                  </p>
                </div>
              )
            })()}

            {/* IMACEC */}
            {macroData.indicators.imacec && (() => {
              const series  = macroData.indicators.imacec.data.slice(-24)
              const latest  = macroData.indicators.imacec.latest
              const recent3 = macroData.indicators.imacec.data.slice(-3).map((d: any) => d.value)
              const avg3    = recent3.length ? recent3.reduce((a: number, b: number) => a + b, 0) / recent3.length : 0
              return (
                <div className="rounded-xl border border-gray-100 dark:border-gray-700 p-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">🏭 IMACEC</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${avg3 > 2 ? 'bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300' : avg3 < 0 ? 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300'}`}>
                      Prom 3m: {avg3.toFixed(1)}%
                    </span>
                  </div>
                  <p className="text-2xl font-bold text-gray-800 dark:text-white mb-0.5">{latest?.value?.toFixed(1)}%</p>
                  <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">Var. anual · Banco Central</p>
                  <ResponsiveContainer width="100%" height={60}>
                    <BarChart data={series}>
                      <Bar dataKey="value" fill={avg3 > 2 ? '#22c55e' : avg3 < 0 ? '#ef4444' : '#6b7280'} radius={[2,2,0,0]} />
                    </BarChart>
                  </ResponsiveContainer>
                  <p className="text-xs text-gray-400 dark:text-gray-600 mt-1">
                    {avg3 > 2 ? '✅ Actividad económica en expansión — favorable para A/B' : avg3 < 0 ? '⚠️ Actividad en contracción — cautela en renta variable' : '→ Actividad económica moderada'}
                  </p>
                </div>
              )
            })()}
          </div>

          <p className="text-xs text-gray-400 dark:text-gray-600">
            Fuente: mindicador.cl · TPM, cobre y UF: datos diarios · IPC e IMACEC: variación mensual · Desempleo: trimestral INE
          </p>
        </div>
      )}
    </div>
  )
}
