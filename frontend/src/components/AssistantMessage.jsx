import { Pause, ThumbsDown, ThumbsUp, Volume2 } from 'lucide-react'
import FormattedAnswer from './FormattedAnswer'
import SourceList from './SourceList'
import AbstentionCard from './AbstentionCard'
import { t } from '../data/translations'
import { canPlayAnswer } from '../hooks/useSpeechPlayback'

export default function AssistantMessage({
  messageId,
  language,
  responseLanguage,
  content,
  playback,
  onPlay,
  onFollowUp,
  feedback,
  onFeedback,
}) {
  const { answer, abstained, abstentionReason, sources } = content
  const playable = canPlayAnswer(answer, responseLanguage, abstained)
  const isCurrent = playback.messageId === messageId
  const isLoading = isCurrent && playback.status === 'loading'
  const isPlaying = isCurrent && playback.status === 'playing'
  const errorKey = isCurrent && playback.status === 'error' ? playback.errorKey : null

  return (
    <div className="message message--assistant">
      <span className="message__label">{t(language, 'assistant')}</span>
      <div className="message__bubble message__bubble--assistant">
        {abstained ? (
          <AbstentionCard language={language} abstentionReason={abstentionReason} />
        ) : (
          <>
            <FormattedAnswer text={answer} />
            <div className="answer-controls">
              {playable && (
                <button
                  type="button"
                  className={`answer-control${isPlaying ? ' answer-control--active' : ''}`}
                  onClick={() => onPlay(messageId, answer, responseLanguage, abstained)}
                  disabled={isLoading}
                  aria-label={t(language, isPlaying ? 'stopAnswerAudio' : 'listenToAnswer')}
                >
                  {isPlaying ? <Pause size={17} aria-hidden="true" /> : <Volume2 size={17} aria-hidden="true" />}
                  <span>{t(language, isLoading ? 'ttsPreparing' : isPlaying ? 'ttsStop' : 'ttsListen')}</span>
                </button>
              )}
              <button type="button" className={`answer-control answer-control--icon${feedback === 'up' ? ' answer-control--active' : ''}`}
                onClick={() => onFeedback(feedback === 'up' ? null : 'up')} aria-label={t(language, 'helpful')} title={t(language, 'helpful')}>
                <ThumbsUp size={16} /></button>
              <button type="button" className={`answer-control answer-control--icon${feedback === 'down' ? ' answer-control--active' : ''}`}
                onClick={() => onFeedback(feedback === 'down' ? null : 'down')} aria-label={t(language, 'notHelpful')} title={t(language, 'notHelpful')}>
                <ThumbsDown size={16} /></button>
            </div>
            {errorKey && <span className="answer-audio__error" role="status">{t(language, errorKey)}</span>}
            <SourceList language={language} sources={sources} />
            {onFollowUp && answer?.trim() && (
              <div className="answer-follow-ups">
                {['followDocuments', 'followTimeline', 'followReport', 'followOther'].map((key) => (
                  <button type="button" className="follow-up-chip" key={key}
                    onClick={() => onFollowUp(t(language, key))}>{t(language, key)}</button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
