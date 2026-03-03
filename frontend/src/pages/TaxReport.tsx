import { useEffect, useState, useCallback } from 'react'
import api from '../services/api'

// ─── Tipos ──────────────────────────────────────────────────────────────────

interface TramoDesglose {
  tramo: string
  base_clp: number
  tasa: number
  impuesto_clp: number
}

interface Sugerencia {
  categoria: string
  titulo: string
  detalle: string
  impacto: 'Alto' | 'Medio' | 'Bajo'
}

interface AnalisisSpa {
  nivel: string
  conviene: boolean
  muy_conveniente: boolean
  renta_uta: number
  impuesto_persona_clp: number
  impuesto_estimado_spa_clp: number
  ahorro_estimado_clp: number
  umbral_estudio_uta: number
  umbral_migracion_uta: number
  explicacion: string
  pasos: string[]
}

interface FiscalReport {
  anio: number
  dolar_observado: number
  uta_clp: number
  resumen_usd: {
    ingresos_ventas_acciones: number
    costo_compras_acciones: number
    ganancia_capital_neta: number
    primas_cobradas: number
    cierres_opciones: number
    primas_netas: number
    dividendos: number
    comisiones_totales: number
  }
  resumen_clp: {
    ganancia_capital: number
    primas_netas: number
    dividendos: number
    sueldo_bruto: number
    otros_ingresos: number
    renta_trabajo: number
    renta_inversiones: number
    renta_total_base_imponible: number
    comisiones_deducibles: number
  }
  impuesto_global_complementario: {
    impuesto_bruto_clp: number
    credito_iusc_clp: number
    credito_art41a_clp: number
    retencion_dividendos_clp: number
    tope_credito_exterior_clp: number
    impuesto_neto_clp: number
    devolucion_clp: number
    tasa_efectiva_pct: number
    desglose_tramos: TramoDesglose[]
    nota_tratado: string
    advertencia: string
  }
  conteo_operaciones: {
    total: number
    ventas_acciones: number
    compras_acciones: number
    primas_cobradas: number
    opciones_cerradas: number
    dividendos: number
    asignaciones: number
  }
  transacciones: {
    id: number
    fecha: string
    ticker: string
    tipo: string
    cantidad: number
    precio_usd: number
    total_usd: number
    total_clp: number
    comision_usd: number
    notas: string
  }[]
  sugerencias_optimizacion: Sugerencia[]
  analisis_spa: AnalisisSpa
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const fmtCLP = (v: number) =>
  new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP', maximumFractionDigits: 0 }).format(v)

const fmtUSD = (v: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(v)

const fmtPct = (v: number) => `${v.toFixed(1)}%`

const impactoColor: Record<string, string> = {
  Alto: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  Medio: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300',
  Bajo: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
}

const tipoLabels: Record<string, string> = {
  BUY_STOCK: 'Compra Acción',
  SELL_STOCK: 'Venta Acción',
  SELL_CALL: 'Prima Covered Call',
  BUY_CALL: 'Cierre Call',
  SELL_PUT: 'Prima CSP',
  BUY_PUT: 'Cierre Put',
  DIVIDEND: 'Dividendo',
  ASSIGNMENT: 'Asignación',
}

const tipoClassMap: Record<string, string> = {
  SELL_STOCK: 'text-green-600 dark:text-green-400',
  BUY_STOCK: 'text-red-500 dark:text-red-400',
  SELL_CALL: 'text-blue-600 dark:text-blue-400',
  SELL_PUT: 'text-blue-600 dark:text-blue-400',
  BUY_CALL: 'text-orange-500 dark:text-orange-400',
  BUY_PUT: 'text-orange-500 dark:text-orange-400',
  DIVIDEND: 'text-purple-600 dark:text-purple-400',
  ASSIGNMENT: 'text-gray-500',
}

// ─── Componente principal ─────────────────────────────────────────────────────

export default function TaxReport() {
  const currentYear = new Date().getFullYear()

  const [availableYears, setAvailableYears] = useState<number[]>([currentYear - 1])
  const [params, setParams] = useState({
    year: currentYear - 1,
    dolar_observado: 970,
    sueldo_bruto_clp: 0,
    iusc_pagado_clp: 0,
    retencion_dividendos_usd: 0,
    otros_ingresos_clp: 0,
    uta_clp: 807528,
  })
  const [report, setReport] = useState<FiscalReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [openTip, setOpenTip] = useState<number | null>(null)
  const [openSpa, setOpenSpa] = useState(false)
  const [showTx, setShowTx] = useState(false)

  // Cargar años disponibles
  useEffect(() => {
    api.get('/api/fiscal/years').then(r => {
      setAvailableYears(r.data.years)
      if (r.data.years.length > 0) {
        setParams(p => ({ ...p, year: r.data.years[0] }))
      }
    }).catch(() => {})
  }, [])

  const fetchReport = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const qs = new URLSearchParams({
        year: params.year.toString(),
        dolar_observado: params.dolar_observado.toString(),
        sueldo_bruto_clp: params.sueldo_bruto_clp.toString(),
        iusc_pagado_clp: params.iusc_pagado_clp.toString(),
        retencion_dividendos_usd: params.retencion_dividendos_usd.toString(),
        otros_ingresos_clp: params.otros_ingresos_clp.toString(),
        uta_clp: params.uta_clp.toString(),
      })
      const r = await api.get<FiscalReport>(`/api/fiscal/report?${qs}`)
      setReport(r.data)
    } catch {
      setError('No se pudo cargar el informe. Verifica tu conexión.')
    } finally {
      setLoading(false)
    }
  }, [params])

  useEffect(() => {
    fetchReport()
  }, [fetchReport])

  // ── Export CSV ──────────────────────────────────────────────────────────────
  const exportCSV = () => {
    if (!report) return
    const headers = ['Fecha', 'Ticker', 'Tipo', 'Cantidad', 'Precio USD', 'Total USD', 'Total CLP', 'Comisión USD', 'Notas']
    const rows = report.transacciones.map(t => [
      t.fecha, t.ticker, tipoLabels[t.tipo] || t.tipo,
      t.cantidad, t.precio_usd, t.total_usd, t.total_clp, t.comision_usd, t.notas
    ])
    const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `Reporte_Fiscal_${report.anio}_Kover.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8">

      {/* ── Cabecera ─────────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            🇨🇱 Informe Fiscal Chile
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Estimado de Global Complementario para personas naturales con inversiones en EE.UU.
          </p>
        </div>
        <button
          onClick={exportCSV}
          disabled={!report}
          className="flex items-center gap-2 bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white font-semibold px-5 py-2 rounded-lg transition"
        >
          📥 Exportar CSV para contador
        </button>
      </div>

      {/* ── Panel de parámetros ──────────────────────────────────────────── */}
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
        <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100 mb-4">
          ⚙️ Parámetros del ejercicio
        </h2>
        {/* Fila 1: año, dólar, UTA */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Año tributario</label>
            <select
              value={params.year}
              onChange={e => setParams(p => ({ ...p, year: Number(e.target.value) }))}
              className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 dark:text-white"
            >
              {availableYears.map(y => (<option key={y} value={y}>{y}</option>))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Dólar Observado promedio (CLP)</label>
            <input type="number" value={params.dolar_observado}
              onChange={e => setParams(p => ({ ...p, dolar_observado: Number(e.target.value) }))}
              className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 dark:text-white" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Valor UTA {params.year} (CLP)</label>
            <input type="number" value={params.uta_clp}
              onChange={e => setParams(p => ({ ...p, uta_clp: Number(e.target.value) }))}
              className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 dark:text-white" />
          </div>
        </div>

        {/* Fila 2: Sueldo e impuestos */}
        <div className="border-t border-gray-100 dark:border-gray-700 pt-4">
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">💼 Ingresos por trabajo y créditos</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                Sueldo bruto anual (CLP)
                <span className="ml-1 text-gray-400" title="Suma el total bruto de todas tus liquidaciones del año. Lo encuentras en 'Total Haberes' de cada liquidación.">ⓘ</span>
              </label>
              <input type="number" value={params.sueldo_bruto_clp}
                onChange={e => setParams(p => ({ ...p, sueldo_bruto_clp: Number(e.target.value) }))}
                placeholder="Ej: 24000000"
                className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 dark:text-white" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                IUSC pagado en el año (CLP)
                <span className="ml-1 text-gray-400" title="Suma la línea 'Impuesto a la Renta' o 'IUSC' de cada liquidación. Este monto es un crédito directo contra tu GC.">ⓘ</span>
              </label>
              <input type="number" value={params.iusc_pagado_clp}
                onChange={e => setParams(p => ({ ...p, iusc_pagado_clp: Number(e.target.value) }))}
                placeholder="Ej: 1200000"
                className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 dark:text-white" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">
                Retención dividendos USA (USD)
                <span className="ml-1 text-gray-400" title="Monto retenido por IB en USA sobre dividendos (30%). Lo encuentras en tu formulario 1042-S del broker. Es crédito Art.41A contra tu GC.">ⓘ</span>
              </label>
              <input type="number" value={params.retencion_dividendos_usd}
                onChange={e => setParams(p => ({ ...p, retencion_dividendos_usd: Number(e.target.value) }))}
                placeholder="Ej: 1.20"
                className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 dark:text-white" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Otros ingresos (CLP)</label>
              <input type="number" value={params.otros_ingresos_clp}
                onChange={e => setParams(p => ({ ...p, otros_ingresos_clp: Number(e.target.value) }))}
                placeholder="Honorarios, arriendos..."
                className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 dark:text-white" />
            </div>
          </div>
          <div className="mt-3 p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg text-xs text-amber-700 dark:text-amber-300">
            <strong>📄 ¿Cómo ingresar el sueldo?</strong> Ingresa manualmente los totales anuales. Suma el <em>"Total Haberes"</em> de todas tus liquidaciones para el sueldo bruto, y la línea <em>"Impuesto a la Renta"</em> para el IUSC. No es posible subir liquidaciones directamente ya que cada empleador las formatea diferente.
          </div>
        </div>

        <p className="mt-3 text-xs text-gray-400 italic">
          * Usa el Dólar Observado del Banco Central de Chile para efectos SII.
          La UTA la encuentras en{' '}
          <a href="https://www.sii.cl" target="_blank" rel="noreferrer" className="underline text-blue-500">sii.cl</a>.
        </p>
      </div>

      {/* ── Loading / Error ───────────────────────────────────────────────── */}
      {loading && (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
        </div>
      )}
      {error && (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-300 dark:border-red-700 text-red-700 dark:text-red-300 rounded-lg p-4">
          {error}
        </div>
      )}

      {report && !loading && (
        <>
          {/* ── Tarjetas resumen ─────────────────────────────────────────── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              {
                label: 'Ganancia de Capital',
                usd: report.resumen_usd.ganancia_capital_neta,
                clp: report.resumen_clp.ganancia_capital,
                icon: '📈',
                color: report.resumen_clp.ganancia_capital >= 0
                  ? 'border-green-400 dark:border-green-600'
                  : 'border-red-400 dark:border-red-600',
              },
              {
                label: 'Primas Netas (Opciones)',
                usd: report.resumen_usd.primas_netas,
                clp: report.resumen_clp.primas_netas,
                icon: '⚡',
                color: 'border-blue-400 dark:border-blue-600',
              },
              {
                label: 'Dividendos',
                usd: report.resumen_usd.dividendos,
                clp: report.resumen_clp.dividendos,
                icon: '💰',
                color: 'border-purple-400 dark:border-purple-600',
              },
              {
                label: 'Base Imponible Total',
                usd: null,
                clp: report.resumen_clp.renta_total_base_imponible,
                icon: '🧾',
                color: 'border-orange-400 dark:border-orange-600',
              },
            ].map(card => (
              <div
                key={card.label}
                className={`bg-white dark:bg-gray-800 rounded-xl shadow p-4 border-l-4 ${card.color}`}
              >
                <p className="text-xs text-gray-500 dark:text-gray-400">{card.icon} {card.label}</p>
                {card.usd !== null && (
                  <p className="text-sm font-medium text-gray-600 dark:text-gray-300 mt-1">
                    {fmtUSD(card.usd)}
                  </p>
                )}
                <p className={`text-lg font-bold mt-1 ${card.clp < 0 ? 'text-red-500' : 'text-gray-900 dark:text-white'}`}>
                  {fmtCLP(card.clp)}
                </p>
              </div>
            ))}
          </div>

          {/* ── Nota Tratado USA-Chile ───────────────────────────────── */}
          <div className="bg-green-50 dark:bg-green-900/20 border border-green-300 dark:border-green-700 rounded-xl p-4 text-sm space-y-3">
            <p className="font-bold text-green-800 dark:text-green-300 text-base">
              ✅ Tratado de doble tributación Chile-USA: <span className="underline">VIGENTE desde el 19/12/2023</span>
            </p>
            <p className="text-green-700 dark:text-green-300">
              Publicado en el Diario Oficial el <strong>27/01/2024</strong>, Decreto Supremo N°200.
              Sus efectos rigen desde el <strong>01/01/2024</strong>, cubriendo íntegramente el año tributario 2025.
              Fuente oficial:{' '}
              <a href="https://www.sii.cl/normativa_legislacion/convenios_internacionales.html" target="_blank" rel="noreferrer" className="underline">
                SII – Convenios Internacionales
              </a>
            </p>

            {/* Tabla de tasas */}
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="bg-green-100 dark:bg-green-800/40">
                    <th className="border border-green-300 dark:border-green-600 px-3 py-1 text-left text-green-800 dark:text-green-200">Situación</th>
                    <th className="border border-green-300 dark:border-green-600 px-3 py-1 text-center text-green-800 dark:text-green-200">Tasa retención dividendos (Art. 10)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="border border-green-300 dark:border-green-600 px-3 py-1 text-green-700 dark:text-green-300">Empresa con ≥10% derechos de voto</td>
                    <td className="border border-green-300 dark:border-green-600 px-3 py-1 text-center font-semibold text-green-700 dark:text-green-300">5%</td>
                  </tr>
                  <tr className="bg-yellow-50 dark:bg-yellow-900/20">
                    <td className="border border-green-300 dark:border-green-600 px-3 py-1 font-semibold text-yellow-800 dark:text-yellow-300">
                      Inversor de portafolio (personas naturales) ← <strong>tu caso</strong>
                    </td>
                    <td className="border border-green-300 dark:border-green-600 px-3 py-1 text-center font-bold text-yellow-700 dark:text-yellow-300">15%</td>
                  </tr>
                  <tr>
                    <td className="border border-green-300 dark:border-green-600 px-3 py-1 text-red-600 dark:text-red-400">Sin W-8BEN presentado (mora)</td>
                    <td className="border border-green-300 dark:border-green-600 px-3 py-1 text-center font-semibold text-red-600 dark:text-red-400">30%</td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Instrucciones W-8BEN */}
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-300 dark:border-amber-600 rounded-lg p-3">
              <p className="font-semibold text-amber-800 dark:text-amber-300 mb-2">⚠️ Para que IB aplique el 15% debes presentar el formulario W-8BEN:</p>
              <ol className="list-decimal list-inside space-y-1 text-amber-700 dark:text-amber-300">
                <li>Inicia sesión en el <strong>IB Client Portal</strong> → Settings → Account Settings → Tax Forms</li>
                <li>Completa el <strong>W-8BEN</strong>: país de residencia Chile, artículo del tratado: <strong>Art. 10</strong></li>
                <li>Una vez aprobado, IB aplica automáticamente la tasa del <strong>15%</strong></li>
                <li>Solicita el <strong>Formulario 1042-S</strong> (Tax Forms → año) para declarar el crédito Art. 41 A en tu F22</li>
              </ol>
            </div>

            <p className="text-xs text-green-600 dark:text-green-400">
              La retención ya pagada (15% o 30%) es crédito Art. 41 A LIR y se descuenta de tu Global Complementario.
              El campo <em>"Retención dividendos (USD)"</em> del formulario anterior la aplica automáticamente.
            </p>
          </div>

          {/* ── Estimado Global Complementario ──────────────────────────── */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 mb-5">
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                  📊 Estimado Impuesto Global Complementario {params.year}
                </h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Base imponible: {fmtCLP(report.resumen_clp.renta_total_base_imponible)}
                  {' · '}
                  Renta en UTA: {(report.resumen_clp.renta_total_base_imponible / params.uta_clp).toFixed(1)} UTA
                </p>
              </div>
              <div className="text-right">
                <p className="text-xs text-gray-400 uppercase tracking-wide">GC bruto</p>
                <p className="text-xl font-bold text-gray-500 dark:text-gray-400 line-through">
                  {fmtCLP(report.impuesto_global_complementario.impuesto_bruto_clp)}
                </p>
                <p className="text-xs text-gray-400 uppercase tracking-wide mt-1">Neto a pagar</p>
                <p className="text-3xl font-extrabold text-red-600 dark:text-red-400">
                  {fmtCLP(report.impuesto_global_complementario.impuesto_neto_clp)}
                </p>
                {report.impuesto_global_complementario.devolucion_clp > 0 && (
                  <p className="text-sm font-bold text-green-600 dark:text-green-400 mt-1">
                    🎉 Devolución estimada: {fmtCLP(report.impuesto_global_complementario.devolucion_clp)}
                  </p>
                )}
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Tasa efectiva: {fmtPct(report.impuesto_global_complementario.tasa_efectiva_pct)}
                </p>
              </div>
            </div>

            {/* Tabla de créditos */}
            {(report.impuesto_global_complementario.credito_iusc_clp > 0 || report.impuesto_global_complementario.credito_art41a_clp > 0) && (
              <div className="mb-5 bg-green-50 dark:bg-green-900/20 rounded-lg p-4">
                <p className="text-sm font-semibold text-green-700 dark:text-green-300 mb-3">✅ Créditos que reducen tu impuesto</p>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-600 dark:text-gray-300">GC bruto (antes de créditos)</span>
                    <span className="font-medium text-gray-800 dark:text-gray-200">{fmtCLP(report.impuesto_global_complementario.impuesto_bruto_clp)}</span>
                  </div>
                  {report.impuesto_global_complementario.credito_iusc_clp > 0 && (
                    <div className="flex justify-between text-green-700 dark:text-green-400">
                      <span>− Crédito IUSC (impuesto 2ª categoría retenido por empleador)</span>
                      <span className="font-medium">{fmtCLP(report.impuesto_global_complementario.credito_iusc_clp)}</span>
                    </div>
                  )}
                  {report.impuesto_global_complementario.credito_art41a_clp > 0 && (
                    <div className="flex justify-between text-green-700 dark:text-green-400">
                      <span>− Crédito Art. 41A LIR (retención 30% USA: {fmtCLP(report.impuesto_global_complementario.retencion_dividendos_clp)}, tope: {fmtCLP(report.impuesto_global_complementario.tope_credito_exterior_clp)})</span>
                      <span className="font-medium">{fmtCLP(report.impuesto_global_complementario.credito_art41a_clp)}</span>
                    </div>
                  )}
                  <div className="flex justify-between border-t border-green-200 dark:border-green-700 pt-2 font-bold">
                    <span className="text-gray-800 dark:text-gray-100">= GC neto a pagar</span>
                    <span className="text-red-600 dark:text-red-400">{fmtCLP(report.impuesto_global_complementario.impuesto_neto_clp)}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Desglose por tramos */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 dark:bg-gray-700/50 text-left">
                    <th className="px-3 py-2 text-gray-600 dark:text-gray-300 font-medium">Tramo</th>
                    <th className="px-3 py-2 text-gray-600 dark:text-gray-300 font-medium text-right">Base (CLP)</th>
                    <th className="px-3 py-2 text-gray-600 dark:text-gray-300 font-medium text-right">Tasa</th>
                    <th className="px-3 py-2 text-gray-600 dark:text-gray-300 font-medium text-right">Impuesto (CLP)</th>
                  </tr>
                </thead>
                <tbody>
                  {report.impuesto_global_complementario.desglose_tramos.map((t, i) => (
                    <tr
                      key={i}
                      className="border-t border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/30"
                    >
                      <td className="px-3 py-2 text-gray-700 dark:text-gray-300">{t.tramo}</td>
                      <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300">{fmtCLP(t.base_clp)}</td>
                      <td className="px-3 py-2 text-right text-blue-600 dark:text-blue-400 font-medium">
                        {(t.tasa * 100).toFixed(1)}%
                      </td>
                      <td className="px-3 py-2 text-right font-semibold text-red-600 dark:text-red-400">
                        {fmtCLP(t.impuesto_clp)}
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t-2 border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700/40 font-bold">
                    <td className="px-3 py-2 text-gray-800 dark:text-gray-100" colSpan={3}>
                      GC bruto (antes de créditos)
                    </td>
                    <td className="px-3 py-2 text-right text-gray-600 dark:text-gray-400 text-base">
                      {fmtCLP(report.impuesto_global_complementario.impuesto_bruto_clp)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {/* Advertencia */}
            <p className="mt-4 text-xs text-gray-400 italic bg-yellow-50 dark:bg-yellow-900/20 rounded-lg p-3">
              ⚠️ {report.impuesto_global_complementario.advertencia}
            </p>
          </div>

          {/* ── Sugerencias de optimización ──────────────────────────────── */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
              💡 Sugerencias de optimización tributaria
            </h2>
            <div className="space-y-3">
              {report.sugerencias_optimizacion.map((tip, i) => (
                <div
                  key={i}
                  className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden"
                >
                  <button
                    onClick={() => setOpenTip(openTip === i ? null : i)}
                    className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-700/30 transition"
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-gray-500 dark:text-gray-400 font-medium">
                        {tip.categoria}
                      </span>
                      <span className="font-semibold text-gray-800 dark:text-gray-100">
                        {tip.titulo}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${impactoColor[tip.impacto]}`}>
                        Impacto {tip.impacto}
                      </span>
                      <span className="text-gray-400 text-lg">{openTip === i ? '▲' : '▼'}</span>
                    </div>
                  </button>
                  {openTip === i && (
                    <div className="px-4 pb-4 pt-2 text-sm text-gray-600 dark:text-gray-300 bg-gray-50 dark:bg-gray-700/20 border-t border-gray-100 dark:border-gray-700">
                      {tip.detalle}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* ── Análisis SpA ─────────────────────────────────────────────── */}
          <div className={`rounded-xl shadow p-6 border-2 ${report.analisis_spa.muy_conveniente
              ? 'bg-orange-50 dark:bg-orange-900/10 border-orange-400 dark:border-orange-600'
              : report.analisis_spa.conviene
              ? 'bg-yellow-50 dark:bg-yellow-900/10 border-yellow-400 dark:border-yellow-600'
              : 'bg-white dark:bg-gray-800 border-gray-200 dark:border-gray-700'}`}
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                  🏢 ¿Cuándo conviene una SpA?
                </h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Sociedad por Acciones inversionista para diferir el Global Complementario
                </p>
              </div>
              <div className="text-center sm:text-right">
                <span className="text-lg font-bold px-4 py-2 rounded-full bg-white dark:bg-gray-800 shadow-sm border border-gray-200 dark:border-gray-700">
                  {report.analisis_spa.nivel}
                </span>
              </div>
            </div>

            {/* Comparativa */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-5">
              <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm text-center">
                <p className="text-xs text-gray-500 dark:text-gray-400">Renta (en UTA)</p>
                <p className="text-2xl font-extrabold text-gray-900 dark:text-white">
                  {report.analisis_spa.renta_uta}
                </p>
                <p className="text-xs text-gray-400 mt-1">
                  Umbral SpA óptima: ≥ {report.analisis_spa.umbral_migracion_uta} UTA
                </p>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm text-center">
                <p className="text-xs text-gray-500 dark:text-gray-400">Impuesto como persona natural</p>
                <p className="text-2xl font-extrabold text-red-500 dark:text-red-400">
                  {fmtCLP(report.analisis_spa.impuesto_persona_clp)}
                </p>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm text-center">
                <p className="text-xs text-gray-500 dark:text-gray-400">Impuesto estimado vía SpA (IDPC 27%)</p>
                <p className="text-2xl font-extrabold text-blue-600 dark:text-blue-400">
                  {fmtCLP(report.analisis_spa.impuesto_estimado_spa_clp)}
                </p>
                {report.analisis_spa.ahorro_estimado_clp > 0 && (
                  <p className="text-xs text-green-600 dark:text-green-400 font-semibold mt-1">
                    Ahorro diferido ≈ {fmtCLP(report.analisis_spa.ahorro_estimado_clp)}
                  </p>
                )}
              </div>
            </div>

            {/* Acordeón explicación */}
            <button
              onClick={() => setOpenSpa(!openSpa)}
              className="w-full text-left text-sm font-semibold text-blue-600 dark:text-blue-400 hover:underline mb-2"
            >
              {openSpa ? '▲ Ocultar detalles' : '▼ Ver explicación y pasos para migrar'}
            </button>

            {openSpa && (
              <div className="space-y-4 text-sm text-gray-700 dark:text-gray-300">
                <p className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
                  {report.analisis_spa.explicacion}
                </p>
                <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow-sm">
                  <h4 className="font-semibold text-gray-800 dark:text-gray-100 mb-3">
                    📋 Pasos para constituir una SpA inversionista
                  </h4>
                  <ol className="space-y-2">
                    {report.analisis_spa.pasos.map((paso, i) => (
                      <li key={i} className="text-gray-600 dark:text-gray-300 leading-relaxed">
                        {paso}
                      </li>
                    ))}
                  </ol>
                </div>
              </div>
            )}
          </div>

          {/* ── Resumen de operaciones ───────────────────────────────────── */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
              🗂️ Resumen del año {params.year}
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 text-center text-sm">
              {[
                { label: 'Total operaciones', val: report.conteo_operaciones.total, icon: '🔢' },
                { label: 'Compras acción', val: report.conteo_operaciones.compras_acciones, icon: '🛒' },
                { label: 'Ventas acción', val: report.conteo_operaciones.ventas_acciones, icon: '💹' },
                { label: 'Primas cobradas', val: report.conteo_operaciones.primas_cobradas, icon: '⚡' },
                { label: 'Opciones cerradas', val: report.conteo_operaciones.opciones_cerradas, icon: '🔒' },
                { label: 'Dividendos', val: report.conteo_operaciones.dividendos, icon: '💰' },
              ].map(item => (
                <div key={item.label} className="bg-gray-50 dark:bg-gray-700/40 rounded-lg p-3">
                  <div className="text-2xl">{item.icon}</div>
                  <div className="text-xl font-bold text-gray-800 dark:text-gray-100">{item.val}</div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">{item.label}</div>
                </div>
              ))}
            </div>

            {/* Detalle USD/CLP */}
            <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-6">
              <div>
                <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-2 text-sm">En USD</h3>
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                    {[
                      ['Ingresos ventas acciones', fmtUSD(report.resumen_usd.ingresos_ventas_acciones)],
                      ['Costo compras acciones', fmtUSD(report.resumen_usd.costo_compras_acciones)],
                      ['Ganancia capital neta', fmtUSD(report.resumen_usd.ganancia_capital_neta)],
                      ['Primas cobradas', fmtUSD(report.resumen_usd.primas_cobradas)],
                      ['Cierres de opciones', fmtUSD(report.resumen_usd.cierres_opciones)],
                      ['Primas netas', fmtUSD(report.resumen_usd.primas_netas)],
                      ['Dividendos', fmtUSD(report.resumen_usd.dividendos)],
                      ['Comisiones (deducibles)', fmtUSD(report.resumen_usd.comisiones_totales)],
                    ].map(([k, v]) => (
                      <tr key={k}>
                        <td className="py-1.5 text-gray-600 dark:text-gray-400">{k}</td>
                        <td className="py-1.5 text-right font-medium text-gray-800 dark:text-gray-200">{v}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <h3 className="font-semibold text-gray-700 dark:text-gray-300 mb-2 text-sm">En CLP</h3>
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                    {[
                      ['Ganancia capital', fmtCLP(report.resumen_clp.ganancia_capital)],
                      ['Primas netas', fmtCLP(report.resumen_clp.primas_netas)],
                      ['Dividendos', fmtCLP(report.resumen_clp.dividendos)],
                      ['Renta inversiones (subtotal)', fmtCLP(report.resumen_clp.renta_inversiones)],
                      ['Sueldo bruto', fmtCLP(report.resumen_clp.sueldo_bruto)],
                      ['Otros ingresos', fmtCLP(report.resumen_clp.otros_ingresos)],
                      ['Renta trabajo (subtotal)', fmtCLP(report.resumen_clp.renta_trabajo)],
                      ['Base imponible total', fmtCLP(report.resumen_clp.renta_total_base_imponible)],
                      ['Comisiones deducibles', fmtCLP(report.resumen_clp.comisiones_deducibles)],
                    ].map(([k, v]) => (
                      <tr key={k}>
                        <td className="py-1.5 text-gray-600 dark:text-gray-400">{k}</td>
                        <td className="py-1.5 text-right font-medium text-gray-800 dark:text-gray-200">{v}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* ── Detalle transacciones ────────────────────────────────────── */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                📋 Transacciones del año ({report.transacciones.length})
              </h2>
              <button
                onClick={() => setShowTx(!showTx)}
                className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
              >
                {showTx ? '▲ Ocultar' : '▼ Ver detalle'}
              </button>
            </div>

            {showTx && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-700/50 text-left">
                      {['Fecha', 'Ticker', 'Tipo', 'Cantidad', 'Precio USD', 'Total USD', 'Total CLP', 'Comisión', 'Notas'].map(h => (
                        <th key={h} className="px-3 py-2 text-gray-600 dark:text-gray-300 font-medium whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {report.transacciones.map(t => (
                      <tr key={t.id} className="border-t border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/20">
                        <td className="px-3 py-2 text-gray-600 dark:text-gray-400 whitespace-nowrap">{t.fecha}</td>
                        <td className="px-3 py-2 font-bold text-gray-800 dark:text-gray-100">{t.ticker}</td>
                        <td className={`px-3 py-2 whitespace-nowrap font-medium ${tipoClassMap[t.tipo] || 'text-gray-600'}`}>
                          {tipoLabels[t.tipo] || t.tipo}
                        </td>
                        <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300">{t.cantidad}</td>
                        <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300">{fmtUSD(t.precio_usd)}</td>
                        <td className="px-3 py-2 text-right text-gray-700 dark:text-gray-300">{fmtUSD(t.total_usd)}</td>
                        <td className="px-3 py-2 text-right font-semibold text-blue-700 dark:text-blue-400">{fmtCLP(t.total_clp)}</td>
                        <td className="px-3 py-2 text-right text-gray-500 dark:text-gray-400">{fmtUSD(t.comision_usd)}</td>
                        <td className="px-3 py-2 text-gray-500 dark:text-gray-400 max-w-xs truncate">{t.notas}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {report.transacciones.length === 0 && (
                  <p className="text-center text-gray-400 py-8">
                    No hay transacciones registradas para el año {params.year}.
                  </p>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
