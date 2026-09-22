import { t } from '../data/translations'

export default function Footer({ language }) {
  return (
    <footer className="footer">
      <p>{t(language, 'appName')} · {t(language, 'tagline')}</p>
      <p className="footer__disclaimer">{t(language, 'disclaimer')}</p>
    </footer>
  )
}
