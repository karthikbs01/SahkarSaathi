import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, transcribeAudio } from '../services/api'

const MAX_RECORDING_SECONDS = 20
const MIN_RECORDING_SECONDS = 0.25
const INITIALIZATION_TIMEOUT_MS = 10000

function devLog(stage, details = undefined) {
  if (!import.meta.env.DEV) return
  if (details === undefined) console.debug(`[voice] ${stage}`)
  else console.debug(`[voice] ${stage}`, details)
}

function withTimeout(promise, timeoutMs) {
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      const error = new Error('Microphone initialization timed out')
      error.name = 'MicrophoneInitializationTimeoutError'
      reject(error)
    }, timeoutMs)
  })
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer))
}

function writeAscii(view, offset, value) {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index))
  }
}

function encodeWav(chunks, sampleRate, sampleCount) {
  const buffer = new ArrayBuffer(44 + sampleCount * 2)
  const view = new DataView(buffer)
  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + sampleCount * 2, true)
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeAscii(view, 36, 'data')
  view.setUint32(40, sampleCount * 2, true)

  let offset = 44
  chunks.forEach((chunk) => {
    chunk.forEach((sample) => {
      const clamped = Math.max(-1, Math.min(1, sample))
      view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
      offset += 2
    })
  })
  return new Blob([view], { type: 'audio/wav' })
}

function errorKey(error) {
  if (error?.name === 'NotAllowedError' || error?.name === 'SecurityError') return 'voicePermissionDenied'
  if (error?.name === 'NotFoundError' || error?.name === 'DevicesNotFoundError') return 'voiceNoMicrophone'
  if (error instanceof ApiError) {
    if (error.code === 'speech_invalid') return 'voiceRecordingInvalid'
    if (error.code === 'speech_too_large') return 'voiceRecordingTooLarge'
    if (error.code === 'speech_unrecognized') return 'voiceNotUnderstood'
    if (error.code === 'speech_empty') return 'voiceNoSpeech'
    return 'voiceNetworkError'
  }
  return 'voiceRecordingError'
}

