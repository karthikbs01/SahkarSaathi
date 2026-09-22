import { ChevronRight } from 'lucide-react'
import { CATEGORIES } from '../data/categories'
import { t } from '../data/translations'

export default function SuggestedQuestions({ language, categoryId, onPickQuestion }) {
  const category = CATEGORIES.find((item) => item.id === categoryId)
  if (!category) return null

  return (
    <section className="suggested-questions" aria-label={t(language, 'suggestedQuestions')}>
      <h3 className="suggested-questions__heading">{t(language, 'suggestedQuestions')}</h3>
      <ul className="suggested-questions__list">
        {category.suggestedQuestions.map((question, index) => {
          const localizedQuestion = t(language, category.suggestedQuestionKeys[index]) || question
          return <li key={category.suggestedQuestionKeys[index]}>
            <button
              type="button"
              className="suggested-questions__item"
              onClick={() => onPickQuestion(localizedQuestion)}
            >
              <span>{localizedQuestion}</span>
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </li>
        })}
      </ul>
    </section>
  )
}
