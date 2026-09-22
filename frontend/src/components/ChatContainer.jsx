import { useEffect, useRef } from 'react'
import UserMessage from './UserMessage'
import AssistantMessage from './AssistantMessage'
import LoadingResponse from './LoadingResponse'
import ErrorMessage from './ErrorMessage'
import { t } from '../data/translations'
import { useSpeechPlayback } from '../hooks/useSpeechPlayback'

export default function ChatContainer({ language, messages, loading, error, onRetry, onFollowUp, onFeedback }) {
  const bottomRef = useRef(null)
  const nearBottomRef = useRef(true)
  const { playback, play, stop } = useSpeechPlayback()

  useEffect(() => {
    function trackPosition() {
      const remaining = document.documentElement.scrollHeight - (window.scrollY + window.innerHeight)
      nearBottomRef.current = remaining < 260
    }
    window.addEventListener('scroll', trackPosition, { passive: true })
    return () => window.removeEventListener('scroll', trackPosition)
  }, [])

  useEffect(() => {
    if (nearBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages.length, loading, error])

  useEffect(() => {
    if (messages.length === 0) stop()
  }, [messages.length, stop])

  if (messages.length === 0 && !loading && !error) return null

  return (
    <section className="chat" aria-label={t(language, 'assistant')}>
      <div className="chat__messages">
        {messages.map((message) =>
          message.role === 'user' ? (
            <UserMessage key={message.id} language={language} content={message.content} />
          ) : (
            <AssistantMessage
              key={message.id}
              messageId={message.id}
              language={language}
              responseLanguage={message.language ?? language}
              content={message.content}
              playback={playback}
              onPlay={play}
              onFollowUp={onFollowUp}
              feedback={message.feedback ?? null}
              onFeedback={(value) => onFeedback(message.id, value)}
            />
          ),
        )}
        {loading && <LoadingResponse language={language} />}
        {error && <ErrorMessage language={language} code={error} onRetry={onRetry} />}
        <div ref={bottomRef} />
      </div>
    </section>
  )
}