export function useAudioRecorder({ language, onTranscript }) {
  const [status, setStatus] = useState('idle')
  const [elapsed, setElapsed] = useState(0)
  const [messageKey, setMessageKey] = useState(null)
  const mountedRef = useRef(true)
  const activeRef = useRef(false)
  const streamRef = useRef(null)
  const contextRef = useRef(null)
  const sourceRef = useRef(null)
  const processorRef = useRef(null)
  const gainRef = useRef(null)
  const chunksRef = useRef([])
  const sampleCountRef = useRef(0)
  const sampleRateRef = useRef(48000)
  const languageRef = useRef(language)
  const intervalRef = useRef(null)
  const timeoutRef = useRef(null)
  const startedAtRef = useRef(0)
  const onTranscriptRef = useRef(onTranscript)
  const stopRef = useRef(null)

  useEffect(() => {
    onTranscriptRef.current = onTranscript
  }, [onTranscript])

  const releaseResources = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    intervalRef.current = null
    timeoutRef.current = null
    if (processorRef.current) processorRef.current.onaudioprocess = null
    processorRef.current?.disconnect()
    sourceRef.current?.disconnect()
    gainRef.current?.disconnect()
    streamRef.current?.getTracks().forEach((track) => track.stop())
    contextRef.current?.close().catch(() => {})
    processorRef.current = null
    sourceRef.current = null
    gainRef.current = null
    streamRef.current = null
    contextRef.current = null
  }, [])

  const stopRecording = useCallback(async ({ cancel = false } = {}) => {
    if (!activeRef.current) return
    setStatus(cancel ? 'idle' : 'processing')
    releaseResources()
    const chunks = chunksRef.current
    const sampleCount = sampleCountRef.current
    const sampleRate = sampleRateRef.current
    chunksRef.current = []
    sampleCountRef.current = 0

    if (cancel) {
      activeRef.current = false
      setElapsed(0)
      setMessageKey(null)
      return
    }
    if (sampleCount < sampleRate * MIN_RECORDING_SECONDS) {
      activeRef.current = false
      setStatus('error')
      setMessageKey('voiceTooShort')
      return
    }

    try {
      const wavBlob = encodeWav(chunks, sampleRate, sampleCount)
      const wavFile = new File([wavBlob], 'question.wav', { type: 'audio/wav' })
      const transcript = await transcribeAudio(wavFile, languageRef.current)
      if (!mountedRef.current) return
      onTranscriptRef.current(transcript)
      setStatus('success')
      setMessageKey('voiceTranscriptAdded')
    } catch (error) {
      if (!mountedRef.current) return
      setStatus('error')
      setMessageKey(errorKey(error))
    } finally {
      activeRef.current = false
      if (mountedRef.current) setElapsed(0)
    }
  }, [releaseResources])

  useEffect(() => {
    stopRef.current = stopRecording
  }, [stopRecording])

  const startRecording = useCallback(async () => {
    if (activeRef.current) return
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('error')
      setMessageKey('voiceUnsupported')
      return
    }
    activeRef.current = true
    languageRef.current = language
    setStatus('requesting')
    setMessageKey(null)
    setElapsed(0)
    chunksRef.current = []
    sampleCountRef.current = 0

    try {
      const initializationStartedAt = Date.now()
      devLog('mic request started')
      const streamPromise = navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      streamPromise.then((lateStream) => {
        if (!activeRef.current || !mountedRef.current) {
          lateStream.getTracks().forEach((track) => track.stop())
        }
      }).catch(() => {})
      const stream = await withTimeout(streamPromise, INITIALIZATION_TIMEOUT_MS)
      devLog('getUserMedia succeeded')
      devLog('stream tracks found', stream.getAudioTracks().length)
      streamRef.current = stream
      if (!mountedRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      const AudioContext = window.AudioContext || window.webkitAudioContext
      if (!AudioContext) throw new Error('AudioContext unavailable')
      const context = new AudioContext()
      contextRef.current = context
      devLog('AudioContext created')
      devLog('AudioContext state', context.state)
      if (context.state !== 'running') {
        const remainingTime = Math.max(
          1,
          INITIALIZATION_TIMEOUT_MS - (Date.now() - initializationStartedAt),
        )
        await withTimeout(context.resume(), remainingTime)
        devLog('AudioContext state after resume', context.state)
      }
      if (context.state !== 'running') {
        throw new Error(`AudioContext did not start (state: ${context.state})`)
      }
      const source = context.createMediaStreamSource(stream)
      const processor = context.createScriptProcessor(4096, 1, 1)
      const gain = context.createGain()
      gain.gain.value = 0
      processor.onaudioprocess = (event) => {
        if (!activeRef.current) return
        const chunk = new Float32Array(event.inputBuffer.getChannelData(0))
        chunksRef.current.push(chunk)
        sampleCountRef.current += chunk.length
      }
      source.connect(processor)
      processor.connect(gain)
      gain.connect(context.destination)
      sourceRef.current = source
      processorRef.current = processor
      gainRef.current = gain
      devLog('recorder initialized')
      sampleRateRef.current = context.sampleRate
      startedAtRef.current = Date.now()
      intervalRef.current = setInterval(() => {
        setElapsed(Math.min(MAX_RECORDING_SECONDS, Math.floor((Date.now() - startedAtRef.current) / 1000)))
      }, 250)
      timeoutRef.current = setTimeout(() => stopRef.current?.(), MAX_RECORDING_SECONDS * 1000)
      setStatus('recording')
      devLog('recording started')
    } catch (error) {
      devLog('caught initialization error', { name: error?.name, message: error?.message })
      releaseResources()
      activeRef.current = false
      setStatus('idle')
      setMessageKey(errorKey(error))
    }
  }, [language, releaseResources])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      activeRef.current = false
      releaseResources()
    }
  }, [releaseResources])

  return {
    status,
    elapsed,
    messageKey,
    startRecording,
    stopRecording: () => stopRecording(),
    cancelRecording: () => stopRecording({ cancel: true }),
    busy: ['requesting', 'recording', 'processing'].includes(status),
  }
}
