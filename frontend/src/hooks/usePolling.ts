import { useCallback, useEffect, useRef, useState } from 'react'

interface PollingOptions {
  /** Só faz polling enquanto for verdadeiro (ex.: documento ainda não está em estado terminal). */
  active: boolean
  /** O que repetir a cada intervalo (normalmente, recarregar os dados). */
  onTick: () => void
  /** A última tentativa falhou? Falhas seguidas pausam o polling. */
  hasError: boolean
  intervalMs?: number
  maxFailures?: number
}

/**
 * Repete `onTick` a cada `intervalMs` enquanto `active`. Para sozinho quando `active` vira falso
 * ou o componente desmonta (o timer é sempre limpo). Depois de `maxFailures` falhas seguidas
 * pausa, para não bater em um servidor fora do ar; `resume` retoma.
 */
export function usePolling({ active, onTick, hasError, intervalMs = 2000, maxFailures = 5 }: PollingOptions) {
  const [paused, setPaused] = useState(false)
  const tickRef = useRef(onTick)
  const errorRef = useRef(hasError)
  const failures = useRef(0)

  useEffect(() => {
    tickRef.current = onTick
    errorRef.current = hasError
  })

  useEffect(() => {
    if (!active || paused) return
    const id = setInterval(() => {
      if (errorRef.current) {
        failures.current += 1
        if (failures.current >= maxFailures) {
          setPaused(true)
          return
        }
      } else {
        failures.current = 0
      }
      tickRef.current()
    }, intervalMs)
    return () => clearInterval(id)
  }, [active, paused, intervalMs, maxFailures])

  const resume = useCallback(() => {
    failures.current = 0
    setPaused(false)
  }, [])

  return { paused, resume }
}
