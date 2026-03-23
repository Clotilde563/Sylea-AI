// Page Agents Sylea.AI — Agent Sylea 1
import { useState, useEffect, useRef, useCallback } from 'react'
import { useT } from '../i18n/LanguageContext'
import { api } from '../api/client'
import { useDeviceContext } from '../contexts/DeviceContext'

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
}

// ── Storage keys ─────────────────────────────────────────────────────────────
const STORAGE_ACTIVE = 'sylea_agent1_active'
const STORAGE_MESSAGES = 'sylea_agent1_messages'
const STORAGE_VOICE_ENABLED = 'sylea_agent1_voice_enabled'

function loadActive(): boolean {
  try { return localStorage.getItem(STORAGE_ACTIVE) === 'true' } catch { return false }
}
function saveActive(v: boolean) {
  try { localStorage.setItem(STORAGE_ACTIVE, String(v)) } catch {}
}
function loadMessages(): AgentMessage[] {
  try {
    const raw = localStorage.getItem(STORAGE_MESSAGES)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}
function saveMessages(msgs: AgentMessage[]) {
  try { localStorage.setItem(STORAGE_MESSAGES, JSON.stringify(msgs)) } catch {}
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
  const frenchVoice = voices.find(v => v.lang.startsWith('fr') && v.name.includes('Google'))
    || voices.find(v => v.lang.startsWith('fr'))
  if (frenchVoice) utterance.voice = frenchVoice

  synth.speak(utterance)
}

// ── Main component ──────────────────────────────────────────────────────────
export default function AgentsPage() {
  const t = useT()
  const { ctx: deviceCtx } = useDeviceContext()
  const [active, setActive] = useState(loadActive)
  const [showActivateModal, setShowActivateModal] = useState(false)
  const [showDeactivateModal, setShowDeactivateModal] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [messages, setMessages] = useState<AgentMessage[]>(loadMessages)
  const [inputText, setInputText] = useState('')
  const [sending, setSending] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Voice states
  const [isRecording, setIsRecording] = useState(false)
  const [recordingTime, setRecordingTime] = useState(0)
  const [voiceEnabled, setVoiceEnabled] = useState(loadVoiceEnabled)
  const [speakingMsgIdx, setSpeakingMsgIdx] = useState<number | null>(null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const recordingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Persist messages
  useEffect(() => { saveMessages(messages) }, [messages])
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
  }

  const handleDeactivate = () => {
    setActive(false)
    setShowDeactivateModal(false)
    setChatOpen(false)
  }

  const openChat = () => {
    if (messages.length === 0) {
      setMessages([{
        role: 'agent',
        content: WELCOME_MESSAGE,
        timestamp: new Date().toISOString(),
        type: 'text',
      }])
    }
    setChatOpen(true)
  }

  // ── Send message (text or voice) ──────────────────────────────────────────
  const handleSend = useCallback(async (overrideText?: string, msgType: 'text' | 'voice' = 'text') => {
    const text = (overrideText ?? inputText).trim()
    if (!text || sending) return
    const userMsg: AgentMessage = {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
      type: msgType,
    }
    const updated = [...messages, userMsg]
    setMessages(updated)
    setInputText('')
    setSending(true)

    try {
      const chatHistory = updated.map(m => ({
        role: m.role === 'agent' ? 'assistant' : 'user',
        content: m.content,
      }))
      const res = await api.agentChat(chatHistory, deviceCtx ?? undefined)
      const agentMsg: AgentMessage = {
        role: 'agent',
        content: res.message,
        timestamp: new Date().toISOString(),
        type: 'text',
      }
      setMessages(prev => {
        const next = [...prev, agentMsg]
        // Auto-speak agent response if voice is enabled
        if (voiceEnabled) {
          speakMessage(res.message)
        }
        return next
      })
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

  // ── Voice recording (Speech-to-Text) ──────────────────────────────────────
  const startVoiceRecording = useCallback(() => {
    const SpeechRecognitionClass = getSpeechRecognitionClass()
    if (!SpeechRecognitionClass) {
      alert("Votre navigateur ne supporte pas la reconnaissance vocale")
      return
    }

    const recognition = new SpeechRecognitionClass()
    recognition.lang = 'fr-FR'
    recognition.continuous = false
    recognition.interimResults = false

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = event.results[0][0].transcript
      if (transcript.trim()) {
        handleSend(transcript, 'voice')
      }
    }

    recognition.onerror = () => {
      setIsRecording(false)
      setRecordingTime(0)
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current)
        recordingTimerRef.current = null
      }
    }

    recognition.onend = () => {
      setIsRecording(false)
      setRecordingTime(0)
      if (recordingTimerRef.current) {
        clearInterval(recordingTimerRef.current)
        recordingTimerRef.current = null
      }
    }

    recognitionRef.current = recognition
    recognition.start()
    setIsRecording(true)
    setRecordingTime(0)

    // Start recording timer
    recordingTimerRef.current = setInterval(() => {
      setRecordingTime(prev => prev + 1)
    }, 1000)
  }, [handleSend])

  const stopVoiceRecording = useCallback(() => {
    recognitionRef.current?.stop()
    setIsRecording(false)
    setRecordingTime(0)
    if (recordingTimerRef.current) {
      clearInterval(recordingTimerRef.current)
      recordingTimerRef.current = null
    }
  }, [])

  const toggleRecording = useCallback(() => {
    if (isRecording) {
      stopVoiceRecording()
    } else {
      startVoiceRecording()
    }
  }, [isRecording, startVoiceRecording, stopVoiceRecording])

  // ── Speak a specific message (TTS playback) ──────────────────────────────
  const handleSpeakMessage = useCallback((text: string, idx: number) => {
    if (!isTTSSupported()) return
    const synth = window.speechSynthesis

    if (speakingMsgIdx === idx && synth.speaking) {
      synth.cancel()
      setSpeakingMsgIdx(null)
      return
    }

    synth.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = 'fr-FR'
    utterance.rate = 1.0
    utterance.pitch = 1.0

    const voices = synth.getVoices()
    const frenchVoice = voices.find(v => v.lang.startsWith('fr') && v.name.includes('Google'))
      || voices.find(v => v.lang.startsWith('fr'))
    if (frenchVoice) utterance.voice = frenchVoice

    utterance.onend = () => setSpeakingMsgIdx(null)
    utterance.onerror = () => setSpeakingMsgIdx(null)

    setSpeakingMsgIdx(idx)
    synth.speak(utterance)
  }, [speakingMsgIdx])

  // Format recording time
  const formatRecordingTime = (seconds: number) => {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  const lastInteraction = messages.length > 0
    ? `Derniere interaction : ${relativeTime(messages[messages.length - 1].timestamp)}`
    : 'Aucune interaction'

  // ── Features list ───────────────────────────────────────────────────────────
  const features = [
    { icon: '\uD83D\uDCAC', text: t('agents.feature_messages') },
    { icon: '\uD83C\uDFA4', text: t('agents.feature_voice') },
    { icon: '\uD83E\uDDE0', text: t('agents.feature_learning') },
    { icon: '\uD83D\uDCCA', text: t('agents.feature_data') },
  ]

  // ── Chat view ──────────────────────────────────────────────────────────────
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
            <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'linear-gradient(135deg, #d4a017, #fbbf24)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 700, color: '#050810' }}>S</span>
            </div>
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
            {messages.map((msg, idx) => (
              <div key={idx} style={{
                display: 'flex',
                justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                animation: 'agent-msg-in 0.3s ease forwards',
              }}>
                <div style={{
                  maxWidth: '80%',
                  padding: '0.75rem 1rem',
                  borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                  background: msg.role === 'user'
                    ? 'linear-gradient(135deg, #6366f1, #8b5cf6)'
                    : 'rgba(255,255,255,0.06)',
                  borderLeft: msg.role === 'agent' ? '3px solid #f59e0b' : 'none',
                  color: 'var(--text-primary)',
                  fontSize: '0.88rem',
                  lineHeight: '1.55',
                  boxShadow: msg.role === 'user'
                    ? '0 2px 12px rgba(99,102,241,0.3)'
                    : '0 1px 8px rgba(0,0,0,0.25)',
                }}>
                  <p style={{ margin: 0 }}>{msg.content}</p>
                  <div style={{
                    margin: '0.35rem 0 0', fontSize: '0.65rem',
                    color: msg.role === 'user' ? 'rgba(255,255,255,0.5)' : 'var(--text-muted)',
                    display: 'flex', alignItems: 'center', gap: '0.4rem',
                    justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  }}>
                    {/* Microphone icon for voice messages */}
                    {msg.type === 'voice' && (
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.7 }}>
                        <rect x="9" y="1" width="6" height="11" rx="3" />
                        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                        <line x1="12" y1="19" x2="12" y2="23" />
                        <line x1="8" y1="23" x2="16" y2="23" />
                      </svg>
                    )}
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
            {/* Recording indicator */}
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

  // ── Card view ──────────────────────────────────────────────────────────────
  return (
    <div className="page animate-fade-in">
      <style>{`
        @keyframes agent-pulse-dot {
          0%, 100% { opacity: 1; box-shadow: 0 0 6px #4ade80; }
          50% { opacity: 0.5; box-shadow: 0 0 12px #4ade80; }
        }
        @keyframes agent-float {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-6px); }
        }
        @keyframes agent-glow {
          0%, 100% { filter: drop-shadow(0 0 8px rgba(245,158,11,0.3)); }
          50% { filter: drop-shadow(0 0 20px rgba(245,158,11,0.55)); }
        }
      `}</style>
      <div className="container page-content" style={{ maxWidth: 580, margin: '0 auto', padding: '2rem 1rem' }}>
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

        {/* Agent card */}
        <div style={{
          background: 'linear-gradient(135deg, rgba(245,158,11,0.06), rgba(251,191,36,0.02), var(--bg-surface))',
          border: '1px solid rgba(245,158,11,0.2)',
          borderRadius: 'var(--radius-lg)',
          padding: '2rem 1.5rem',
          boxShadow: '0 4px 32px rgba(245,158,11,0.08)',
          transition: 'all 0.3s',
        }}>
          {/* Logo + title */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: '1.5rem' }}>
            <div style={{ animation: 'agent-float 4s ease-in-out infinite, agent-glow 3s ease-in-out infinite', marginBottom: '1rem' }}>
              <AgentSyleaLogo size={100} />
            </div>
            <h3 style={{
              fontSize: '1.35rem', fontWeight: 700, marginBottom: '0.25rem',
              background: 'linear-gradient(135deg, #d4a017, #f59e0b, #fbbf24)',
              WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
            }}>
              Agent Sylea 1
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
              {t('agents.subtitle')}
            </p>

            {/* Status badge */}
            {active ? (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
                padding: '0.3rem 0.85rem', borderRadius: '999px', fontSize: '0.72rem',
                fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)',
                color: '#4ade80',
              }}>
                <span style={{
                  width: 7, height: 7, borderRadius: '50%', background: '#4ade80',
                  animation: 'agent-pulse-dot 2s ease-in-out infinite',
                }} />
                {t('agents.status_active')}
              </span>
            ) : (
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
                padding: '0.3rem 0.85rem', borderRadius: '999px', fontSize: '0.72rem',
                fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                color: 'var(--text-muted)',
              }}>
                {t('agents.status_inactive')}
              </span>
            )}
          </div>

          {/* Description */}
          <p style={{
            color: 'var(--text-secondary)', fontSize: '0.88rem', lineHeight: '1.6',
            textAlign: 'center', marginBottom: '1.5rem', maxWidth: 440, margin: '0 auto 1.5rem',
          }}>
            {t('agents.description')}
          </p>

          {/* Features */}
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.65rem',
            marginBottom: '1.75rem',
          }}>
            {features.map((f, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: '0.5rem',
                padding: '0.6rem 0.75rem', borderRadius: 'var(--radius-md)',
                background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)',
                transition: 'all 0.2s',
              }}>
                <span style={{ fontSize: '1.1rem', flexShrink: 0 }}>{f.icon}</span>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: '1.3' }}>{f.text}</span>
              </div>
            ))}
          </div>

          {/* Last interaction (only when active) */}
          {active && (
            <p style={{
              textAlign: 'center', fontSize: '0.75rem', color: 'var(--text-muted)',
              marginBottom: '1.25rem', fontStyle: 'italic',
            }}>
              {lastInteraction}
            </p>
          )}

          {/* Action buttons */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.75rem' }}>
            {active ? (
              <>
                <button
                  onClick={openChat}
                  style={{
                    width: '100%', padding: '0.85rem 1.5rem', borderRadius: 'var(--radius-md)',
                    border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem',
                    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                    color: '#fff', transition: 'all 0.2s',
                    boxShadow: '0 4px 16px rgba(99,102,241,0.35)',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 6px 24px rgba(99,102,241,0.5)' }}
                  onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 16px rgba(99,102,241,0.35)' }}
                >
                  {t('agents.btn_chat')}
                </button>
                <button
                  onClick={() => setShowDeactivateModal(true)}
                  style={{
                    background: 'transparent', border: 'none', cursor: 'pointer',
                    color: '#ef4444', fontSize: '0.78rem', padding: '0.4rem 0.75rem',
                    transition: 'opacity 0.15s', opacity: 0.7,
                  }}
                  onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                  onMouseLeave={e => e.currentTarget.style.opacity = '0.7'}
                >
                  {t('agents.btn_deactivate')}
                </button>
              </>
            ) : (
              <button
                onClick={() => setShowActivateModal(true)}
                style={{
                  width: '100%', padding: '0.85rem 1.5rem', borderRadius: 'var(--radius-md)',
                  border: 'none', cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem',
                  background: 'linear-gradient(135deg, #d4a017, #f59e0b, #fbbf24)',
                  color: '#050810', transition: 'all 0.2s',
                  boxShadow: '0 4px 16px rgba(245,158,11,0.35)',
                }}
                onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 6px 24px rgba(245,158,11,0.5)' }}
                onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 16px rgba(245,158,11,0.35)' }}
              >
                {t('agents.btn_activate')}
              </button>
            )}
          </div>
        </div>
      </div>

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
    </div>
  )
}
