import { useCallback, useState } from 'react'

export function useLocalStorage(key, defaultValue) {
  const [value, setValue] = useState(() => {
    try {
      const stored = window.localStorage.getItem(key)
      return stored !== null ? JSON.parse(stored) : defaultValue
    } catch {
      return defaultValue
    }
  })

  const setPersistedValue = useCallback((next) => {
    setValue((current) => {
      const resolved = typeof next === 'function' ? next(current) : next
      try {
        window.localStorage.setItem(key, JSON.stringify(resolved))
      } catch {
        // storage unavailable (private mode, quota) — ignore, state still works in-memory
      }
      return resolved
    })
  }, [key])

  return [value, setPersistedValue]
}
