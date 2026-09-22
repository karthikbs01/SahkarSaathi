import { t } from '../data/translations'
const PROMPTS = [['faqCrop', 'faqCropQuestion'], ['faqComplaint', 'faqComplaintQuestion'], ['faqEligibility', 'faqEligibilityQuestion'], ['faqPacs', 'faqPacsQuestion']]
export default function QuickPrompts({ language, onSubmit, disabled = false }) {
  return <section className="quick-prompts" aria-label={t(language, 'quickPrompts')}>
    {PROMPTS.map(([label, question]) => <button type="button" key={label} disabled={disabled}
      onClick={() => onSubmit(t(language, question))}>{t(language, label)}</button>)}
  </section>
}
