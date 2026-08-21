import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'

/**
 * Universo y Fundamentales son etapas del scanner, no destinos propios: se
 * consultan para entender por qué un candidato aparece (o no) en esta lista.
 * Por eso viven colapsados acá y no como entradas del menú principal.
 */
export default function ScannerInsumos() {
  const [qualified, setQualified] = useState<number | null>(null)
  const [lastRun, setLastRun] = useState<string | null>(null)

  useEffect(() => {
    api
      .get('/api/scanner/universe/status')
      .then(({ data }) => {
        if (!data?.last_run) return
        setQualified(data.last_run.funnel?.qualified ?? null)
        setLastRun(data.last_run.started_at ?? null)
      })
      .catch(() => {
        /* el detalle vive en la sub-página; acá un fallo solo oculta el conteo */
      })
  }, [])

  const fecha = lastRun
    ? new Date(lastRun).toLocaleDateString('es-CL', { day: '2-digit', month: 'short' })
    : null

  return (
    <details className="group card">
      <summary className="flex cursor-pointer items-center gap-2 px-5 py-3.5 text-sm font-medium text-gray-700 dark:text-gray-200 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
        <svg
          className="w-4 h-4 flex-shrink-0 text-gray-400 transition-transform group-open:rotate-90 motion-reduce:transition-none"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        De dónde salen estos candidatos
      </summary>

      <div className="grid gap-3 px-5 pb-5 sm:grid-cols-2">
        <InsumoCard
          to="/opciones/buscar/universo"
          icon="🔭"
          title="Universo"
          badge={qualified !== null ? `${qualified} califican` : null}
          desc="Acciones US$5–20, optionables y con liquidez suficiente. Es el conjunto sobre el que corre el scanner."
          foot={fecha ? `Última corrida: ${fecha}` : 'Sin corridas registradas'}
        />
        <InsumoCard
          to="/opciones/buscar/fundamentales"
          icon="🔎"
          title="Fundamentales"
          badge="SEC EDGAR"
          desc="Financial Safety Score con los números del filing de origen. Es el filtro de calidad del subyacente antes de vender la call."
          foot="Se refresca a diario, 06:15 ET"
        />
      </div>
    </details>
  )
}

function InsumoCard({
  to,
  icon,
  title,
  badge,
  desc,
  foot,
}: {
  to: string
  icon: string
  title: string
  badge: string | null
  desc: string
  foot: string
}) {
  return (
    <Link
      to={to}
      className="block rounded-lg border border-gray-200 dark:border-gray-700 p-4 transition-colors hover:border-blue-400 dark:hover:border-blue-500 hover:bg-gray-50 dark:hover:bg-gray-700/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span aria-hidden="true">{icon}</span>
        <span className="font-semibold text-gray-900 dark:text-white">{title}</span>
        {badge && (
          <span className="ml-auto rounded-full bg-blue-50 dark:bg-blue-900/40 px-2 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-300">
            {badge}
          </span>
        )}
      </div>
      <p className="text-sm text-gray-600 dark:text-gray-300">{desc}</p>
      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">{foot}</p>
    </Link>
  )
}
