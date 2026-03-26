// Page Agents Sylea.AI — Agent Sylea 1
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useT } from '../i18n/LanguageContext'
import { api } from '../api/client'
import { useDeviceContext } from '../contexts/DeviceContext'
import { useStore } from '../store/useStore'
import VoiceCall from '../components/VoiceCall'

// ── Gold variant of the Sylea logo SVG ──────────────────────────────────────
const CX = 190, CY = 170
const S_PATH = `M ${CX} ${CY-105} C ${CX+90} ${CY-105}, ${CX+90} ${CY-28}, ${CX} ${CY} C ${CX-90} ${CY+28}, ${CX-90} ${CY+105}, ${CX} ${CY+105}`

function AgentSyleaLogo({ size = 120 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id="agent-gold-g" x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%" stopColor="#d4a017" />
          <stop offset="40%" stopColor="#f59e0b" />
          <stop offset="100%" stopColor="#fbbf24" />
        </linearGradient>
        <filter id="agent-gold-blur">
          <feGaussianBlur stdDeviation="20" />
        </filter>
      </defs>
      {/* Halo */}
      <path d={S_PATH} stroke="url(#agent-gold-g)" strokeWidth="90" fill="none" strokeLinecap="round"
        style={{ filter: 'url(#agent-gold-blur)', opacity: 0.18 }} />
      {/* Outer border */}
      <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
      {/* Gold body */}
      <path d={S_PATH} stroke="url(#agent-gold-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
      {/* Inner hollow */}
      <path d={S_PATH} stroke="#050810" strokeWidth="18" fill="none" strokeLinecap="butt" />
      {/* Specular highlight */}
      <path d={S_PATH} stroke="rgba(255,230,150,0.5)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  )
}

// ── Types ────────────────────────────────────────────────────────────────────
interface AgentMessage {
  role: 'agent' | 'user'
  content: string
  timestamp: string
  type: 'text' | 'voice'
  audioUrl?: string  // blob URL for user recorded audio (legacy, ephemeral)
  audioData?: string  // base64 encoded audio (persisted server-side)
  choices?: string[]  // unused, kept for backward compat
}

// ── Storage keys ─────────────────────────────────────────────────────────────
const STORAGE_ACTIVE = 'sylea_agent1_active'
const STORAGE_VOICE_ENABLED = 'sylea_agent1_voice_enabled'

function loadActive(): boolean {
  try { return localStorage.getItem(STORAGE_ACTIVE) === 'true' } catch { return false }
}
function saveActive(v: boolean) {
  try { localStorage.setItem(STORAGE_ACTIVE, String(v)) } catch {}
}
function loadVoiceEnabled(): boolean {
  try { return localStorage.getItem(STORAGE_VOICE_ENABLED) === 'true' } catch { return false }
}
function saveVoiceEnabled(v: boolean) {
  try { localStorage.setItem(STORAGE_VOICE_ENABLED, String(v)) } catch {}
}

// ── Check browser support ───────────────────────────────────────────────────
function getSpeechRecognitionClass(): (new () => SpeechRecognition) | null {
  const w = window as any
  return w.SpeechRecognition || w.webkitSpeechRecognition || null
}

function isTTSSupported(): boolean {
  return 'speechSynthesis' in window
}

// ── Relative time helper ─────────────────────────────────────────────────────
function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return "a l'instant"
  if (mins < 60) return `il y a ${mins} minute${mins > 1 ? 's' : ''}`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `il y a ${hrs} heure${hrs > 1 ? 's' : ''}`
  const days = Math.floor(hrs / 24)
  return `il y a ${days} jour${days > 1 ? 's' : ''}`
}

const WELCOME_MESSAGE = "Bonjour ! Je suis votre Agent Sylea 1. Mon role est de vous accompagner au quotidien vers votre objectif. Comment allez-vous aujourd'hui ?"

// ── TTS helper ──────────────────────────────────────────────────────────────
function speakMessage(text: string) {
  if (!isTTSSupported()) return
  const synth = window.speechSynthesis
  synth.cancel()

  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'fr-FR'
  utterance.rate = 1.0
  utterance.pitch = 1.0

  const voices = synth.getVoices()
  // Priorite : voix les plus naturelles en francais
  const frenchVoice =
    // Microsoft Edge Neural voices (tres naturelles)
    voices.find(v => v.lang.startsWith('fr') && v.name.includes('Denise') && v.name.includes('Online'))
    || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Online') && v.name.includes('Natural'))
    || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Denise'))
    // Google voices (correctes)
    || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Google'))
    // Microsoft desktop voices
    || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Julie'))
    || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Hortense'))
    // N'importe quelle voix francaise
    || voices.find(v => v.lang.startsWith('fr'))
  if (frenchVoice) utterance.voice = frenchVoice
  // Rendre la voix plus naturelle
  utterance.rate = 0.95  // legerement plus lent = plus naturel
  utterance.pitch = 1.05 // legerement plus aigu = plus chaleureux

  synth.speak(utterance)
}

// ── Max recording duration ──────────────────────────────────────────────────
const MAX_RECORDING_SECONDS = 60

