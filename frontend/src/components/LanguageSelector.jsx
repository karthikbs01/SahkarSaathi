import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Globe } from 'lucide-react'
import { LANGUAGES } from '../data/translations'

export default function LanguageSelector({ language, onChange }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

  useEffect(() => {
    function handleOutsideClick(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false)
      }
    }
    function handleEscape(event) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handleOutsideClick)
    document.addEventListener('keydown', handleEscape)
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [])

  const current = LANGUAGES.find((lng) => lng.code === language) ?? LANGUAGES[0]

  return (
    <div className="lang-selector" ref={containerRef}>
      <button
        type="button"
        className="lang-selector__trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Language: ${current.native}`}
        onClick={() => setOpen((v) => !v)}
      >
        <Globe size={17} aria-hidden="true" />
        <span>{current.native}</span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {open && (
        <ul className="lang-selector__menu" role="listbox">
          {LANGUAGES.map((lng) => (
            <li key={lng.code} role="option" aria-selected={lng.code === language}>
              <button
                type="button"
                className="lang-selector__option"
                onClick={() => {
                  onChange(lng.code)
                  setOpen(false)
                }}
              >
                <span>{lng.native}</span>
                {lng.code === language && <Check size={16} aria-hidden="true" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
