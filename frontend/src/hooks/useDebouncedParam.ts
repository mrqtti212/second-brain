import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Campo de texto ligado a um parâmetro da URL. A URL só muda depois de uma
 * pausa na digitação, e a página volta para a primeira.
 */
export function useDebouncedParam(param: string, delayMs = 300) {
  const [params, setParams] = useSearchParams()
  const [input, setInput] = useState(params.get(param) ?? '')
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(timer.current), [])

  function onChange(value: string) {
    setInput(value)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (value.trim()) next.set(param, value.trim())
          else next.delete(param)
          next.delete('page')
          return next
        },
        { replace: true },
      )
    }, delayMs)
  }

  function reset() {
    clearTimeout(timer.current)
    setInput('')
  }

  return { input, onChange, reset }
}
