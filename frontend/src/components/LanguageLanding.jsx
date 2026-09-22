import { useEffect, useState } from 'react'
import Logo from './Logo'
import { LANGUAGES } from '../data/translations'

export default function LanguageLanding({ onSelect }) {
  const [ready, setReady] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)

  useEffect(() => {
    if (ready) return undefined
    const timer = window.setTimeout(() => setReady(true), 1300)
    return () => window.clearTimeout(timer)
  }, [ready])

  return <main className={`language-landing${ready ? ' language-landing--ready' : ''}`}>
    <div className="language-landing__logo"><Logo /></div>
    <section className="language-landing__selection" aria-labelledby="language-title" aria-hidden={!ready}>
      <p>Welcome · स्वागत · ಸ್ವಾಗತ · स्वागत</p>
      <h1 id="language-title">Choose your language</h1>
      <p className="language-landing__multilingual">ನಿಮ್ಮ ಭಾಷೆ · अपनी भाषा · तुमची भाषा</p>
      <div className="language-landing__choices">{['en', 'hi', 'kn', 'mr'].map((code) => {
        const item = LANGUAGES.find((language) => language.code === code)
        return <button type="button" key={code} onClick={() => onSelect(code)} lang={code} tabIndex={ready ? 0 : -1}>{item.native}</button>
      })}</div>
    </section>
  </main>
}
