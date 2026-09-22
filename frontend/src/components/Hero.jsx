import QuestionComposer from './QuestionComposer'
import QuickPrompts from './QuickPrompts'
import { t } from '../data/translations'

export default function Hero({
  language,
  question,
  onQuestionChange,
  onSubmit,
  loading,
}) {
  return (
    <section className="hero" aria-label={t(language, 'headline')}>
      <h1 className="hero__headline">{t(language, 'headline')}</h1>
      <p className="hero__subheadline">{t(language, 'subheadline')}</p>
      <p className="hero__trust-line">{t(language, 'trustLine')}</p>

      <div className="hero__composer-card">
        <QuickPrompts language={language} onSubmit={onSubmit} disabled={loading} />
        <QuestionComposer
          language={language}
          value={question}
          onChange={onQuestionChange}
          onSubmit={onSubmit}
          loading={loading}
        />
      </div>
    </section>
  )
}
