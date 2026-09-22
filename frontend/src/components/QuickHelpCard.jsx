import { ShieldCheck, MessageCircleWarning, Users, Landmark, Scale, Network } from 'lucide-react'
import { t } from '../data/translations'

const ICONS = {
  ShieldCheck,
  MessageCircleWarning,
  Users,
  Landmark,
  Scale,
  Network,
}

export default function QuickHelpCard({ category, language, selected, onSelect }) {
  const Icon = ICONS[category.icon]
  return (
    <button
      type="button"
      className={selected ? 'quick-help-card quick-help-card--selected' : 'quick-help-card'}
      onClick={() => onSelect(category.id)}
      aria-pressed={selected}
    >
      <span className="quick-help-card__icon">
        <Icon size={22} aria-hidden="true" />
      </span>
      <span className="quick-help-card__title">{t(language, category.titleKey)}</span>
      <span className="quick-help-card__description">{t(language, category.descriptionKey)}</span>
    </button>
  )
}
