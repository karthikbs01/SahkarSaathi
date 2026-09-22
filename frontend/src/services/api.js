import { getMockResponse } from '../data/mockResponses'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const USE_MOCK_API = import.meta.env.VITE_USE_MOCK_API === 'true'
const REQUEST_TIMEOUT_MS = 20000
const TTS_REQUEST_TIMEOUT_MS = 45000
const MOCK_DELAY_MS = 900
export const MAX_TTS_TEXT_LENGTH = 4000

export class ApiError extends Error {
  constructor(code) {
    super(code)
    this.code = code
  }
}

// Normalizes whatever shape the backend sends into a stable structure the UI can rely on,
// so components never have to guard against missing/renamed backend fields directly.
function normalizeResponse(raw) {
  const sources = Array.isArray(raw?.sources)
    ? raw.sources
        .filter(Boolean)
        .map((source) => ({
          sourceId: source.source_id ?? null,
          title: source.title ?? null,
          section: source.section ?? null,
          pageStart: source.page_start ?? null,
          pageEnd: source.page_end ?? null,
          sourceUrl: source.source_url ?? null,
        }))
        .filter((source) => source.title)
    : []

  return {
    answer: typeof raw?.answer === 'string' ? raw.answer : '',
    abstained: Boolean(raw?.abstained),
    abstentionReason: raw?.abstention_reason ?? null,
    jurisdiction: raw?.jurisdiction ?? null,
    sources,
  }
}

async function callMockApi(question) {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS))
  return normalizeResponse(getMockResponse(question))
}

async function callRealApi({ question, jurisdiction, language, conversation_history = [] }) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, jurisdiction, language, conversation_history }),
      signal: controller.signal,
    })
  } catch {
    throw new ApiError('network')
  } finally {
    clearTimeout(timeout)
  }

  if (response.status === 429) throw new ApiError('rate_limit')
  if (response.status === 413) throw new ApiError('payload_too_large')
  if (response.status >= 500) throw new ApiError('server_error')
  if (!response.ok) throw new ApiError('unknown')

  let json
  try {
    json = await response.json()
  } catch {
    throw new ApiError('unknown')
  }

  return normalizeResponse(json)
}

export async function askQuestion({ question, jurisdiction, language, conversation_history = [] }) {
  if (USE_MOCK_API) return callMockApi(question)
  return callRealApi({ question, jurisdiction, language, conversation_history })
}

export async function transcribeAudio(file, language) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 35000)
  const formData = new FormData()
  formData.append('file', file)
  formData.append('language', language)

  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/transcribe`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    })
  } catch {
    throw new ApiError('speech_network')
  } finally {
    clearTimeout(timeout)
  }

  if (response.status === 400) throw new ApiError('speech_invalid')
  if (response.status === 413) throw new ApiError('speech_too_large')
  if (response.status === 502) throw new ApiError('speech_unrecognized')
  if (response.status >= 500) throw new ApiError('speech_network')
  if (!response.ok) throw new ApiError('speech_invalid')

  let body
  try {
    body = await response.json()
  } catch {
    throw new ApiError('speech_unrecognized')
  }
  if (typeof body?.transcript !== 'string' || !body.transcript.trim()) {
    throw new ApiError('speech_empty')
  }
  return body.transcript.trim()
}

export async function synthesizeSpeech(text, language, signal) {
  const controller = new AbortController()
  const abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  const timeout = setTimeout(abort, TTS_REQUEST_TIMEOUT_MS)

  let response
  try {
    response = await fetch(`${API_BASE_URL}/api/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, language }),
      signal: controller.signal,
    })
  } catch {
    if (controller.signal.aborted && signal?.aborted) throw new ApiError('tts_cancelled')
    throw new ApiError('tts_network')
  } finally {
    clearTimeout(timeout)
    signal?.removeEventListener('abort', abort)
  }

  if (response.status === 400) throw new ApiError('tts_invalid')
  if (response.status === 413) throw new ApiError('tts_too_long')
  if (response.status === 502) throw new ApiError('tts_unavailable')
  if (response.status >= 500) throw new ApiError('tts_unavailable')
  if (!response.ok) throw new ApiError('tts_invalid')

  const contentType = response.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase()
  if (!contentType?.startsWith('audio/')) throw new ApiError('tts_malformed')
  const audio = await response.blob()
  if (!audio.size || !audio.type.startsWith('audio/')) throw new ApiError('tts_malformed')
  return audio
}

export function isMockMode() {
  return USE_MOCK_API
}
