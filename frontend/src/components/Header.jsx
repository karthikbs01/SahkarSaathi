import { useEffect, useRef, useState } from 'react'
import { BookOpen, Check, Copy, History, Info, MoreVertical, Phone, Plus, Type } from 'lucide-react'
import Logo from './Logo'
import { JURISDICTIONS } from '../data/categories'
import { LANGUAGES, t } from '../data/translations'

const HELPLINES = {
  karnataka: { label: 'Karnataka', number: '1800-425-3553' },
  maharashtra: { label: 'Maharashtra', number: '022-69801000' },
  national: { label: 'National', number: '1800-180-1551' },
}

export default function Header({ language, jurisdiction, onLanguageChange, onJurisdictionChange,
  onNewConversation, onOpenHistory, onOpenAbout, onOpenSources, textSize, onTextSizeChange }) {
  const [panel, setPanel] = useState(null)
  const [copyStatus, setCopyStatus] = useState(null)
  const areaRef = useRef(null)
  const languageLabel = LANGUAGES.find((item) => item.code === language)?.native ?? 'Language'
  const jurisdictionLabel = jurisdiction === 'not-sure' ? t(language, 'setLocation')
    : t(language, JURISDICTIONS.find((item) => item.id === jurisdiction)?.labelKey ?? 'notSure')
  const helpline = HELPLINES[jurisdiction] ?? HELPLINES.national

  useEffect(() => {
    function close(event) {
      if (event.key === 'Escape') setPanel(null)
      if (event.type === 'pointerdown' && !areaRef.current?.contains(event.target)) setPanel(null)
    }
    document.addEventListener('keydown', close)
    document.addEventListener('pointerdown', close)
    return () => { document.removeEventListener('keydown', close); document.removeEventListener('pointerdown', close) }
  }, [])

  async function copyNumber() {
    try { await navigator.clipboard.writeText(helpline.number); setCopyStatus('copied') }
    catch { setCopyStatus('failed') }
  }
  function toggle(next) { setCopyStatus(null); setPanel((current) => current === next ? null : next) }

  return (
    <header className="header">
      <div className="header__inner" ref={areaRef}>
        <div className="header__brand"><Logo /><div className="header__brand-text">
          <span className="header__name">{t(language, 'appName')}</span><span className="header__tagline">{t(language, 'tagline')}</span>
        </div></div>
        <div className="header__actions">
          <button type="button" className="context-pill" onClick={() => toggle('context')}
            aria-expanded={panel === 'context'} aria-label={t(language, 'changeContext')}>
            <span>{languageLabel}</span><span aria-hidden="true">·</span><span>{jurisdictionLabel}</span>
          </button>
          <button type="button" className="header__icon-button" onClick={() => toggle('phone')}
            aria-label={t(language, 'helpline')} aria-expanded={panel === 'phone'}><Phone size={19} /></button>
          <button type="button" className="header__icon-button" onClick={() => toggle('menu')}
            aria-label={t(language, 'moreOptions')} aria-expanded={panel === 'menu'}><MoreVertical size={21} /></button>

          {panel === 'context' && <div className="header-panel header-panel--context" role="dialog" aria-label={t(language, 'changeContext')}>
            <p className="header-panel__eyebrow">{t(language, 'languageLabel')}</p>
            <div className="context-options">{LANGUAGES.map((item) => <button type="button" key={item.code}
              className={language === item.code ? 'option-pill option-pill--active' : 'option-pill'} onClick={() => onLanguageChange(item.code)}>
              {item.native}{language === item.code && <Check size={14} />}</button>)}</div>
            <p className="header-panel__eyebrow">{t(language, 'locationLabel')}</p>
            <div className="context-options context-options--stacked">{JURISDICTIONS.map((item) => <button type="button" key={item.id}
              className={jurisdiction === item.id ? 'option-row option-row--active' : 'option-row'}
              onClick={() => { onJurisdictionChange(item.id); setPanel(null) }}><span>{t(language, item.labelKey)}</span>
              {jurisdiction === item.id && <Check size={16} />}</button>)}</div>
          </div>}

          {panel === 'phone' && <div className="header-panel header-panel--phone" role="dialog" aria-label={t(language, 'helplineTitle')}>
            <p className="header-panel__eyebrow">{t(language, 'helplineTitle')}</p><strong>{helpline.label}</strong>
            <span className="helpline-number">{helpline.number}</span><div className="helpline-actions">
              <a className="panel-action panel-action--primary" href={`tel:${helpline.number}`}>{t(language, 'call')}</a>
              <button type="button" className="panel-action" onClick={copyNumber}><Copy size={15} />{t(language, 'copy')}</button>
            </div>{copyStatus && <p className="panel-note" role="status">{t(language, copyStatus === 'copied' ? 'copied' : 'copyFailed')}</p>}
          </div>}

          {panel === 'menu' && <div className="header-panel header-panel--menu" role="menu">
            <button type="button" role="menuitem" className="menu-row" onClick={() => { setPanel(null); onNewConversation() }}><Plus size={17} />{t(language, 'newConversation')}</button>
            <button type="button" role="menuitem" className="menu-row" onClick={() => { setPanel(null); onOpenHistory() }}><History size={17} />{t(language, 'pastConversations')}</button>
            <div className="menu-row menu-row--setting"><Type size={17} /><span>{t(language, 'textSize')}</span><button type="button" className="size-toggle"
              onClick={() => onTextSizeChange(textSize === 'large' ? 'normal' : 'large')}>{t(language, textSize === 'large' ? 'largeText' : 'normalText')}</button></div>
            <div className="menu-divider" />
            <button type="button" role="menuitem" className="menu-row" onClick={() => { setPanel(null); onOpenAbout() }}><Info size={17} />{t(language, 'about')}</button>
            <button type="button" role="menuitem" className="menu-row" onClick={() => { setPanel(null); onOpenSources() }}><BookOpen size={17} />{t(language, 'officialSources')}</button>
          </div>}
        </div>
      </div>
    </header>
  )
}
