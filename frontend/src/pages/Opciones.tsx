import { useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { ActionsSlotProvider } from '../components/PageActions'
import ScannerInsumos from '../components/ScannerInsumos'
import CoveredCalls from './CoveredCalls'

/**
 * Sección única para todo el flujo de covered calls. Las pestañas van en el
 * orden en que se usan —buscar, simular, registrar, revisar—, no por afinidad
 * temática: el problema que resuelve esta página es saber cuál abrir, y eso lo
 * responde el momento, no el nombre.
 *
 * Cada pestaña es una ruta hija para que el deep link, el botón atrás y el
 * resaltado del nav sigan funcionando.
 */

type Tab = {
  to: string
  label: string
  title: string
  desc: string
  /** Enlace a la página que alimenta esta pestaña, cuando no es evidente. */
  hint?: { to: string; label: string }
}

export const OPCIONES_TABS: Tab[] = [
  {
    to: '/opciones/buscar',
    label: 'Buscar',
    title: 'Buscar',
    desc: 'Qué vender hoy: candidatos con cadenas reales de CBOE, comprando la acción al ask y vendiendo la call al bid.',
  },
  {
    to: '/opciones/simular',
    label: 'Simular',
    title: 'Simular',
    desc: 'Antes de mandar la orden: compara strikes, vencimientos y primas con los datos de tu broker.',
  },
  {
    to: '/opciones/posiciones',
    label: 'Mis posiciones',
    title: 'Mis posiciones',
    desc: 'Los contratos que tienes vivos: días al vencimiento, roll y cierre.',
    hint: { to: '/import-ib', label: '¿Operaste en IBKR? Importa las transacciones →' },
  },
  {
    to: '/opciones/resultados',
    label: 'Resultados',
    title: 'Resultados',
    desc: 'Cómo terminó cada bloque de acciones: prima cobrada, dividendos, comisiones y P&L.',
    hint: { to: '/import-ib', label: '¿Faltan operaciones? Importa desde IBKR →' },
  },
]

// Etapas del scanner: se llega desde Buscar, no desde las pestañas.
const SUBPAGES: Record<string, { parent: string; parentLabel: string; title: string; desc: string }> = {
  '/opciones/buscar/universo': {
    parent: '/opciones/buscar',
    parentLabel: 'Buscar',
    title: '🔭 Universo',
    desc: 'De dónde salen los candidatos: acciones US$5–20, optionables y con liquidez suficiente.',
  },
  '/opciones/buscar/fundamentales': {
    parent: '/opciones/buscar',
    parentLabel: 'Buscar',
    title: '🔎 Fundamentales',
    desc: 'El filtro de calidad del subyacente: Financial Safety Score con los números del filing de SEC EDGAR.',
  },
}

export default function Opciones() {
  const { pathname } = useLocation()
  const [actionsSlot, setActionsSlot] = useState<HTMLElement | null>(null)

  const subpage = SUBPAGES[pathname]
  const activeTab =
    OPCIONES_TABS.find(t => pathname === t.to) ??
    OPCIONES_TABS.find(t => pathname.startsWith(t.to + '/')) ??
    OPCIONES_TABS[0]

  const heading = subpage ?? activeTab

  return (
    <div className="w-full max-w-[1440px] mx-auto px-4 sm:px-6 py-6 space-y-5">
      <nav aria-label="Secciones de opciones" className="-mx-4 px-4 sm:mx-0 sm:px-0 overflow-x-auto">
        <div className="flex gap-1 border-b border-gray-200 dark:border-gray-700 min-w-max">
          {OPCIONES_TABS.map(tab => {
            const active = tab === activeTab
            return (
              <Link
                key={tab.to}
                to={tab.to}
                aria-current={active ? 'page' : undefined}
                className={`px-4 py-3 text-sm font-semibold whitespace-nowrap border-b-2 -mb-px transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded-t-lg ${
                  active
                    ? 'border-blue-600 text-blue-700 dark:text-blue-300'
                    : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:border-gray-300 dark:hover:border-gray-600'
                }`}
              >
                {tab.label}
              </Link>
            )
          })}
        </div>
      </nav>

      <div className="page-header !mb-0">
        <div className="min-w-0">
          {subpage && (
            <Link
              to={subpage.parent}
              className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-blue-700 dark:hover:text-blue-300 mb-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
            >
              ← Volver a {subpage.parentLabel}
            </Link>
          )}
          <h1 className="page-title">{heading.title}</h1>
          <p className="page-subtitle max-w-3xl">{heading.desc}</p>
          {!subpage && activeTab.hint && (
            <Link
              to={activeTab.hint.to}
              className="inline-block mt-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
            >
              {activeTab.hint.label}
            </Link>
          )}
        </div>
        <div ref={setActionsSlot} className="flex flex-wrap items-center gap-2 sm:justify-end" />
      </div>

      <ActionsSlotProvider value={actionsSlot}>
        <Outlet />
      </ActionsSlotProvider>
    </div>
  )
}

/** Pestaña Buscar: el scanner, con sus etapas de origen colapsadas debajo. */
export function BuscarTab() {
  return (
    <div className="space-y-6">
      <CoveredCalls />
      <ScannerInsumos />
    </div>
  )
}
