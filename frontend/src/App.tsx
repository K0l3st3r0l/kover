import { useState, useEffect } from 'react'
import { BrowserRouter as Router, Routes, Route, Link, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ThemeProvider, useTheme } from './contexts/ThemeContext'
import Dashboard from './pages/Dashboard'
import Stocks from './pages/Stocks'
import Options from './pages/Options'
import Transactions from './pages/Transactions'
import Watchlist from './pages/Watchlist'
import Calculator from './pages/Calculator'
import Login from './pages/Login'
import ChangePassword from './pages/ChangePassword'
import TaxReport from './pages/TaxReport'
import ImportIB from './pages/ImportIB'
import ChileanMarkets from './pages/ChileanMarkets'

function PrivateRoute({ children }: { children: JSX.Element }) {
  const { user, isLoading } = useAuth()
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="animate-spin rounded-full h-10 w-10 border-2 border-blue-600 border-t-transparent" />
      </div>
    )
  }
  return user ? children : <Navigate to="/login" />
}

const NAV_LINKS = [
  { to: '/',             exact: true,  label: 'Dashboard' },
  { to: '/stocks',       exact: false, label: 'Stocks' },
  { to: '/options',      exact: false, label: 'Options' },
  { to: '/transactions', exact: false, label: 'Historial' },
  { to: '/watchlist',    exact: false, label: 'Watchlist' },
  { to: '/calculator',   exact: false, label: 'Calculadora' },
]
const NAV_EXTRA = [
  { to: '/tax-report',  label: '🇨🇱 Fiscal' },
  { to: '/import-ib',   label: '📥 Import IB' },
  { to: '/mercado-cl',  label: '📊 Mercado CL' },
]

function NavLink({ to, exact, label, onClick }: { to: string; exact?: boolean; label: string; onClick?: () => void }) {
  const { pathname } = useLocation()
  const isActive = exact ? pathname === to : pathname.startsWith(to)
  return (
    <Link
      to={to}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap ${
        isActive
          ? 'bg-blue-600 text-white shadow-sm'
          : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/60 hover:text-gray-900 dark:hover:text-white'
      }`}
    >
      {label}
    </Link>
  )
}

function AppContent() {
  const { user, logout, isLoading } = useAuth()
  const { isDark, toggleTheme } = useTheme()
  const [mobileOpen, setMobileOpen] = useState(false)
  const { pathname } = useLocation()

  // Close mobile nav on route change
  useEffect(() => { setMobileOpen(false) }, [pathname])

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="animate-spin rounded-full h-10 w-10 border-2 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (!user) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" />} />
      </Routes>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors">

      {/* ── Top nav ── */}
      <nav className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700/60 sticky top-0 z-50 shadow-sm">
        <div className="max-w-[1440px] mx-auto px-4 sm:px-6">
          <div className="flex items-center h-14 gap-3">

            {/* Logo */}
            <Link to="/" className="flex-shrink-0 flex items-center gap-2 mr-2">
              <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center">
                <span className="text-white text-xs font-bold">K</span>
              </div>
              <span className="text-lg font-bold text-gray-900 dark:text-white tracking-tight">Kover</span>
            </Link>

            {/* Desktop nav links */}
            <div className="hidden md:flex items-center gap-0.5 flex-1 overflow-x-auto scrollbar-hide">
              {NAV_LINKS.map(l => <NavLink key={l.to} {...l} />)}
              <span className="w-px h-5 bg-gray-200 dark:bg-gray-700 mx-1 flex-shrink-0" />
              {NAV_EXTRA.map(l => <NavLink key={l.to} to={l.to} label={l.label} />)}
            </div>

            {/* Right side */}
            <div className="flex items-center gap-1.5 ml-auto">
              {/* Theme toggle */}
              <button
                onClick={toggleTheme}
                className="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                title={isDark ? 'Modo claro' : 'Modo oscuro'}
              >
                {isDark ? (
                  <svg className="w-4 h-4 text-yellow-400" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                  </svg>
                )}
              </button>

              {/* User info — hidden on mobile */}
              <div className="hidden sm:flex items-center gap-1.5 text-sm text-gray-600 dark:text-gray-300 px-2.5 py-1.5 bg-gray-100 dark:bg-gray-800 rounded-lg">
                <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
                </svg>
                <span className="font-medium max-w-[120px] truncate">{user.username}</span>
              </div>

              <Link
                to="/change-password"
                className="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors hidden sm:block"
                title="Configuración"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </Link>

              <button
                onClick={logout}
                className="hidden sm:flex items-center gap-1 text-sm font-medium text-red-500 hover:text-red-600 dark:text-red-400 px-2.5 py-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
                Salir
              </button>

              {/* Hamburger (mobile) */}
              <button
                className="md:hidden p-2 rounded-lg text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
                onClick={() => setMobileOpen(o => !o)}
                aria-label="Toggle menu"
              >
                {mobileOpen ? (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  </svg>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Mobile menu */}
        {mobileOpen && (
          <div className="md:hidden border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 animate-slide-up">
            <div className="px-4 py-3 space-y-1">
              {NAV_LINKS.map(l => (
                <Link
                  key={l.to}
                  to={l.to}
                  onClick={() => setMobileOpen(false)}
                  className={`flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    (l.exact ? pathname === l.to : pathname.startsWith(l.to))
                      ? 'bg-blue-600 text-white'
                      : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/60'
                  }`}
                >
                  {l.label}
                </Link>
              ))}
              <div className="border-t border-gray-200 dark:border-gray-700 my-2" />
              {NAV_EXTRA.map(l => (
                <Link
                  key={l.to}
                  to={l.to}
                  onClick={() => setMobileOpen(false)}
                  className={`flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                    pathname.startsWith(l.to)
                      ? 'bg-blue-600 text-white'
                      : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/60'
                  }`}
                >
                  {l.label}
                </Link>
              ))}
              <div className="border-t border-gray-200 dark:border-gray-700 my-2" />
              <div className="flex items-center justify-between px-3 py-2">
                <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clipRule="evenodd" />
                  </svg>
                  <span className="font-medium">{user.username}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Link to="/change-password" onClick={() => setMobileOpen(false)} className="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                  </Link>
                  <button onClick={logout} className="flex items-center gap-1 text-sm font-medium text-red-500 px-2 py-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20">
                    Salir
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </nav>

      {/* Main content */}
      <main className="max-w-[1440px] mx-auto">
        <Routes>
          <Route path="/"             element={<PrivateRoute><Dashboard /></PrivateRoute>} />
          <Route path="/stocks"       element={<PrivateRoute><Stocks /></PrivateRoute>} />
          <Route path="/options"      element={<PrivateRoute><Options /></PrivateRoute>} />
          <Route path="/transactions" element={<PrivateRoute><Transactions /></PrivateRoute>} />
          <Route path="/watchlist"    element={<PrivateRoute><Watchlist /></PrivateRoute>} />
          <Route path="/calculator"   element={<PrivateRoute><Calculator /></PrivateRoute>} />
          <Route path="/tax-report"   element={<PrivateRoute><TaxReport /></PrivateRoute>} />
          <Route path="/import-ib"    element={<PrivateRoute><ImportIB /></PrivateRoute>} />
          <Route path="/mercado-cl"   element={<PrivateRoute><ChileanMarkets /></PrivateRoute>} />
          <Route path="/change-password" element={<PrivateRoute><ChangePassword /></PrivateRoute>} />
        </Routes>
      </main>
    </div>
  )
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Router>
          <AppContent />
        </Router>
      </AuthProvider>
    </ThemeProvider>
  )
}

export default App
