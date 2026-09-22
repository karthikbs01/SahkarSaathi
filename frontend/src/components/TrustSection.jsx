import { BadgeCheck } from 'lucide-react'
import { TRUST_SOURCES } from '../data/categories'
import { t } from '../data/translations'

export default function TrustSection({ language }) {
  return (
    <section className="trust-section" aria-label={t(language, 'trustHeading')}>
      <div className="trust-section__heading">
        <BadgeCheck size={22} aria-hidden="true" />
        <h2>{t(language, 'trustHeading')}</h2>
      </div>
      <p className="trust-section__body">{t(language, 'trustBody')}</p>
      <ul className="trust-section__sources">
        {TRUST_SOURCES.map((source) => (
          <li key={source}>{source}</li>
        ))}
      </ul>
      <p className="trust-section__disclaimer">{t(language, 'disclaimer')}</p>
    </section>
  )
}
