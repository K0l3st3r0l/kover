export interface BrokerOptionRow {
  id: number
  side: 'sell' | 'buy'
  type: 'call' | 'put'
  strike: string
  expiration: string
  premium: string
  contracts: string
}

export interface BrokerOptionCalc {
  id: number
  side: 'sell' | 'buy'
  type: 'call' | 'put'
  strike: number
  expiration: string
  premium: number
  contracts: number
  dte: number
  totalCashFlow: number
  otmPct: number
  breakeven: number
  breakevenMovePct: number
  downsideProtection?: number
  downsideProtectionPct?: number
  maxProfit: number
  maxLoss: number
  roiPct: number
  annualizedRoiPct: number
  score: number
  strategyName: string
}

export function calcBrokerOption(
  row: BrokerOptionRow,
  stockPrice: number,
  costBasis: number,
  commissionPerContract = 0,
  now = new Date()
): BrokerOptionCalc | null {
  const strike = parseFloat(row.strike)
  const premium = parseFloat(row.premium)
  const contracts = Number(row.contracts)
  if (!row.expiration || ![strike, premium, stockPrice, costBasis, commissionPerContract].every(Number.isFinite) || strike <= 0 || premium < 0 || stockPrice <= 0 || commissionPerContract < 0 || !Number.isInteger(contracts) || contracts <= 0) return null

  const totalCommission = commissionPerContract * contracts

  const today = new Date(now)
  today.setHours(0, 0, 0, 0)
  const exp = new Date(row.expiration + 'T00:00:00')
  if (!Number.isFinite(exp.getTime()) || exp < today) return null
  const dte = Math.round((Date.UTC(exp.getFullYear(), exp.getMonth(), exp.getDate()) - Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) / 86400000)
  const feePerShare = commissionPerContract / 100

  const otmPct =
    row.type === 'call'
      ? ((strike - stockPrice) / stockPrice) * 100
      : ((stockPrice - strike) / stockPrice) * 100

  let breakeven: number
  let maxProfit: number
  let maxLoss: number
  let roiPct: number
  let strategyName: string
  let totalCashFlow: number

  let downsideProtection: number | undefined
  let downsideProtectionPct: number | undefined

  if (row.side === 'sell') {
    totalCashFlow = premium * 100 * contracts - totalCommission

    if (row.type === 'call') {
      strategyName = 'Covered Call'
      const basis = costBasis > 0 ? costBasis : stockPrice
      breakeven = basis - premium + feePerShare
      maxProfit = (strike - basis + premium) * 100 * contracts - totalCommission
      maxLoss = Math.max(0, (basis - premium) * 100 * contracts + totalCommission)
      const capitalAtRisk = basis * 100 * contracts
      roiPct = (totalCashFlow / capitalAtRisk) * 100
      downsideProtection = breakeven
      downsideProtectionPct = ((stockPrice - downsideProtection) / stockPrice) * 100
    } else {
      strategyName = 'Cash-Secured Put'
      breakeven = strike - premium + feePerShare
      maxProfit = premium * 100 * contracts - totalCommission
      maxLoss = Math.max(0, (strike - premium) * 100 * contracts + totalCommission)
      const capitalAtRisk = strike * 100 * contracts
      roiPct = (totalCashFlow / capitalAtRisk) * 100
    }
  } else {
    totalCashFlow = -(premium * 100 * contracts) - totalCommission

    if (row.type === 'call') {
      strategyName = 'Buy Call'
      breakeven = strike + premium + feePerShare
      maxProfit = Infinity
      maxLoss = premium * 100 * contracts + totalCommission
      roiPct = maxLoss > 0 ? ((Math.max(stockPrice - strike, 0) * 100 * contracts - maxLoss) / maxLoss) * 100 : 0
    } else {
      strategyName = 'Buy Put'
      breakeven = strike - premium - feePerShare
      maxProfit = Math.max(0, (strike - premium) * 100 * contracts - totalCommission)
      maxLoss = premium * 100 * contracts + totalCommission
      roiPct = maxLoss > 0 ? ((Math.max(strike - stockPrice, 0) * 100 * contracts - maxLoss) / maxLoss) * 100 : 0
    }
  }

  const annualizedRoiPct = row.side === 'sell' && dte > 0 ? (roiPct / dte) * 365 : roiPct
  const breakevenMovePct = ((breakeven - stockPrice) / stockPrice) * 100

  let score: number
  if (row.side === 'sell') {
    const safetyBonus = otmPct > 5 ? 1.1 : otmPct > 0 ? 1.0 : 0.85
    score = annualizedRoiPct * safetyBonus
  } else {
    score = Number.NEGATIVE_INFINITY
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

export function rollCost(premium: string, contracts: number, commission: number): number | null {
  if (premium.trim() === '') return null
  const value = Number(premium)
  return Number.isFinite(value) && value >= 0 && Number.isInteger(contracts) && contracts > 0 && Number.isFinite(commission) && commission >= 0
    ? (value * 100 + commission) * contracts : null
}

export function rolledCostBasis(basis: number, originalPremium: number, contracts: number, closingCost: number, shares: number): number {
  return shares > 0 ? basis - (originalPremium * contracts * 100 - closingCost) / shares : basis
}
