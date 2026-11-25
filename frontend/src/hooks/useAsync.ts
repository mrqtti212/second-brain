import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../services/api'

interface Result<T> {
  key: string
  data?: T
  error?: ApiError | Error
}

export interface AsyncState<T> {
  data: T | undefined
  error: Error | undefined
  /** true enquanto a requisição da chave atual não terminou. */
  loading: boolean
  reload: () => void
}

/**
 * Executa `fetcher` quando `key` muda e expõe loading/erro/dados.
 * O `fetcher` deve depender apenas do que está codificado em `key`.
 */
export function useAsync<T>(fetcher: () => Promise<T>, key: string): AsyncState<T> {
  const [result, setResult] = useState<Result<T> | null>(null)
  const [tick, setTick] = useState(0)
  const fetcherRef = useRef(fetcher)
  const fullKey = `${key}#${tick}`

  useEffect(() => {
    fetcherRef.current = fetcher
  })

  useEffect(() => {
    let cancelled = false
    fetcherRef.current().then(
      (data) => !cancelled && setResult({ key: fullKey, data }),
      // Mantém o último dado bom junto com o erro: uma recarga que falha não apaga o que já estava na tela.
      (error: Error) => !cancelled && setResult((previous) => ({ key: fullKey, error, data: previous?.data })),
    )
    return () => {
      cancelled = true
    }
  }, [fullKey])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  const settled = result?.key === fullKey
  return {
    data: result?.data, // mantém o dado anterior enquanto recarrega e quando a recarga falha
    error: settled ? result.error : undefined,
    loading: !settled,
    reload,
  }
}
