// Mock backend responses used only in development/demo mode (VITE_USE_MOCK_API=true).
// Shape mirrors the real POST /api/chat response contract documented in services/api.js.

export const MOCK_RESPONSES = [
  {
    match: /crop|pmfby|damage|insurance/i,
    response: {
      answer:
        "If your crop is damaged, you should report it as soon as possible.\n\n1. **Inform your insurance company, bank branch or the local agriculture/insurance department** within the notification window, generally within 72 hours of the damage.\n2. **Provide details** such as your survey number, crop, and extent of loss when reporting.\n3. **A joint inspection** will typically be carried out by insurance company and government officials to assess the loss.\n4. **Claim settlement** follows once the assessment is finalized, based on the applicable yield or loss-assessment method for your area.\n\nKeep photographs of the damage and your policy/enrolment details handy — they help during the assessment process.",
      abstained: false,
      abstention_reason: null,
      jurisdiction: 'Karnataka',
      sources: [
        {
          source_id: 'PMFBY_2023',
          title: 'PMFBY Operational Guidelines 2023',
          section: '21.6.8.3',
          page_start: 52,
          page_end: 53,
          source_url: null,
        },
        {
          source_id: 'PMFBY_2023_NOTIF',
          title: 'PMFBY Operational Guidelines 2023',
          section: '14.2',
          page_start: 31,
          page_end: 31,
          source_url: null,
        },
      ],
    },
  },
  {
    match: /member|eligib|join|disqualif/i,
    response: {
      answer:
        "Cooperative society membership eligibility is generally governed by the society's bye-laws along with the applicable state Cooperative Societies Act.\n\n**Common requirements include:**\n- Being of legal age (usually 18 years or above)\n- Residing or operating within the society's area of operation\n- Paying the prescribed membership fee/share capital\n\n**Common disqualifications:**\n- Being declared insolvent\n- Conviction for an offence involving moral turpitude\n- Holding a similar membership that creates a conflict as defined in the bye-laws\n\nExact conditions vary by state and by the individual society's registered bye-laws.",
      abstained: false,
      abstention_reason: null,
      jurisdiction: 'Maharashtra',
      sources: [
        {
          source_id: 'MCS_ACT_1960',
          title: 'Maharashtra Co-operative Societies Act, 1960',
          section: '22',
          page_start: 14,
          page_end: 15,
          source_url: null,
        },
      ],
    },
  },
  {
    match: /complain|grievance|ombudsman|deposit/i,
    response: {
      answer:
        "If you have a complaint or grievance against a cooperative society, there are a few routes available depending on the nature of the issue.\n\n1. **Raise it with the society's managing committee first** — many issues are resolved internally.\n2. **Approach the Registrar of Cooperative Societies** for your state if the internal process does not resolve it.\n3. **For banking/deposit-related grievances**, the Cooperative Ombudsman mechanism (where applicable) provides an independent redressal channel.\n4. **Keep written records** of your complaint, including dates and any acknowledgements received — these are often required as evidence.",
      abstained: false,
      abstention_reason: null,
      jurisdiction: null,
      sources: [
        {
          source_id: 'OMBUDSMAN_GUIDE',
          title: 'Cooperative Ombudsman Guidance',
          section: null,
          page_start: null,
          page_end: null,
          source_url: null,
        },
      ],
    },
  },
  {
    match: /pacs|primary agricultural/i,
    response: {
      answer:
        "PACS (Primary Agricultural Credit Societies) are village-level cooperative institutions that provide short and medium-term credit and related services to farmers.\n\n**Typical services include:**\n- Crop loans and input credit\n- Distribution of seeds and fertilizers\n- Storage and marketing support for produce\n- In many states, PACS are also being computerized to link with district and state cooperative banks for faster, more transparent service delivery.",
      abstained: false,
      abstention_reason: null,
      jurisdiction: 'Central / India Scheme',
      sources: [
        {
          source_id: 'PACS_MODEL_BYELAWS',
          title: 'PACS Model Bye-Laws',
          section: '4',
          page_start: 8,
          page_end: 9,
          source_url: null,
        },
      ],
    },
  },
]

export const MOCK_ABSTENTION_RESPONSE = {
  answer: '',
  abstained: true,
  abstention_reason:
    'The available official sources do not clearly cover this specific situation. It may depend on your state, cooperative type, or the specific circumstances involved.',
  jurisdiction: null,
  sources: [],
}

export function getMockResponse(question) {
  const matched = MOCK_RESPONSES.find((entry) => entry.match.test(question))
  if (matched) return matched.response
  return MOCK_ABSTENTION_RESPONSE
}
