import { TriangleAlert } from 'lucide-react'
import { t } from '../data/translations'

const ERROR_KEY_BY_CODE = {
  network: 'networkError',
  rate_limit: 'rateLimitError',
  payload_too_large: 'payloadError',
  server_error: 'serverError',
  unknown: 'unknownError',
}

export default function ErrorMessage({ language, code, onRetry }) {
  const key = ERROR_KEY_BY_CODE[code] ?? 'unknownError'

  return (
    <div className="error-message" role="alert">
      <TriangleAlert size={18} aria-hidden="true" />
      <span>{t(language, key)}</span>
      {onRetry && (
        <button type="button" className="error-message__retry" onClick={onRetry}>
          {t(language, 'retry')}
        </button>
      )}
    </div>
  )
}
