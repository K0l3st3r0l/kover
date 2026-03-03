import { useState, useEffect } from 'react'
import api from '../services/api'

// --- Broker Data types ---
interface BrokerOptionRow {
  id: number
  side: 'sell' | 'buy'
  type: 'call' | 'put'
  strike: string
  expiration: string     // yyyy-mm-dd
  premium: string        // per share (bid/ask mid)
  contracts: string
}

interface BrokerOptionCalc {
  id: number
  side: 'sell' | 'buy'
  type: 'call' | 'put'
  strike: number
  expiration: string
  premium: number
  contracts: number
  dte: number
  totalCashFlow: number  // positive = recibís, negative = pagás
  otmPct: number         // positive = OTM, negative = ITM
  breakeven: number           // precio donde empezás a perder upside (call) o downside (put)
  breakevenMovePct: number    // % vs precio actual
  downsideProtection?: number // solo covered call: costBasis - premium (cuánto puede caer la acción)
  downsideProtectionPct?: number
  maxProfit: number      // por todos los contratos (Infinity para buy call)
  maxLoss: number        // por todos los contratos
  roiPct: number
  annualizedRoiPct: number
  score: number
  strategyName: string
}

function calcBrokerOption(
  row: BrokerOptionRow,
  stockPrice: number,
  costBasis: number,
  commissionPerContract = 0
): BrokerOptionCalc | null {
  const strike = parseFloat(row.strike)
  const premium = parseFloat(row.premium)
  const contracts = parseInt(row.contracts) || 1
  if (!row.expiration || isNaN(strike) || isNaN(premium) || strike <= 0 || premium <= 0 || stockPrice <= 0) return null

  const totalCommission = commissionPerContract * contracts

  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const exp = new Date(row.expiration + 'T00:00:00')
  const dte = Math.max(0, Math.round((exp.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)))

  // % OTM desde el precio actual (positivo = fuera del dinero en la dirección favorable)
  const otmPct =
    row.type === 'call'
      ? ((strike - stockPrice) / stockPrice) * 100   // call OTM si strike > precio
      : ((stockPrice - strike) / stockPrice) * 100    // put OTM si strike < precio

  let breakeven: number
  let maxProfit: number
  let maxLoss: number
  let roiPct: number
  let strategyName: string
  let totalCashFlow: number

  let downsideProtection: number | undefined
  let downsideProtectionPct: number | undefined

  if (row.side === 'sell') {
    // ── VENDER opción ──────────────────────────────────────────
    totalCashFlow = premium * 100 * contracts - totalCommission  // neto tras comisión

    if (row.type === 'call') {
      strategyName = 'Covered Call'
      breakeven = strike + premium
      maxProfit = premium * 100 * contracts - totalCommission
      const basis = costBasis > 0 ? costBasis : stockPrice
      maxLoss = Math.max(0, (basis - premium) * 100 * contracts + totalCommission)
      const capitalAtRisk = basis * 100
      roiPct = (maxProfit / capitalAtRisk) * 100
      downsideProtection = basis - premium
      downsideProtectionPct = ((stockPrice - downsideProtection) / stockPrice) * 100
    } else {
      strategyName = 'Cash-Secured Put'
      breakeven = strike - premium
      maxProfit = premium * 100 * contracts - totalCommission
      maxLoss = Math.max(0, (strike - premium) * 100 * contracts + totalCommission)
      const capitalAtRisk = strike * 100
      roiPct = (maxProfit / capitalAtRisk) * 100
    }
  } else {
    // ── COMPRAR opción ─────────────────────────────────────────
    totalCashFlow = -(premium * 100 * contracts) - totalCommission  // costo total

    if (row.type === 'call') {
      strategyName = 'Buy Call'
      breakeven = strike + premium
      maxProfit = Infinity
      maxLoss = premium * 100 * contracts + totalCommission
      roiPct = ((stockPrice - breakeven) / breakeven) * 100
    } else {
      strategyName = 'Buy Put'
      breakeven = strike - premium
      maxProfit = Math.max(0, (strike - premium) * 100 * contracts - totalCommission)
      maxLoss = premium * 100 * contracts + totalCommission
      roiPct = ((breakeven - stockPrice) / stockPrice) * 100
    }
  }

  const annualizedRoiPct = row.side === 'sell' && dte > 0 ? (roiPct / dte) * 365 : roiPct
  const breakevenMovePct = ((breakeven - stockPrice) / stockPrice) * 100

  // Score: para ventas = ROI anualizado ponderado por seguridad OTM
  //        para compras = potencial de retorno (negativo si estás perdiendo ya)
  let score: number
  if (row.side === 'sell') {
    const safetyBonus = otmPct > 5 ? 1.1 : otmPct > 0 ? 1.0 : 0.85
    score = annualizedRoiPct * safetyBonus
  } else {
    score = roiPct  // para compras: ROI potencial
  }

  return {
    id: row.id,
    side: row.side,
    type: row.type,
    strike,
    expiration: row.expiration,
    premium,
    contracts,
    dte,
    totalCashFlow,
    otmPct,
    breakeven,
    breakevenMovePct,
    downsideProtection,
    downsideProtectionPct,
    maxProfit,
    maxLoss,
    roiPct,
    annualizedRoiPct,
    score,
    strategyName,
  }
}
// --- end Broker Data ---

interface PortfolioStock {
  id: number
  ticker: string
  company_name: string
  shares: number
  adjusted_cost_basis: number
}

interface ActiveOption {
  id: number
  ticker: string
  option_type: 'CALL' | 'PUT'
  strategy: string
  strike_price: number
  contracts: number
  premium_per_contract: number
  expiration_date: string
  days_to_expiration?: number
}

