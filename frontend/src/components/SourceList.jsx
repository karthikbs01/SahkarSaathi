import { useMemo, useState } from 'react'
import { CheckCircle2, ChevronDown } from 'lucide-react'
import SourceCard from './SourceCard'
import { t } from '../data/translations'

function presentationKey(source) {
  return [source.sourceId, source.title, source.section, source.pageStart, source.pageEnd].join('|')
}

export default function SourceList({ language, sources }) {
  const [expanded, setExpanded] = useState(false)
  const uniqueSources = useMemo(() => {
    const seen = new Set()
    return (sources ?? []).filter((source) => {
      const key = presentationKey(source)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [sources])
  if (uniqueSources.length === 0) return null
  const first = uniqueSources[0]
  const extra = uniqueSources.length - 1

  return <div className="source-list">
    <div className="citation-summary"><CheckCircle2 size={16} aria-hidden="true" />
      <span>{first.title}{first.section ? ` · §${first.section}` : ''}{extra > 0 ? ` · +${extra}` : ''}</span>
    </div>
    <button type="button" className="source-list__toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
      {t(language, expanded ? 'hideSources' : 'viewSources')}
      <ChevronDown size={15} className={expanded ? 'source-card__chevron source-card__chevron--open' : 'source-card__chevron'} />
    </button>
    {expanded && <div className="source-list__items">{uniqueSources.map((source) =>
      <SourceCard key={presentationKey(source)} language={language} source={source} />)}</div>}
  </div>
}
