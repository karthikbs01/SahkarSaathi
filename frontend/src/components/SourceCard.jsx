import { useState } from 'react'
import { ChevronDown, FileText } from 'lucide-react'
import { t } from '../data/translations'

function formatPages(source) {
  if (source.pageStart == null) return null
  if (source.pageEnd == null || source.pageEnd === source.pageStart) {
    return `p. ${source.pageStart}`
  }
  return `pp. ${source.pageStart}–${source.pageEnd}`
}

export default function SourceCard({ language, source }) {
  const [expanded, setExpanded] = useState(false)
  const pages = formatPages(source)
  const hasDetails = Boolean(source.section || pages || source.sourceId)

  return (
    <div className="source-card">
      <div className="source-card__main">
        <FileText size={16} aria-hidden="true" className="source-card__icon" />
        {source.sourceUrl ? (
          <a
            href={source.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="source-card__title source-card__title--link"
          >
            {source.title}
          </a>
        ) : (
          <span className="source-card__title">{source.title}</span>
        )}
      </div>
      {hasDetails && (
        <>
          <button
            type="button"
            className="source-card__toggle"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            <span>{expanded ? t(language, 'hideSourceDetails') : t(language, 'viewSourceDetails')}</span>
            <ChevronDown
              size={14}
              aria-hidden="true"
              className={expanded ? 'source-card__chevron source-card__chevron--open' : 'source-card__chevron'}
            />
          </button>
          {expanded && (
            <dl className="source-card__details">
              {source.section && (
                <div>
                  <dt>{t(language, 'sectionLabel')}</dt>
                  <dd>{source.section}</dd>
                </div>
              )}
              {pages && (
                <div>
                  <dt>{t(language, 'pagesLabel')}</dt>
                  <dd>{pages}</dd>
                </div>
              )}
              {source.sourceId && (
                <div>
                  <dt>ID</dt>
                  <dd>{source.sourceId}</dd>
                </div>
              )}
            </dl>
          )}
        </>
      )}
    </div>
  )
}
