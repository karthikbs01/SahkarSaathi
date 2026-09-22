export const CATEGORIES = [
  {
    id: 'crop-loss',
    icon: 'ShieldCheck',
    titleKey: 'quickCropLossTitle',
    descriptionKey: 'quickCropLossDescription',
    suggestedQuestions: [
      'What should I do after crop damage under PMFBY?',
      'How is crop loss assessed?',
      'How do I report crop damage?',
    ],
    suggestedQuestionKeys: ['cropQuestion1', 'cropQuestion2', 'cropQuestion3'],
  },
  {
    id: 'complaint',
    icon: 'MessageCircleWarning',
    titleKey: 'quickComplaintTitle',
    descriptionKey: 'quickComplaintDescription',
    suggestedQuestions: [
      'Where can I complain about a deposit issue?',
      'How do I approach the Cooperative Ombudsman?',
    ],
    suggestedQuestionKeys: ['complaintQuestion1', 'complaintQuestion2'],
  },
  {
    id: 'membership',
    icon: 'Users',
    titleKey: 'quickMembershipTitle',
    descriptionKey: 'quickMembershipDescription',
    suggestedQuestions: [
      'Who can become a cooperative society member?',
      'What can disqualify someone from membership?',
    ],
    suggestedQuestionKeys: ['membershipQuestion1', 'membershipQuestion2'],
  },
  {
    id: 'pacs',
    icon: 'Landmark',
    titleKey: 'quickPacsTitle',
    descriptionKey: 'quickPacsDescription',
    suggestedQuestions: [
      'What services can PACS provide?',
      'What is PACS computerization?',
    ],
    suggestedQuestionKeys: ['pacsQuestion1', 'pacsQuestion2'],
  },
  {
    id: 'state-law',
    icon: 'Scale',
    titleKey: 'quickStateLawTitle',
    descriptionKey: 'quickStateLawDescription',
    suggestedQuestions: [
      'What does the Karnataka Cooperative Societies Act say about elections?',
      'What does the Maharashtra Cooperative Societies Act say about audits?',
    ],
    suggestedQuestionKeys: ['stateLawQuestion1', 'stateLawQuestion2'],
  },
  {
    id: 'multi-state',
    icon: 'Network',
    titleKey: 'quickMultiStateTitle',
    descriptionKey: 'quickMultiStateDescription',
    suggestedQuestions: [
      'What law governs Multi-State Cooperative Societies?',
      'How does a society register as Multi-State Cooperative?',
    ],
    suggestedQuestionKeys: ['multiStateQuestion1', 'multiStateQuestion2'],
  },
]

export const JURISDICTIONS = [
  { id: 'karnataka', labelKey: 'karnataka' },
  { id: 'maharashtra', labelKey: 'maharashtra' },
  { id: 'multi-state', labelKey: 'multiState' },
  { id: 'central', labelKey: 'central' },
  { id: 'not-sure', labelKey: 'notSure' },
]

const JURISDICTION_API_LABELS = {
  karnataka: 'Karnataka',
  maharashtra: 'Maharashtra',
  'multi-state': 'Multi-State Cooperative',
  central: 'Central / India Scheme',
  'not-sure': null,
}

export function jurisdictionToApiValue(jurisdictionId) {
  return JURISDICTION_API_LABELS[jurisdictionId] ?? null
}

export function jurisdictionFromApiValue(value) {
  const normalized = String(value ?? '').trim().toLowerCase()
  if (normalized === 'karnataka') return 'karnataka'
  if (normalized === 'maharashtra') return 'maharashtra'
  if (['multi-state cooperative', 'multi-state', 'multistate'].includes(normalized)) return 'multi-state'
  if (['central / india scheme', 'central', 'india', 'india scheme'].includes(normalized)) return 'central'
  return null
}

export const TRUST_SOURCES = [
  'Karnataka Co-operative Societies Act',
  'Maharashtra Co-operative Societies Act',
  'Multi-State Cooperative Societies Act & Rules',
  'PMFBY Guidelines',
  'PACS Model Bye-Laws',
  'Cooperative Ombudsman Guidance',
]
