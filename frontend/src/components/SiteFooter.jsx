import { NavLink } from 'react-router-dom'
import Logo from './Logo'
import { getSiteCopy } from '../data/siteContent'

export default function SiteFooter({ language }) {
  const copy = getSiteCopy(language)
  return <footer className="site-footer">
    <div className="site-footer__inner">
      <div className="site-footer__brand"><Logo /><div><strong>Sahkaar Saathi</strong><span>{copy.privacyLine}</span></div></div>
      <nav aria-label={copy.footerLinks}>{['/', '/schemes', '/services', '/about'].map((route, index) =>
        <NavLink key={route} to={route}>{copy.nav[index]}</NavLink>)}</nav>
    </div>
  </footer>
}
