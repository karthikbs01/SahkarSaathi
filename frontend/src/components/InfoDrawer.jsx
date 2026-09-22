import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { t } from '../data/translations'
import { TRUST_SOURCES } from '../data/categories'

export default function InfoDrawer({ language, mode, onClose }) {
  const closeButtonRef = useRef(null)

  useEffect(() => {
    closeButtonRef.current?.focus()
    function handleEscape(event) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [onClose])

  const title = mode === 'about' ? t(language, 'about') : t(language, 'officialSources')

  return (
    <div className="drawer-overlay" onMouseDown={onClose}>
      <div
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer__header">
          <h2 id="drawer-title">{title}</h2>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            ref={closeButtonRef}
            aria-label={t(language, 'close')}
          >
            <X size={20} aria-hidden="true" />
          </button>
        </div>
        <div className="drawer__body">
          {mode === 'about' ? (
            <p>{t(language, 'aboutBody')}</p>
          ) : (
            <>
              <p>{t(language, 'trustBody')}</p>
              <ul className="drawer__source-list">
                {TRUST_SOURCES.map((source) => (
                  <li key={source}>{source}</li>
                ))}
              </ul>
            </>
          )}
          <p className="drawer__disclaimer">{t(language, 'disclaimer')}</p>
        </div>
      </div>
    </div>
  )
}
