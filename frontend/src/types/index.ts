export interface Stock {
  id: number;
  ticker: string;
  company_name?: string;
  quantity: number;
  average_cost: number;
  current_price: number;
  total_cost: number;
  current_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  created_at: string;
  updated_at: string;
}

export interface Option {
  id: number;
  stock_id: number;
  option_type: 'covered_call' | 'cash_secured_put';
  strike_price: number;
  expiration_date: string;
  contracts: number;
  premium: number;
  status: 'open' | 'closed' | 'expired' | 'assigned';
  opened_at: string;
  closed_at?: string;
  notes?: string;
  realized_pnl?: number;
}

export interface DashboardSummary {
  total_stocks: number;
  total_invested: number;
  current_portfolio_value: number;
  total_premium_earned: number;
  open_options: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_pnl_pct: number;
}

export type TransactionType = 
  | 'BUY_STOCK' 
  | 'SELL_STOCK' 
  | 'SELL_CALL' 
  | 'BUY_CALL' 
  | 'SELL_PUT' 
  | 'BUY_PUT' 
  | 'ASSIGNMENT' 
  | 'DIVIDEND';

export interface Transaction {
  id: number;
  user_id: number;
  stock_id?: number;
  option_id?: number;
  ticker: string;
  transaction_type: TransactionType;
  quantity: number;
  price: number;
  total_amount: number;
  commission: number;
  notes?: string;
  transaction_date: string;
  created_at: string;
}

export interface TransactionSummary {
  total_transactions: number;
  total_invested: number;
  total_received: number;
  total_commissions: number;
  by_type: {
    [key: string]: {
      count: number;
      total_amount: number;
    };
  };
}

export interface TransactionsResponse {
  transactions: Transaction[];
  total: number;
  skip: number;
  limit: number;
}

export interface PortfolioHistory {
  date: string;
  portfolio_value: number;
  invested: number;
  pnl: number;
}

export interface PerformanceMetrics {
  total_invested: number;
  current_value: number;
  total_premium: number;
  total_pnl: number;
  roi: number;
  best_position?: {
    ticker: string;
    pnl_pct: number;
    pnl: number;
  };
  worst_position?: {
    ticker: string;
    pnl_pct: number;
    pnl: number;
  };
  total_positions: number;
  active_options: number;
}

export interface AllocationData {
  ticker: string;
  value: number;
  percentage: number;
  shares: number;
  current_price?: number;
}

export interface AllocationResponse {
  allocation: AllocationData[];
  total_value: number;
}

export interface PremiumTimelineData {
  month: string;
  calls: number;
  puts: number;
  total: number;
}

export interface WatchlistItem {
  id: number;
  ticker: string;
  company_name?: string;
  target_price?: number;
  notes?: string;
  current_price?: number;
  price_change?: number;
  price_change_pct?: number;
  distance_to_target?: number;
  distance_to_target_pct?: number;
  added_at: string;
}

export interface WatchlistCreate {
  ticker: string;
  company_name?: string;
  target_price?: number;
  notes?: string;
}

export interface WatchlistUpdate {
  company_name?: string;
  target_price?: number;
  notes?: string;
}

export interface BenchmarkData {
  date: string;
  portfolio_value: number;
  portfolio_return: number;
  sp500_value: number;
  sp500_return: number;
  outperformance: number;
}

export interface BenchmarkSummary {
  portfolio_total_return: number;
  sp500_total_return: number;
  outperformance: number;
  portfolio_final_value: number;
  sp500_final_value: number;
  beat_market: boolean;
}

export interface BenchmarkComparison {
  data: BenchmarkData[];
  summary: BenchmarkSummary;
  period_days: number;
}