// ── Voice Message Bubble (Instagram-style waveform) ─────────────────────────
function VoiceMessageBubble({ msg, isAgent, onSpeakToggle, isSpeaking }: {
  msg: AgentMessage
  isAgent: boolean
  onSpeakToggle: () => void
  isSpeaking: boolean
}) {
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [loading, setLoading] = useState(false)
  const [showTranscript, setShowTranscript] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const audioBlobUrlRef = useRef<string | null>(null)

  // Generate consistent waveform from content
  const bars = useMemo(() => {
    const hash = msg.content.split('').reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0)
    return Array.from({ length: 28 }, (_, i) => {
      const seed = Math.abs(hash * (i + 1) * 2654435761) % 100
      return 0.2 + (seed / 100) * 0.8 // height between 0.2 and 1.0
    })
  }, [msg.content])

  const duration = Math.max(2, Math.ceil(msg.content.length / 15)) // rough estimate

  // Pre-cache TTS for agent voice messages (skip if audioData already available)
  useEffect(() => {
    if (isAgent && msg.type === 'voice' && !audioBlobUrlRef.current && !msg.audioData) {
      api.agentTTS(msg.content).then(blob => {
        if (blob) {
          audioBlobUrlRef.current = URL.createObjectURL(blob)
        }
      }).catch(() => {})
    }
  }, [msg.content, msg.type, isAgent, msg.audioData])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
      // Only revoke URLs we created (not user audioUrl which is managed by the parent)
      if (audioBlobUrlRef.current) {
        URL.revokeObjectURL(audioBlobUrlRef.current)
        audioBlobUrlRef.current = null
      }
    }
  }, [])

  const handlePlay = async () => {
    if (playing) {
      // Stop playing
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.currentTime = 0
      }
      window.speechSynthesis.cancel()
      setPlaying(false)
      setProgress(0)
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      return
    }

    setPlaying(true)

    // Play from base64 audioData if available (persisted across sessions)
    const audioSrc = msg.audioData
      ? `data:audio/mp3;base64,${msg.audioData}`
      : (!isAgent && msg.audioUrl) ? msg.audioUrl : null

    if (audioSrc) {
      try {
        const audio = new Audio(audioSrc)
        audioRef.current = audio

        audio.onended = () => {
          setPlaying(false)
          setProgress(0)
          if (intervalRef.current) clearInterval(intervalRef.current)
          intervalRef.current = null
        }

        audio.onerror = () => {
          setPlaying(false)
          setProgress(0)
          if (intervalRef.current) clearInterval(intervalRef.current)
          intervalRef.current = null
        }

        // Animate progress based on actual audio duration
        audio.onloadedmetadata = () => {
          const totalMs = audio.duration * 1000
          const startTime = Date.now()
          intervalRef.current = setInterval(() => {
            const elapsed = Date.now() - startTime
            setProgress(Math.min(1, elapsed / totalMs))
          }, 50)
        }

        await audio.play()
        return
      } catch {
        // Fall through to TTS fallback
      }
    }

    // For agent messages, use OpenAI TTS
    if (isAgent) {
      try {
        // Check if we already have cached audio
        if (!audioBlobUrlRef.current) {
          setLoading(true)
          const blob = await api.agentTTS(msg.content)
          setLoading(false)
          if (blob) {
            audioBlobUrlRef.current = URL.createObjectURL(blob)
          }
        }

        if (audioBlobUrlRef.current) {
          const audio = new Audio(audioBlobUrlRef.current)
          audioRef.current = audio

          audio.onended = () => {
            setPlaying(false)
            setProgress(0)
            if (intervalRef.current) clearInterval(intervalRef.current)
            intervalRef.current = null
          }

          audio.onerror = () => {
            setPlaying(false)
            setProgress(0)
            if (intervalRef.current) clearInterval(intervalRef.current)
            intervalRef.current = null
          }

          // Animate progress
          const startTime = Date.now()
          const totalMs = duration * 1000
          intervalRef.current = setInterval(() => {
            const elapsed = Date.now() - startTime
            setProgress(Math.min(1, elapsed / totalMs))
          }, 50)

          await audio.play()
          return
        }
      } catch {
        setLoading(false)
        // Fall through to browser TTS
      }
    }

    // Fallback: browser TTS
    const utterance = new SpeechSynthesisUtterance(msg.content)
    utterance.lang = 'fr-FR'
    utterance.rate = 1.0

    const voices = window.speechSynthesis.getVoices()
    const frenchVoice = voices.find(v => v.lang.startsWith('fr') && v.name.includes('Google'))
      || voices.find(v => v.lang.startsWith('fr'))
    if (frenchVoice) utterance.voice = frenchVoice

    // Animate progress
    const startTime = Date.now()
    const totalMs = duration * 1000
    intervalRef.current = setInterval(() => {
      const elapsed = Date.now() - startTime
      setProgress(Math.min(1, elapsed / totalMs))
    }, 50)

    utterance.onend = () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      intervalRef.current = null
      setPlaying(false)
      setProgress(0)
    }

    utterance.onerror = () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      intervalRef.current = null
      setPlaying(false)
      setProgress(0)
    }

    window.speechSynthesis.speak(utterance)
  }

  const barColor = isAgent ? '#f59e0b' : '#fbbf24'
  const barDimColor = isAgent ? 'rgba(245,158,11,0.25)' : 'rgba(251,191,36,0.25)'

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m}:${String(s).padStart(2, '0')}`
  }

  return (
    <div style={{
      maxWidth: '80%',
      padding: '0.75rem 1rem',
      borderRadius: isAgent ? '16px 16px 16px 4px' : '16px 16px 4px 16px',
      background: !isAgent
        ? 'linear-gradient(135deg, #d4a017, #f59e0b)'
        : 'rgba(255,255,255,0.06)',
      borderLeft: isAgent ? '3px solid #f59e0b' : 'none',
      boxShadow: !isAgent
        ? '0 2px 12px rgba(245,158,11,0.3)'
        : '0 1px 8px rgba(0,0,0,0.25)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        {/* Play/Pause button with loading spinner */}
        <button onClick={handlePlay} style={{
          width: 32, height: 32, borderRadius: '50%',
          background: barColor, border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0, transition: 'transform 0.1s',
        }}
          onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.08)'}
          onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
        >
          {loading ? (
            <span style={{
              width: 14, height: 14, border: '2px solid #050810',
              borderTopColor: 'transparent', borderRadius: '50%',
              display: 'inline-block',
              animation: 'spin 0.8s linear infinite',
            }} />
          ) : playing ? (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="#050810">
              <rect x="2" y="1" width="3" height="10" rx="1" />
              <rect x="7" y="1" width="3" height="10" rx="1" />
            </svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 12 12" fill="#050810">
              <polygon points="2,0 12,6 2,12" />
            </svg>
          )}
        </button>

        {/* Waveform */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '2px', height: 28, flex: 1 }}>
          {bars.map((h, i) => {
            const barProgress = i / bars.length
            const isPlayed = playing && barProgress <= progress
            return (
              <div key={i} style={{
                width: 3, borderRadius: '1.5px',
                height: `${h * 100}%`,
                background: isPlayed || !playing ? barColor : barDimColor,
                transition: 'background 0.1s',
              }} />
            )
          })}
        </div>

        {/* Duration */}
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', flexShrink: 0, minWidth: 28, textAlign: 'right' }}>
          {playing ? formatTime(progress * duration) : formatTime(duration)}
        </span>
      </div>

      {/* Transcript toggle — for BOTH user and agent voice messages */}
      <button
        onClick={() => setShowTranscript(!showTranscript)}
        style={{
          margin: '0.4rem 0 0', padding: '0.15rem 0.5rem', borderRadius: '999px',
          background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)',
          color: 'rgba(255,255,255,0.55)', cursor: 'pointer',
          fontSize: '0.65rem', fontWeight: 500, transition: 'all 0.15s',
          display: 'inline-block',
        }}
        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.14)'; e.currentTarget.style.color = 'rgba(255,255,255,0.8)' }}
        onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.08)'; e.currentTarget.style.color = 'rgba(255,255,255,0.55)' }}
      >
        {showTranscript ? 'Masquer la transcription' : 'Afficher la transcription'}
      </button>
      {showTranscript && (
        <p style={{
          margin: '0.3rem 0 0', fontSize: '0.75rem',
          color: 'rgba(255,255,255,0.6)', fontStyle: 'italic', lineHeight: 1.4,
        }}>
          {msg.content}
        </p>
      )}

      {/* Timestamp + speaker icon */}
      <div style={{
        margin: '0.35rem 0 0', fontSize: '0.65rem',
        color: !isAgent ? 'rgba(255,255,255,0.5)' : 'var(--text-muted)',
        display: 'flex', alignItems: 'center', gap: '0.4rem',
        justifyContent: !isAgent ? 'flex-end' : 'flex-start',
      }}>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.7 }}>
          <rect x="9" y="1" width="6" height="11" rx="3" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
        <span>{new Date(msg.timestamp).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span>
      </div>
    </div>
  )
}

// ── Main component ──────────────────────────────────────────────────────────
export default function AgentsPage() {
  const t = useT()
  const { ctx: deviceCtx } = useDeviceContext()
  const [active, setActive] = useState(loadActive)
  const [showActivateModal, setShowActivateModal] = useState(false)
  const [showDeactivateModal, setShowDeactivateModal] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [inputText, setInputText] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Voice call state (Agent 2)
  const [inCall, setInCall] = useState(false)

  // OpenAI TTS cache for speaker button on text messages
  const ttsAudioCacheRef = useRef<Map<number, string>>(new Map())
  const ttsSpeakingAudioRef = useRef<HTMLAudioElement | null>(null)

  // Voice states
  const [isRecording, setIsRecording] = useState(false)
  const [recordingTime, setRecordingTime] = useState(0)
  const [voiceEnabled, setVoiceEnabled] = useState(loadVoiceEnabled)
  const [speakingMsgIdx, setSpeakingMsgIdx] = useState<number | null>(null)
  const [lastUserMsgWasVoice, setLastUserMsgWasVoice] = useState(false)
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // MediaRecorder refs for real audio capture
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const pendingAudioUrlRef = useRef<string | null>(null)
  const pendingAudioBase64Ref = useRef<string>('')
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const maxRecordingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Store transcript from SpeechRecognition while recording
  const pendingTranscriptRef = useRef<string>('')

  // Persist active & voice settings
  useEffect(() => { saveActive(active) }, [active])
  useEffect(() => { saveVoiceEnabled(voiceEnabled) }, [voiceEnabled])

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, chatOpen])

  // Focus input when chat opens
  useEffect(() => {
    if (chatOpen) inputRef.current?.focus()
  }, [chatOpen])

  // Cleanup recording on unmount
  useEffect(() => {
    return () => {
      recognitionRef.current?.abort()
      if (recordingTimerRef.current) clearInterval(recordingTimerRef.current)
      if (maxRecordingTimerRef.current) clearTimeout(maxRecordingTimerRef.current)
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop()
      }
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach(t => t.stop())
      }
    }
  }, [])

  // Preload voices for TTS
  useEffect(() => {
    if (isTTSSupported()) {
      window.speechSynthesis.getVoices()
      window.speechSynthesis.onvoiceschanged = () => { window.speechSynthesis.getVoices() }
    }
  }, [])

  const handleActivate = () => {
    setActive(true)
    setShowActivateModal(false)
    // Demander la permission de notifications des l'activation
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }

  const handleDeactivate = () => {
    setActive(false)
    setShowDeactivateModal(false)
    setChatOpen(false)
  }

  // ── Fetch messages from server on chat open ─────────────────────────────
  const openChat = useCallback(async () => {
    setChatOpen(true)
    setLoadingMessages(true)
    // Clear unread notification dot
    useStore.getState().clearUnreadAgentMessages()
    try {
      const serverMessages = await api.getAgentMessages()
      if (serverMessages && serverMessages.length > 0) {
        setMessages(serverMessages.map(m => ({
          role: m.role as 'agent' | 'user',
          content: m.content,
          timestamp: m.created_at,
          type: (m.type || 'text') as 'text' | 'voice',
          audioData: (m as any).audioData || undefined,
        })))
      } else {
        // No server messages — show welcome
        setMessages([{
          role: 'agent',
          content: WELCOME_MESSAGE,
          timestamp: new Date().toISOString(),
          type: 'text',
        }])
      }
    } catch {
      // Fallback: if API fails (no auth), show welcome
      if (messages.length === 0) {
        setMessages([{
          role: 'agent',
          content: WELCOME_MESSAGE,
          timestamp: new Date().toISOString(),
          type: 'text',
        }])
      }
    } finally {
      setLoadingMessages(false)
    }
  }, [messages.length])

  // ── Send message (text or voice) ──────────────────────────────────────────
  const handleSend = useCallback(async (overrideText?: string, msgType: 'text' | 'voice' = 'text', audioUrl?: string, audioBase64?: string) => {
    const text = (overrideText ?? inputText).trim()
    if (!text || sending) return
    const userMsg: AgentMessage = {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
      type: msgType,
      audioUrl: audioUrl || undefined,
      audioData: audioBase64 || undefined,
    }
    const updated = [...messages, userMsg]
    setMessages(updated)
    setInputText('')
    setSending(true)
    setLastUserMsgWasVoice(msgType === 'voice')

    try {
      const chatHistory = updated.map(m => ({
        role: m.role === 'agent' ? 'assistant' : 'user',
        content: m.content,
        type: m.type,
      }))
      const res = await api.agentChat(chatHistory, deviceCtx ?? undefined, msgType === 'voice' ? audioBase64 : undefined)
      // If user sent voice, agent responds as voice (waveform only, no text)
      const agentResponseType = msgType === 'voice' ? 'voice' : 'text'
      const agentMsg: AgentMessage = {
        role: 'agent',
        content: res.message,
        timestamp: new Date().toISOString(),
        type: agentResponseType,
        choices: res.choices || undefined,
        audioData: res.audioData || undefined,
      }
      setMessages(prev => [...prev, agentMsg])
    } catch {
      const errMsg: AgentMessage = {
        role: 'agent',
        content: "Desole, une erreur est survenue. Reessayez dans un instant.",
        timestamp: new Date().toISOString(),
        type: 'text',
      }
      setMessages(prev => [...prev, errMsg])
    } finally {
      setSending(false)
    }
  }, [inputText, sending, messages, voiceEnabled, deviceCtx])

  // ── Voice recording (MediaRecorder for audio + SpeechRecognition for transcript) ──
  const stopVoiceRecording = useCallback(() => {
    // Stop SpeechRecognition
    if (recognitionRef.current) {
      try { recognitionRef.current.stop() } catch {}
      recognitionRef.current = null
    }

    // Stop MediaRecorder — this triggers onstop which resolves the audio blob
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }

    // Stop media stream tracks
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => t.stop())
      mediaStreamRef.current = null
    }

    setIsRecording(false)
    setRecordingTime(0)
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current)
      recordingTimerRef.current = null
    }
    if (maxRecordingTimerRef.current) {
      clearTimeout(maxRecordingTimerRef.current)
      maxRecordingTimerRef.current = null
    }
  }, [])

  const startVoiceRecording = useCallback(() => {
    const SpeechRecognitionClass = getSpeechRecognitionClass()
    if (!SpeechRecognitionClass) {
      alert("Votre navigateur ne supporte pas la reconnaissance vocale")
      return
    }

    // Reset pending data
    pendingAudioUrlRef.current = null
    pendingAudioBase64Ref.current = ''
    pendingTranscriptRef.current = ''

    // 1. Start MediaRecorder for actual audio capture
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
      mediaStreamRef.current = stream

      // Determine best supported mimeType
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : undefined

      const mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      const chunks: Blob[] = []

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }

      mediaRecorder.onstop = () => {
        const blobType = mimeType || 'audio/webm'
        const blob = new Blob(chunks, { type: blobType })
        const url = URL.createObjectURL(blob)
        pendingAudioUrlRef.current = url

        // Convert blob to base64 for server-side persistence
        const reader = new FileReader()
        reader.onload = () => {
          const base64 = (reader.result as string).split(',')[1] || ''
          pendingAudioBase64Ref.current = base64

          // Try to send — if transcript is ready, send now
          // If not, a timeout will check again
          const trySend = (attempts: number) => {
            const transcript = pendingTranscriptRef.current.trim()
            if (transcript) {
              handleSend(transcript, 'voice', url, base64)
            } else if (attempts < 20) {
              // Wait 200ms and retry (max 4 seconds)
              setTimeout(() => trySend(attempts + 1), 200)
            } else {
              // Fallback: send with generic message if no transcript after 4s
              handleSend('[Message vocal]', 'voice', url, base64)
            }
          }
          trySend(0)
        }
        reader.readAsDataURL(blob)
      }

      mediaRecorderRef.current = mediaRecorder
      mediaRecorder.start()

      // 2. Start SpeechRecognition for transcript
      const recognition = new SpeechRecognitionClass()
      recognition.lang = 'fr-FR'
      recognition.continuous = true     // Don't stop after first result
      recognition.interimResults = false

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        // Accumulate all final results
        let fullTranscript = ''
        for (let i = 0; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            fullTranscript += event.results[i][0].transcript + ' '
          }
        }
        pendingTranscriptRef.current = fullTranscript.trim()
      }

      recognition.onerror = () => {
        // Don't auto-stop on error — user clicks stop button
      }

      // Don't auto-stop on recognition end — only stop when user clicks or 60s max
      recognition.onend = () => {
        // SpeechRecognition may auto-end on silence; restart if still recording
        if (isRecording && recognitionRef.current) {
          try { recognitionRef.current.start() } catch {}
        }
      }

      recognitionRef.current = recognition
      recognition.start()
      setIsRecording(true)
      setRecordingTime(0)

      // Start recording timer (counts up)
      recordingTimerRef.current = setInterval(() => {
        setRecordingTime(prev => {
          const next = prev + 1
          // Auto-stop after 60 seconds
          if (next >= MAX_RECORDING_SECONDS) {
            stopVoiceRecording()
          }
          return next
        })
      }, 1000)

      // Safety: max 60 second hard timeout
      maxRecordingTimerRef.current = setTimeout(() => {
        stopVoiceRecording()
      }, MAX_RECORDING_SECONDS * 1000)

    }).catch(() => {
      alert("Impossible d'acceder au microphone. Verifiez les permissions de votre navigateur.")
    })
  }, [handleSend, stopVoiceRecording, isRecording])

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      // User clicked stop — stop everything, the onstop handler will send the message
      // First grab transcript before stopping recognition
      stopVoiceRecording()
    } else {
      startVoiceRecording()
    }
  }, [isRecording, startVoiceRecording, stopVoiceRecording])

  // ── Speak a specific message (TTS playback) ──────────────────────────────
  const handleSpeakMessage = useCallback(async (text: string, idx: number) => {
    // Stop current playback if clicking same message
    if (speakingMsgIdx === idx) {
      if (ttsSpeakingAudioRef.current) {
        ttsSpeakingAudioRef.current.pause()
        ttsSpeakingAudioRef.current.currentTime = 0
        ttsSpeakingAudioRef.current = null
      }
      window.speechSynthesis.cancel()
      setSpeakingMsgIdx(null)
      return
    }

    // Stop any previous playback
    if (ttsSpeakingAudioRef.current) {
      ttsSpeakingAudioRef.current.pause()
      ttsSpeakingAudioRef.current.currentTime = 0
      ttsSpeakingAudioRef.current = null
    }
    window.speechSynthesis.cancel()

    // For agent messages, try OpenAI TTS first
    const isAgentMsg = messages[idx]?.role === 'agent'
    if (isAgentMsg) {
      try {
        let blobUrl = ttsAudioCacheRef.current.get(idx)
        if (!blobUrl) {
          const blob = await api.agentTTS(text)
          if (blob) {
            blobUrl = URL.createObjectURL(blob)
            ttsAudioCacheRef.current.set(idx, blobUrl)
          }
        }
        if (blobUrl) {
          const audio = new Audio(blobUrl)
          ttsSpeakingAudioRef.current = audio
          audio.onended = () => { setSpeakingMsgIdx(null); ttsSpeakingAudioRef.current = null }
          audio.onerror = () => { setSpeakingMsgIdx(null); ttsSpeakingAudioRef.current = null }
          setSpeakingMsgIdx(idx)
          await audio.play()
          return
        }
      } catch {
        // Fall through to browser TTS
      }
    }

    // Fallback: browser TTS
    if (!isTTSSupported()) return
    const synth = window.speechSynthesis
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = 'fr-FR'

    const voices = synth.getVoices()
    const frenchVoice =
      voices.find(v => v.lang.startsWith('fr') && v.name.includes('Denise') && v.name.includes('Online'))
      || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Online') && v.name.includes('Natural'))
      || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Denise'))
      || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Google'))
      || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Julie'))
      || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Hortense'))
      || voices.find(v => v.lang.startsWith('fr'))
    if (frenchVoice) utterance.voice = frenchVoice
    utterance.rate = 0.95
    utterance.pitch = 1.05

    utterance.onend = () => setSpeakingMsgIdx(null)
    utterance.onerror = () => setSpeakingMsgIdx(null)

    setSpeakingMsgIdx(idx)
    synth.speak(utterance)
  }, [speakingMsgIdx, messages])

  // ── QCM click handler ──────────────────────────────────────────────────
  const handleQCMClick = useCallback((choice: string) => {
    handleSend(choice, 'text')
  }, [handleSend])

  // Format recording time with countdown
  const formatRecordingTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    const maxM = Math.floor(MAX_RECORDING_SECONDS / 60)
    const maxS = MAX_RECORDING_SECONDS % 60
    return `${m}:${s.toString().padStart(2, '0')} / ${maxM}:${maxS.toString().padStart(2, '0')}`
  }

  const lastInteraction = messages.length > 0
    ? `Derniere interaction : ${relativeTime(messages[messages.length - 1].timestamp)}`
    : 'Aucune interaction'

  // ── Agent 2 chat endpoint for voice call ───────────────────────────────────
  const agent2ChatEndpoint = useCallback(async (msgs: Array<{ role: string; content: string }>) => {
    // Use the same agent chat API — the voice call sends conversation history
    const chatHistory = msgs.map(m => ({
      role: m.role === 'assistant' ? 'assistant' : 'user',
      content: m.content,
      type: 'text' as const,
    }))
    return api.agentChat(chatHistory, deviceCtx ?? undefined)
  }, [deviceCtx])

  const handleVoiceCallMessage = useCallback((userText: string, agentText: string) => {
    // Messages from voice call are saved via the chat endpoint already
    // This callback can be used to update local state if needed
    void userText
    void agentText
  }, [])

  // ── Agent 2 state ──────────────────────────────────────────────────────────
  const STORAGE_ACTIVE_2 = 'sylea_agent2_active'
  const loadActive2 = () => { try { return localStorage.getItem(STORAGE_ACTIVE_2) === 'true' } catch { return false } }
  const saveActive2 = (v: boolean) => { try { localStorage.setItem(STORAGE_ACTIVE_2, String(v)) } catch {} }

  const [active2, setActive2] = useState(loadActive2)
  const [showActivateModal2, setShowActivateModal2] = useState(false)
  const [showDeactivateModal2, setShowDeactivateModal2] = useState(false)
  const [chat2Open, setChat2Open] = useState(false)
  const [messages2, setMessages2] = useState<AgentMessage[]>([])
  const [inputText2, setInputText2] = useState('')
  const [sending2, setSending2] = useState(false)
  const [loadingMessages2, setLoadingMessages2] = useState(false)
  const messagesEndRef2 = useRef<HTMLDivElement>(null)
  const inputRef2 = useRef<HTMLInputElement>(null)
  const [actionToast, setActionToast] = useState<string | null>(null)

  useEffect(() => { saveActive2(active2) }, [active2])
  useEffect(() => {
    messagesEndRef2.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages2, chat2Open])
  useEffect(() => {
    if (chat2Open) inputRef2.current?.focus()
  }, [chat2Open])

  // Reminder checker
  useEffect(() => {
    if (!active2) return
    const checkReminders = setInterval(async () => {
      try {
        const reminders = await api.agent2GetReminders()
        const now = new Date()
        reminders.forEach(r => {
          const reminderTime = new Date(`${r.date}T${r.time}`)
          if (Math.abs(now.getTime() - reminderTime.getTime()) < 60000 && !r.completed) {
            if ('Notification' in window && Notification.permission === 'granted') {
              new Notification('Agent Sylea 2 - Rappel', { body: r.message })
            }
            api.agent2CompleteReminder(r.id)
          }
        })
      } catch { /* silent */ }
    }, 30000)
    return () => clearInterval(checkReminders)
  }, [active2])

  const handleActivate2 = () => {
    setActive2(true)
    setShowActivateModal2(false)
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }
  const handleDeactivate2 = () => {
    setActive2(false)
    setShowDeactivateModal2(false)
    setChat2Open(false)
  }

  const WELCOME_MESSAGE_2 = "Salut ! Je suis ton Agent Sylea 2. Je peux envoyer des mails, rediger des textes, creer des rappels et bien plus. Qu'est-ce que je peux faire pour toi ?"

  const openChat2 = useCallback(async () => {
    setChat2Open(true)
    setLoadingMessages2(true)
    try {
      const serverMessages = await api.getAgent2Messages()
      if (serverMessages && serverMessages.length > 0) {
        setMessages2(serverMessages.map(m => ({
          role: m.role as 'agent' | 'user',
          content: m.content,
          timestamp: m.created_at,
          type: (m.type || 'text') as 'text' | 'voice',
          audioData: (m as any).audioData || undefined,
        })))
      } else {
        setMessages2([{
          role: 'agent', content: WELCOME_MESSAGE_2,
          timestamp: new Date().toISOString(), type: 'text',
        }])
      }
    } catch {
      if (messages2.length === 0) {
        setMessages2([{
          role: 'agent', content: WELCOME_MESSAGE_2,
          timestamp: new Date().toISOString(), type: 'text',
        }])
      }
    } finally {
      setLoadingMessages2(false)
    }
  }, [messages2.length])

  // ── Action parsing & handling ────────────────────────────────────────────
  interface AgentAction {
    type: 'EMAIL' | 'TEXT' | 'REMINDER' | 'LINK' | 'COPY'
    data: Record<string, string>
  }

  const parseActions = (content: string): { text: string; actions: AgentAction[] } => {
    const actions: AgentAction[] = []
    let text = content
    const regex = /\[ACTION:(EMAIL|TEXT|REMINDER|LINK|COPY)\]([\s\S]*?)\[\/ACTION\]/g
    let match
    while ((match = regex.exec(content)) !== null) {
      try {
        const data = JSON.parse(match[2])
        actions.push({ type: match[1] as AgentAction['type'], data })
      } catch { /* skip malformed */ }
      text = text.replace(match[0], '')
    }
    return { text: text.trim(), actions }
  }

  const handleAction = async (action: AgentAction) => {
    switch (action.type) {
      case 'EMAIL': {
        try {
          const res = await api.agent2SendEmail(action.data.to, action.data.subject, action.data.body)
          setActionToast(res.ok ? 'Email envoye avec succes !' : `Erreur : ${res.error || 'Envoi echoue'}`)
        } catch { setActionToast("Erreur lors de l'envoi") }
        setTimeout(() => setActionToast(null), 3000)
        break
      }
      case 'TEXT': {
        const blob = new Blob([action.data.content], { type: 'text/plain;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `${action.data.title || 'document'}.txt`; a.click()
        URL.revokeObjectURL(url)
        setActionToast('Fichier telecharge !')
        setTimeout(() => setActionToast(null), 3000)
        break
      }
      case 'REMINDER': {
        try {
          await api.agent2CreateReminder(action.data.time, action.data.date, action.data.message)
          setActionToast('Rappel cree !')
        } catch { setActionToast('Erreur lors de la creation du rappel') }
        setTimeout(() => setActionToast(null), 3000)
        break
      }
      case 'LINK':
        window.open(action.data.url, '_blank')
        break
      case 'COPY':
        try {
          await navigator.clipboard.writeText(action.data.text)
          setActionToast('Copie dans le presse-papier !')
        } catch { setActionToast('Erreur de copie') }
        setTimeout(() => setActionToast(null), 3000)
        break
    }
  }

  const handleSend2 = useCallback(async (overrideText?: string) => {
    const text = (overrideText ?? inputText2).trim()
    if (!text || sending2) return
    const userMsg: AgentMessage = {
      role: 'user', content: text,
      timestamp: new Date().toISOString(), type: 'text',
    }
    const updated = [...messages2, userMsg]
    setMessages2(updated)
    setInputText2('')
    setSending2(true)
    try {
      const chatHistory = updated.map(m => ({
        role: m.role === 'agent' ? 'assistant' : 'user',
        content: m.content, type: m.type,
      }))
      const res = await api.agent2Chat(chatHistory, deviceCtx ?? undefined)
      setMessages2(prev => [...prev, {
        role: 'agent', content: res.message,
        timestamp: new Date().toISOString(), type: 'text',
        audioData: res.audioData || undefined,
      }])
    } catch {
      setMessages2(prev => [...prev, {
        role: 'agent', content: "Desole, une erreur est survenue. Reessayez dans un instant.",
        timestamp: new Date().toISOString(), type: 'text',
      }])
    } finally { setSending2(false) }
  }, [inputText2, sending2, messages2, deviceCtx])

  const lastInteraction2 = messages2.length > 0
    ? `Derniere interaction : ${relativeTime(messages2[messages2.length - 1].timestamp)}`
    : 'Aucune interaction'

  // ── Future agents placeholder data ─────────────────────────────────────────
  const futureAgents = [
    { name: 'Agent Sylea 3', subtitle: 'Executant de taches', desc: 'Toutes taches sur instruction' },
    { name: 'Super Agent Sylea', subtitle: 'Cerveau autonome 24/7', desc: 'Agit pour vous pendant que vous dormez' },
  ]

  // ── Agent 2 Chat view ────────────────────────────────────────────────────
  if (chat2Open) {
    return (
      <div className="page animate-fade-in">
        <style>{`
          @keyframes agent-msg-in {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
          }
          @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
          @keyframes toast-in {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
          }
        `}</style>
        <div className="container page-content" style={{ maxWidth: 680, margin: '0 auto', padding: '0', display: 'flex', flexDirection: 'column', height: 'calc(100vh - 3.5rem - 3rem)' }}>
          {/* Chat header */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '0.75rem',
            padding: '1rem 1.25rem',
            borderBottom: '1px solid var(--border)',
            background: 'rgba(3,7,15,0.6)',
            backdropFilter: 'blur(12px)',
          }}>
            <button onClick={() => setChat2Open(false)} style={{
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: '0.9rem', padding: '0.25rem 0.5rem',
              borderRadius: '6px', transition: 'all 0.15s',
            }}
              onMouseEnter={e => e.currentTarget.style.color = '#f87171'}
              onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
            >
              {'\u2190'} Retour
            </button>
            <svg width={24} height={24} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
              <defs>
                <linearGradient id="agent2-chat-g" x1="50%" y1="100%" x2="50%" y2="0%">
                  <stop offset="0%" stopColor="#b91c1c" />
                  <stop offset="40%" stopColor="#ef4444" />
                  <stop offset="100%" stopColor="#f87171" />
                </linearGradient>
              </defs>
              <path d={S_PATH} stroke="url(#agent2-chat-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
              <path d={S_PATH} stroke="#050810" strokeWidth="18" fill="none" strokeLinecap="butt" />
            </svg>
            <div style={{ flex: 1 }}>
              <p style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-primary)', lineHeight: 1.2 }}>Agent Sylea 2</p>
              <p style={{ fontSize: '0.7rem', color: '#4ade80', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#4ade80', display: 'inline-block' }} />
                {t('agents.status_active')}
              </p>
            </div>
          </div>

          {/* Messages area */}
          <div style={{
            flex: 1, overflowY: 'auto', padding: '1rem 1.25rem',
            display: 'flex', flexDirection: 'column', gap: '0.75rem',
          }}>
            {loadingMessages2 && (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
                <span className="spinner spinner-sm" />
              </div>
            )}
            {messages2.map((msg, idx) => {
              const { text: msgText, actions } = msg.role === 'agent' ? parseActions(msg.content) : { text: msg.content, actions: [] }
              return (
                <div key={idx} style={{
                  display: 'flex',
                  justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  animation: 'agent-msg-in 0.3s ease forwards',
                }}>
                  <div style={{ maxWidth: '80%' }}>
                    {msgText && (
                      <div style={{
                        padding: '0.75rem 1rem',
                        borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                        background: msg.role === 'user'
                          ? 'linear-gradient(135deg, #b91c1c, #ef4444)'
                          : 'rgba(255,255,255,0.06)',
                        borderLeft: msg.role === 'agent' ? '3px solid #ef4444' : 'none',
                        color: 'var(--text-primary)',
                        fontSize: '0.88rem', lineHeight: '1.55',
                        boxShadow: msg.role === 'user'
                          ? '0 2px 12px rgba(239,68,68,0.3)'
                          : '0 1px 8px rgba(0,0,0,0.25)',
                      }}>
                        <p style={{ margin: 0 }}>{msgText}</p>
                        <div style={{
                          margin: '0.35rem 0 0', fontSize: '0.65rem',
                          color: msg.role === 'user' ? 'rgba(255,255,255,0.5)' : 'var(--text-muted)',
                          textAlign: msg.role === 'user' ? 'right' : 'left',
                        }}>
                          {new Date(msg.timestamp).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    )}
                    {/* Action cards */}
                    {actions.map((action, ai) => (
                      <div key={ai} style={{
                        marginTop: '0.5rem', padding: '0.75rem',
                        borderRadius: '12px',
                        background: 'rgba(239,68,68,0.06)',
                        border: '1px solid rgba(239,68,68,0.2)',
                      }}>
                        {action.type === 'EMAIL' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#f87171', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                              Email
                            </div>
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: '0 0 0.15rem' }}>
                              <strong>A :</strong> {action.data.to}
                            </p>
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: '0 0 0.15rem' }}>
                              <strong>Objet :</strong> {action.data.subject}
                            </p>
                            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0 0 0.5rem', lineHeight: 1.4, maxHeight: '4rem', overflow: 'hidden' }}>
                              {action.data.body?.substring(0, 200)}...
                            </p>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                              <button onClick={() => handleAction(action)} style={{
                                padding: '0.4rem 1rem', borderRadius: '8px', border: 'none',
                                background: '#22c55e', color: '#fff', fontSize: '0.78rem',
                                fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
                              }}>
                                Envoyer
                              </button>
                              <button onClick={() => {
                                try { navigator.clipboard.writeText(action.data.body) } catch {}
                                setActionToast('Corps du mail copie !')
                                setTimeout(() => setActionToast(null), 3000)
                              }} style={{
                                padding: '0.4rem 1rem', borderRadius: '8px',
                                background: 'rgba(255,255,255,0.08)', border: '1px solid var(--border)',
                                color: 'var(--text-muted)', fontSize: '0.78rem',
                                fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
                              }}>
                                Copier
                              </button>
                            </div>
                          </>
                        )}
                        {action.type === 'TEXT' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#f87171', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                              Document : {action.data.title}
                            </div>
                            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0 0 0.5rem', lineHeight: 1.4, maxHeight: '4rem', overflow: 'hidden' }}>
                              {action.data.content?.substring(0, 200)}...
                            </p>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                              <button onClick={() => handleAction(action)} style={{
                                padding: '0.4rem 1rem', borderRadius: '8px', border: 'none',
                                background: 'linear-gradient(135deg, #b91c1c, #ef4444)', color: '#fff',
                                fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer',
                              }}>
                                Telecharger
                              </button>
                              <button onClick={() => handleAction({ type: 'COPY', data: { text: action.data.content } })} style={{
                                padding: '0.4rem 1rem', borderRadius: '8px',
                                background: 'rgba(255,255,255,0.08)', border: '1px solid var(--border)',
                                color: 'var(--text-muted)', fontSize: '0.78rem',
                                fontWeight: 600, cursor: 'pointer',
                              }}>
                                Copier
                              </button>
                            </div>
                          </>
                        )}
                        {action.type === 'REMINDER' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#f87171', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                              Rappel
                            </div>
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: '0 0 0.5rem' }}>
                              {action.data.date} a {action.data.time} - {action.data.message}
                            </p>
                            <button onClick={() => handleAction(action)} style={{
                              padding: '0.4rem 1rem', borderRadius: '8px', border: 'none',
                              background: '#22c55e', color: '#fff', fontSize: '0.78rem',
                              fontWeight: 600, cursor: 'pointer',
                            }}>
                              Confirmer le rappel
                            </button>
                          </>
                        )}
                        {action.type === 'LINK' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#f87171', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                              Lien
                            </div>
                            <button onClick={() => handleAction(action)} style={{
                              padding: '0.4rem 1rem', borderRadius: '8px', border: 'none',
                              background: 'linear-gradient(135deg, #2563eb, #3b82f6)', color: '#fff',
                              fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer',
                              display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                            }}>
                              Ouvrir : {action.data.label || action.data.url}
                            </button>
                          </>
                        )}
                        {action.type === 'COPY' && (
                          <button onClick={() => handleAction(action)} style={{
                            padding: '0.4rem 1rem', borderRadius: '8px', border: 'none',
                            background: 'rgba(255,255,255,0.08)', color: 'var(--text-secondary)',
                            fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer',
                            border: '1px solid var(--border)',
                          }}>
                            Copier dans le presse-papier
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
            {sending2 && (
              <div style={{ display: 'flex', justifyContent: 'flex-start', animation: 'agent-msg-in 0.3s ease forwards' }}>
                <div style={{
                  padding: '0.75rem 1.25rem', borderRadius: '16px 16px 16px 4px',
                  background: 'rgba(255,255,255,0.06)', borderLeft: '3px solid #ef4444',
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                }}>
                  <span className="spinner spinner-sm" />
                  <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>{t('agents.thinking')}</span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef2} />
          </div>

          {/* Input bar */}
          <div style={{
            padding: '0.75rem 1.25rem', borderTop: '1px solid var(--border)',
            background: 'rgba(3,7,15,0.6)', backdropFilter: 'blur(12px)',
            display: 'flex', alignItems: 'center', gap: '0.5rem',
          }}>
            <input
              ref={inputRef2}
              type="text"
              value={inputText2}
              onChange={e => setInputText2(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend2() } }}
              placeholder="Demande-moi quelque chose..."
              style={{
                flex: 1, background: 'rgba(255,255,255,0.06)',
                border: '1px solid var(--border)',
                borderRadius: '24px', padding: '0.65rem 1rem', color: 'var(--text-primary)',
                fontSize: '0.88rem', outline: 'none', transition: 'all 0.2s',
              }}
              onFocus={e => e.currentTarget.style.borderColor = 'rgba(239,68,68,0.5)'}
              onBlur={e => e.currentTarget.style.borderColor = 'var(--border)'}
            />
            <button
              onClick={() => handleSend2()}
              disabled={!inputText2.trim() || sending2}
              style={{
                width: 40, height: 40, borderRadius: '50%', border: 'none',
                background: inputText2.trim() && !sending2
                  ? 'linear-gradient(135deg, #b91c1c, #ef4444)'
                  : 'rgba(255,255,255,0.06)',
                color: inputText2.trim() && !sending2 ? '#fff' : 'var(--text-muted)',
                cursor: inputText2.trim() && !sending2 ? 'pointer' : 'not-allowed',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.2s', flexShrink: 0,
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>

        {/* Action toast */}
        {actionToast && (
          <div style={{
            position: 'fixed', bottom: '5rem', left: '50%', transform: 'translateX(-50%)',
            padding: '0.6rem 1.5rem', borderRadius: '999px', zIndex: 2000,
            background: 'rgba(34,197,94,0.9)', color: '#fff', fontSize: '0.85rem',
            fontWeight: 600, animation: 'toast-in 0.2s ease', boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
          }}>
            {actionToast}
          </div>
        )}
      </div>
    )
  }

  // ── Agent 1 Chat view ──────────────────────────────────────────────────
  if (chatOpen) {
    return (
      <div className="page animate-fade-in">
        <style>{`
          @keyframes agent-msg-in {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
          }
          @keyframes recording-pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
            50% { box-shadow: 0 0 0 12px rgba(239, 68, 68, 0); }
          }
          @keyframes recording-dot-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
          }
          @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
        `}</style>
        <div className="container page-content" style={{ maxWidth: 680, margin: '0 auto', padding: '0', display: 'flex', flexDirection: 'column', height: 'calc(100vh - 3.5rem - 3rem)' }}>
          {/* Chat header */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '0.75rem',
            padding: '1rem 1.25rem',
            borderBottom: '1px solid var(--border)',
            background: 'rgba(3,7,15,0.6)',
            backdropFilter: 'blur(12px)',
          }}>
            <button onClick={() => setChatOpen(false)} style={{
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: '0.9rem', padding: '0.25rem 0.5rem',
              borderRadius: '6px', transition: 'all 0.15s',
            }}
              onMouseEnter={e => e.currentTarget.style.color = '#fbbf24'}
              onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
            >
              {'\u2190'} Retour
            </button>
            <AgentSyleaLogo size={24} />
            <div style={{ flex: 1 }}>
              <p style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-primary)', lineHeight: 1.2 }}>Agent Sylea 1</p>
              <p style={{ fontSize: '0.7rem', color: '#4ade80', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#4ade80', display: 'inline-block' }} />
                {t('agents.status_active')}
              </p>
            </div>

            {/* Voice auto-play toggle */}
            {isTTSSupported() && (
              <button
                onClick={() => setVoiceEnabled(v => !v)}
                title={voiceEnabled ? 'Desactiver la voix automatique' : 'Activer la voix automatique'}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.35rem',
                  padding: '0.3rem 0.65rem', borderRadius: '999px',
                  border: voiceEnabled ? '1px solid rgba(245,158,11,0.4)' : '1px solid var(--border)',
                  background: voiceEnabled ? 'rgba(245,158,11,0.12)' : 'rgba(255,255,255,0.04)',
                  color: voiceEnabled ? '#fbbf24' : 'var(--text-muted)',
                  cursor: 'pointer', fontSize: '0.72rem', fontWeight: 600,
                  transition: 'all 0.2s',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                  {voiceEnabled ? (
                    <>
                      <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
                      <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                    </>
                  ) : (
                    <line x1="23" y1="9" x2="17" y2="15" />
                  )}
                </svg>
                Voix
              </button>
            )}
          </div>

          {/* Messages area */}
          <div style={{
            flex: 1, overflowY: 'auto', padding: '1rem 1.25rem',
            display: 'flex', flexDirection: 'column', gap: '0.75rem',
          }}>
            {loadingMessages && (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
                <span className="spinner spinner-sm" />
              </div>
            )}
            {messages.map((msg, idx) => (
              <div key={idx} style={{
                display: 'flex',
                justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                animation: 'agent-msg-in 0.3s ease forwards',
              }}>
                {/* Use VoiceMessageBubble for voice messages */}
                {msg.type === 'voice' ? (
                  <VoiceMessageBubble
                    msg={msg}
                    isAgent={msg.role === 'agent'}
                    onSpeakToggle={() => handleSpeakMessage(msg.content, idx)}
                    isSpeaking={speakingMsgIdx === idx}
                  />
                ) : (
                  <div style={{ maxWidth: '80%' }}>
                    <div style={{
                      padding: '0.75rem 1rem',
                      borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                      background: msg.role === 'user'
                        ? 'linear-gradient(135deg, #d4a017, #f59e0b)'
                        : 'rgba(255,255,255,0.06)',
                      borderLeft: msg.role === 'agent' ? '3px solid #f59e0b' : 'none',
                      color: 'var(--text-primary)',
                      fontSize: '0.88rem',
                      lineHeight: '1.55',
                      boxShadow: msg.role === 'user'
                        ? '0 2px 12px rgba(245,158,11,0.3)'
                        : '0 1px 8px rgba(0,0,0,0.25)',
                    }}>
                      <p style={{ margin: 0 }}>{msg.content}</p>
                      <div style={{
                        margin: '0.35rem 0 0', fontSize: '0.65rem',
                        color: msg.role === 'user' ? 'rgba(255,255,255,0.5)' : 'var(--text-muted)',
                        display: 'flex', alignItems: 'center', gap: '0.4rem',
                        justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                      }}>
                        <span>{new Date(msg.timestamp).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}</span>
                        {/* Speaker button for agent messages */}
                        {msg.role === 'agent' && isTTSSupported() && (
                          <button
                            onClick={() => handleSpeakMessage(msg.content, idx)}
                            title="Ecouter ce message"
                            style={{
                              background: 'none', border: 'none', cursor: 'pointer',
                              padding: '2px', display: 'flex', alignItems: 'center',
                              color: speakingMsgIdx === idx ? '#fbbf24' : 'inherit',
                              opacity: speakingMsgIdx === idx ? 1 : 0.6,
                              transition: 'all 0.15s',
                            }}
                            onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                            onMouseLeave={e => { if (speakingMsgIdx !== idx) e.currentTarget.style.opacity = '0.6' }}
                          >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                              <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                              <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                            </svg>
                          </button>
                        )}
                      </div>
                    </div>
                    {/* QCM supprimé — réponses trop imprécises */}
                  </div>
                )}
              </div>
            ))}
            {sending && (
              <div style={{ display: 'flex', justifyContent: 'flex-start', animation: 'agent-msg-in 0.3s ease forwards' }}>
                <div style={{
                  padding: '0.75rem 1.25rem', borderRadius: '16px 16px 16px 4px',
                  background: 'rgba(255,255,255,0.06)', borderLeft: '3px solid #f59e0b',
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                }}>
                  <span className="spinner spinner-sm" />
                  <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>{t('agents.thinking')}</span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input bar */}
          <div style={{
            padding: '0.75rem 1.25rem', borderTop: '1px solid var(--border)',
            background: 'rgba(3,7,15,0.6)', backdropFilter: 'blur(12px)',
            display: 'flex', alignItems: 'center', gap: '0.5rem',
            position: 'relative',
          }}>
            {/* Recording indicator with countdown */}
            {isRecording && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '0.4rem',
                padding: '0.3rem 0.6rem', borderRadius: '999px',
                background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.3)',
                position: 'absolute', top: '-2.5rem', left: '50%', transform: 'translateX(-50%)',
                zIndex: 10,
              }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%', background: '#ef4444',
                  animation: 'recording-dot-pulse 1s ease-in-out infinite',
                }} />
                <span style={{ fontSize: '0.72rem', color: '#ef4444', fontWeight: 600 }}>
                  Enregistrement... {formatRecordingTime(recordingTime)}
                </span>
              </div>
            )}

            <input
              ref={inputRef}
              type="text"
              value={inputText}
              onChange={e => setInputText(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
              placeholder={isRecording ? 'Parlez maintenant...' : t('agents.input_placeholder')}
              disabled={isRecording}
              style={{
                flex: 1, background: isRecording ? 'rgba(239,68,68,0.06)' : 'rgba(255,255,255,0.06)',
                border: isRecording ? '1px solid rgba(239,68,68,0.3)' : '1px solid var(--border)',
                borderRadius: '24px', padding: '0.65rem 1rem', color: 'var(--text-primary)',
                fontSize: '0.88rem', outline: 'none', transition: 'all 0.2s',
              }}
              onFocus={e => { if (!isRecording) e.currentTarget.style.borderColor = 'rgba(245,158,11,0.5)' }}
              onBlur={e => { if (!isRecording) e.currentTarget.style.borderColor = 'var(--border)' }}
            />

            {/* Microphone button */}
            <button
              onClick={toggleRecording}
              disabled={sending}
              title={isRecording ? "Arreter l'enregistrement" : "Enregistrement vocal"}
              style={{
                width: 40, height: 40, borderRadius: '50%', border: 'none',
                background: isRecording ? 'rgba(239,68,68,0.2)' : 'rgba(255,255,255,0.06)',
                color: isRecording ? '#ef4444' : 'var(--text-muted)',
                cursor: sending ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.15s', flexShrink: 0,
                animation: isRecording ? 'recording-pulse 1.5s ease-in-out infinite' : 'none',
              }}
              onMouseEnter={e => {
                if (!isRecording) {
                  e.currentTarget.style.background = 'rgba(245,158,11,0.15)'
                  e.currentTarget.style.color = '#fbbf24'
                }
              }}
              onMouseLeave={e => {
                if (!isRecording) {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.06)'
                  e.currentTarget.style.color = 'var(--text-muted)'
                }
              }}
            >
              {isRecording ? (
                /* Stop icon (square) */
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="4" y="4" width="16" height="16" rx="2" />
                </svg>
              ) : (
                /* Microphone icon */
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="1" width="6" height="11" rx="3" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" y1="19" x2="12" y2="23" />
                  <line x1="8" y1="23" x2="16" y2="23" />
                </svg>
              )}
            </button>

            {/* Send button */}
            <button
              onClick={() => handleSend()}
              disabled={!inputText.trim() || sending}
              style={{
                width: 40, height: 40, borderRadius: '50%', border: 'none',
                background: inputText.trim() && !sending
                  ? 'linear-gradient(135deg, #d4a017, #f59e0b)'
                  : 'rgba(255,255,255,0.06)',
                color: inputText.trim() && !sending ? '#050810' : 'var(--text-muted)',
                cursor: inputText.trim() && !sending ? 'pointer' : 'not-allowed',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.2s', flexShrink: 0,
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ── Grey logo for locked agents ────────────────────────────────────────────
  function GreyAgentLogo({ size = 48 }: { size?: number }) {
    return (
      <svg width={size} height={size} viewBox="0 0 380 380" style={{ overflow: 'visible', opacity: 0.4 }}>
        <path d={S_PATH} stroke="#6b7280" strokeWidth="46" fill="none" strokeLinecap="round" />
        <path d={S_PATH} stroke="#1f2937" strokeWidth="18" fill="none" strokeLinecap="butt" />
      </svg>
    )
  }

  // ── Card view ──────────────────────────────────────────────────────────────
  return (
    <div className="page animate-fade-in">
      <style>{`
        @keyframes agent-pulse-dot {
          0%, 100% { opacity: 1; box-shadow: 0 0 6px #4ade80; }
          50% { opacity: 0.5; box-shadow: 0 0 12px #4ade80; }
        }
      `}</style>
      <div className="container page-content" style={{ maxWidth: 680, margin: '0 auto', padding: '2rem 1rem' }}>
        {/* Page header */}
        <div style={{ textAlign: 'center', marginBottom: '1.5rem' }}>
          <h2 style={{
            fontSize: '1.4rem', fontWeight: 800, marginBottom: '0.35rem',
            background: 'linear-gradient(90deg, #3b82f6, #8b5cf6, #ef4444, #f59e0b)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
          }}>
            {t('nav.agents')}
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            {t('agents.page_subtitle')}
          </p>
        </div>

        {/* Agent 1 — horizontal card */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: '1rem',
          background: active
            ? 'linear-gradient(135deg, rgba(245,158,11,0.08), rgba(251,191,36,0.03), var(--bg-surface))'
            : 'var(--bg-surface)',
          border: active ? '1px solid rgba(245,158,11,0.3)' : '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          padding: '1rem 1.25rem',
          boxShadow: active ? '0 2px 20px rgba(245,158,11,0.1)' : '0 1px 8px rgba(0,0,0,0.15)',
          transition: 'all 0.3s',
          marginBottom: '0.75rem',
        }}>
          {/* Logo */}
          <div style={{ flexShrink: 0 }}>
            <AgentSyleaLogo size={48} />
          </div>

          {/* Text center */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.15rem' }}>
              <h3 style={{
                fontSize: '1rem', fontWeight: 700, margin: 0,
                background: 'linear-gradient(135deg, #d4a017, #f59e0b, #fbbf24)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
              }}>
                Agent Sylea 1
              </h3>
            </div>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', margin: '0 0 0.25rem', lineHeight: 1.3 }}>
              Votre compagnon personnel
            </p>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
              Votre assistant personnel dedie a votre objectif de vie. Il apprend a vous connaitre
              pour affiner chaque analyse et vous aider a prendre les meilleures decisions.
            </p>
            {active && (
              <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', margin: '0.2rem 0 0', fontStyle: 'italic', opacity: 0.7 }}>
                {lastInteraction}
              </p>
            )}
          </div>

          {/* Status + buttons right */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.4rem', flexShrink: 0 }}>
            {/* Status badge */}
            {active ? (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                padding: '0.2rem 0.6rem', borderRadius: '999px', fontSize: '0.65rem',
                fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)',
                color: '#4ade80', whiteSpace: 'nowrap',
              }}>
                <span style={{
                  width: 6, height: 6, borderRadius: '50%', background: '#4ade80',
                  animation: 'agent-pulse-dot 2s ease-in-out infinite',
                }} />
                ACTIF
              </span>
            ) : (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                padding: '0.2rem 0.6rem', borderRadius: '999px', fontSize: '0.65rem',
                fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                color: 'var(--text-muted)', whiteSpace: 'nowrap',
              }}>
                INACTIF
              </span>
            )}

            {/* Action buttons */}
            {active ? (
              <>
                <button
                  onClick={openChat}
                  style={{
                    padding: '0.55rem 1.4rem', borderRadius: 'var(--radius-md)',
                    border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.85rem',
                    background: 'linear-gradient(135deg, #d4a017, #f59e0b, #fbbf24)',
                    color: '#050810', transition: 'all 0.2s', whiteSpace: 'nowrap',
                    boxShadow: '0 2px 10px rgba(245,158,11,0.3)',
                  }}
                  onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-1px)'}
                  onMouseLeave={e => e.currentTarget.style.transform = 'translateY(0)'}
                >
                  Discuter avec mon agent
                </button>
                <button
                  onClick={() => setShowDeactivateModal(true)}
                  style={{
                    background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
                    borderRadius: 'var(--radius-md)', cursor: 'pointer',
                    color: '#ef4444', fontSize: '0.78rem', fontWeight: 600,
                    padding: '0.4rem 1rem',
                    transition: 'all 0.15s', whiteSpace: 'nowrap',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.15)'; e.currentTarget.style.borderColor = 'rgba(239,68,68,0.4)' }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.08)'; e.currentTarget.style.borderColor = 'rgba(239,68,68,0.2)' }}
                >
                  Desactiver cet agent
                </button>
              </>
            ) : (
              <button
                onClick={() => setShowActivateModal(true)}
                style={{
                  padding: '0.55rem 1.4rem', borderRadius: 'var(--radius-md)',
                  border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.85rem',
                  background: 'linear-gradient(135deg, #d4a017, #f59e0b, #fbbf24)',
                  color: '#050810', transition: 'all 0.2s', whiteSpace: 'nowrap',
                  boxShadow: '0 2px 10px rgba(245,158,11,0.3)',
                }}
                onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-1px)'}
                onMouseLeave={e => e.currentTarget.style.transform = 'translateY(0)'}
              >
                Activer cet agent
              </button>
            )}
          </div>
        </div>

        {/* Agent 2 — horizontal card */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: '1rem',
          background: active2
            ? 'linear-gradient(135deg, rgba(239,68,68,0.08), rgba(248,113,113,0.03), var(--bg-surface))'
            : 'var(--bg-surface)',
          border: active2 ? '1px solid rgba(239,68,68,0.3)' : '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          padding: '1rem 1.25rem',
          boxShadow: active2 ? '0 2px 20px rgba(239,68,68,0.1)' : '0 1px 8px rgba(0,0,0,0.15)',
          transition: 'all 0.3s',
          marginBottom: '0.75rem',
        }}>
          {/* Logo */}
          <div style={{ flexShrink: 0 }}>
            <svg width={48} height={48} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
              <defs>
                <linearGradient id="agent2-red-g" x1="50%" y1="100%" x2="50%" y2="0%">
                  <stop offset="0%" stopColor="#b91c1c" />
                  <stop offset="40%" stopColor="#ef4444" />
                  <stop offset="100%" stopColor="#f87171" />
                </linearGradient>
                <filter id="agent2-red-blur">
                  <feGaussianBlur stdDeviation="20" />
                </filter>
              </defs>
              <path d={S_PATH} stroke="url(#agent2-red-g)" strokeWidth="90" fill="none" strokeLinecap="round"
                style={{ filter: 'url(#agent2-red-blur)', opacity: 0.18 }} />
              <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
              <path d={S_PATH} stroke="url(#agent2-red-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
              <path d={S_PATH} stroke="#050810" strokeWidth="18" fill="none" strokeLinecap="butt" />
              <path d={S_PATH} stroke="rgba(255,150,150,0.5)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
            </svg>
          </div>

          {/* Text center */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 style={{
              fontSize: '1rem', fontWeight: 700, margin: '0 0 0.15rem',
              background: 'linear-gradient(135deg, #b91c1c, #ef4444, #f87171)',
              WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            }}>
              Agent Sylea 2
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', margin: '0 0 0.25rem', lineHeight: 1.3 }}>
              Votre assistant personnel
            </p>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
              Envoi de mails, redaction de textes, rappels et notifications, appel vocal.
            </p>
            {active2 && (
              <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', margin: '0.2rem 0 0', fontStyle: 'italic', opacity: 0.7 }}>
                {lastInteraction2}
              </p>
            )}
          </div>

          {/* Status + buttons right */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.4rem', flexShrink: 0 }}>
            {active2 ? (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                padding: '0.2rem 0.6rem', borderRadius: '999px', fontSize: '0.65rem',
                fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)',
                color: '#4ade80', whiteSpace: 'nowrap',
              }}>
                <span style={{
                  width: 6, height: 6, borderRadius: '50%', background: '#4ade80',
                  animation: 'agent-pulse-dot 2s ease-in-out infinite',
                }} />
                ACTIF
              </span>
            ) : (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                padding: '0.2rem 0.6rem', borderRadius: '999px', fontSize: '0.65rem',
                fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase',
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                color: 'var(--text-muted)', whiteSpace: 'nowrap',
              }}>
                INACTIF
              </span>
            )}

            {active2 ? (
              <>
                <div style={{ display: 'flex', gap: '0.4rem' }}>
                  <button
                    onClick={openChat2}
                    style={{
                      padding: '0.55rem 1rem', borderRadius: 'var(--radius-md)',
                      border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.82rem',
                      background: 'linear-gradient(135deg, #b91c1c, #ef4444, #f87171)',
                      color: '#fff', transition: 'all 0.2s', whiteSpace: 'nowrap',
                      boxShadow: '0 2px 10px rgba(239,68,68,0.3)',
                    }}
                    onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-1px)'}
                    onMouseLeave={e => e.currentTarget.style.transform = 'translateY(0)'}
                  >
                    Discuter
                  </button>
                  <button
                    onClick={() => setInCall(true)}
                    style={{
                      padding: '0.55rem 0.8rem', borderRadius: 'var(--radius-md)',
                      border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.82rem',
                      background: 'linear-gradient(135deg, #b91c1c, #ef4444)',
                      color: '#fff', transition: 'all 0.2s', whiteSpace: 'nowrap',
                      boxShadow: '0 2px 10px rgba(239,68,68,0.3)',
                      display: 'flex', alignItems: 'center', gap: '0.3rem',
                    }}
                    onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-1px)'}
                    onMouseLeave={e => e.currentTarget.style.transform = 'translateY(0)'}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2z" />
                    </svg>
                    Appeler
                  </button>
                </div>
                <button
                  onClick={() => setShowDeactivateModal2(true)}
                  style={{
                    background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
                    borderRadius: 'var(--radius-md)', cursor: 'pointer',
                    color: '#ef4444', fontSize: '0.78rem', fontWeight: 600,
                    padding: '0.4rem 1rem',
                    transition: 'all 0.15s', whiteSpace: 'nowrap',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.15)'; e.currentTarget.style.borderColor = 'rgba(239,68,68,0.4)' }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.08)'; e.currentTarget.style.borderColor = 'rgba(239,68,68,0.2)' }}
                >
                  Desactiver cet agent
                </button>
              </>
            ) : (
              <button
                onClick={() => setShowActivateModal2(true)}
                style={{
                  padding: '0.55rem 1.4rem', borderRadius: 'var(--radius-md)',
                  border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.85rem',
                  background: 'linear-gradient(135deg, #b91c1c, #ef4444, #f87171)',
                  color: '#fff', transition: 'all 0.2s', whiteSpace: 'nowrap',
                  boxShadow: '0 2px 10px rgba(239,68,68,0.3)',
                }}
                onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-1px)'}
                onMouseLeave={e => e.currentTarget.style.transform = 'translateY(0)'}
              >
                Activer cet agent
              </button>
            )}
          </div>
        </div>

        {/* Future agent placeholder cards */}
        {futureAgents.map((agent, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: '1rem',
            background: 'var(--bg-surface)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 'var(--radius-lg)',
            padding: '1rem 1.25rem',
            marginBottom: '0.75rem',
            opacity: 0.45,
          }}>
            {/* Grey logo */}
            <div style={{ flexShrink: 0 }}>
              <GreyAgentLogo size={48} />
            </div>

            {/* Text */}
            <div style={{ flex: 1, minWidth: 0 }}>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, margin: '0 0 0.15rem', color: 'var(--text-secondary)' }}>
                {agent.name}
              </h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', margin: '0 0 0.1rem', lineHeight: 1.3 }}>
                {agent.subtitle}
              </p>
              <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.3 }}>
                {agent.desc}
              </p>
            </div>

            {/* Locked badge */}
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
              padding: '0.2rem 0.6rem', borderRadius: '999px', fontSize: '0.6rem',
              fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase',
              background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
              color: 'var(--text-muted)', whiteSpace: 'nowrap', flexShrink: 0,
            }}>
              {'\uD83D\uDD12'} BIENTOT DISPONIBLE
            </span>
          </div>
        ))}
      </div>

      {/* ── Voice Call overlay (Agent 2) ── */}
      {inCall && (
        <VoiceCall
          onEndCall={() => setInCall(false)}
          onMessage={handleVoiceCallMessage}
          agentColor="#ef4444"
          agentName="Agent Sylea 2"
          chatEndpoint={agent2ChatEndpoint}
        />
      )}

      {/* ── Activation modal ── */}
      {showActivateModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          animation: 'fadeInScale 0.2s ease',
        }}
          onClick={() => setShowActivateModal(false)}
        >
          <div style={{
            background: 'var(--bg-card)', border: '1px solid rgba(245,158,11,0.25)',
            borderRadius: 'var(--radius-lg)', padding: '2rem', maxWidth: 420, width: '90%',
            boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fbbf24', marginBottom: '0.75rem' }}>
              {t('agents.modal_activate_title')}
            </h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: '1.5rem' }}>
              {t('agents.modal_activate_text')}
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowActivateModal(false)} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border)',
                color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.85rem',
                transition: 'all 0.15s',
              }}>
                {t('common.annuler')}
              </button>
              <button onClick={handleActivate} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: 'linear-gradient(135deg, #d4a017, #f59e0b)', border: 'none',
                color: '#050810', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600,
                transition: 'all 0.15s',
              }}>
                {t('agents.modal_activate_confirm')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Deactivation modal ── */}
      {showDeactivateModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          animation: 'fadeInScale 0.2s ease',
        }}
          onClick={() => setShowDeactivateModal(false)}
        >
          <div style={{
            background: 'var(--bg-card)', border: '1px solid rgba(239,68,68,0.25)',
            borderRadius: 'var(--radius-lg)', padding: '2rem', maxWidth: 420, width: '90%',
            boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#ef4444', marginBottom: '0.75rem' }}>
              {t('agents.modal_deactivate_title')}
            </h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: '1.5rem' }}>
              {t('agents.modal_deactivate_text')}
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowDeactivateModal(false)} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border)',
                color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.85rem',
                transition: 'all 0.15s',
              }}>
                {t('common.annuler')}
              </button>
              <button onClick={handleDeactivate} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: '#ef4444', border: 'none',
                color: '#fff', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600,
                transition: 'all 0.15s',
              }}>
                {t('agents.modal_deactivate_confirm')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Agent 2 Activation modal ── */}
      {showActivateModal2 && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          animation: 'fadeInScale 0.2s ease',
        }}
          onClick={() => setShowActivateModal2(false)}
        >
          <div style={{
            background: 'var(--bg-card)', border: '1px solid rgba(239,68,68,0.25)',
            borderRadius: 'var(--radius-lg)', padding: '2rem', maxWidth: 420, width: '90%',
            boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#f87171', marginBottom: '0.75rem' }}>
              Activer l'Agent Sylea 2
            </h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: '1.5rem' }}>
              L'Agent Sylea 2 est votre assistant personnel capable d'agir : envoi de mails, redaction de textes,
              rappels et notifications. Il apprend a vous connaitre pour agir en votre nom.
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowActivateModal2(false)} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border)',
                color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.85rem',
                transition: 'all 0.15s',
              }}>
                {t('common.annuler')}
              </button>
              <button onClick={handleActivate2} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: 'linear-gradient(135deg, #b91c1c, #ef4444)', border: 'none',
                color: '#fff', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600,
                transition: 'all 0.15s',
              }}>
                Activer
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Agent 2 Deactivation modal ── */}
      {showDeactivateModal2 && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          animation: 'fadeInScale 0.2s ease',
        }}
          onClick={() => setShowDeactivateModal2(false)}
        >
          <div style={{
            background: 'var(--bg-card)', border: '1px solid rgba(239,68,68,0.25)',
            borderRadius: 'var(--radius-lg)', padding: '2rem', maxWidth: 420, width: '90%',
            boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#ef4444', marginBottom: '0.75rem' }}>
              Desactiver l'Agent Sylea 2
            </h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: '1.5rem' }}>
              Votre Agent Sylea 2 sera mis en pause. Il ne pourra plus envoyer de mails,
              creer des rappels ou rediger des textes pour vous.
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowDeactivateModal2(false)} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border)',
                color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.85rem',
                transition: 'all 0.15s',
              }}>
                {t('common.annuler')}
              </button>
              <button onClick={handleDeactivate2} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: '#ef4444', border: 'none',
                color: '#fff', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600,
                transition: 'all 0.15s',
              }}>
                Desactiver
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Action toast for Agent 2 */}
      {actionToast && (
        <div style={{
          position: 'fixed', bottom: '5rem', left: '50%', transform: 'translateX(-50%)',
          padding: '0.6rem 1.5rem', borderRadius: '999px', zIndex: 2000,
          background: 'rgba(34,197,94,0.9)', color: '#fff', fontSize: '0.85rem',
          fontWeight: 600, boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
        }}>
          {actionToast}
        </div>
      )}
    </div>
  )
}
