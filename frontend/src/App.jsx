import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import Header from './components/Header'
import PublicHeader from './components/PublicHeader'
import SiteFooter from './components/SiteFooter'
import ChatContainer from './components/ChatContainer'
import QuestionComposer from './components/QuestionComposer'
import QuickPrompts from './components/QuickPrompts'
import InfoDrawer from './components/InfoDrawer'
import LanguageLanding from './components/LanguageLanding'
import ConversationHistory from './components/ConversationHistory'
import { HomePage, ServicesPage, SchemesPage, AboutPage } from './pages/PublicPages'
import { useLocalStorage } from './hooks/useLocalStorage'
import { askQuestion } from './services/api'
import { jurisdictionFromApiValue, jurisdictionToApiValue } from './data/categories'
import { t } from './data/translations'

const SUPPORTED_LANGUAGES = new Set(['en', 'kn', 'hi', 'mr'])
const JURISDICTIONS = new Set(['karnataka', 'maharashtra', 'multi-state', 'central', 'not-sure'])
const MAX_SAVED_CONVERSATIONS = 20

function makeId(prefix) {
  return `${prefix}-${Date.now()}-${crypto.getRandomValues(new Uint32Array(1))[0].toString(36)}`
}

function validStoredLanguage() {
  try {
    const value = JSON.parse(localStorage.getItem('sahkarsaathi:language'))
    return SUPPORTED_LANGUAGES.has(value)
  } catch { return false }
}

function safeConversations(value) {
  if (!Array.isArray(value)) return []
  return value.filter((item) => item && typeof item.id === 'string' && typeof item.title === 'string'
    && Number.isFinite(Date.parse(item.createdAt)) && Number.isFinite(Date.parse(item.updatedAt))
    && Array.isArray(item.messages) && item.messages.every((message) => message
      && typeof message.id === 'string' && SUPPORTED_LANGUAGES.has(message.language)
      && ((message.role === 'user' && typeof message.content === 'string')
        || (message.role === 'assistant' && message.content && typeof message.content.answer === 'string'))))
    .slice(0, MAX_SAVED_CONVERSATIONS)
}

