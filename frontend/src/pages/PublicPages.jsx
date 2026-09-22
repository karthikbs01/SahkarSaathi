import { ArrowRight, BookOpenCheck, Building2, CheckCircle2, Landmark, MessageCircleWarning,
  Network, Scale, ShieldCheck, Sparkles, Users } from 'lucide-react'
import { CATEGORIES } from '../data/categories'
import { t } from '../data/translations'
import { getSiteCopy, serviceDetails } from '../data/siteContent'
import QuestionComposer from '../components/QuestionComposer'

const ICONS = { ShieldCheck, MessageCircleWarning, Users, Landmark, Scale, Network }

function ServiceIcon({ name }) {
  const Icon = ICONS[name] ?? BookOpenCheck
  return <Icon size={24} aria-hidden="true" />
}

function ServiceCards({ language, onAsk, detailed = false }) {
  const copy = getSiteCopy(language)
  return <div className={detailed ? 'service-list' : 'service-grid'}>
    {CATEGORIES.map((service) => {
      const detail = serviceDetails[service.id]
      const questions = detail.asks[language] ?? detail.asks.en
      return <article className={detailed ? 'service-detail' : 'service-card'} key={service.id}>
        <div className="service-card__icon"><ServiceIcon name={service.icon} /></div>
        <div className="service-card__content">
          <h3>{t(language, service.titleKey)}</h3>
          <p>{t(language, service.descriptionKey)}</p>
          {detailed && <>
            <h4>{copy.whatAsk}</h4>
            <ul>{questions.map((question) => <li key={question}>{question}</li>)}</ul>
            <p className="source-family"><BookOpenCheck size={16} /> <span><strong>{copy.sourcesUsed}:</strong> {detail.sources}</span></p>
          </>}
        </div>
        <button type="button" className={detailed ? 'button button--primary' : 'service-card__action'}
          onClick={() => onAsk(questions[0])}>{detailed ? copy.askAbout : <><span className="sr-only">{copy.askAbout}</span><ArrowRight size={18} /></>}</button>
      </article>
    })}
  </div>
}

export function HomePage({ language, onLanguageChange, question, onQuestionChange, onAsk, onOpenChat, loading }) {
  const copy = getSiteCopy(language)
  const popular = [serviceDetails['crop-loss'], serviceDetails.complaint, serviceDetails.membership,
    serviceDetails.pacs, serviceDetails['multi-state']].map((item) => (item.asks[language] ?? item.asks.en)[0])
  function scrollToServices() { document.getElementById('services')?.scrollIntoView({ behavior: 'smooth' }) }

  return <>
    <main>
      <section className="public-hero page-shell">
        <div className="public-hero__copy">
          <span className="eyebrow"><Sparkles size={16} /> Sahkaar Saathi</span>
          <h1>{copy.heroTitle}</h1><p>{copy.heroBody}</p>
          <div className="hero-actions">
            <button type="button" className="button button--primary" onClick={onOpenChat}>{copy.startChatting}<ArrowRight size={18} /></button>
            <button type="button" className="button button--secondary" onClick={scrollToServices}>{copy.exploreFeatures}</button>
          </div>
          <p className="hero-trust"><CheckCircle2 size={17} />{t(language, 'trustLine')}</p>
        </div>
        <div className="public-hero__image"><img src="/assets/hero-farmers.png" alt="Farmers using Sahkaar Saathi in a field" /></div>
      </section>

      <section id="services" className="section page-shell">
        <div className="section-heading"><span>{copy.servicesEyebrow}</span><h2>{copy.servicesTitle}</h2><p>{copy.servicesBody}</p></div>
        <ServiceCards language={language} onAsk={onAsk} />
      </section>

      <section className="ask-section">
        <div className="page-shell ask-section__grid">
          <div><span className="eyebrow">{copy.homeQuestion}</span><h2>{copy.askTitle}</h2><p>{copy.askBody}</p>
            <div className="language-chips" aria-label={copy.language}>{['en', 'hi', 'kn', 'mr'].map((code) =>
              <button key={code} type="button" className={language === code ? 'language-chip language-chip--active' : 'language-chip'}
                onClick={() => onLanguageChange(code)}>{code === 'en' ? 'English' : code === 'hi' ? 'हिंदी' : code === 'kn' ? 'ಕನ್ನಡ' : 'मराठी'}</button>)}</div>
          </div>
          <div className="home-composer"><QuestionComposer compact language={language} value={question} onChange={onQuestionChange}
            onSubmit={onAsk} loading={loading} /></div>
        </div>
      </section>

      <section className="section page-shell popular-section">
        <div className="section-heading section-heading--left"><h2>{copy.popularTitle}</h2><p>{copy.popularBody}</p></div>
        <div className="popular-list">{popular.map((item, index) => <button type="button" key={item} onClick={() => onAsk(item)}>
          <span>{String(index + 1).padStart(2, '0')}</span>{item}<ArrowRight size={17} /></button>)}</div>
      </section>

      <section className="future-band"><img src="/assets/grassland-footer.png" alt="Green fields at sunrise" />
        <div className="future-band__overlay"><div className="page-shell"><h2>{copy.bandTitle}</h2><p>{copy.bandBody}</p>
          <button type="button" className="button button--light" onClick={onOpenChat}>{copy.startChatting}<ArrowRight size={18} /></button></div></div>
      </section>
    </main>
  </>
}

