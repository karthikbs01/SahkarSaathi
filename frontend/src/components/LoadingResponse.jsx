import { t } from '../data/translations'

export default function LoadingResponse({ language }) {
  return (
    <div className="message message--assistant">
      <span className="message__label">{t(language, 'assistant')}</span>
      <div className="message__bubble message__bubble--assistant loading-response" role="status">
        <span className="loading-response__dots" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </span>
        <span>{t(language, 'checkingSources')}</span>
      </div>
    </div>
  )
}
