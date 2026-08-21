import { createContext, useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/**
 * Deja que una página monte sus botones de acción en el encabezado de la
 * sección que la contiene, sin duplicar el título ni la maquetación.
 *
 * El default `undefined` distingue "no hay shell" (renderiza inline, como
 * siempre) de "el shell existe pero su nodo todavía no montó" (espera un
 * frame). Sin esa distinción, una página abierta fuera de una sección con
 * pestañas perdería sus botones.
 */
const ActionsSlotContext = createContext<HTMLElement | null | undefined>(undefined)

export const ActionsSlotProvider = ActionsSlotContext.Provider

export default function PageActions({ children }: { children: ReactNode }) {
  const slot = useContext(ActionsSlotContext)
  if (slot === undefined) return <>{children}</>
  if (slot === null) return null
  return createPortal(children, slot)
}
