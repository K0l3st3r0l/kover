import { useState, useRef } from 'react'
import api from '../services/api'

// ─── Tipos ────────────────────────────────────────────────────────────────────

interface ParsedTransaction {
  ib_row: number
  fecha: string
  ticker: string
  tipo: string
  tipo_label: string
  asset_category: string
  cantidad: number
  precio_usd: number
  total_usd: number
  comision_usd: number
  notas: string
  advertencia: string
  duplicado: boolean
}

interface PreviewResponse {
  transacciones: ParsedTransaction[]
  tickers_acciones: string[]
  total_filas_csv: number
  total_importables: number
  total_duplicados: number
  total_advertencias: number
  errores_parseo: string[]
}

interface ImportResult {
  importadas: number
  omitidas: number
  stocks_creados: string[]
  stocks_actualizados: string[]
  errores: string[]
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmtUSD = (v: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(v)

const TIPO_COLORS: Record<string, string> = {
  BUY_STOCK:  'text-red-500 dark:text-red-400',
  SELL_STOCK: 'text-green-600 dark:text-green-400',
  SELL_CALL:  'text-blue-600 dark:text-blue-400',
  BUY_CALL:   'text-orange-500 dark:text-orange-400',
  SELL_PUT:   'text-blue-600 dark:text-blue-400',
  BUY_PUT:    'text-orange-500 dark:text-orange-400',
  DIVIDEND:   'text-purple-600 dark:text-purple-400',
  ASSIGNMENT: 'text-gray-500',
}

// ─── Componente ───────────────────────────────────────────────────────────────

type Step = 'upload' | 'preview' | 'done'

export default function ImportIB() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<Step>('upload')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [omitirDuplicados, setOmitirDuplicados] = useState(true)
  const [showErrors, setShowErrors] = useState(false)
  const [filterTipo, setFilterTipo] = useState('all')
  const [showOnlyNew, setShowOnlyNew] = useState(true)
  const [rebuilding, setRebuilding] = useState(false)
  const [rebuildResult, setRebuildResult] = useState<{
    ok: boolean
    tickers_reconstruidos: number
    posiciones_activas: string[]
    posiciones_cerradas: string[]
    total_transacciones_procesadas: number
  } | null>(null)

  // ── Paso 1: subir archivo y obtener preview ──────────────────────────────
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setLoading(true)
    setError('')
    setPreview(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await api.post<PreviewResponse>('/api/import-ib/preview', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setPreview(res.data)
      setStep('preview')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Error al procesar el archivo. Verifica que sea un Activity Statement de IB en formato CSV.')
    } finally {
      setLoading(false)
    }
  }

  // ── Paso 2: confirmar importación ────────────────────────────────────────
  const handleImport = async () => {
    if (!preview) return
    setLoading(true)
    setError('')

    try {
      const res = await api.post<ImportResult>('/api/import-ib/confirm', {
        transacciones: preview.transacciones,
        omitir_duplicados: omitirDuplicados,
      })
      setResult(res.data)
      setStep('done')
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Error al importar. Intenta de nuevo.')
    } finally {
      setLoading(false)
    }
  }

  // ── Reconstruir posiciones desde transacciones ───────────────────────────
  const handleRebuild = async () => {
    if (!confirm('⚠️ Esto borrará y recalculará TODAS las posiciones de tu portafolio desde cero usando las transacciones guardadas.\n\nLas transacciones NO se borran.\n\n¿Continuar?')) return
    setRebuilding(true)
    setRebuildResult(null)
    try {
      const res = await api.post('/api/import-ib/rebuild-positions')
      setRebuildResult(res.data)
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Error al reconstruir posiciones')
    } finally {
      setRebuilding(false)
    }
  }

  // ── Filtrar transacciones para la tabla ──────────────────────────────────
  const txFiltradas = preview?.transacciones.filter(t => {
    if (showOnlyNew && t.duplicado) return false
    if (filterTipo !== 'all' && t.tipo !== filterTipo) return false
    return true
  }) ?? []

  // ─── PASO 1: Upload ───────────────────────────────────────────────────────
  if (step === 'upload') {
    return (
      <div className="max-w-3xl mx-auto px-4 py-10 space-y-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            📥 Importar desde Interactive Brokers
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Sube tu Activity Statement en CSV para importar automáticamente todas tus operaciones.
          </p>
        </div>

        {/* Instrucciones */}
        <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-xl p-6">
          <h2 className="font-semibold text-blue-800 dark:text-blue-300 mb-3">
            📋 Cómo exportar desde Interactive Brokers
          </h2>
          <ol className="space-y-2 text-sm text-blue-700 dark:text-blue-300">
            <li className="flex gap-2">
              <span className="font-bold flex-shrink-0">1.</span>
              <span>Inicia sesión en <strong>IB Client Portal</strong> (clientportal.ibkr.com)</span>
            </li>
            <li className="flex gap-2">
              <span className="font-bold flex-shrink-0">2.</span>
              <span>Ve a <strong>Reports → Activity → Statements</strong></span>
            </li>
            <li className="flex gap-2">
              <span className="font-bold flex-shrink-0">3.</span>
              <span>Selecciona tipo <strong>Activity</strong>, período: el <strong>año completo</strong> que deseas importar</span>
            </li>
            <li className="flex gap-2">
              <span className="font-bold flex-shrink-0">4.</span>
              <span>Formato: <strong>CSV</strong> → Click en <strong>Download</strong></span>
            </li>
            <li className="flex gap-2">
              <span className="font-bold flex-shrink-0">5.</span>
              <span>Sube el archivo descargado aquí abajo</span>
            </li>
          </ol>
          <div className="mt-4 p-3 bg-blue-100 dark:bg-blue-900/40 rounded-lg text-xs text-blue-600 dark:text-blue-400">
            ✅ Se importan: <strong>Compras y ventas de acciones</strong>, <strong>primas de opciones (Calls y Puts)</strong>, <strong>cierres de opciones</strong>, <strong>dividendos</strong> y <strong>asignaciones</strong>.<br />
            ❌ Se ignoran: Forex, Bonds, divisas, filas de totales y subtotales.
          </div>
        </div>

        {/* Zona de upload */}
        <div
          className="border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-xl p-12 text-center cursor-pointer hover:border-blue-400 dark:hover:border-blue-500 transition-colors"
          onClick={() => fileInputRef.current?.click()}
        >
          <div className="text-5xl mb-3">📄</div>
          <p className="text-lg font-medium text-gray-700 dark:text-gray-300">
            Haz click para seleccionar el archivo CSV
          </p>
          <p className="text-sm text-gray-400 mt-1">o arrastra y suelta aquí</p>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleFileUpload}
            className="hidden"
          />
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-3 py-4">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600" />
            <span className="text-gray-600 dark:text-gray-300">Analizando el archivo...</span>
          </div>
        )}

        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 text-red-700 dark:text-red-300 rounded-lg p-4 text-sm">
            ❌ {error}
          </div>
        )}

        {/* ── Herramienta: Reconstruir posiciones ── */}
        <div className="border border-amber-300 dark:border-amber-600 bg-amber-50 dark:bg-amber-900/20 rounded-xl p-5 space-y-3">
          <div>
            <h2 className="font-semibold text-amber-800 dark:text-amber-300">🔧 Recalcular posiciones desde transacciones</h2>
            <p className="text-sm text-amber-700 dark:text-amber-400 mt-1">
              Si importaste archivos fuera de orden cronológico, las posiciones pueden haber quedado incorrectas.
              Esta herramienta borra y reconstruye todas las posiciones usando las transacciones guardadas en orden cronológico.
              <strong> Las transacciones no se borran.</strong>
            </p>
          </div>

          {rebuildResult && (
            <div className="bg-green-50 dark:bg-green-900/30 border border-green-300 dark:border-green-600 rounded-lg p-4 text-sm space-y-2">
              <p className="font-bold text-green-700 dark:text-green-300">✅ Reconstrucción completada</p>
              <p className="text-green-700 dark:text-green-300">{rebuildResult.total_transacciones_procesadas} transacciones procesadas · {rebuildResult.tickers_reconstruidos} tickers</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div>
                  <p className="font-semibold text-green-700 dark:text-green-300">Posiciones activas ({rebuildResult.posiciones_activas.length}):</p>
                  <p className="text-green-600 dark:text-green-400">{rebuildResult.posiciones_activas.join(', ') || '—'}</p>
                </div>
                <div>
                  <p className="font-semibold text-gray-600 dark:text-gray-400">Cerradas ({rebuildResult.posiciones_cerradas.length}):</p>
                  <p className="text-gray-500 dark:text-gray-400 text-xs">{rebuildResult.posiciones_cerradas.join(', ') || '—'}</p>
                </div>
              </div>
            </div>
          )}

          <button
            onClick={handleRebuild}
            disabled={rebuilding}
            className="bg-amber-600 hover:bg-amber-700 disabled:opacity-50 text-white font-semibold px-5 py-2 rounded-lg transition flex items-center gap-2"
          >
            {rebuilding
              ? <><span className="animate-spin">⏳</span> Recalculando...</>
              : '🔄 Recalcular todas las posiciones'}
          </button>
        </div>
      </div>
    )
  }

  // ─── PASO 3: Resultado ────────────────────────────────────────────────────
  if (step === 'done' && result) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-10 space-y-6">
        <div className="text-center">
          <div className="text-6xl mb-4">
            {result.errores.length === 0 ? '🎉' : '⚠️'}
          </div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            {result.errores.length === 0 ? '¡Importación exitosa!' : 'Importación con advertencias'}
          </h1>
        </div>

        <div className="grid grid-cols-2 gap-4">
          {[
            { label: 'Transacciones importadas', val: result.importadas, color: 'text-green-600 dark:text-green-400' },
            { label: 'Omitidas (duplicadas)', val: result.omitidas, color: 'text-gray-500' },
          ].map(item => (
            <div key={item.label} className="bg-white dark:bg-gray-800 rounded-xl shadow p-5 text-center">
              <p className={`text-3xl font-extrabold ${item.color}`}>{item.val}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{item.label}</p>
            </div>
          ))}
        </div>

        {result.stocks_creados.length > 0 && (
          <div className="bg-green-50 dark:bg-green-900/20 border border-green-300 dark:border-green-700 rounded-lg p-4 text-sm">
            <p className="font-semibold text-green-700 dark:text-green-300 mb-1">✅ Stocks creados:</p>
            <p className="text-green-600 dark:text-green-400">{result.stocks_creados.join(', ')}</p>
          </div>
        )}

        {result.stocks_actualizados.length > 0 && (
          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-300 dark:border-blue-700 rounded-lg p-4 text-sm">
            <p className="font-semibold text-blue-700 dark:text-blue-300 mb-1">🔄 Stocks actualizados:</p>
            <p className="text-blue-600 dark:text-blue-400">{result.stocks_actualizados.join(', ')}</p>
          </div>
        )}

        {result.errores.length > 0 && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 rounded-lg p-4 text-sm">
            <p className="font-semibold text-red-700 dark:text-red-300 mb-2">❌ Errores ({result.errores.length}):</p>
            <ul className="space-y-1 text-red-600 dark:text-red-400">
              {result.errores.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          </div>
        )}

        <div className="flex gap-3 justify-center mt-4">
          <a
            href="/transactions"
            className="bg-blue-600 hover:bg-blue-700 text-white font-semibold px-6 py-2 rounded-lg transition"
          >
            Ver Transactions →
          </a>
          <a
            href="/tax-report"
            className="bg-green-600 hover:bg-green-700 text-white font-semibold px-6 py-2 rounded-lg transition"
          >
            Ver Informe Fiscal →
          </a>
          <button
            onClick={() => { setStep('upload'); setPreview(null); setResult(null); if (fileInputRef.current) fileInputRef.current.value = ''; }}
            className="bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 font-semibold px-6 py-2 rounded-lg transition"
          >
            Importar otro archivo
          </button>
        </div>
      </div>
    )
  }

  // ─── PASO 2: Preview ──────────────────────────────────────────────────────
  if (!preview) return null

  const tiposUnicos = [...new Set(preview.transacciones.map(t => t.tipo))]

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 space-y-6">

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            🔍 Previsualización de importación
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
            Revisa las transacciones antes de confirmar. Nada se ha guardado aún.
          </p>
        </div>
        <button
          onClick={() => { setStep('upload'); setPreview(null); if (fileInputRef.current) fileInputRef.current.value = ''; }}
          className="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 underline"
        >
          ← Cambiar archivo
        </button>
      </div>

      {/* Tarjetas resumen */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Filas en CSV', val: preview.total_filas_csv, icon: '📄', color: 'border-gray-300' },
          { label: 'Para importar', val: preview.total_importables, icon: '✅', color: 'border-green-400' },
          { label: 'Duplicados', val: preview.total_duplicados, icon: '🔁', color: 'border-yellow-400' },
          { label: 'Advertencias', val: preview.total_advertencias, icon: '⚠️', color: 'border-orange-400' },
        ].map(card => (
          <div key={card.label} className={`bg-white dark:bg-gray-800 rounded-xl shadow p-4 border-l-4 ${card.color}`}>
            <p className="text-xs text-gray-500 dark:text-gray-400">{card.icon} {card.label}</p>
            <p className="text-2xl font-extrabold text-gray-900 dark:text-white mt-1">{card.val}</p>
          </div>
        ))}
      </div>

      {/* Errores de parseo */}
      {preview.errores_parseo.length > 0 && (
        <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-300 dark:border-yellow-700 rounded-lg p-4">
          <button
            onClick={() => setShowErrors(!showErrors)}
            className="flex items-center gap-2 font-semibold text-yellow-700 dark:text-yellow-300 text-sm"
          >
            ⚠️ {preview.errores_parseo.length} filas no pudieron parsearse
            <span>{showErrors ? '▲' : '▼'}</span>
          </button>
          {showErrors && (
            <ul className="mt-2 space-y-1 text-xs text-yellow-600 dark:text-yellow-400">
              {preview.errores_parseo.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
        </div>
      )}

      {/* Opciones de importación */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={omitirDuplicados}
            onChange={e => setOmitirDuplicados(e.target.checked)}
            className="w-4 h-4 rounded"
          />
          <div>
            <p className="font-medium text-gray-800 dark:text-gray-100 text-sm">
              Omitir duplicados ({preview.total_duplicados} detectados)
            </p>
            <p className="text-xs text-gray-400">
              Se detecta duplicado si ya existe una transacción con el mismo ticker, fecha, tipo y monto
            </p>
          </div>
        </label>
        <button
          onClick={handleImport}
          disabled={loading || preview.total_importables === 0}
          className="flex-shrink-0 bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white font-bold px-8 py-3 rounded-xl transition text-sm"
        >
          {loading
            ? '⏳ Importando...'
            : `✅ Importar ${omitirDuplicados ? preview.total_importables : preview.transacciones.length} transacciones`}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 text-red-700 dark:text-red-300 rounded-lg p-4 text-sm">
          ❌ {error}
        </div>
      )}

      {/* Filtros de tabla */}
      <div className="flex flex-wrap gap-3 items-center">
        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300 cursor-pointer">
          <input
            type="checkbox"
            checked={showOnlyNew}
            onChange={e => setShowOnlyNew(e.target.checked)}
            className="w-4 h-4 rounded"
          />
          Mostrar solo nuevas (sin duplicados)
        </label>
        <select
          value={filterTipo}
          onChange={e => setFilterTipo(e.target.value)}
          className="border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-1.5 text-sm bg-white dark:bg-gray-700 dark:text-white"
        >
          <option value="all">Todos los tipos</option>
          {tiposUnicos.map(t => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <span className="text-sm text-gray-400">
          Mostrando {txFiltradas.length} de {preview.transacciones.length}
        </span>
      </div>

      {/* Tabla de previsualización */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-700/60 text-left">
                {['Estado', 'Fecha', 'Ticker', 'Tipo', 'Cant.', 'Precio USD', 'Total USD', 'Comisión', 'Notas'].map(h => (
                  <th key={h} className="px-3 py-2.5 text-gray-600 dark:text-gray-300 font-medium whitespace-nowrap text-xs uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {txFiltradas.length === 0 && (
                <tr>
                  <td colSpan={9} className="text-center text-gray-400 py-10">
                    No hay transacciones que mostrar con los filtros actuales.
                  </td>
                </tr>
              )}
              {txFiltradas.map((t) => (
                <tr
                  key={t.ib_row}
                  className={`border-t border-gray-100 dark:border-gray-700 ${
                    t.duplicado ? 'opacity-40 bg-gray-50 dark:bg-gray-900/20' : 'hover:bg-gray-50 dark:hover:bg-gray-700/20'
                  }`}
                >
                  <td className="px-3 py-2 whitespace-nowrap">
                    {t.duplicado ? (
                      <span className="text-xs text-yellow-600 dark:text-yellow-400 font-medium bg-yellow-50 dark:bg-yellow-900/30 px-2 py-0.5 rounded-full">
                        🔁 Dup.
                      </span>
                    ) : t.advertencia ? (
                      <span className="text-xs text-orange-600 dark:text-orange-400 font-medium bg-orange-50 dark:bg-orange-900/30 px-2 py-0.5 rounded-full" title={t.advertencia}>
                        ⚠️ Aviso
                      </span>
                    ) : (
                      <span className="text-xs text-green-600 dark:text-green-400 font-medium bg-green-50 dark:bg-green-900/30 px-2 py-0.5 rounded-full">
                        ✅ Nuevo
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                    {t.fecha.substring(0, 10)}
                  </td>
                  <td className="px-3 py-2 font-bold text-gray-800 dark:text-gray-100">{t.ticker}</td>
                  <td className={`px-3 py-2 font-medium whitespace-nowrap ${TIPO_COLORS[t.tipo] || 'text-gray-600'}`}>
                    {t.tipo_label}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300">{t.cantidad || '—'}</td>
                  <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300">
                    {t.precio_usd ? fmtUSD(t.precio_usd) : '—'}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold text-gray-800 dark:text-gray-200">
                    {fmtUSD(t.total_usd)}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500 dark:text-gray-400">
                    {t.comision_usd ? fmtUSD(t.comision_usd) : '—'}
                  </td>
                  <td className="px-3 py-2 text-gray-400 dark:text-gray-500 max-w-xs truncate text-xs" title={t.notas}>
                    {t.notas}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