export function ServicesPage({ language, onAsk }) {
  const copy = getSiteCopy(language)
  return <main className="page-shell inner-page"><div className="page-intro"><span className="eyebrow">{copy.servicesEyebrow}</span>
    <h1>{copy.servicesPageTitle}</h1><p>{copy.servicesPageIntro}</p></div>
    <ServiceCards language={language} onAsk={onAsk} detailed />
  </main>
}

export function SchemesPage({ language, onAsk }) {
  const copy = getSiteCopy(language)
  const cards = [
    { icon: ShieldCheck, title: copy.pmfbyTitle, body: copy.pmfbyBody, source: 'PMFBY Operational Guidelines', questions: serviceDetails['crop-loss'].asks[language] ?? serviceDetails['crop-loss'].asks.en },
    { icon: Building2, title: copy.pacsSchemeTitle, body: copy.pacsSchemeBody, source: 'PACS documents and Computerization Guidelines', questions: serviceDetails.pacs.asks[language] ?? serviceDetails.pacs.asks.en },
  ]
  return <main className="page-shell inner-page"><div className="page-intro"><span className="eyebrow">{copy.nav[1]}</span><h1>{copy.schemesTitle}</h1><p>{copy.schemesIntro}</p></div>
    <div className="scheme-grid">{cards.map(({ icon: Icon, title, body, source, questions }) => <article className="scheme-card" key={title}>
      <div className="scheme-card__icon"><Icon size={27} /></div><h2>{title}</h2><p>{body}</p>
      <h3>{copy.discoverQuestions}</h3><ul>{questions.map((question) => <li key={question}><button type="button" onClick={() => onAsk(question)}>{question}<ArrowRight size={15} /></button></li>)}</ul>
      <p className="source-family"><BookOpenCheck size={16} /><span><strong>{copy.sourcesUsed}:</strong> {source}</span></p>
    </article>)}</div>
  </main>
}

export function AboutPage({ language, onOpenChat }) {
  const copy = getSiteCopy(language)
  const cards = [[Users, copy.whoTitle, copy.whoBody], [BookOpenCheck, copy.coversTitle, copy.coversBody]]
  return <main className="page-shell inner-page about-page"><div className="page-intro"><span className="eyebrow">{copy.nav[3]}</span><h1>{copy.aboutTitle}</h1><p>{copy.aboutIntro}</p></div>
    <div className="about-grid">{cards.map(([Icon, title, body]) => <article key={title}><Icon size={25} /><h2>{title}</h2><p>{body}</p></article>)}</div>
    <section className="how-section"><div><span className="eyebrow">{copy.howTitle}</span><h2>{copy.trustTitle}</h2><p className="trust-statement">“{copy.trustStatement}”</p><p>{copy.aboutDisclaimer}</p>
      <button type="button" className="button button--primary" onClick={onOpenChat}>{copy.startChatting}<ArrowRight size={18} /></button></div>
      <ol>{copy.howSteps.map((step, index) => <li key={step}><span>{index + 1}</span>{step}</li>)}</ol></section>
  </main>
}
