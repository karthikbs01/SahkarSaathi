import { CircleHelp } from 'lucide-react'
import { t } from '../data/translations'

export default function AbstentionCard({ language, abstentionReason }) {
  return (
    <div className="abstention-card" role="status">
      <CircleHelp size={20} aria-hidden="true" className="abstention-card__icon" />
      <div>
        <p className="abstention-card__title">{t(language, 'abstainedTitle')}</p>
        {abstentionReason && <p className="abstention-card__reason">{abstentionReason}</p>}
        <p className="abstention-card__help">{t(language, 'abstainedHelp')}</p>
      </div>
    </div>
  )
}
