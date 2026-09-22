import { MapPin } from 'lucide-react'
import { JURISDICTIONS } from '../data/categories'
import { t } from '../data/translations'

export default function JurisdictionSelector({ language, jurisdiction, onChange }) {
  return (
    <div className="jurisdiction-selector">
      <label htmlFor="jurisdiction-select" className="jurisdiction-selector__label">
        <MapPin size={16} aria-hidden="true" />
        {t(language, 'chooseState')}
      </label>
      <select
        id="jurisdiction-select"
        className="jurisdiction-selector__select"
        value={jurisdiction}
        onChange={(event) => onChange(event.target.value)}
      >
        {JURISDICTIONS.map((option) => (
          <option key={option.id} value={option.id}>
            {t(language, option.labelKey)}
          </option>
        ))}
      </select>
    </div>
  )
}
