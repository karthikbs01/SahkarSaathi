# SahkarSaathi

SahkarSaathi is a multilingual, farmer-friendly frontend for a source-grounded
assistant that helps cooperative members and farmers understand cooperative
membership, PACS services, PMFBY/crop insurance, grievance redressal, and
Karnataka/Maharashtra/Multi-State cooperative law.

This repository contains **only the frontend**. It is built to call a backend
RAG service (owned by another team member) that performs retrieval,
grounding, and answer generation. This frontend never talks to Groq,
Bhashini, or any AI provider directly — it only calls one backend endpoint
(`POST /api/chat`) and renders the result.

## Requirements

- Node.js 18+
- npm

## Getting started

```bash
npm install
npm run dev
```

The app runs at **http://localhost:5173**.

Other scripts:

```bash
npm run build    # production build to dist/
npm run preview  # preview the production build locally
npm run lint      # oxlint
```

## Environment variables

Copy `.env.example` to `.env` and adjust as needed:

```bash
VITE_API_BASE_URL=http://localhost:8000
VITE_USE_MOCK_API=true
```

- `VITE_API_BASE_URL` — base URL of the backend. The frontend calls
  `POST {VITE_API_BASE_URL}/api/chat`.
- `VITE_USE_MOCK_API` — when `true`, the app uses local mock responses
  (`src/data/mockResponses.js`) instead of calling the backend, so the UI can
  be developed and demoed without it running. Set to `false` to always call
  the real backend.

No API keys (Groq, Bhashini, OpenAI, etc.) are used or required by this
frontend — all of that lives in the backend.

## Mock mode

With `VITE_USE_MOCK_API=true`, the API service layer (`src/services/api.js`)
short-circuits to `src/data/mockResponses.js`, which contains example
answers for crop loss/PMFBY, membership, grievance/Ombudsman, and PACS
questions, plus an abstention example for anything else. Mock mode is
isolated to the service layer — components always work with the same
normalized response shape regardless of where it came from.

To disable mock mode and hit a real backend, set `VITE_USE_MOCK_API=false`
(or remove the line) and point `VITE_API_BASE_URL` at the running backend.

## Backend contract

The frontend expects:

**Request** — `POST /api/chat`

```json
{
  "question": "What should I do after crop damage?",
  "jurisdiction": "Karnataka",
  "language": "en"
}
```

**Response**

```json
{
  "answer": "....",
  "abstained": false,
  "abstention_reason": null,
  "jurisdiction": "Karnataka",
  "sources": [
    {
      "source_id": "PMFBY_2023",
      "title": "PMFBY Operational Guidelines 2023",
      "section": "21.6.8.3",
      "page_start": 52,
      "page_end": 53,
      "source_url": null
    }
  ]
}
```

All raw backend responses are normalized in one place
(`src/services/api.js`), so components never depend on the raw JSON shape
directly and missing fields (null sources, missing sections/pages, etc.)
are handled gracefully.

## Project structure

```
src/
  components/   UI components (Header, Hero, chat, sources, etc.)
  data/         translations, categories, mock responses
  services/     api.js — the only place that talks to the backend
  hooks/        useLocalStorage
  assets/
  App.jsx
  main.jsx
  index.css
```