export default function App() {
  const navigate = useNavigate()
  const [language, setLanguage] = useLocalStorage('sahkarsaathi:language', 'en')
  const [preferredJurisdiction, setPreferredJurisdiction] = useLocalStorage('sahkarsaathi:jurisdiction', 'not-sure')
  const [textSize, setTextSize] = useLocalStorage('sahkarsaathi:text-size', 'normal')
  const [storedConversations, setStoredConversations] = useLocalStorage('sahkarsaathi:conversations', [])
  const conversations = useMemo(() => safeConversations(storedConversations), [storedConversations])
  const [activeConversationId, setActiveConversationId] = useLocalStorage('sahkarsaathi:active-conversation', null)
  const restored = conversations.find((item) => item.id === activeConversationId)
  const [messages, setMessages] = useState(() => restored?.messages ?? [])
  const [createdAt, setCreatedAt] = useState(() => restored?.createdAt ?? new Date().toISOString())
  const [sessionJurisdiction, setSessionJurisdiction] = useState(() => restored?.jurisdiction
    ?? (JURISDICTIONS.has(preferredJurisdiction) ? preferredJurisdiction : 'not-sure'))
  const [showLanguageLanding, setShowLanguageLanding] = useState(() => !validStoredLanguage())
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [drawerMode, setDrawerMode] = useState(null)
  const submittingRef = useRef(false)
  const lastSubmissionRef = useRef(null)

  useEffect(() => {
    document.documentElement.dataset.theme = 'light'
    return () => delete document.documentElement.dataset.theme
  }, [])

  useEffect(() => {
    if (messages.length === 0 || !activeConversationId) return
    const firstQuestion = messages.find((message) => message.role === 'user')?.content ?? t(language, 'conversation')
    const conversation = {
      id: activeConversationId,
      title: firstQuestion.length > 64 ? `${firstQuestion.slice(0, 61)}…` : firstQuestion,
      createdAt,
      updatedAt: new Date().toISOString(),
      messages,
      jurisdiction: sessionJurisdiction,
    }
    setStoredConversations((current) => {
      const valid = safeConversations(current).filter((item) => item.id !== activeConversationId)
      return [conversation, ...valid].slice(0, MAX_SAVED_CONVERSATIONS)
    })
  }, [activeConversationId, createdAt, language, messages, sessionJurisdiction, setStoredConversations])

  const ensureConversation = useCallback(() => {
    if (activeConversationId) return activeConversationId
    const id = makeId('conversation')
    setActiveConversationId(id)
    setCreatedAt(new Date().toISOString())
    return id
  }, [activeConversationId, setActiveConversationId])

  const executeSubmission = useCallback(async (payload, appendUser) => {
    if (submittingRef.current) return
    submittingRef.current = true
    ensureConversation()
    if (appendUser) {
      setMessages((previous) => [...previous, {
        id: makeId('message'), role: 'user', content: payload.question, language: payload.language,
      }])
      setQuestion('')
    }
    setError(null)
    setLoading(true)
    try {
      const result = await askQuestion(payload)
      setMessages((previous) => [...previous, {
        id: makeId('message'), role: 'assistant', content: result, language: payload.language,
      }])
      const inferred = jurisdictionFromApiValue(result.jurisdiction)
      if (inferred) setSessionJurisdiction(inferred)
    } catch (requestError) {
      setError(requestError.code ?? 'unknown')
    } finally {
      setLoading(false)
      submittingRef.current = false
    }
  }, [ensureConversation])

  const sendQuestion = useCallback((text) => {
    if (submittingRef.current || !text?.trim()) return
    const cleanText = text.trim()
    const conversationHistory = messages.slice(-4).filter((message) => message.role === 'user'
      || (message.role === 'assistant' && !message.content.abstained)).map((message) => ({
      role: message.role,
      content: (message.role === 'user' ? message.content : message.content.answer).replace(/https?:\/\/\S+/g, '').slice(0, 4000),
      language: message.language,
    }))
    const payload = {
      question: cleanText,
      jurisdiction: jurisdictionToApiValue(sessionJurisdiction),
      language,
      conversation_history: conversationHistory,
    }
    lastSubmissionRef.current = payload
    executeSubmission(payload, true)
  }, [executeSubmission, language, messages, sessionJurisdiction])

  const handleRetry = useCallback(() => {
    if (!lastSubmissionRef.current || submittingRef.current) return
    executeSubmission(lastSubmissionRef.current, false)
  }, [executeSubmission])

  const handleNewConversation = useCallback(() => {
    if (messages.length > 0 && !window.confirm(t(language, 'confirmNewConversation'))) return
    setMessages([]); setError(null); setLoading(false); setQuestion('')
    setSessionJurisdiction(JURISDICTIONS.has(preferredJurisdiction) ? preferredJurisdiction : 'not-sure')
    setActiveConversationId(null); setCreatedAt(new Date().toISOString()); lastSubmissionRef.current = null
  }, [language, messages.length, preferredJurisdiction, setActiveConversationId])

  function selectLanguage(nextLanguage) {
    if (SUPPORTED_LANGUAGES.has(nextLanguage)) setLanguage(nextLanguage)
  }

  function completeOnboarding(nextLanguage) {
    if (!SUPPORTED_LANGUAGES.has(nextLanguage)) return
    setLanguage(nextLanguage); setShowLanguageLanding(false); navigate('/', { replace: true })
  }

  function selectJurisdiction(nextJurisdiction) {
    if (!JURISDICTIONS.has(nextJurisdiction)) return
    setPreferredJurisdiction(nextJurisdiction); setSessionJurisdiction(nextJurisdiction)
  }

  function openConversation(conversation) {
    setMessages(conversation.messages); setActiveConversationId(conversation.id); setCreatedAt(conversation.createdAt)
    setSessionJurisdiction(JURISDICTIONS.has(conversation.jurisdiction) ? conversation.jurisdiction : preferredJurisdiction)
    setError(null); setQuestion(''); setDrawerMode(null); lastSubmissionRef.current = null; navigate('/chat')
  }

  function openChatWithQuestion(text) {
    navigate('/chat'); sendQuestion(text)
  }

  function updateFeedback(messageId, feedback) {
    setMessages((current) => current.map((message) => message.id === messageId ? { ...message, feedback } : message))
  }

  if (showLanguageLanding) return <LanguageLanding onSelect={completeOnboarding} />

  const publicLayout = (page) => <div className="site-app"><PublicHeader language={language} onLanguageChange={selectLanguage} />
    {page}<SiteFooter language={language} /></div>

  return <div className={textSize === 'large' ? 'app app--large-text' : 'app'}>
    <Routes>
      <Route path="/" element={publicLayout(<HomePage language={language} onLanguageChange={selectLanguage}
        question={question} onQuestionChange={setQuestion} onAsk={openChatWithQuestion}
        onOpenChat={() => navigate('/chat')} loading={loading} />)} />
      <Route path="/services" element={publicLayout(<ServicesPage language={language} onAsk={openChatWithQuestion} />)} />
      <Route path="/schemes" element={publicLayout(<SchemesPage language={language} onAsk={openChatWithQuestion} />)} />
      <Route path="/about" element={publicLayout(<AboutPage language={language} onOpenChat={() => navigate('/chat')} />)} />
      <Route path="/chat" element={<div className="chat-page">
        <Header language={language} jurisdiction={sessionJurisdiction} onLanguageChange={selectLanguage}
          onJurisdictionChange={selectJurisdiction} onNewConversation={handleNewConversation}
          onOpenHistory={() => setDrawerMode('history')} onOpenAbout={() => setDrawerMode('about')}
          onOpenSources={() => setDrawerMode('sources')} textSize={textSize} onTextSizeChange={setTextSize} />
        <main className="chat-page__main">
          {messages.length === 0 && !loading && !error && <section className="chat-welcome">
            <span className="eyebrow">Sahkaar Saathi</span><h1>{t(language, 'headline')}</h1><p>{t(language, 'subheadline')}</p>
          </section>}
          <ChatContainer language={language} messages={messages} loading={loading} error={error}
            onRetry={handleRetry} onFollowUp={sendQuestion} onFeedback={updateFeedback} />
        </main>
        <div className="chat-composer-dock"><div className="chat-composer-dock__inner">
          <QuickPrompts language={language} onSubmit={sendQuestion} disabled={loading} />
          <div className="chat-composer-box"><QuestionComposer compact language={language} value={question}
            onChange={setQuestion} onSubmit={sendQuestion} loading={loading} /></div>
        </div></div>
      </div>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>

    {(drawerMode === 'about' || drawerMode === 'sources') && <InfoDrawer language={language} mode={drawerMode} onClose={() => setDrawerMode(null)} />}
    {drawerMode === 'history' && <ConversationHistory language={language} conversations={conversations}
      onOpen={openConversation} onClose={() => setDrawerMode(null)} />}
  </div>
}
