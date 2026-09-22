import { useCallback, useEffect, useRef, useState } from 'react'
import { Send } from 'lucide-react'
import VoiceButton from './VoiceButton'
import { t } from '../data/translations'
import { useAudioRecorder } from '../hooks/useAudioRecorder'

const CHAR_LIMIT = 1500
const WARNING_THRESHOLD = 150

export default function QuestionComposer({
  language,
  value,
  onChange,
  onSubmit,
  loading,
  compact = false,
}) {
  const [localError, setLocalError] = useState('')
  const textareaRef = useRef(null)

  useEffect(() => {
    if (!compact || !textareaRef.current) return
    const textarea = textareaRef.current
    textarea.style.height = 'auto'
    const maximum = 112
    const desiredHeight = value ? Math.min(textarea.scrollHeight, maximum) : 42
    textarea.style.height = `${desiredHeight}px`
    textarea.style.overflowY = value && textarea.scrollHeight > maximum ? 'auto' : 'hidden'
  }, [compact, value])

  const remaining = CHAR_LIMIT - value.length
  const showCounter = remaining <= WARNING_THRESHOLD
  const overLimit = remaining < 0
  const handleTranscript = useCallback((transcript) => {
    if (!value.trim() || window.confirm(t(language, 'voiceReplaceConfirm'))) {
      onChange(transcript)
      requestAnimationFrame(() => document.getElementById('question-input')?.focus())
    }
  }, [language, onChange, value])
  const recorder = useAudioRecorder({ language, onTranscript: handleTranscript })

  function handleSubmit() {
    if (loading) return
    if (!value.trim()) {
      setLocalError(t(language, 'emptyInputError'))
      return
    }
    if (overLimit) {
      setLocalError(t(language, 'tooLongError'))
      return
    }
    setLocalError('')
    onSubmit(value.trim())
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className={compact ? 'composer composer--compact' : 'composer'}>
      <label htmlFor="question-input" className="sr-only">
        {t(language, compact ? 'askAnotherPlaceholder' : 'inputPlaceholder')}
      </label>
      <textarea
        ref={textareaRef}
        id="question-input"
        className="composer__textarea"
        placeholder={t(language, compact ? 'askAnotherPlaceholder' : 'inputPlaceholder')}
        value={value}
        onChange={(event) => {
          onChange(event.target.value)
          if (localError) setLocalError('')
        }}
        onKeyDown={handleKeyDown}
        rows={compact ? 1 : 3}
        aria-describedby={localError ? 'composer-error' : undefined}
        aria-invalid={Boolean(localError)}
      />
      <div className="composer__footer">
        <div className="composer__status">
          {localError && (
            <span id="composer-error" className="composer__error" role="alert">
              {localError}
            </span>
          )}
          {!localError && showCounter && (
            <span className={overLimit ? 'composer__counter composer__counter--over' : 'composer__counter'}>
              {remaining} {t(language, 'charLimitWarning')}
            </span>
          )}
        </div>
        <div className="composer__actions">
          <VoiceButton language={language} recorder={recorder} disabled={loading} />
          <button
            type="button"
            className="composer__send"
            onClick={handleSubmit}
            disabled={loading}
            aria-label={t(language, 'send')}
          >
            <Send size={18} aria-hidden="true" />
            <span>{t(language, 'send')}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
