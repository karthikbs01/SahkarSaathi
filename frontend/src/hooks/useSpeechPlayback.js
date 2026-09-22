import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, MAX_TTS_TEXT_LENGTH, synthesizeSpeech } from '../services/api'

const SUPPORTED_LANGUAGES = new Set(['en', 'kn', 'hi', 'mr'])
const IDLE_PLAYBACK = { messageId: null, status: 'idle', errorKey: null }

function playbackErrorKey(error) {
  if (!(error instanceof ApiError)) return 'ttsPlaybackError'
  if (error.code === 'tts_invalid') return 'ttsCannotRead'
  if (error.code === 'tts_too_long') return 'ttsTooLong'
  if (error.code === 'tts_unavailable') return 'ttsUnavailable'
  if (error.code === 'tts_network') return 'ttsNetwork'
  return 'ttsPlaybackError'
}

export function canPlayAnswer(answer, language, abstained) {
  return !abstained && Boolean(answer?.trim()) && SUPPORTED_LANGUAGES.has(language)
}

export function useSpeechPlayback() {
  const [playback, setPlayback] = useState(IDLE_PLAYBACK)
  const activeRef = useRef(IDLE_PLAYBACK)
  const audioRef = useRef(null)
  const objectUrlRef = useRef(null)
  const requestControllerRef = useRef(null)
  const generationRef = useRef(0)

  const releaseAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.onended = null
      audioRef.current.onerror = null
      audioRef.current.pause()
      audioRef.current.currentTime = 0
      audioRef.current.src = ''
    }
    audioRef.current = null
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current)
    objectUrlRef.current = null
  }, [])

  const stop = useCallback(() => {
    generationRef.current += 1
    requestControllerRef.current?.abort()
    requestControllerRef.current = null
    releaseAudio()
    activeRef.current = IDLE_PLAYBACK
    setPlayback(IDLE_PLAYBACK)
  }, [releaseAudio])

  const play = useCallback(async (messageId, answer, language, abstained = false) => {
    if (!canPlayAnswer(answer, language, abstained)) return
    if (activeRef.current.messageId === messageId) {
      if (activeRef.current.status === 'loading') return
      if (activeRef.current.status === 'playing') {
        stop()
        return
      }
    }

    stop()
    if (answer.length > MAX_TTS_TEXT_LENGTH) {
      const next = { messageId, status: 'error', errorKey: 'ttsTooLong' }
      activeRef.current = next
      setPlayback(next)
      return
    }

    const generation = generationRef.current + 1
    generationRef.current = generation
    const controller = new AbortController()
    requestControllerRef.current = controller
    const loading = { messageId, status: 'loading', errorKey: null }
    activeRef.current = loading
    setPlayback(loading)

    try {
      const blob = await synthesizeSpeech(answer, language, controller.signal)
      if (generationRef.current !== generation || controller.signal.aborted) return
      requestControllerRef.current = null
      const objectUrl = URL.createObjectURL(blob)
      const audio = new Audio(objectUrl)
      objectUrlRef.current = objectUrl
      audioRef.current = audio
      audio.onended = () => {
        if (generationRef.current !== generation) return
        releaseAudio()
        activeRef.current = IDLE_PLAYBACK
        setPlayback(IDLE_PLAYBACK)
      }
      audio.onerror = () => {
        if (generationRef.current !== generation) return
        releaseAudio()
        const failed = { messageId, status: 'error', errorKey: 'ttsPlaybackError' }
        activeRef.current = failed
        setPlayback(failed)
      }
      await audio.play()
      if (generationRef.current !== generation) return
      const playing = { messageId, status: 'playing', errorKey: null }
      activeRef.current = playing
      setPlayback(playing)
    } catch (error) {
      if (generationRef.current !== generation || error?.code === 'tts_cancelled') return
      requestControllerRef.current = null
      releaseAudio()
      const failed = { messageId, status: 'error', errorKey: playbackErrorKey(error) }
      activeRef.current = failed
      setPlayback(failed)
    }
  }, [releaseAudio, stop])

  useEffect(() => () => {
    generationRef.current += 1
    requestControllerRef.current?.abort()
    requestControllerRef.current = null
    releaseAudio()
  }, [releaseAudio])

  return { playback, play, stop }
}
