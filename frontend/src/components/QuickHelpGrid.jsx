import QuickHelpCard from './QuickHelpCard'
import { CATEGORIES } from '../data/categories'
import { t } from '../data/translations'

export default function QuickHelpGrid({ language, selectedCategory, onSelectCategory }) {
  return (
    <section className="quick-help" aria-label={t(language, 'howCanWeHelp')}>
      <h2 className="quick-help__heading">{t(language, 'howCanWeHelp')}</h2>
      <div className="quick-help__grid">
        {CATEGORIES.map((category) => (
          <QuickHelpCard
            key={category.id}
            category={category}
            language={language}
            selected={selectedCategory === category.id}
            onSelect={onSelectCategory}
          />
        ))}
      </div>
    </section>
  )
}