function Calculator() {
  // --- Broker Data state ---
  const [portfolioStocks, setPortfolioStocks] = useState<PortfolioStock[]>([])
  const [portfolioLoading, setPortfolioLoading] = useState(false)
  const [selectedStockId, setSelectedStockId] = useState<number | ''>('')
  const [activeOptions, setActiveOptions] = useState<ActiveOption[]>([])
  const [rollOption, setRollOption] = useState<ActiveOption | null>(null)
  const [brokerTicker, setBrokerTicker] = useState('')
  const [brokerStockPrice, setBrokerStockPrice] = useState('')
  const [brokerCostBasis, setBrokerCostBasis] = useState('')
  const [brokerCommission, setBrokerCommission] = useState('0.65')  // IB default

  useEffect(() => {
    setPortfolioLoading(true)
    api.get('/api/stocks/')
      .then(res => setPortfolioStocks(res.data.filter((s: any) => s.is_active)))
      .catch(() => {})
      .finally(() => setPortfolioLoading(false))
  }, [])

  const handleStockSelect = (id: number | '') => {
    setSelectedStockId(id)
    setRollOption(null)
    setActiveOptions([])
    if (id === '') {
      setBrokerTicker('')
      setBrokerCostBasis('')
      return
    }
    const s = portfolioStocks.find(s => s.id === id)
    if (s) {
      setBrokerTicker(s.ticker)
      setBrokerCostBasis(s.adjusted_cost_basis.toFixed(2))
      // Cargar opciones abiertas de esta acción (filtramos por stock_id en el frontend)
      api.get(`/api/options/?status=OPEN`)
        .then(res => setActiveOptions((res.data || []).filter((o: any) => o.stock_id === id)))
        .catch(() => {})
    }
  }

  const loadRollOption = (opt: ActiveOption) => {
    setRollOption(opt)
    const expDate = opt.expiration_date.split('T')[0]
    setBrokerOptionRows(prev => {
      const updated = prev.map((r, i) => i === 0
        ? { ...r, side: 'sell' as const, type: opt.option_type.toLowerCase() as 'call'|'put',
            strike: opt.strike_price.toString(), expiration: expDate,
            premium: '',  // usuario debe ingresar precio actual de cierre (BTC)
            contracts: opt.contracts.toString(),
            _originalPremium: opt.premium_per_contract.toString() } as any
        : r
      )
      if (updated.length < 2) {
        const newId = updated[updated.length - 1].id + 1
        setNextId(newId + 1)
        return [
          ...updated,
          { id: newId, side: 'sell' as const, type: opt.option_type.toLowerCase() as 'call'|'put',
            strike: '', expiration: '', premium: '', contracts: opt.contracts.toString() }
        ]
      }
      return updated
    })
  }

  const [rollConfirm, setRollConfirm] = useState<BrokerOptionCalc | null>(null)
  const [rollExecuting, setRollExecuting] = useState(false)
  const [rollDone, setRollDone] = useState<string | null>(null)

  const executeRoll = async () => {
    if (!rollConfirm || !rollOption) return
    setRollExecuting(true)
    try {
      await api.put(`/api/options/${rollOption.id}`, {
        strike_price: rollConfirm.strike,
        premium_per_contract: rollConfirm.premium,
        contracts: rollConfirm.contracts,
        expiration_date: rollConfirm.expiration + 'T00:00:00',
        opened_at: new Date().toISOString(),
      })
      const expFmt = new Date(rollConfirm.expiration + 'T00:00:00')
        .toLocaleDateString('es-CL', { day: '2-digit', month: 'short', year: '2-digit' })
      setRollDone(`Roll ejecutado: ${rollOption.option_type} $${rollConfirm.strike.toFixed(2)} vto. ${expFmt} @ $${rollConfirm.premium.toFixed(2)}/acc`)
      setRollConfirm(null)
      // Refrescar opciones activas
      if (selectedStockId !== '') {
        api.get('/api/options/?status=OPEN')
          .then(res => {
            setActiveOptions((res.data || []).filter((o: any) => o.stock_id === selectedStockId))
            setRollOption(null)
          })
          .catch(() => {})
      }
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Error al ejecutar el roll')
    } finally {
      setRollExecuting(false)
    }
  }
  const [brokerOptionRows, setBrokerOptionRows] = useState<BrokerOptionRow[]>([
    { id: 1, side: 'sell', type: 'call', strike: '', expiration: '', premium: '', contracts: '1' },
  ])
  const [nextId, setNextId] = useState(2)

  const addOptionRow = () => {
    setBrokerOptionRows(prev => [
      ...prev,
      { id: nextId, side: 'sell', type: 'call', strike: '', expiration: '', premium: '', contracts: '1' },
    ])
    setNextId(n => n + 1)
  }

  const removeOptionRow = (id: number) => {
    setBrokerOptionRows(prev => prev.filter(r => r.id !== id))
  }

  const updateOptionRow = (id: number, field: keyof BrokerOptionRow, value: string) => {
    setBrokerOptionRows(prev =>
      prev.map(r => (r.id === id ? { ...r, [field]: value } : r))
    )
  }

  const brokerCalcResults: (BrokerOptionCalc | null)[] = brokerOptionRows.map(row =>
    calcBrokerOption(row, parseFloat(brokerStockPrice) || 0, parseFloat(brokerCostBasis) || 0, parseFloat(brokerCommission) || 0)
  )

  const validResults = brokerCalcResults.filter((r): r is BrokerOptionCalc => r !== null)
  // Excluir la fila base del roll del cálculo de mejor opción
  const rollBaseId = rollOption ? brokerOptionRows[0]?.id : null
  const candidatesForBest = rollBaseId != null ? validResults.filter(r => r.id !== rollBaseId) : validResults
  const bestId = candidatesForBest.length > 0 ? candidatesForBest.reduce((a, b) => (a.score > b.score ? a : b)).id : null
  // --- end Broker Data state ---

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Calculadora de Opciones</h1>
          <p className="page-subtitle">Analiza y compara estrategias con datos reales de tu broker</p>
        </div>
      </div>

      <div className="space-y-6">

          {/* Roll confirmation modal */}
          {rollConfirm && rollOption && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-md w-full mx-4">
                <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100 mb-1">Confirmar Roll</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
                  Esto actualiza la opción activa con los nuevos valores seleccionados.
                </p>
                <div className="space-y-3 mb-5">
                  <div className="rounded-lg bg-gray-100 dark:bg-gray-700 p-3">
                    <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase mb-2">Opción actual (se reemplaza)</p>
                    <div className="grid grid-cols-3 gap-2 text-sm text-gray-700 dark:text-gray-200">
                      <div><span className="block text-xs text-gray-400">Strike</span><strong>${rollOption.strike_price.toFixed(2)}</strong></div>
                      <div><span className="block text-xs text-gray-400">Vencimiento</span><strong>{new Date(rollOption.expiration_date.split('T')[0] + 'T00:00:00').toLocaleDateString('es-CL', {day:'2-digit',month:'short',year:'2-digit'})}</strong></div>
                      <div><span className="block text-xs text-gray-400">Prima/acc</span><strong>${rollOption.premium_per_contract.toFixed(2)}</strong></div>
                    </div>
                  </div>
                  <div className="flex items-center justify-center"><span className="text-2xl text-green-500">↓</span></div>
                  <div className="rounded-lg bg-green-50 dark:bg-green-900/30 border border-green-300 dark:border-green-700 p-3">
                    <p className="text-xs font-semibold text-green-700 dark:text-green-400 uppercase mb-2">Nueva opción (roll)</p>
                    <div className="grid grid-cols-3 gap-2 text-sm text-gray-700 dark:text-gray-200">
                      <div>
                        <span className="block text-xs text-gray-400">Strike</span>
                        <strong className={rollConfirm.strike !== rollOption.strike_price ? 'text-blue-600 dark:text-blue-400' : ''}>
                          ${rollConfirm.strike.toFixed(2)}
                          {rollConfirm.strike !== rollOption.strike_price && (
                            <span className="ml-1 text-xs">({rollConfirm.strike > rollOption.strike_price ? '+' : ''}{(rollConfirm.strike - rollOption.strike_price).toFixed(2)})</span>
                          )}
                        </strong>
                      </div>
                      <div><span className="block text-xs text-gray-400">Vencimiento</span><strong>{new Date(rollConfirm.expiration + 'T00:00:00').toLocaleDateString('es-CL', {day:'2-digit',month:'short',year:'2-digit'})}</strong></div>
                      <div><span className="block text-xs text-gray-400">Prima/acc</span><strong>${rollConfirm.premium.toFixed(2)}</strong></div>
                    </div>
                  </div>
                  {(() => {
                    const baseRow = validResults.find(vr => vr.id === rollBaseId)
                    const commission = parseFloat(brokerCommission) || 0
                    const btcCost = baseRow
                      ? baseRow.premium * 100 * baseRow.contracts + commission * baseRow.contracts
                      : rollOption.premium_per_contract * rollOption.contracts * 100 + commission * rollOption.contracts
                    const netCredit = rollConfirm.totalCashFlow - btcCost
                    return (
                      <div className={`rounded-lg p-3 text-sm font-semibold ${netCredit >= 0 ? 'bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-300' : 'bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300'}`}>
                        {netCredit >= 0 ? `✅ Roll por crédito neto: +$${netCredit.toFixed(2)}` : `⚠️ Roll por débito neto: -$${Math.abs(netCredit).toFixed(2)}`}
                        <span className="block text-xs font-normal mt-0.5 opacity-80">DTE nuevos: {rollConfirm.dte} días · ROI anualizado: {rollConfirm.annualizedRoiPct.toFixed(1)}%</span>
                        {baseRow && <span className="block text-xs font-normal opacity-70">BTC: ${(baseRow.premium * 100 * baseRow.contracts + commission * baseRow.contracts).toFixed(2)} · STO: ${rollConfirm.totalCashFlow.toFixed(2)}</span>}
                      </div>
                    )
                  })()}
                </div>
                <div className="flex gap-3">
                  <button onClick={() => setRollConfirm(null)} className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700">
                    Cancelar
                  </button>
                  <button onClick={executeRoll} disabled={rollExecuting} className="flex-1 px-4 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white font-semibold rounded-lg">
                    {rollExecuting ? 'Ejecutando...' : 'Confirmar Roll'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Roll success banner */}
          {rollDone && (
            <div className="flex items-center justify-between bg-green-100 dark:bg-green-900/40 border border-green-300 dark:border-green-700 rounded-lg px-4 py-3">
              <span className="text-sm text-green-800 dark:text-green-300 font-medium">✅ {rollDone}</span>
              <button onClick={() => setRollDone(null)} className="text-green-600 hover:text-green-800 text-lg font-bold ml-4">×</button>
            </div>
          )}

          {/* Explanation banner */}
          <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-700 rounded-lg p-4">
            <p className="text-sm text-green-800 dark:text-green-300 font-medium mb-1">
              📋 Calculadora con datos reales del broker
            </p>
            <p className="text-sm text-green-700 dark:text-green-400">
              Ingresa el precio actual de la acción, base de costo y luego agrega las opciones que ves en tu broker
              (strike, vencimiento y prima). La calculadora compara todas y te indica cuál conviene más.
            </p>
          </div>

          {/* Stock info */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
            <h3 className="text-base font-semibold text-gray-800 dark:text-gray-100 mb-4">1. Seleccioná la acción</h3>

            {/* Portfolio selector */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Acción del portfolio
              </label>
              {portfolioLoading ? (
                <p className="text-xs text-gray-400">Cargando portfolio...</p>
              ) : portfolioStocks.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {portfolioStocks.map(s => (
                    <button
                      key={s.id}
                      onClick={() => handleStockSelect(selectedStockId === s.id ? '' : s.id)}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors ${
                        selectedStockId === s.id
                          ? 'bg-green-600 border-green-600 text-white'
                          : 'bg-white dark:bg-gray-700 border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 hover:border-green-500'
                      }`}
                    >
                      <span className="font-bold">{s.ticker}</span>
                      <span className="ml-1.5 text-xs opacity-75">{s.shares} acc · base ${s.adjusted_cost_basis.toFixed(2)}</span>
                    </button>
                  ))}
                  <button
                    onClick={() => handleStockSelect('')}
                    className="px-3 py-1.5 rounded-lg text-sm border border-dashed border-gray-400 dark:border-gray-500 text-gray-500 dark:text-gray-400 hover:border-gray-600"
                  >
                    + otra acción
                  </button>
                </div>
              ) : (
                <p className="text-xs text-gray-400">No tienes acciones registradas. Ingresa los datos manualmente abajo.</p>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-3 border-t border-gray-100 dark:border-gray-700">
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Ticker</label>
                <input
                  type="text"
                  value={brokerTicker}
                  onChange={e => { setBrokerTicker(e.target.value.toUpperCase()); setSelectedStockId('') }}
                  placeholder="AAPL"
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                  Precio actual — ingresalo desde tu broker
                </label>
                <input
                  type="number"
                  value={brokerStockPrice}
                  onChange={e => setBrokerStockPrice(e.target.value)}
                  placeholder="7.55"
                  step="0.01"
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
                />
                <p className="text-xs text-gray-400 mt-1">⚡ Usa el precio en tiempo real de tu broker</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                  Comisión por contrato
                </label>
                <input
                  type="number"
                  value={brokerCommission}
                  onChange={e => setBrokerCommission(e.target.value)}
                  placeholder="0.65"
                  step="0.01"
                  min="0"
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
                />
                <p className="text-xs text-gray-400 mt-1">IB ≈ $0.65/contrato · 0 para ignorar</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                  Base de costo / acción
                </label>
                <input
                  type="number"
                  value={brokerCostBasis}
                  onChange={e => setBrokerCostBasis(e.target.value)}
                  placeholder="140.00"
                  step="0.01"
                  className={`w-full px-3 py-2 border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-green-500 ${
                    selectedStockId !== ''
                      ? 'border-green-400 dark:border-green-600 bg-green-50 dark:bg-green-900/20 text-gray-900 dark:text-gray-100'
                      : 'border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100'
                  }`}
                />
                <p className="text-xs text-gray-400 mt-1">
                  {selectedStockId !== '' ? '✅ Base de costo del portfolio' : 'Opcional — para Covered Call'}
                </p>
              </div>
            </div>
          </div>

          {/* Active options panel (roll) */}
          {activeOptions.length > 0 && (
            <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-yellow-700 dark:text-yellow-300 font-semibold text-sm">🔄 Opciones abiertas en {brokerTicker}</span>
                <span className="text-xs text-yellow-600 dark:text-yellow-400">— haz clic en "Usar para roll" para pre-cargar los datos actuales</span>
              </div>
              <div className="space-y-2">
                {activeOptions.map(opt => {
                  const expFmt = new Date(opt.expiration_date + (opt.expiration_date.includes('T') ? '' : 'T00:00:00'))
                    .toLocaleDateString('es-CL', { day: '2-digit', month: 'short', year: '2-digit' })
                  const isRoll = rollOption?.id === opt.id
                  return (
                    <div key={opt.id} className={`flex flex-wrap items-center gap-3 rounded-lg px-3 py-2 text-sm ${isRoll ? 'bg-yellow-200 dark:bg-yellow-800/40' : 'bg-white dark:bg-gray-800'}`}>
                      <span className={`font-bold px-2 py-0.5 rounded text-xs ${opt.option_type === 'CALL' ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300' : 'bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300'}`}>
                        {opt.option_type}
                      </span>
                      <span className="text-gray-700 dark:text-gray-200">Strike <strong>${opt.strike_price.toFixed(2)}</strong></span>
                      <span className="text-gray-700 dark:text-gray-200">Vto. <strong>{expFmt}</strong>{opt.days_to_expiration != null && <span className="text-gray-400 ml-1">({opt.days_to_expiration}d)</span>}</span>
                      <span className="text-gray-700 dark:text-gray-200">Prima <strong>${opt.premium_per_contract.toFixed(2)}/acc</strong></span>
                      <span className="text-gray-700 dark:text-gray-200">{opt.contracts} contrato{opt.contracts > 1 ? 's' : ''}</span>
                      <button
                        onClick={() => isRoll ? setRollOption(null) : loadRollOption(opt)}
                        className={`ml-auto px-3 py-1 text-xs rounded-md font-medium ${isRoll ? 'bg-yellow-500 text-white' : 'bg-yellow-400 hover:bg-yellow-500 text-yellow-900'}`}
                      >
                        {isRoll ? '✓ Usando para roll' : 'Usar para roll'}
                      </button>
                    </div>
                  )
                })}
              </div>
              {rollOption && (
                <p className="mt-2 text-xs text-yellow-700 dark:text-yellow-400">
                  💡 Fila 1 = posición actual (BTC). Fila 2+ = candidatos del roll (STO). El campo <strong>⚠️ Precio cierre (BTC)</strong> debe ser el precio actual de mercado para cerrar, no la prima original.
                </p>
              )}
            </div>
          )}

          {/* Options entry table */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-gray-800 dark:text-gray-100">
                {rollOption ? `2. Comparar opciones — Roll desde $${rollOption.strike_price.toFixed(2)} ${rollOption.option_type}` : '2. Opciones del broker'}
              </h3>
              <button
                onClick={addOptionRow}
                className="px-3 py-1.5 text-sm bg-green-600 hover:bg-green-700 text-white rounded-md"
              >
                + Agregar opción
              </button>
            </div>

            {/* Column headers */}
            <div className="hidden md:grid gap-2 mb-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase px-1" style={{gridTemplateColumns:'1fr 1fr 1fr 1fr 1fr 1fr 32px'}}>
              <span>Acción</span>
              <span>Tipo</span>
              <span>Strike (USD)</span>
              <span>Vencimiento</span>
              <span>Prima / acción (USD)</span>
              <span>Contratos</span>
              <span></span>
            </div>

            <div className="space-y-3">
              {brokerOptionRows.map((row, rowIdx) => {
                const isBaseRow = rollOption != null && rowIdx === 0
                return (
                <div key={row.id} className={`grid gap-2 items-center rounded-lg p-3 border-l-4 ${
                  isBaseRow
                    ? 'bg-yellow-50 dark:bg-yellow-900/10 border-yellow-500'
                    : row.side === 'sell'
                    ? 'bg-blue-50 dark:bg-blue-900/10 border-blue-400'
                    : 'bg-orange-50 dark:bg-orange-900/10 border-orange-400'
                }`} style={{gridTemplateColumns:'1fr 1fr 1fr 1fr 1fr 1fr 32px'}}>

                  {/* Side: Sell / Buy */}
                  <div>
                    <label className="md:hidden text-xs text-gray-500 dark:text-gray-400">Acción</label>
                    <div className="flex rounded-md overflow-hidden border border-gray-300 dark:border-gray-600 text-sm font-medium">
                      <button
                        onClick={() => updateOptionRow(row.id, 'side', 'sell')}
                        className={`flex-1 py-1.5 transition-colors ${
                          row.side === 'sell'
                            ? 'bg-blue-600 text-white'
                            : 'bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                        }`}
                      >
                        Vender
                      </button>
                      <button
                        onClick={() => updateOptionRow(row.id, 'side', 'buy')}
                        className={`flex-1 py-1.5 transition-colors ${
                          row.side === 'buy'
                            ? 'bg-orange-500 text-white'
                            : 'bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'
                        }`}
                      >
                        Comprar
                      </button>
                    </div>
                    <p className="text-xs mt-1 text-center">
                      {row.side === 'sell'
                        ? <span className="text-blue-600 dark:text-blue-400">{row.type === 'call' ? 'Covered Call' : 'Cash-Secured Put'}</span>
                        : <span className="text-orange-500">{row.type === 'call' ? 'Buy Call (alcista)' : 'Buy Put (bajista/cobertura)'}</span>
                      }
                    </p>
                  </div>

                  {/* Type */}
                  <div>
                    <label className="md:hidden text-xs text-gray-500 dark:text-gray-400">Tipo</label>
                    <select
                      value={row.type}
                      onChange={e => updateOptionRow(row.id, 'type', e.target.value)}
                      className="w-full px-2 py-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-md focus:outline-none focus:ring-1 focus:ring-green-500"
                    >
                      <option value="call">📈 Call</option>
                      <option value="put">📉 Put</option>
                    </select>
                  </div>

                  {/* Strike */}
                  <div>
                    <label className="md:hidden text-xs text-gray-500 dark:text-gray-400">Strike</label>
                    <input
                      type="number"
                      value={row.strike}
                      onChange={e => updateOptionRow(row.id, 'strike', e.target.value)}
                      placeholder="155.00"
                      step="0.5"
                      className="w-full px-2 py-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-md focus:outline-none focus:ring-1 focus:ring-green-500"
                    />
                  </div>

                  {/* Expiration */}
                  <div>
                    <label className="md:hidden text-xs text-gray-500 dark:text-gray-400">Vencimiento</label>
                    <input
                      type="date"
                      value={row.expiration}
                      onChange={e => updateOptionRow(row.id, 'expiration', e.target.value)}
                      className="w-full px-2 py-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-md focus:outline-none focus:ring-1 focus:ring-green-500"
                    />
                  </div>

                  {/* Premium */}
                  <div>
                    <label className="md:hidden text-xs text-gray-500 dark:text-gray-400">Prima / acción</label>
                    {isBaseRow && (
                      <p className="text-xs font-semibold text-red-500 dark:text-red-400 mb-1">
                        ⚠️ Precio cierre (BTC)
                        {(row as any)._originalPremium && (
                          <span className="ml-1 text-gray-400 font-normal">era ${(row as any)._originalPremium}</span>
                        )}
                      </p>
                    )}
                    <input
                      type="number"
                      value={row.premium}
                      onChange={e => updateOptionRow(row.id, 'premium', e.target.value)}
                      placeholder={isBaseRow ? (
                        (row as any)._originalPremium ? `era $${(row as any)._originalPremium}` : '0.02'
                      ) : '2.50'}
                      step="0.01"
                      className={`w-full px-2 py-1.5 text-sm border rounded-md focus:outline-none focus:ring-1 ${
                        isBaseRow
                          ? 'border-red-400 dark:border-red-500 bg-red-50 dark:bg-red-900/20 dark:text-gray-100 focus:ring-red-500'
                          : 'border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 focus:ring-green-500'
                      }`}
                    />
                  </div>

                  {/* Contracts */}
                  <div>
                    <label className="md:hidden text-xs text-gray-500 dark:text-gray-400">Contratos</label>
                    <input
                      type="number"
                      value={row.contracts}
                      onChange={e => updateOptionRow(row.id, 'contracts', e.target.value)}
                      min="1"
                      step="1"
                      className="w-full px-2 py-1.5 text-sm border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-md focus:outline-none focus:ring-1 focus:ring-green-500"
                    />
                  </div>

                  {/* Remove */}
                  <div className="flex justify-end">
                    {brokerOptionRows.length > 1 && (
                      <button
                        onClick={() => removeOptionRow(row.id)}
                        className="text-red-500 hover:text-red-700 text-lg font-bold px-2"
                        title="Eliminar"
                      >
                        ×
                      </button>
                    )}
                  </div>
                </div>
              )})}
            </div>

            <p className="mt-3 text-xs text-gray-400 dark:text-gray-500">
              💡 La <strong>prima</strong> es el precio por acción que ves en la columna &ldquo;bid&rdquo;, &ldquo;ask&rdquo; o &ldquo;last&rdquo; de la cadena de opciones de tu broker (cada contrato = 100 acciones).
            </p>
          </div>

          {/* Results */}
          {validResults.length > 0 && parseFloat(brokerStockPrice) > 0 && (
            <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                <h3 className="text-base font-semibold text-gray-800 dark:text-gray-100">
                  3. Análisis comparativo {brokerTicker && <span className="text-green-600 dark:text-green-400 ml-1">— {brokerTicker}</span>}
                </h3>
                {bestId && (
                  <span className="text-xs bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 px-2 py-1 rounded-full">
                    ✅ Mejor opción resaltada
                  </span>
                )}
              </div>

              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-900">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Estrategia</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Strike</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Vto.</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">DTE</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Flujo de caja</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">OTM / ITM</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Breakeven / Protección</th>
                      {rollOption && <th className="px-4 py-3 text-left text-xs font-medium text-yellow-600 dark:text-yellow-400 uppercase">Roll vs actual</th>}
                      {rollOption && <th className="px-4 py-3 text-left text-xs font-medium text-green-600 dark:text-green-400 uppercase">Acción</th>}
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Ganancia máx.</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Pérdida máx.</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">ROI Anualizado</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                    {validResults
                      .slice()
                      .sort((a, b) => b.score - a.score)
                      .map((r) => {
                        const isBest = r.id === bestId
                        const isSell = r.side === 'sell'
                        const isRollBase = rollOption != null && r.id === rollBaseId
                        const otmLabel =
                          r.otmPct > 0
                            ? <span className="text-green-600 dark:text-green-400">+{r.otmPct.toFixed(1)}% OTM</span>
                            : r.otmPct < 0
                            ? <span className="text-red-500 dark:text-red-400">{r.otmPct.toFixed(1)}% ITM</span>
                            : <span className="text-yellow-500">ATM</span>

                        // Crédito/débito neto del roll vs la posición base (primera fila)
                        let rollCell = null
                        if (rollOption) {
                          if (isRollBase) {
                            rollCell = <td className="px-4 py-3 text-xs text-gray-400 dark:text-gray-500 italic">posición actual</td>
                          } else {
                            // BTC cost = prima base × 100 × contratos + comisión (se paga al cerrar)
                            const baseRow = validResults.find(vr => vr.id === rollBaseId)
                            const commission = parseFloat(brokerCommission) || 0
                            const btcCost = baseRow
                              ? baseRow.premium * 100 * baseRow.contracts + commission * baseRow.contracts
                              : rollOption.premium_per_contract * rollOption.contracts * 100 + commission * rollOption.contracts
                            const netCredit = r.totalCashFlow - btcCost
                            const strikeChange = r.strike - rollOption.strike_price
                            rollCell = (
                              <td className="px-4 py-3">
                                <span className={`block font-semibold ${netCredit >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}`}>
                                  {netCredit >= 0 ? '+' : ''}${netCredit.toFixed(2)}
                                </span>
                                <span className="block text-xs text-gray-400">
                                  {netCredit >= 0 ? 'crédito neto' : 'débito neto'}
                                </span>
                                {strikeChange !== 0 && (
                                  <span className={`block text-xs font-medium ${strikeChange > 0 ? 'text-green-500' : 'text-orange-500'}`}>
                                    Strike {strikeChange > 0 ? '+' : ''}{strikeChange.toFixed(2)}
                                  </span>
                                )}
                                {strikeChange === 0 && (
                                  <span className="block text-xs text-gray-400">mismo strike</span>
                                )}
                              </td>
                            )
                          }
                        }

                        return (
                          <tr key={r.id} className={
                            isRollBase ? 'bg-yellow-50 dark:bg-yellow-900/10 opacity-75' :
                            isBest ? 'bg-green-50 dark:bg-green-900/30' : ''
                          }>
                            <td className={`px-4 py-3 font-medium${isBest && !isRollBase ? ' border-l-4 border-green-500' : ''}`}>
                              {isBest && !isRollBase && (
                                <span className="inline-block mr-2 px-2 py-0.5 rounded-full text-xs font-bold bg-green-500 text-white">✓ MEJOR</span>
                              )}
                              {isRollBase && <span className="mr-1 text-yellow-600">📌</span>}
                              <span className={`inline-block px-2 py-0.5 rounded text-xs font-bold mr-1 ${
                                isSell ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300' : 'bg-orange-100 dark:bg-orange-900 text-orange-700 dark:text-orange-300'
                              }`}>
                                {isSell ? 'Vender' : 'Comprar'}
                              </span>
                              <span className={r.type === 'call' ? 'text-blue-600 dark:text-blue-400' : 'text-purple-600 dark:text-purple-400'}>
                                {r.strategyName}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-gray-900 dark:text-gray-100">
                              ${r.strike.toFixed(2)}
                            </td>
                            <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                              {new Date(r.expiration + 'T00:00:00').toLocaleDateString('es-CL', { day:'2-digit', month:'short', year:'2-digit' })}
                            </td>
                            <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                              <span className={r.dte <= 21 ? 'text-orange-500 font-medium' : ''}>
                                {r.dte}d
                              </span>
                            </td>
                            <td className="px-4 py-3 font-semibold">
                              <span className={r.totalCashFlow >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'}>
                                {r.totalCashFlow >= 0 ? '+' : ''}{r.totalCashFlow.toFixed(2)}
                              </span>
                              <span className="block text-xs text-gray-400 font-normal">
                                {isRollBase ? 'BTC → pagas' : (r.totalCashFlow >= 0 ? 'recibes' : 'pagas')}
                                {parseFloat(brokerCommission) > 0 && (
                                  <span className="ml-1 text-gray-400">· c/com.</span>
                                )}
                              </span>
                              {/* Para filas candidato en modo roll: mostrar neto del roll */}
                              {rollOption && !isRollBase && (() => {
                                const baseRow = validResults.find(vr => vr.id === rollBaseId)
                                const commission = parseFloat(brokerCommission) || 0
                                const btcCost = baseRow
                                  ? baseRow.premium * 100 * baseRow.contracts + commission * baseRow.contracts
                                  : rollOption.premium_per_contract * rollOption.contracts * 100 + commission * rollOption.contracts
                                const netRoll = r.totalCashFlow - btcCost
                                return (
                                  <span className={`block text-xs font-semibold mt-0.5 ${netRoll >= 0 ? 'text-green-500' : 'text-red-400'}`}>
                                    Neto roll: {netRoll >= 0 ? '+' : ''}${netRoll.toFixed(2)}
                                  </span>
                                )
                              })()}
                            </td>
                            <td className="px-4 py-3">{otmLabel}</td>
                            <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                              {/* Para Covered Call: dos valores */}
                              {r.side === 'sell' && r.type === 'call' ? (
                                <>
                                  <div className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">Upside cap:</div>
                                  <div className="font-medium">${r.breakeven.toFixed(2)}</div>
                                  <div className={`text-xs ${r.breakevenMovePct > 0 ? 'text-blue-400' : 'text-gray-400'}`}>
                                    {r.breakevenMovePct > 0 ? '+' : ''}{r.breakevenMovePct.toFixed(1)}% vs precio
                                  </div>
                                  {r.downsideProtection != null && r.downsideProtectionPct != null && (
                                    <>
                                      <div className="text-xs text-gray-500 dark:text-gray-400 mt-1.5 mb-0.5">Protección baja:</div>
                                      <div className="font-medium text-green-600 dark:text-green-400">${r.downsideProtection.toFixed(2)}</div>
                                      <div className="text-xs text-green-500">−{r.downsideProtectionPct.toFixed(1)}% puede caer</div>
                                    </>
                                  )}
                                </>
                              ) : (
                                <>
                                  <div className="font-medium">${r.breakeven.toFixed(2)}</div>
                                  <span className={`text-xs ${r.breakevenMovePct > 0 ? 'text-red-400' : 'text-green-500'}`}>
                                    {r.breakevenMovePct > 0 ? '+' : ''}{r.breakevenMovePct.toFixed(1)}% vs precio
                                  </span>
                                </>
                              )}
                            </td>
                            {rollOption && rollCell}
                            {/* Ejecutar Roll button */}
                            {rollOption && !isRollBase && (
                              <td className="px-4 py-3">
                                <button
                                  onClick={() => setRollConfirm(r)}
                                  className="px-3 py-1.5 text-xs font-semibold bg-green-600 hover:bg-green-700 text-white rounded-lg whitespace-nowrap"
                                >
                                  🔄 Ejecutar Roll
                                </button>
                              </td>
                            )}
                            {rollOption && isRollBase && <td className="px-4 py-3" />}
                            <td className="px-4 py-3 text-green-600 dark:text-green-400 font-medium">
                              {r.maxProfit === Infinity ? '∞ ilimitada' : `$${r.maxProfit.toFixed(2)}`}
                            </td>
                            <td className="px-4 py-3 text-red-500 dark:text-red-400">
                              ${r.maxLoss.toFixed(2)}
                            </td>
                            <td className="px-4 py-3 font-bold">
                              {isSell ? (
                                <span className={r.annualizedRoiPct >= 20 ? 'text-green-600 dark:text-green-400' : r.annualizedRoiPct >= 10 ? 'text-blue-600 dark:text-blue-400' : 'text-gray-700 dark:text-gray-300'}>
                                  {r.annualizedRoiPct.toFixed(1)}%
                                </span>
                              ) : (
                                <span className="text-xs text-gray-500 dark:text-gray-400 font-normal">
                                  ROI varía con el precio
                                </span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                  </tbody>
                </table>
              </div>

              {/* Legend */}
              <div className="px-6 py-4 bg-gray-50 dark:bg-gray-900/50 border-t border-gray-200 dark:border-gray-700">
                <h4 className="text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase mb-2">Glosario</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1 text-xs text-gray-600 dark:text-gray-400">
                  <span><strong>Vender Call</strong> (Covered Call): recibes prima, limitas el upside</span>
                  <span><strong>Vender Put</strong> (CSP): recibes prima, te comprometes a comprar al strike</span>
                  <span><strong>Comprar Call</strong>: pagas prima, ganas si el precio sube del breakeven</span>
                  <span><strong>Comprar Put</strong>: pagas prima, ganas si el precio baja / cobertura</span>
                  <span><strong>Upside cap</strong>: precio desde el cual ya no ganas más (Covered Call)</span>
                  <span><strong>Protección baja</strong>: hasta qué precio puede caer la acción antes de perder dinero neto</span>
                  <span><strong>Flujo de caja</strong>: + recibes, − pagas (por todos los contratos)</span>
                  <span><strong>OTM</strong>: fuera del dinero — para ventas significa que expira sin valor</span>
                  <span><strong>DTE</strong>: días hasta el vencimiento</span>
                  <span><strong>Roll crédito neto</strong>: prima nueva − prima actual (positivo = roll por crédito)</span>
                  <span><strong>ROI Anualizado</strong>: solo aplica para ventas (ingreso por tiempo)</span>
                  <span><strong>c/com.</strong>: flujo de caja ya incluye comisión del broker por contrato</span>
                </div>
              </div>
            </div>
          )}

          {/* ── PROYECCIÓN ANUAL (Wheel) ────────────────────────── */}
          {(() => {
            const sellResults = validResults.filter(r => r.side === 'sell' && r.id !== rollBaseId)
            if (sellResults.length === 0 || !parseFloat(brokerStockPrice)) return null
            const best = candidatesForBest.length > 0
              ? candidatesForBest.filter(r => r.side === 'sell').reduce((a, b) => a.score > b.score ? a : b, candidatesForBest.filter(r => r.side === 'sell')[0])
              : sellResults[0]
            if (!best) return null
            const cyclesPerYear = best.dte > 0 ? 365 / best.dte : 0
            const annualIncome = best.maxProfit * cyclesPerYear
            const capitalAtRisk = best.type === 'call'
              ? (parseFloat(brokerCostBasis) || parseFloat(brokerStockPrice)) * 100 * best.contracts
              : best.strike * 100 * best.contracts
            const annualRoi = capitalAtRisk > 0 ? (annualIncome / capitalAtRisk) * 100 : 0
            const monthlyIncome = annualIncome / 12
            const totalCycles = Math.floor(cyclesPerYear)
            let compoundedCapital = capitalAtRisk
            for (let i = 0; i < totalCycles; i++) compoundedCapital += best.maxProfit
            const compoundedGain = compoundedCapital - capitalAtRisk
            return (
              <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center gap-2">
                  <span className="text-lg">📈</span>
                  <h3 className="text-base font-semibold text-gray-800 dark:text-gray-100">4. Proyección anual (Wheel)</h3>
                  <span className="text-xs text-gray-400 ml-2">basada en: {best.strategyName} ${best.strike.toFixed(2)} · {best.dte}d</span>
                </div>
                <div className="px-6 py-5 grid grid-cols-2 md:grid-cols-4 gap-5">
                  <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-4">
                    <p className="text-xs text-gray-500 dark:text-gray-400 uppercase mb-1">Ciclos / año</p>
                    <p className="text-2xl font-bold text-gray-900 dark:text-gray-100">{cyclesPerYear.toFixed(1)}</p>
                    <p className="text-xs text-gray-400 mt-1">cada {best.dte} días</p>
                  </div>
                  <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-4">
                    <p className="text-xs text-gray-500 dark:text-gray-400 uppercase mb-1">Ingreso mensual est.</p>
                    <p className="text-2xl font-bold text-green-600 dark:text-green-400">${monthlyIncome.toFixed(0)}</p>
                    <p className="text-xs text-gray-400 mt-1">${annualIncome.toFixed(0)} / año</p>
                  </div>
                  <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4">
                    <p className="text-xs text-gray-500 dark:text-gray-400 uppercase mb-1">ROI anual simple</p>
                    <p className={`text-2xl font-bold ${annualRoi >= 20 ? 'text-green-600 dark:text-green-400' : annualRoi >= 10 ? 'text-blue-600 dark:text-blue-400' : 'text-gray-700 dark:text-gray-300'}`}>{annualRoi.toFixed(1)}%</p>
                    <p className="text-xs text-gray-400 mt-1">sobre ${capitalAtRisk.toFixed(0)} capital</p>
                  </div>
                  <div className="bg-purple-50 dark:bg-purple-900/20 rounded-lg p-4">
                    <p className="text-xs text-gray-500 dark:text-gray-400 uppercase mb-1">Ganancia total ({totalCycles} ciclos)</p>
                    <p className="text-2xl font-bold text-purple-600 dark:text-purple-400">${compoundedGain.toFixed(0)}</p>
                    <p className="text-xs text-gray-400 mt-1">capital final ${compoundedCapital.toFixed(0)}</p>
                  </div>
                </div>
                <div className="px-6 pb-4">
                  <p className="text-xs text-gray-400 dark:text-gray-500">
                    ⚠️ Proyección lineal asumiendo que cada ciclo se renueva al mismo strike/prima y todas las opciones expiran sin valor (escenario óptimo). No incluye asignación ni cambios de precio. Capital en riesgo: {best.type === 'call' ? 'base de costo × 100 × contratos (Covered Call)' : 'strike × 100 × contratos (Cash-Secured Put)'}.
                  </p>
                </div>
              </div>
            )
          })()}

          {validResults.length === 0 && parseFloat(brokerStockPrice) > 0 && (
            <div className="text-center py-8 text-gray-400 dark:text-gray-500">
              Completa los campos de al menos una opción para ver el análisis.
            </div>
          )}

          {!parseFloat(brokerStockPrice) && (
            <div className="text-center py-8 text-gray-400 dark:text-gray-500">
              Ingresa el precio actual de la acción para comenzar.
            </div>
          )}
      </div>
    </div>
  )
}

export default Calculator
