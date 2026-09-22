import { t } from '../data/translations'

export default function UserMessage({ language, content }) {
  return (
    <div className="message message--user">
      <span className="message__label">{t(language, 'you')}</span>
      <div className="message__bubble message__bubble--user">{content}</div>
    </div>
  )
}
