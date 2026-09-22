import { useEffect, useRef, useState } from 'react'
import { Menu, X } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import Logo from './Logo'
import { LANGUAGES } from '../data/translations'
import { getSiteCopy } from '../data/siteContent'

const ROUTES = ['/', '/schemes', '/services', '/about']

export default function PublicHeader({ language, onLanguageChange }) {
  const [open, setOpen] = useState(false)
  const headerRef = useRef(null)
  const copy = getSiteCopy(language)

  useEffect(() => {
    function close(event) {
      if (event.key === 'Escape') setOpen(false)
      if (event.type === 'pointerdown' && !headerRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('keydown', close)
    document.addEventListener('pointerdown', close)
    return () => {
      document.removeEventListener('keydown', close)
      document.removeEventListener('pointerdown', close)
    }
  }, [])

  return <header className="site-header" ref={headerRef}>
    <div className="site-header__inner">
      <NavLink to="/" className="site-brand" aria-label="Sahkaar Saathi home" onClick={() => setOpen(false)}>
        <Logo /><span className="site-brand__name">Sahkaar Saathi</span>
      </NavLink>
      <button className="site-header__menu" type="button" onClick={() => setOpen((value) => !value)}
        aria-expanded={open} aria-controls="public-navigation" aria-label={open ? copy.closeMenu : copy.menu}>
        {open ? <X size={22} /> : <Menu size={22} />}
      </button>
      <div id="public-navigation" className={`site-header__nav-wrap${open ? ' site-header__nav-wrap--open' : ''}`}>
        <nav className="site-nav" aria-label="Primary navigation">
          {ROUTES.map((route, index) => <NavLink key={route} to={route} end={route === '/'}
            onClick={() => setOpen(false)} className={({ isActive }) => isActive ? 'site-nav__link site-nav__link--active' : 'site-nav__link'}>
            {copy.nav[index]}
          </NavLink>)}
        </nav>
        <label className="site-language">
          <span className="sr-only">{copy.language}</span>
          <select value={language} onChange={(event) => onLanguageChange(event.target.value)}>
            {LANGUAGES.map((item) => <option key={item.code} value={item.code}>{item.native}</option>)}
          </select>
        </label>
      </div>
    </div>
  </header>
}
