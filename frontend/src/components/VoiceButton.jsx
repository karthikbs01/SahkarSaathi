import { LoaderCircle, Mic, Square, X } from 'lucide-react'
import { t } from '../data/translations'

function formatTime(seconds) {
  return `0:${String(seconds).padStart(2, '0')}`
}

export default function VoiceButton({ language, recorder, disabled }) {
  if (recorder.status === 'recording') {
    return (
      <div className="voice-recording">
        <span className="voice-recording__status" role="status" aria-live="polite">
          <span className="voice-recording__dot" aria-hidden="true" />
          {t(language, 'voiceListening')} {formatTime(recorder.elapsed)}
        </span>
        <button type="button" className="voice-button voice-button--stop" onClick={recorder.stopRecording}>
          <Square size={17} aria-hidden="true" />
          <span className="voice-button__label">{t(language, 'stopRecording')}</span>
        </button>
        <button
          type="button"
          className="voice-button voice-button--cancel"
          onClick={recorder.cancelRecording}
          aria-label={t(language, 'cancelRecording')}
        >
          <X size={18} aria-hidden="true" />
        </button>
      </div>
    )
  }

  const waiting = recorder.status === 'requesting' || recorder.status === 'processing'
  return (
    <div className="voice-control">
      <button
        type="button"
        className="voice-button"
        onClick={recorder.startRecording}
        disabled={disabled || waiting}
        aria-label={t(language, 'speak')}
      >
        {waiting ? <LoaderCircle className="voice-button__spinner" size={20} aria-hidden="true" /> : <Mic size={20} aria-hidden="true" />}
        <span className="voice-button__label">{t(language, 'speak')}</span>
      </button>
      {recorder.messageKey && (
        <span className="voice-control__message" role="status" aria-live="polite">
          {t(language, recorder.messageKey)}
        </span>
      )}
      {recorder.status === 'requesting' && (
        <span className="voice-control__message" role="status" aria-live="polite">
          {t(language, 'voiceRequesting')}
        </span>
      )}
      {recorder.status === 'processing' && (
        <span className="voice-control__message" role="status" aria-live="polite">
          {t(language, 'voiceProcessing')}
        </span>
      )}
    </div>
  )
}
