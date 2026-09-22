import { useEffect, useRef } from 'react'
import { MessageCircle, X } from 'lucide-react'
import { t } from '../data/translations'

export default function ConversationHistory({ language, conversations, onOpen, onClose }) {
  const closeRef = useRef(null)
  useEffect(() => {
    closeRef.current?.focus()
    const escape = (event) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [onClose])
  return <div className="drawer-overlay" onMouseDown={onClose}>
    <section className="drawer history-drawer" role="dialog" aria-modal="true" aria-labelledby="history-title"
      onMouseDown={(event) => event.stopPropagation()}>
      <div className="drawer__header"><h2 id="history-title">{t(language, 'pastConversations')}</h2>
        <button type="button" className="icon-button" ref={closeRef} onClick={onClose} aria-label={t(language, 'close')}><X size={20} /></button></div>
      <div className="history-list">{conversations.length === 0 ? <p className="history-empty">{t(language, 'noPastConversations')}</p>
        : conversations.map((conversation) => <button type="button" className="history-item" key={conversation.id} onClick={() => onOpen(conversation)}>
          <MessageCircle size={18} aria-hidden="true" /><span><strong>{conversation.title}</strong>
            <small>{new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(conversation.updatedAt))}</small></span>
        </button>)}</div>
    </section>
  </div>
}
