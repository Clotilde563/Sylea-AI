// Page Agents Sylea.AI — Agent Sylea 1
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useT } from '../i18n/LanguageContext'
import { api } from '../api/client'
import { useDeviceContext } from '../contexts/DeviceContext'
import { useStore } from '../store/useStore'

// Agent 2 feature flag — set to true when desktop version is ready
const AGENT2_ENABLED = true

// VoiceCall is only used by Agent 2 — import kept but component only rendered when AGENT2_ENABLED is true
import VoiceCall from '../components/VoiceCall'

// ── Gold variant of the Sylea logo SVG ──────────────────────────────────────
const CX = 190, CY = 170
const S_PATH = `M ${CX} ${CY-105} C ${CX+90} ${CY-105}, ${CX+90} ${CY-28}, ${CX} ${CY} C ${CX-90} ${CY+28}, ${CX-90} ${CY+105}, ${CX} ${CY+105}`

function AgentSyleaLogo({ size = 120 }: { size?: number }) {
  const uid = 'agent-logo'
  return (
    <svg width={size} height={size} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id={`${uid}-gold-g`} x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%" stopColor="#d4a017" />
          <stop offset="40%" stopColor="#f59e0b" />
          <stop offset="100%" stopColor="#fbbf24" />
        </linearGradient>
        <filter id={`${uid}-blur`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="20" />
        </filter>
        {/* Mask to create the hollow tube effect without opaque background colors */}
        <mask id={`${uid}-tube-mask`}>
          <path d={S_PATH} stroke="white" strokeWidth="46" fill="none" strokeLinecap="round" />
          <path d={S_PATH} stroke="black" strokeWidth="18" fill="none" strokeLinecap="butt" />
        </mask>
      </defs>
      {/* Halo */}
      <path d={S_PATH} stroke={`url(#${uid}-gold-g)`} strokeWidth="90" fill="none" strokeLinecap="round"
        style={{ filter: `url(#${uid}-blur)`, opacity: 0.18 }} />
      {/* Gold tube body with hollow center via mask */}
      <path d={S_PATH} stroke={`url(#${uid}-gold-g)`} strokeWidth="46" fill="none" strokeLinecap="round"
        mask={`url(#${uid}-tube-mask)`} />
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
  actions?: Array<{ type: string; data: Record<string, string> }>  // parsed actions from backend
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

// ── Markdown-light renderer ─────────────────────────────────────────────────
// Converts markdown-ish text (links, bold, tables, headers, lists, hr) to React elements
function renderFormattedText(text: string) {
  if (!text) return null
  const lines = text.split('\n')
  const elements: React.ReactNode[] = []
  let tableRows: string[][] = []
  let inTable = false

  const flushTable = () => {
    if (tableRows.length === 0) return
    // First row = header, skip separator row (---|---), rest = body
    const header = tableRows[0]
    const body = tableRows.filter((_, i) => i > 0 && !/^[\s|:-]+$/.test(tableRows[i].join('|')))
    elements.push(
      <div key={`tbl-${elements.length}`} style={{ overflowX: 'auto', margin: '0.5rem 0' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem', lineHeight: '1.45' }}>
          <thead>
            <tr>
              {header.map((cell, ci) => (
                <th key={ci} style={{
                  padding: '0.35rem 0.5rem', borderBottom: '2px solid rgba(255,255,255,0.2)',
                  textAlign: 'left', fontWeight: 600, whiteSpace: 'nowrap',
                  color: 'rgba(255,255,255,0.9)', fontSize: '0.78rem',
                }}>{formatInline(cell.trim())}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((row, ri) => (
              <tr key={ri} style={{ background: ri % 2 === 0 ? 'rgba(255,255,255,0.03)' : 'transparent' }}>
                {row.map((cell, ci) => (
                  <td key={ci} style={{
                    padding: '0.3rem 0.5rem', borderBottom: '1px solid rgba(255,255,255,0.08)',
                    color: 'rgba(255,255,255,0.8)', fontSize: '0.8rem',
                  }}>{formatInline(cell.trim())}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
    tableRows = []
    inTable = false
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()

    // Table row detection
    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      const cells = trimmed.slice(1, -1).split('|')
      // Skip separator rows like |---|---|
      if (/^[\s|:-]+$/.test(trimmed.replace(/\|/g, '').trim())) {
        inTable = true
        continue
      }
      tableRows.push(cells)
      inTable = true
      continue
    } else if (inTable) {
      flushTable()
    }

    // Empty line
    if (!trimmed) {
      elements.push(<div key={`br-${i}`} style={{ height: '0.3rem' }} />)
      continue
    }
    // HR
    if (/^---+$/.test(trimmed)) {
      elements.push(<hr key={`hr-${i}`} style={{ border: 'none', borderTop: '1px solid rgba(255,255,255,0.15)', margin: '0.5rem 0' }} />)
      continue
    }
    // Headers
    const hMatch = trimmed.match(/^(#{1,4})\s+(.+)/)
    if (hMatch) {
      const level = hMatch[1].length
      const fontSize = level === 1 ? '1.05rem' : level === 2 ? '0.95rem' : '0.88rem'
      elements.push(
        <div key={`h-${i}`} style={{ fontWeight: 700, fontSize, margin: '0.5rem 0 0.2rem', color: 'rgba(255,255,255,0.95)' }}>
          {formatInline(hMatch[2])}
        </div>
      )
      continue
    }
    // List items
    const liMatch = trimmed.match(/^[-*•]\s+(.+)/)
    if (liMatch) {
      elements.push(
        <div key={`li-${i}`} style={{ display: 'flex', gap: '0.4rem', margin: '0.15rem 0', paddingLeft: '0.3rem' }}>
          <span style={{ color: 'rgba(255,255,255,0.4)', flexShrink: 0 }}>•</span>
          <span>{formatInline(liMatch[1])}</span>
        </div>
      )
      continue
    }
    // Numbered list
    const olMatch = trimmed.match(/^(\d+)\.\s+(.+)/)
    if (olMatch) {
      elements.push(
        <div key={`ol-${i}`} style={{ display: 'flex', gap: '0.4rem', margin: '0.15rem 0', paddingLeft: '0.3rem' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)', flexShrink: 0, fontWeight: 600, minWidth: '1.2rem' }}>{olMatch[1]}.</span>
          <span>{formatInline(olMatch[2])}</span>
        </div>
      )
      continue
    }
    // Blockquote
    if (trimmed.startsWith('>')) {
      elements.push(
        <div key={`bq-${i}`} style={{
          borderLeft: '3px solid rgba(96,165,250,0.5)', paddingLeft: '0.6rem',
          margin: '0.3rem 0', color: 'rgba(255,255,255,0.75)', fontStyle: 'italic', fontSize: '0.85rem',
        }}>
          {formatInline(trimmed.slice(1).trim())}
        </div>
      )
      continue
    }
    // Regular paragraph
    elements.push(<div key={`p-${i}`} style={{ margin: '0.1rem 0' }}>{formatInline(trimmed)}</div>)
  }
  flushTable() // flush any remaining table
  return <>{elements}</>
}

// Inline formatting: **bold**, `code`, links (<url> and [text](url) and bare https://...)
function formatInline(text: string): React.ReactNode {
  if (!text) return null
  // Split on patterns: **bold**, `code`, [text](url), <url>, bare URLs
  const parts: React.ReactNode[] = []
  // Combined regex for all inline patterns
  const regex = /(\*\*(.+?)\*\*)|(`([^`]+)`)|(\[([^\]]+)\]\(([^)]+)\))|(<(https?:\/\/[^>]+)>)|((?:^|\s)(https?:\/\/[^\s),]+))/g
  let lastIndex = 0
  let match
  let keyIdx = 0

  while ((match = regex.exec(text)) !== null) {
    // Add text before match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    if (match[1]) {
      // **bold**
      parts.push(<strong key={`b-${keyIdx++}`} style={{ fontWeight: 700, color: 'rgba(255,255,255,0.95)' }}>{match[2]}</strong>)
    } else if (match[3]) {
      // `code`
      parts.push(<code key={`c-${keyIdx++}`} style={{ background: 'rgba(255,255,255,0.1)', padding: '0.1rem 0.3rem', borderRadius: '4px', fontSize: '0.82rem' }}>{match[4]}</code>)
    } else if (match[5]) {
      // [text](url)
      parts.push(<a key={`a-${keyIdx++}`} href={match[7]} target="_blank" rel="noopener noreferrer" style={{ color: '#60a5fa', textDecoration: 'underline', textUnderlineOffset: '2px' }}>{match[6]}</a>)
    } else if (match[8]) {
      // <url>
      parts.push(<a key={`a-${keyIdx++}`} href={match[9]} target="_blank" rel="noopener noreferrer" style={{ color: '#60a5fa', textDecoration: 'underline', textUnderlineOffset: '2px', wordBreak: 'break-all' }}>{match[9]}</a>)
    } else if (match[10]) {
      // bare URL (https://...)
      const url = match[11]
      const prefix = match[10].slice(0, match[10].length - url.length)
      if (prefix) parts.push(prefix)
      parts.push(<a key={`a-${keyIdx++}`} href={url} target="_blank" rel="noopener noreferrer" style={{ color: '#60a5fa', textDecoration: 'underline', textUnderlineOffset: '2px', wordBreak: 'break-all' }}>{url}</a>)
    }
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts.length === 1 ? parts[0] : <>{parts}</>
}

// ── Max recording duration ──────────────────────────────────────────────────
const MAX_RECORDING_SECONDS = 60

// ── Voice Message Bubble (Instagram-style waveform) ─────────────────────────
function VoiceMessageBubble({ msg, isAgent, onSpeakToggle, isSpeaking, agentColor }: {
  msg: AgentMessage
  isAgent: boolean
  onSpeakToggle: () => void
  isSpeaking: boolean
  agentColor?: string  // '#ef4444' for Agent 2, default gold for Agent 1
}) {
  const isRed = !!agentColor && agentColor.includes('ef4444')
  const isBlue = !!agentColor && agentColor.includes('2563eb')
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
      const ttsFn = isBlue ? api.agent3TTS : isRed ? api.agent2TTS : api.agentTTS
      ttsFn(msg.content).then(blob => {
        if (blob) {
          audioBlobUrlRef.current = URL.createObjectURL(blob)
        }
      }).catch(() => {})
    }
  }, [msg.content, msg.type, isAgent, msg.audioData, isRed])

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
          const ttsFn = isBlue ? api.agent3TTS : isRed ? api.agent2TTS : api.agentTTS
          const blob = await ttsFn(msg.content)
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

  const barColor = isRed
    ? (isAgent ? '#ef4444' : '#f87171')
    : isBlue
      ? (isAgent ? '#2563eb' : '#3b82f6')
      : (isAgent ? '#f59e0b' : '#fbbf24')
  const barDimColor = isRed
    ? (isAgent ? 'rgba(239,68,68,0.25)' : 'rgba(248,113,113,0.25)')
    : isBlue
      ? (isAgent ? 'rgba(37,99,235,0.25)' : 'rgba(59,130,246,0.25)')
      : (isAgent ? 'rgba(245,158,11,0.25)' : 'rgba(251,191,36,0.25)')

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = Math.floor(secs % 60)
    return `${m}:${String(s).padStart(2, '0')}`
  }

  return (
    <div
      className={isBlue ? (!isAgent ? 'agent3-voice-user' : 'agent3-voice-agent') : ''}
      style={{
        maxWidth: '80%',
        padding: '0.75rem 1rem',
        borderRadius: isAgent ? '16px 16px 16px 4px' : '16px 16px 4px 16px',
        background: !isAgent
          ? (isRed ? 'linear-gradient(135deg, #b91c1c, #ef4444)' : isBlue ? undefined /* CSS class */ : 'linear-gradient(135deg, #d4a017, #f59e0b)')
          : 'rgba(255,255,255,0.06)',
        borderLeft: isAgent ? `3px solid ${isRed ? '#ef4444' : isBlue ? '#2563eb' : '#f59e0b'}` : 'none',
        boxShadow: !isAgent
          ? (isRed ? '0 2px 12px rgba(239,68,68,0.3)' : isBlue ? '0 2px 12px rgba(37,99,235,0.3), 0 0 20px rgba(212,160,23,0.1)' : '0 2px 12px rgba(245,158,11,0.3)')
          : '0 1px 8px rgba(0,0,0,0.25)',
      }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        {/* Play/Pause button with loading spinner */}
        <button onClick={handlePlay} className={isBlue ? 'agent3-play-btn' : ''} style={{
          width: 32, height: 32, borderRadius: '50%',
          background: isBlue ? '#2563eb' : barColor, border: 'none', cursor: 'pointer',
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
              <div key={i}
                className={isBlue ? (isPlayed || !playing ? 'agent3-bar' : 'agent3-bar-dim') : ''}
                style={{
                  width: isBlue ? 3.5 : 3, borderRadius: '1.5px',
                  height: `${h * 100}%`,
                  background: isBlue ? '#2563eb' : (isPlayed || !playing ? barColor : barDimColor),
                  transition: isBlue ? 'none' : 'background 0.1s',
                  animationDelay: isBlue ? `${i * 0.05}s` : undefined,
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
  const API = import.meta.env.VITE_API_URL || ''
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

  // Voice call state (Agent 2 & Agent 3)
  const [inCall, setInCall] = useState(false)
  const [inCall3, setInCall3] = useState(false)

  // OpenAI TTS cache for speaker button on text messages
  const ttsAudioCacheRef = useRef<Map<number, string>>(new Map())
  const ttsSpeakingAudioRef = useRef<HTMLAudioElement | null>(null)

  // Voice states
  const [isRecording, setIsRecording] = useState(false)
  const [recordingTime, setRecordingTime] = useState(0)
  const [voiceEnabled, setVoiceEnabled] = useState(loadVoiceEnabled)
  const [speakingMsgIdx, setSpeakingMsgIdx] = useState<number | null>(null)
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

  const [conflictModal, setConflictModal] = useState<string | null>(null)

  const handleActivate = () => {
    // Vérifier si un autre agent est déjà actif (Agent 2 excluded when hidden)
    if (AGENT2_ENABLED && active2) {
      setConflictModal('Agent Syléa 2')
      setShowActivateModal(false)
      return
    }
    if (active3) {
      setConflictModal('Agent Syléa 3')
      setShowActivateModal(false)
      return
    }
    setActive(true)
    setShowActivateModal(false)
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
  }, [inputText, sending, messages, deviceCtx])

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
    // Use Agent 2 chat API with voice type to get TTS audio back
    const chatHistory = msgs.map(m => ({
      role: m.role === 'assistant' ? 'assistant' : 'user',
      content: m.content,
      type: 'voice' as const,
    }))
    return api.agent2Chat(chatHistory, deviceCtx ?? undefined)
  }, [deviceCtx])

  const handleVoiceCallMessage = useCallback((userText: string, agentText: string) => {
    // Messages from voice call are saved via the chat endpoint already
    // This callback can be used to update local state if needed
    void userText
    void agentText
  }, [])

  // ── Agent 3 chat endpoint for voice call ───────────────────────────────────
  const agent3ChatEndpoint = useCallback(async (msgs: Array<{ role: string; content: string }>) => {
    const chatHistory = msgs.map(m => ({
      role: m.role === 'assistant' ? 'assistant' : 'user',
      content: m.content,
      type: 'voice' as const,
    }))
    return api.agent3Chat(chatHistory, deviceCtx ?? undefined)
  }, [deviceCtx])

  const handleVoiceCallMessage3 = useCallback((userText: string, agentText: string) => {
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

  // Agent 2 voice states
  const [isRecording2, setIsRecording2] = useState(false)
  const [recordingTime2, setRecordingTime2] = useState(0)
  const [voiceEnabled2, setVoiceEnabled2] = useState(() => {
    try { return localStorage.getItem('sylea_agent2_voice_enabled') === 'true' } catch { return false }
  })
  const [speakingMsgIdx2, setSpeakingMsgIdx2] = useState<number | null>(null)
  const recognitionRef2 = useRef<any>(null)
  const mediaRecorderRef2 = useRef<MediaRecorder | null>(null)
  const pendingAudioUrlRef2 = useRef<string | null>(null)
  const pendingAudioBase64Ref2 = useRef<string>('')
  const mediaStreamRef2 = useRef<MediaStream | null>(null)
  const maxRecordingTimerRef2 = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingTranscriptRef2 = useRef<string>('')
  const recordingTimerRef2 = useRef<ReturnType<typeof setInterval> | null>(null)
  const ttsAudioCacheRef2 = useRef<Map<number, string>>(new Map())
  const ttsSpeakingAudioRef2 = useRef<HTMLAudioElement | null>(null)

  // Persist voice setting for Agent 2
  useEffect(() => {
    try { localStorage.setItem('sylea_agent2_voice_enabled', String(voiceEnabled2)) } catch {}
  }, [voiceEnabled2])

  // Cleanup Agent 2 recording on unmount
  useEffect(() => {
    return () => {
      recognitionRef2.current?.abort?.()
      if (recordingTimerRef2.current) clearInterval(recordingTimerRef2.current)
      if (maxRecordingTimerRef2.current) clearTimeout(maxRecordingTimerRef2.current)
      if (mediaRecorderRef2.current && mediaRecorderRef2.current.state !== 'inactive') {
        mediaRecorderRef2.current.stop()
      }
      if (mediaStreamRef2.current) {
        mediaStreamRef2.current.getTracks().forEach(t => t.stop())
      }
    }
  }, [])

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
    // Vérifier si un autre agent est déjà actif
    if (active) {
      setConflictModal('Agent Syléa 1')
      setShowActivateModal2(false)
      return
    }
    if (active3) {
      setConflictModal('Agent Syléa 3')
      setShowActivateModal2(false)
      return
    }
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
    type: 'EMAIL' | 'TEXT' | 'REMINDER' | 'LINK' | 'COPY' | 'PDF' | 'SEARCH' | 'X_SEARCH' | 'FILE_CREATE' | 'EXEC_RESULT' | 'SCREENSHOT' | 'IMAGE' | 'WEBPAGE' | 'CODE' | 'CRON' | 'MEMORY' | 'WORKSPACE_DOC' | 'CANVAS' | 'SPAWN_AGENT' | 'SKILL_SEARCH' | 'SKILL_INSTALL' | 'ERROR' | string
    data: Record<string, any>
  }

  const parseActions = (content: string): { text: string; actions: AgentAction[] } => {
    const actions: AgentAction[] = []
    let text = content
    // Match ALL action types including PDF, SEARCH, ANALYSIS, etc.
    const regex = /\[ACTION:(\w+)\]([\s\S]*?)\[\/ACTION\]/g
    let match
    while ((match = regex.exec(content)) !== null) {
      try {
        const data = JSON.parse(match[2])
        actions.push({ type: match[1] as AgentAction['type'], data })
      } catch { /* skip malformed */ }
      text = text.replace(match[0], '')
    }
    // Strip any remaining XML-like tags (function_calls, invoke, etc.)
    text = text.replace(/<\/?(?:function_calls|invoke|antml:\w+)[^>]*>/g, '')
    // Strip remaining code blocks with JSON
    text = text.replace(/```(?:json)?\s*\{[\s\S]*?\}\s*```/g, '')
    return { text: text.trim(), actions }
  }

  const handleAction = async (action: AgentAction) => {
    switch (action.type) {
      case 'EMAIL': {
        try {
          const res = await api.agent2SendEmail(action.data.to, action.data.subject, action.data.body)
          if (res.gmail_url) {
            window.open(res.gmail_url, '_blank')
            setActionToast('Gmail ouvert — ton mail est pret, il ne reste plus qu\'a l\'envoyer !')
          } else {
            setActionToast('Erreur ouverture Gmail')
          }
        } catch { setActionToast("Erreur lors de l'ouverture de Gmail") }
        setTimeout(() => setActionToast(null), 4000)
        break
      }
      case 'TEXT': {
        // Generate a nicely formatted HTML document
        const content = (action.data.content || '').replace(/\n/g, '<br>')
        const htmlDoc = `<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>${action.data.title || 'Document'}</title>
<style>
  body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #1a1a2e; line-height: 1.6; }
  h1 { color: #16213e; border-bottom: 2px solid #0f3460; padding-bottom: 10px; }
  p { margin: 8px 0; }
</style>
</head>
<body>
<h1>${action.data.title || 'Document'}</h1>
<div>${content}</div>
<hr style="margin-top:40px;border:1px solid #eee">
<p style="color:#999;font-size:12px;">Genere par Sylea Agent — ${new Date().toLocaleDateString('fr-FR')}</p>
</body>
</html>`
        const blob = new Blob([htmlDoc], { type: 'text/html;charset=utf-8' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `${action.data.title || 'document'}.html`; a.click()
        URL.revokeObjectURL(url)
        setActionToast('Document telecharge !')
        setTimeout(() => setActionToast(null), 3000)
        break
      }
      case 'REMINDER': {
        // Reminders use the shared reminder endpoint (agent2 route handles all agents)
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

  const handleSend2 = useCallback(async (overrideText?: string, msgType: 'text' | 'voice' = 'text', audioUrl?: string, audioBase64?: string) => {
    const text = (overrideText ?? inputText2).trim()
    if (!text || sending2) return
    const userMsg: AgentMessage = {
      role: 'user', content: text,
      timestamp: new Date().toISOString(), type: msgType,
      audioUrl: audioUrl || undefined,
      audioData: audioBase64 || undefined,
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
      const res = await api.agent2Chat(chatHistory, deviceCtx ?? undefined, msgType === 'voice' ? audioBase64 : undefined)
      const agentResponseType = msgType === 'voice' ? 'voice' : 'text'
      setMessages2(prev => [...prev, {
        role: 'agent', content: res.message,
        timestamp: new Date().toISOString(), type: agentResponseType,
        audioData: res.audioData || undefined,
        actions: res.actions || undefined,
      }])
    } catch {
      setMessages2(prev => [...prev, {
        role: 'agent', content: "Desole, une erreur est survenue. Reessayez dans un instant.",
        timestamp: new Date().toISOString(), type: 'text',
      }])
    } finally { setSending2(false) }
  }, [inputText2, sending2, messages2, deviceCtx])

  // ── Voice recording for Agent 2 ──────────────────────────────────────────
  const stopVoiceRecording2 = useCallback(() => {
    if (recognitionRef2.current) {
      try { recognitionRef2.current.stop() } catch {}
      recognitionRef2.current = null
    }
    if (mediaRecorderRef2.current && mediaRecorderRef2.current.state !== 'inactive') {
      mediaRecorderRef2.current.stop()
    }
    if (mediaStreamRef2.current) {
      mediaStreamRef2.current.getTracks().forEach(t => t.stop())
      mediaStreamRef2.current = null
    }
    setIsRecording2(false)
    setRecordingTime2(0)
    if (recordingTimerRef2.current) {
      clearInterval(recordingTimerRef2.current)
      recordingTimerRef2.current = null
    }
    if (maxRecordingTimerRef2.current) {
      clearTimeout(maxRecordingTimerRef2.current)
      maxRecordingTimerRef2.current = null
    }
  }, [])

  const startVoiceRecording2 = useCallback(() => {
    const SpeechRecognitionClass = getSpeechRecognitionClass()
    if (!SpeechRecognitionClass) {
      alert("Votre navigateur ne supporte pas la reconnaissance vocale")
      return
    }
    pendingAudioUrlRef2.current = null
    pendingAudioBase64Ref2.current = ''
    pendingTranscriptRef2.current = ''

    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
      mediaStreamRef2.current = stream
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
        pendingAudioUrlRef2.current = url
        const reader = new FileReader()
        reader.onload = () => {
          const base64 = (reader.result as string).split(',')[1] || ''
          pendingAudioBase64Ref2.current = base64
          const trySend = (attempts: number) => {
            const transcript = pendingTranscriptRef2.current.trim()
            if (transcript) {
              handleSend2(transcript, 'voice', url, base64)
            } else if (attempts < 20) {
              setTimeout(() => trySend(attempts + 1), 200)
            } else {
              handleSend2('[Message vocal]', 'voice', url, base64)
            }
          }
          trySend(0)
        }
        reader.readAsDataURL(blob)
      }
      mediaRecorderRef2.current = mediaRecorder
      mediaRecorder.start()

      const recognition = new SpeechRecognitionClass()
      recognition.lang = 'fr-FR'
      recognition.continuous = true
      recognition.interimResults = false
      recognition.onresult = (event: SpeechRecognitionEvent) => {
        let fullTranscript = ''
        for (let i = 0; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            fullTranscript += event.results[i][0].transcript + ' '
          }
        }
        pendingTranscriptRef2.current = fullTranscript.trim()
      }
      recognition.onerror = () => {}
      recognition.onend = () => {
        if (isRecording2 && recognitionRef2.current) {
          try { recognitionRef2.current.start() } catch {}
        }
      }
      recognitionRef2.current = recognition
      recognition.start()
      setIsRecording2(true)
      setRecordingTime2(0)
      recordingTimerRef2.current = setInterval(() => {
        setRecordingTime2(prev => {
          const next = prev + 1
          if (next >= MAX_RECORDING_SECONDS) {
            stopVoiceRecording2()
          }
          return next
        })
      }, 1000)
      maxRecordingTimerRef2.current = setTimeout(() => {
        stopVoiceRecording2()
      }, MAX_RECORDING_SECONDS * 1000)
    }).catch(() => {
      alert("Impossible d'acceder au microphone. Verifiez les permissions de votre navigateur.")
    })
  }, [handleSend2, stopVoiceRecording2, isRecording2])

  const toggleRecording2 = useCallback(() => {
    if (isRecording2) {
      stopVoiceRecording2()
    } else {
      startVoiceRecording2()
    }
  }, [isRecording2, startVoiceRecording2, stopVoiceRecording2])

  // ── Speak a specific Agent 2 message (TTS playback) ──────────────────────
  const handleSpeakMessage2 = useCallback(async (text: string, idx: number) => {
    if (speakingMsgIdx2 === idx) {
      if (ttsSpeakingAudioRef2.current) {
        ttsSpeakingAudioRef2.current.pause()
        ttsSpeakingAudioRef2.current.currentTime = 0
        ttsSpeakingAudioRef2.current = null
      }
      window.speechSynthesis.cancel()
      setSpeakingMsgIdx2(null)
      return
    }
    if (ttsSpeakingAudioRef2.current) {
      ttsSpeakingAudioRef2.current.pause()
      ttsSpeakingAudioRef2.current.currentTime = 0
      ttsSpeakingAudioRef2.current = null
    }
    window.speechSynthesis.cancel()

    const isAgentMsg = messages2[idx]?.role === 'agent'
    if (isAgentMsg) {
      try {
        let blobUrl = ttsAudioCacheRef2.current.get(idx)
        if (!blobUrl) {
          const blob = await api.agent2TTS(text)
          if (blob) {
            blobUrl = URL.createObjectURL(blob)
            ttsAudioCacheRef2.current.set(idx, blobUrl)
          }
        }
        if (blobUrl) {
          const audio = new Audio(blobUrl)
          ttsSpeakingAudioRef2.current = audio
          audio.onended = () => { setSpeakingMsgIdx2(null); ttsSpeakingAudioRef2.current = null }
          audio.onerror = () => { setSpeakingMsgIdx2(null); ttsSpeakingAudioRef2.current = null }
          setSpeakingMsgIdx2(idx)
          await audio.play()
          return
        }
      } catch {
        // Fall through to browser TTS
      }
    }
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
    utterance.onend = () => setSpeakingMsgIdx2(null)
    utterance.onerror = () => setSpeakingMsgIdx2(null)
    setSpeakingMsgIdx2(idx)
    synth.speak(utterance)
  }, [speakingMsgIdx2, messages2])

  const lastInteraction2 = messages2.length > 0
    ? `Derniere interaction : ${relativeTime(messages2[messages2.length - 1].timestamp)}`
    : 'Aucune interaction'

  // ── Agent 3 state ──────────────────────────────────────────────────────────
  const STORAGE_ACTIVE_3 = 'sylea_agent3_active'
  const loadActive3 = () => { try { return localStorage.getItem(STORAGE_ACTIVE_3) === 'true' } catch { return false } }
  const saveActive3 = (v: boolean) => { try { localStorage.setItem(STORAGE_ACTIVE_3, String(v)) } catch {} }

  const [active3, setActive3] = useState(loadActive3)
  const [showActivateModal3, setShowActivateModal3] = useState(false)
  const [showDeactivateModal3, setShowDeactivateModal3] = useState(false)
  const [showSetupWizard3, setShowSetupWizard3] = useState(false)
  const [setupStep, setSetupStep] = useState(0)
  const [setupStatus, setSetupStatus] = useState<Record<string, any>>({})
  const [setupLoading, setSetupLoading] = useState(false)
  const [setupError, setSetupError] = useState('')
  const [setupProgress, setSetupProgress] = useState(0)
  const [chat3Open, setChat3Open] = useState(false)
  const [messages3, setMessages3] = useState<AgentMessage[]>([])
  const [inputText3, setInputText3] = useState('')
  const [sending3, setSending3] = useState(false)
  const [loadingMessages3, setLoadingMessages3] = useState(false)
  const messagesEndRef3 = useRef<HTMLDivElement>(null)
  const messagesContainerRef3 = useRef<HTMLDivElement>(null)
  const streamPanelRef3 = useRef<HTMLDivElement>(null)
  const inputRef3 = useRef<HTMLInputElement>(null)
  const [openclawConnected, setOpenclawConnected] = useState(false)

  // Agent 3 streaming progress states
  const [streamSteps, setStreamSteps] = useState<Array<{ id: string; label: string; status: string; detail: string }>>([])
  const [streamLogs, setStreamLogs] = useState<Array<{ text: string; type: string; time: string }>>([])
  const [streamTools, setStreamTools] = useState<Array<{ tool: string; description: string; status: string }>>([])
  const [streamActive, setStreamActive] = useState(false)
  const [streamingText, setStreamingText] = useState('')

  // Computer Use state
  const [computerUseActive, setComputerUseActive] = useState(false)
  const [computerScreenshot, setComputerScreenshot] = useState<string | null>(null)
  const [computerActions, setComputerActions] = useState<Array<{ action: string; params: Record<string, any>; time: string }>>([])
  const [computerThinking, setComputerThinking] = useState('')
  const [computerConfirmation, setComputerConfirmation] = useState<{ action: string; params: Record<string, any>; reason: string } | null>(null)
  const [computerIteration, setComputerIteration] = useState({ current: 0, max: 25 })
  const [computerUseMode, setComputerUseMode] = useState(false)

  // Agent 3 management panels
  const [showCronPanel, setShowCronPanel] = useState(false)
  const [cronList, setCronList] = useState<Array<{ id: string; label: string; instruction: string; cron_expr: string; enabled: boolean; last_run?: string; last_result?: string; created_at: string }>>([])
  const [cronLoading, setCronLoading] = useState(false)
  const [showMemoryPanel, setShowMemoryPanel] = useState(false)
  const [memoryList, setMemoryList] = useState<Array<{ key: string; value: string; category?: string; created_at: string }>>([])
  const [memoryLoading, setMemoryLoading] = useState(false)
  const [memorySearch, setMemorySearch] = useState('')
  const [showFilesPanel, setShowFilesPanel] = useState(false)
  const [filesList, setFilesList] = useState<Array<{ id: string; filename: string; filetype: string; filesize: number; created_at: string }>>([])
  const [filesLoading, setFilesLoading] = useState(false)
  const [workspaceInfo, setWorkspaceInfo] = useState<{ exists: boolean; name?: string; path?: string; file_count?: number; hypotheses_count?: number } | null>(null)

  const [showToolsPanel, setShowToolsPanel] = useState(false)
  const [toolsResult, setToolsResult] = useState<Record<string, any> | null>(null)
  const [toolsLoading, setToolsLoading] = useState(false)
  const [showSettingsPanel, setShowSettingsPanel] = useState(false)
  const [showMgmtMenu, setShowMgmtMenu] = useState(false)

  // Agent 3 voice states
  const [isRecording3, setIsRecording3] = useState(false)
  const [recordingTime3, setRecordingTime3] = useState(0)
  const [voiceEnabled3, setVoiceEnabled3] = useState(() => {
    try { return localStorage.getItem('sylea_agent3_voice_enabled') === 'true' } catch { return false }
  })
  const [speakingMsgIdx3, setSpeakingMsgIdx3] = useState<number | null>(null)
  const recognitionRef3 = useRef<any>(null)
  const mediaRecorderRef3 = useRef<MediaRecorder | null>(null)
  const pendingAudioUrlRef3 = useRef<string | null>(null)
  const pendingAudioBase64Ref3 = useRef<string>('')
  const mediaStreamRef3 = useRef<MediaStream | null>(null)
  const maxRecordingTimerRef3 = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingTranscriptRef3 = useRef<string>('')
  const recordingTimerRef3 = useRef<ReturnType<typeof setInterval> | null>(null)
  const ttsAudioCacheRef3 = useRef<Map<number, string>>(new Map())
  const ttsSpeakingAudioRef3 = useRef<HTMLAudioElement | null>(null)

  // Persist voice setting for Agent 3
  useEffect(() => {
    try { localStorage.setItem('sylea_agent3_voice_enabled', String(voiceEnabled3)) } catch {}
  }, [voiceEnabled3])

  // Cleanup Agent 3 recording on unmount
  useEffect(() => {
    return () => {
      recognitionRef3.current?.abort?.()
      if (recordingTimerRef3.current) clearInterval(recordingTimerRef3.current)
      if (maxRecordingTimerRef3.current) clearTimeout(maxRecordingTimerRef3.current)
      if (mediaRecorderRef3.current && mediaRecorderRef3.current.state !== 'inactive') {
        mediaRecorderRef3.current.stop()
      }
      if (mediaStreamRef3.current) {
        mediaStreamRef3.current.getTracks().forEach(t => t.stop())
      }
    }
  }, [])

  useEffect(() => { saveActive3(active3) }, [active3])
  // Scroll vers le bas du conteneur de messages
  const scrollMessagesToBottom = useCallback((smooth = true) => {
    const container = messagesContainerRef3.current
    if (container) {
      if (smooth) {
        container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
      } else {
        container.scrollTop = container.scrollHeight
      }
    }
  }, [])

  useEffect(() => {
    scrollMessagesToBottom(true)
  }, [messages3, chat3Open, scrollMessagesToBottom])

  // Auto-scroll pendant le streaming (steps, logs)
  useEffect(() => {
    if (sending3 || streamActive) {
      // Use scrollIntoView on the panel for reliable scrolling
      if (streamPanelRef3.current) {
        streamPanelRef3.current.scrollIntoView({ behavior: 'auto', block: 'end' })
      } else {
        scrollMessagesToBottom(false)
      }
    }
  }, [streamSteps, streamLogs, sending3, streamActive, scrollMessagesToBottom])
  useEffect(() => {
    if (chat3Open) inputRef3.current?.focus()
  }, [chat3Open])

  // Load workspace info
  useEffect(() => {
    if (!chat3Open) return
    const token = localStorage.getItem('sylea_auth_token')
    if (!token) return
    fetch(`${API}/api/agent3/workspace-info`, {
      headers: { 'Authorization': `Bearer ${token}` },
    })
      .then(r => r.json())
      .then(data => setWorkspaceInfo(data))
      .catch(() => {})
  }, [chat3Open])

  // Check OpenClaw status periodically
  useEffect(() => {
    if (!active3) return
    const check = async () => {
      try {
        const status = await api.agent3Status()
        setOpenclawConnected(status.openclaw_connected)
      } catch { setOpenclawConnected(false) }
    }
    check()
    const interval = setInterval(check, 30000)
    return () => clearInterval(interval)
  }, [active3])

  const handleActivate3 = async () => {
    if (active) {
      setConflictModal('Agent Sylea 1')
      setShowActivateModal3(false)
      return
    }
    if (active2) {
      setConflictModal('Agent Sylea 2')
      setShowActivateModal3(false)
      return
    }
    setShowActivateModal3(false)
    // Check OpenClaw status first
    try {
      const r = await fetch(`${API}/api/agent3/setup/check`)
      const data = await r.json()
      if (data.ready) {
        // Already configured, activate directly
        setActive3(true)
        if ('Notification' in window && Notification.permission === 'default') {
          Notification.requestPermission()
        }
      } else {
        // Launch setup wizard
        setSetupStatus(data)
        setSetupStep(0)
        setSetupError('')
        setSetupProgress(0)
        setShowSetupWizard3(true)
      }
    } catch {
      // Can't check, launch wizard anyway
      setSetupStatus({})
      setSetupStep(0)
      setSetupError('')
      setSetupProgress(0)
      setShowSetupWizard3(true)
    }
  }
  const handleDeactivate3 = () => {
    setActive3(false)
    setShowDeactivateModal3(false)
    setChat3Open(false)
  }

  const WELCOME_MESSAGE_3 = "Salut ! Je suis l'Agent Sylea 3, ton agent d'elite. Je peux realiser n'importe quelle tache complexe avec precision. Dis-moi ce que tu veux accomplir."

  const openChat3 = useCallback(async () => {
    setChat3Open(true)
    setLoadingMessages3(true)
    try {
      const serverMessages = await api.getAgent3Messages()
      if (serverMessages && serverMessages.length > 0) {
        setMessages3(serverMessages.map((m: any) => ({
          role: m.role as 'agent' | 'user',
          content: m.content,
          timestamp: m.created_at,
          type: (m.type || 'text') as 'text' | 'voice',
          audioData: m.audioData,
        })))
      } else {
        setMessages3([{
          role: 'agent', content: WELCOME_MESSAGE_3,
          timestamp: new Date().toISOString(), type: 'text',
        }])
      }
    } catch {
      setMessages3([{
        role: 'agent', content: WELCOME_MESSAGE_3,
        timestamp: new Date().toISOString(), type: 'text',
      }])
    }
    setLoadingMessages3(false)
  }, [])

  // Computer Use handlers
  const handleComputerUse = async (prompt: string) => {
    setComputerUseActive(true)
    setComputerScreenshot(null)
    setComputerActions([])
    setComputerThinking('')
    setComputerConfirmation(null)
    setComputerIteration({ current: 0, max: 25 })

    // Add user message to chat
    setMessages3(prev => [...prev, {
      role: 'user',
      content: prompt,
      timestamp: new Date().toISOString(),
      type: 'computer_use',
    }])

    try {
      await api.computerUseStart(prompt, {
        onScreenshot: async () => {
          try {
            const data = await api.computerUseScreenshot()
            setComputerScreenshot(data.screenshot)
          } catch {}
        },
        onAction: (action, params) => {
          setComputerActions(prev => [...prev, {
            action,
            params,
            time: new Date().toLocaleTimeString(),
          }])
        },
        onThinking: (text) => {
          setComputerThinking(text)
        },
        onConfirmationNeeded: (data) => {
          setComputerConfirmation(data)
        },
        onIteration: (current, max) => {
          setComputerIteration({ current, max })
        },
        onComplete: (text) => {
          setComputerUseActive(false)
          setComputerConfirmation(null)
          setMessages3(prev => [...prev, {
            role: 'agent',
            content: text,
            timestamp: new Date().toISOString(),
            type: 'computer_use_result',
          }])
        },
        onError: (message) => {
          setComputerUseActive(false)
          setMessages3(prev => [...prev, {
            role: 'agent',
            content: `Erreur Computer Use: ${message}`,
            timestamp: new Date().toISOString(),
            type: 'error',
          }])
        },
      })
    } catch (err: any) {
      setComputerUseActive(false)
    }
  }

  const handleComputerConfirm = async (approved: boolean) => {
    try {
      await api.computerUseConfirm(approved)
      setComputerConfirmation(null)
    } catch {}
  }

  const handleComputerAbort = async () => {
    try {
      await api.computerUseAbort()
      setComputerUseActive(false)
      setComputerConfirmation(null)
    } catch {}
  }

  // handleSend3 — avec streaming SSE et jauge de progression
  const handleSend3 = useCallback(async (overrideText?: string, msgType: 'text' | 'voice' = 'text', audioUrl?: string, audioBase64?: string) => {
    const text = (overrideText ?? inputText3).trim()
    if (!text || sending3) return

    if (computerUseMode) {
      handleComputerUse(text)
      setInputText3('')
      setComputerUseMode(false)
      return
    }
    const userMsg: AgentMessage = {
      role: 'user', content: text,
      timestamp: new Date().toISOString(), type: msgType,
      audioUrl: audioUrl || undefined,
      audioData: audioBase64 || undefined,
    }
    const updated = [...messages3, userMsg]
    setMessages3(updated)
    setInputText3('')
    setSending3(true)
    setStreamActive(true)
    setStreamSteps([])
    setStreamLogs([])
    setStreamTools([])
    setStreamingText('')
    try {
      const chatHistory = updated.map(m => ({
        role: m.role === 'agent' ? 'assistant' : 'user',
        content: m.content, type: m.type,
      }))
      const res = await api.agent3ChatStream(
        chatHistory,
        deviceCtx ?? undefined,
        msgType === 'voice' ? audioBase64 : undefined,
        {
          onSteps: (steps) => setStreamSteps(steps),
          onStepUpdate: (stepId, status) => {
            setStreamSteps(prev => prev.map(s => s.id === stepId ? { ...s, status } : s))
          },
          onLog: (logText, logType) => {
            setStreamLogs(prev => [...prev, { text: logText, type: logType, time: new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }])
          },
          onToolProgress: (tool, description, status, index) => {
            setStreamTools(prev => {
              const updated = [...prev]
              if (index < updated.length) {
                updated[index] = { tool, description, status }
              } else {
                updated.push({ tool, description, status })
              }
              return updated
            })
          },
          onToken: (token) => {
            setStreamingText(prev => prev + token)
          },
          onResult: (result) => {
            setStreamingText('')
            const agentResponseType = msgType === 'voice' ? 'voice' : 'text'
            // Refresh workspace info when a workspace doc is created
            if (result.actions?.some((a: any) => a.type === 'WORKSPACE_DOC')) {
              const tkn = localStorage.getItem('sylea_auth_token')
              if (tkn) {
                fetch(`${API}/api/agent3/workspace-info`, { headers: { 'Authorization': `Bearer ${tkn}` } })
                  .then(r => r.json()).then(data => setWorkspaceInfo(data)).catch(() => {})
              }
            }
            setMessages3(prev => [...prev, {
              role: 'agent', content: result.message,
              timestamp: new Date().toISOString(), type: agentResponseType,
              actions: result.actions || undefined,
            }])
          },
          onError: (errMsg) => {
            setStreamLogs(prev => [...prev, { text: errMsg, type: 'error', time: new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }])
          },
        }
      )
    } catch {
      setMessages3(prev => [...prev, {
        role: 'agent', content: "Desole, une erreur est survenue.", actions: [{ type: 'ERROR', data: { retryable: true } }],
        timestamp: new Date().toISOString(), type: 'text',
      }])
    } finally {
      setSending3(false)
      setStreamingText('')
      // Garder le panneau visible 5s puis masquer (pour voir les etapes terminees)
      setTimeout(() => setStreamActive(false), 5000)
    }
  }, [inputText3, sending3, messages3, deviceCtx, voiceEnabled3])

  // ── Voice recording for Agent 3 ──────────────────────────────────────────
  const stopVoiceRecording3 = useCallback(() => {
    if (recognitionRef3.current) {
      try { recognitionRef3.current.stop() } catch {}
      recognitionRef3.current = null
    }
    if (mediaRecorderRef3.current && mediaRecorderRef3.current.state !== 'inactive') {
      mediaRecorderRef3.current.stop()
    }
    if (mediaStreamRef3.current) {
      mediaStreamRef3.current.getTracks().forEach(t => t.stop())
      mediaStreamRef3.current = null
    }
    setIsRecording3(false)
    setRecordingTime3(0)
    if (recordingTimerRef3.current) {
      clearInterval(recordingTimerRef3.current)
      recordingTimerRef3.current = null
    }
    if (maxRecordingTimerRef3.current) {
      clearTimeout(maxRecordingTimerRef3.current)
      maxRecordingTimerRef3.current = null
    }
  }, [])

  const startVoiceRecording3 = useCallback(() => {
    const SpeechRecognitionClass = getSpeechRecognitionClass()
    if (!SpeechRecognitionClass) {
      alert("Votre navigateur ne supporte pas la reconnaissance vocale")
      return
    }
    pendingAudioUrlRef3.current = null
    pendingAudioBase64Ref3.current = ''
    pendingTranscriptRef3.current = ''

    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
      mediaStreamRef3.current = stream
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
        pendingAudioUrlRef3.current = url
        const reader = new FileReader()
        reader.onload = () => {
          const base64 = (reader.result as string).split(',')[1] || ''
          pendingAudioBase64Ref3.current = base64
          const trySend = (attempts: number) => {
            const transcript = pendingTranscriptRef3.current.trim()
            if (transcript) {
              handleSend3(transcript, 'voice', url, base64)
            } else if (attempts < 20) {
              setTimeout(() => trySend(attempts + 1), 200)
            } else {
              handleSend3('[Message vocal]', 'voice', url, base64)
            }
          }
          trySend(0)
        }
        reader.readAsDataURL(blob)
      }
      mediaRecorderRef3.current = mediaRecorder
      mediaRecorder.start()

      const recognition = new SpeechRecognitionClass()
      recognition.lang = 'fr-FR'
      recognition.continuous = true
      recognition.interimResults = false
      recognition.onresult = (event: SpeechRecognitionEvent) => {
        let fullTranscript = ''
        for (let i = 0; i < event.results.length; i++) {
          if (event.results[i].isFinal) {
            fullTranscript += event.results[i][0].transcript + ' '
          }
        }
        pendingTranscriptRef3.current = fullTranscript.trim()
      }
      recognition.onerror = () => {}
      recognition.onend = () => {
        if (isRecording3 && recognitionRef3.current) {
          try { recognitionRef3.current.start() } catch {}
        }
      }
      recognitionRef3.current = recognition
      recognition.start()
      setIsRecording3(true)
      setRecordingTime3(0)
      recordingTimerRef3.current = setInterval(() => {
        setRecordingTime3(prev => {
          const next = prev + 1
          if (next >= MAX_RECORDING_SECONDS) {
            stopVoiceRecording3()
          }
          return next
        })
      }, 1000)
      maxRecordingTimerRef3.current = setTimeout(() => {
        stopVoiceRecording3()
      }, MAX_RECORDING_SECONDS * 1000)
    }).catch(() => {
      alert("Impossible d'acceder au microphone. Verifiez les permissions de votre navigateur.")
    })
  }, [handleSend3, stopVoiceRecording3, isRecording3])

  const toggleRecording3 = useCallback(() => {
    if (isRecording3) {
      stopVoiceRecording3()
    } else {
      startVoiceRecording3()
    }
  }, [isRecording3, startVoiceRecording3, stopVoiceRecording3])

  // ── Speak a specific Agent 3 message (TTS playback) ──────────────────────
  const handleSpeakMessage3 = useCallback(async (text: string, idx: number) => {
    if (speakingMsgIdx3 === idx) {
      if (ttsSpeakingAudioRef3.current) {
        ttsSpeakingAudioRef3.current.pause()
        ttsSpeakingAudioRef3.current.currentTime = 0
        ttsSpeakingAudioRef3.current = null
      }
      window.speechSynthesis.cancel()
      setSpeakingMsgIdx3(null)
      return
    }
    if (ttsSpeakingAudioRef3.current) {
      ttsSpeakingAudioRef3.current.pause()
      ttsSpeakingAudioRef3.current.currentTime = 0
      ttsSpeakingAudioRef3.current = null
    }
    window.speechSynthesis.cancel()

    const isAgentMsg = messages3[idx]?.role === 'agent'
    if (isAgentMsg) {
      try {
        let blobUrl = ttsAudioCacheRef3.current.get(idx)
        if (!blobUrl) {
          const blob = await api.agent3TTS(text)
          if (blob) {
            blobUrl = URL.createObjectURL(blob)
            ttsAudioCacheRef3.current.set(idx, blobUrl)
          }
        }
        if (blobUrl) {
          const audio = new Audio(blobUrl)
          ttsSpeakingAudioRef3.current = audio
          audio.onended = () => { setSpeakingMsgIdx3(null); ttsSpeakingAudioRef3.current = null }
          audio.onerror = () => { setSpeakingMsgIdx3(null); ttsSpeakingAudioRef3.current = null }
          setSpeakingMsgIdx3(idx)
          await audio.play()
          return
        }
      } catch {
        // Fall through to browser TTS
      }
    }
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
    utterance.onend = () => setSpeakingMsgIdx3(null)
    utterance.onerror = () => setSpeakingMsgIdx3(null)
    setSpeakingMsgIdx3(idx)
    synth.speak(utterance)
  }, [speakingMsgIdx3, messages3])

  const lastInteraction3 = messages3.length > 0
    ? `Derniere interaction : ${relativeTime(messages3[messages3.length - 1].timestamp)}`
    : 'Aucune interaction'

  // ── Future agents placeholder data ─────────────────────────────────────────
  const futureAgents = [
    { name: 'Super Agent Sylea', subtitle: 'Cerveau autonome 24/7', desc: 'Agit pour vous pendant que vous dormez' },
  ]

  // ── Agent 3 Chat view ────────────────────────────────────────────────────
  if (chat3Open) {
    return (
      <div className="page animate-fade-in" style={{ flex: 1, height: 'calc(100vh - 3.5rem - 3rem)', minHeight: 0, maxHeight: 'calc(100vh - 3.5rem - 3rem)', overflow: 'hidden' }}>
        <style>{`
          @keyframes agent-msg-in {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
          }
          @keyframes recording-pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.4); }
            50% { box-shadow: 0 0 0 12px rgba(37, 99, 235, 0); }
          }
          @keyframes recording-dot-pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
          }
          @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
          }
          @keyframes toast-in {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
          }
          @keyframes agent3-shimmer {
            0%, 100% { filter: drop-shadow(0 0 6px rgba(37,99,235,0.4)) drop-shadow(0 0 12px rgba(212,160,23,0.2)); }
            50% { filter: drop-shadow(0 0 12px rgba(37,99,235,0.6)) drop-shadow(0 0 20px rgba(245,158,11,0.4)); }
          }
          /* ── Agent 3 animated classes (needed in chat view) ── */
          .agent3-title-shimmer {
            background: linear-gradient(90deg, #2563eb, #d4a017, #fbbf24, #2563eb, #1e3a5f, #2563eb);
            background-size: 300% 100%;
            -webkit-background-clip: text !important; background-clip: text !important;
            -webkit-text-fill-color: transparent !important; color: transparent !important;
            animation: agent3-name-flow 3s ease-in-out infinite;
          }
          @keyframes agent3-name-flow {
            0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; }
          }
          .agent3-btn-shimmer {
            background: linear-gradient(90deg, #1e3a5f, #2563eb, #d4a017, #fbbf24, #2563eb, #1e3a5f) !important;
            background-size: 300% 100% !important;
            animation: agent3-btn-flow 3s ease-in-out infinite;
          }
          @keyframes agent3-btn-flow {
            0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; }
          }
          .agent3-user-bubble {
            background: linear-gradient(135deg, #1e3a5f, #2563eb, #d4a017, #1e3a5f) !important;
            background-size: 300% 300% !important;
            animation: agent3-bubble-flow 4s ease-in-out infinite;
          }
          @keyframes agent3-bubble-flow {
            0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; }
          }
          .agent3-agent-bubble {
            border-image: linear-gradient(180deg, #2563eb, #d4a017, #fbbf24, #2563eb) 1 !important;
            border-left: 3px solid !important;
            animation: agent3-border-anim 3s ease-in-out infinite;
          }
          @keyframes agent3-border-anim {
            0% { border-image: linear-gradient(180deg, #2563eb, #d4a017, #fbbf24, #2563eb) 1; }
            33% { border-image: linear-gradient(180deg, #fbbf24, #2563eb, #d4a017, #fbbf24) 1; }
            66% { border-image: linear-gradient(180deg, #d4a017, #fbbf24, #2563eb, #d4a017) 1; }
            100% { border-image: linear-gradient(180deg, #2563eb, #d4a017, #fbbf24, #2563eb) 1; }
          }
          .agent3-action-card {
            border: 1px solid transparent !important; background-clip: padding-box !important; position: relative !important;
          }
          .agent3-action-card::before {
            content: ''; position: absolute; inset: -1px; border-radius: 13px;
            background: linear-gradient(135deg, #2563eb, #d4a017, #fbbf24, #2563eb);
            background-size: 300% 300%; animation: agent3-bubble-flow 4s ease-in-out infinite;
            z-index: -1; opacity: 0.4;
          }
          .agent3-voice-user {
            background: linear-gradient(135deg, #1e3a5f, #2563eb, #d4a017, #1e3a5f) !important;
            background-size: 300% 300% !important; animation: agent3-bubble-flow 4s ease-in-out infinite;
          }
          .agent3-voice-agent {
            border-left: 3px solid transparent !important;
            border-image: linear-gradient(180deg, #2563eb, #d4a017, #fbbf24, #2563eb) 1 !important;
            animation: agent3-border-anim 3s ease-in-out infinite;
          }
          .agent3-action-label {
            background: linear-gradient(90deg, #60a5fa, #d4a017, #fbbf24, #60a5fa);
            background-size: 300% 100%;
            -webkit-background-clip: text !important; background-clip: text !important;
            -webkit-text-fill-color: transparent !important; animation: agent3-name-flow 3s ease-in-out infinite;
          }
          .agent3-bar {
            animation: agent3-bar-color 3s ease-in-out infinite !important; transition: none !important;
          }
          .agent3-bar-dim {
            animation: agent3-bar-dim-color 3s ease-in-out infinite !important; transition: none !important;
          }
          @keyframes agent3-bar-color {
            0%,100% { background: #2563eb !important; } 33% { background: #d4a017 !important; } 66% { background: #fbbf24 !important; }
          }
          @keyframes agent3-bar-dim-color {
            0%,100% { background: rgba(37,99,235,0.25) !important; } 33% { background: rgba(212,160,23,0.25) !important; } 66% { background: rgba(251,191,36,0.25) !important; }
          }
          .agent3-play-btn {
            animation: agent3-play-bg 3s ease-in-out infinite !important;
          }
          @keyframes agent3-play-bg {
            0%,100% { background: #2563eb !important; } 50% { background: #d4a017 !important; }
          }
          .agent3-text-glow {
            animation: agent3-text-color 3s ease-in-out infinite;
          }
          @keyframes agent3-text-color {
            0%,100% { color: #60a5fa; } 50% { color: #fbbf24; }
          }
          .agent3-border-glow {
            animation: agent3-border-color 3s ease-in-out infinite;
          }
          @keyframes agent3-border-color {
            0%,100% { border-color: rgba(37,99,235,0.3); } 50% { border-color: rgba(212,160,23,0.3); }
          }
          .agent3-small-btn {
            border: 1px solid rgba(37,99,235,0.3); background: rgba(37,99,235,0.08);
            animation: agent3-small-btn-anim 3s ease-in-out infinite;
          }
          @keyframes agent3-small-btn-anim {
            0%,100% { border-color: rgba(37,99,235,0.3); background: rgba(37,99,235,0.08); }
            50% { border-color: rgba(212,160,23,0.3); background: rgba(212,160,23,0.08); }
          }
          .agent3-small-btn:hover {
            border-color: rgba(251,191,36,0.5) !important; background: rgba(212,160,23,0.15) !important;
          }
          .agent3-recording {
            animation: agent3-rec 1.5s ease-in-out infinite;
          }
          @keyframes agent3-rec {
            0%,100% { color: #2563eb; } 50% { color: #d4a017; }
          }
          .agent3-speaker-active {
            animation: agent3-speaker-pulse 1.5s ease-in-out infinite;
          }
          @keyframes agent3-speaker-pulse {
            0%,100% { color: #2563eb; } 50% { color: #fbbf24; }
          }
          @keyframes agent3-cursor-blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
          }
        `}</style>
        <div className="container" style={{ maxWidth: 680, margin: '0 auto', padding: '0', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          {/* Chat header */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '0.75rem',
            padding: '1rem 1.25rem',
            borderBottom: '1px solid var(--border)',
            background: 'rgba(3,7,15,0.95)',
            backdropFilter: 'blur(12px)',
            position: 'relative', zIndex: 50,
          }}>
            <button onClick={() => setChat3Open(false)} style={{
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: '0.9rem', padding: '0.25rem 0.5rem',
              borderRadius: '6px', transition: 'all 0.15s',
            }}
              onMouseEnter={e => e.currentTarget.style.color = '#d4a017'}
              onMouseLeave={e => e.currentTarget.style.color = 'var(--text-muted)'}
            >
              {'\u2190'} Retour
            </button>
            <svg width={28} height={28} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
              <defs>
                <linearGradient id="agent3-chat-g" x1="0%" y1="100%" x2="100%" y2="0%">
                  <stop offset="0%">
                    <animate attributeName="stop-color" values="#1e3a5f;#d4a017;#1e3a5f" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="35%">
                    <animate attributeName="stop-color" values="#2563eb;#fbbf24;#2563eb" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="65%">
                    <animate attributeName="stop-color" values="#d4a017;#2563eb;#d4a017" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="100%">
                    <animate attributeName="stop-color" values="#fbbf24;#1e3a5f;#fbbf24" dur="3s" repeatCount="indefinite" />
                  </stop>
                </linearGradient>
                <linearGradient id="agent3-chat-shine" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%">
                    <animate attributeName="stop-color" values="rgba(255,230,200,0.6);rgba(200,220,255,0.3);rgba(255,230,200,0.6)" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="100%">
                    <animate attributeName="stop-color" values="rgba(200,220,255,0.3);rgba(255,230,200,0.6);rgba(200,220,255,0.3)" dur="3s" repeatCount="indefinite" />
                  </stop>
                </linearGradient>
              </defs>
              <path d={S_PATH} stroke="url(#agent3-chat-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
              <path d={S_PATH} stroke="url(#agent3-chat-shine)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
            </svg>
            <div style={{ flex: 1 }}>
              <p style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-primary)', lineHeight: 1.2 }}>Agent Sylea 3</p>
              <p style={{ fontSize: '0.7rem', color: '#4ade80', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#4ade80', display: 'inline-block' }} />
                {t('agents.status_active')}
              </p>
            </div>

            {/* Voice auto-play toggle */}
            {isTTSSupported() && (
              <button
                onClick={() => setVoiceEnabled3(v => !v)}
                title={voiceEnabled3 ? 'Desactiver la voix automatique' : 'Activer la voix automatique'}
                className={voiceEnabled3 ? 'agent3-small-btn agent3-text-glow' : ''}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.35rem',
                  padding: '0.3rem 0.65rem', borderRadius: '999px',
                  border: voiceEnabled3 ? undefined : '1px solid var(--border)',
                  background: voiceEnabled3 ? undefined : 'rgba(255,255,255,0.04)',
                  color: voiceEnabled3 ? undefined : 'var(--text-muted)',
                  cursor: 'pointer', fontSize: '0.72rem', fontWeight: 600,
                  transition: 'all 0.2s',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                  {voiceEnabled3 ? (
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

            {/* Voice call button */}
            <button
              onClick={() => { setChat3Open(false); setInCall3(true) }}
              title="Appeler l'Agent Sylea 3"
              className="agent3-btn-shimmer"
              style={{
                display: 'flex', alignItems: 'center', gap: '0.35rem',
                padding: '0.3rem 0.65rem', borderRadius: '999px',
                border: 'none', color: '#fff',
                cursor: 'pointer', fontSize: '0.72rem', fontWeight: 600,
                transition: 'all 0.2s',
                boxShadow: '0 2px 8px rgba(212,160,23,0.3)',
              }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2z" />
              </svg>
              Appeler
            </button>

            {/* OpenClaw status indicator */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '0.3rem',
              padding: '0.2rem 0.5rem', borderRadius: '999px',
              background: openclawConnected ? 'rgba(74,222,128,0.08)' : 'rgba(239,68,68,0.08)',
              border: `1px solid ${openclawConnected ? 'rgba(74,222,128,0.2)' : 'rgba(239,68,68,0.2)'}`,
            }}>
              <span style={{
                width: 5, height: 5, borderRadius: '50%',
                background: openclawConnected ? '#4ade80' : '#ef4444',
                display: 'inline-block',
              }} />
              <span style={{ fontSize: '0.62rem', color: openclawConnected ? '#4ade80' : '#ef4444', fontWeight: 600 }}>
                OpenClaw
              </span>
            </div>
            {/* Management menu */}
            <div style={{ position: 'relative' }}>
              <button
                onClick={() => setShowMgmtMenu(v => !v)}
                title="Options"
                className={showMgmtMenu ? 'agent3-text-glow' : ''}
                style={{
                  width: 32, height: 32, borderRadius: '50%', border: 'none',
                  background: showMgmtMenu ? 'rgba(212,160,23,0.15)' : 'rgba(255,255,255,0.06)',
                  color: showMgmtMenu ? undefined : 'var(--text-muted)',
                  cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'all 0.15s',
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/>
                </svg>
              </button>
              {showMgmtMenu && (
                <div className="agent3-border-glow" style={{
                  position: 'absolute', top: '100%', right: 0, marginTop: '0.5rem',
                  background: 'rgba(15,20,35,0.98)', border: '1px solid rgba(212,160,23,0.2)',
                  borderRadius: '12px', padding: '0.4rem', minWidth: '200px', zIndex: 9999,
                  boxShadow: '0 8px 32px rgba(0,0,0,0.7)',
                  backdropFilter: 'blur(16px)',
                  animation: 'agent-msg-in 0.15s ease forwards',
                }}>
                  {[
                    { label: 'Taches planifiees', icon: 'M12 2a10 10 0 0 1 10 10 10 10 0 0 1-10 10A10 10 0 0 1 2 12 10 10 0 0 1 12 2zM12 6v6l4 2', action: () => { setShowMgmtMenu(false); setShowCronPanel(true); setCronLoading(true); api.agent3GetCrons().then(setCronList).catch(() => { setActionToast('Erreur de connexion'); setTimeout(() => setActionToast(null), 4000) }).finally(() => setCronLoading(false)) } },
                    { label: 'Memoires', icon: 'M12 2a10 10 0 0 1 10 10c0 5.52-4.48 10-10 10S2 17.52 2 12 6.48 2 12 2zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z', action: () => { setShowMgmtMenu(false); setShowMemoryPanel(true); setMemoryLoading(true); api.agent3GetMemories().then(setMemoryList).catch(() => { setActionToast('Erreur de connexion'); setTimeout(() => setActionToast(null), 4000) }).finally(() => setMemoryLoading(false)) } },
                    { label: 'Fichiers', icon: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z', action: () => { setShowMgmtMenu(false); setShowFilesPanel(true); setFilesLoading(true); api.agent3GetFiles().then(setFilesList).catch(() => { setActionToast('Erreur de connexion'); setTimeout(() => setActionToast(null), 4000) }).finally(() => setFilesLoading(false)) } },
                    { label: 'Diagnostics outils', icon: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z', action: () => { setShowMgmtMenu(false); setShowToolsPanel(true); setToolsLoading(true); api.agent3TestTools().then(setToolsResult).catch(() => { setActionToast('Erreur de connexion'); setTimeout(() => setActionToast(null), 4000) }).finally(() => setToolsLoading(false)) } },
                    { label: 'Exporter conversation', icon: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3', action: () => { setShowMgmtMenu(false); window.open(`${import.meta.env.VITE_API_URL || ''}/api/agent3/export?format=txt`, '_blank') } },
                  ].map((item, i) => (
                    <button key={i} onClick={item.action} style={{
                      width: '100%', padding: '0.55rem 0.75rem', borderRadius: '8px',
                      background: 'transparent', border: 'none', color: 'var(--text-primary)',
                      fontSize: '0.78rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem',
                      transition: 'all 0.1s', textAlign: 'left',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = 'rgba(212,160,23,0.1)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" strokeWidth="2" strokeLinecap="round" className="agent3-text-glow"><path d={item.icon} stroke="currentColor"/></svg>
                      {item.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Messages area */}
          <div ref={messagesContainerRef3} style={{
            flex: 1, overflowY: 'auto', overflowX: 'hidden', padding: '1rem 1.25rem',
            display: 'flex', flexDirection: 'column', gap: '0.75rem',
            minWidth: 0,
          }}>
            {loadingMessages3 && (
              <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
                <span className="spinner spinner-sm" />
              </div>
            )}
            {messages3.map((msg, idx) => {
              // Use pre-parsed actions from backend if available, otherwise parse from content
              const parsed = msg.role === 'agent' ? parseActions(msg.content) : { text: msg.content, actions: [] }
              const msgText = parsed.text
              const actions = (msg.actions && msg.actions.length > 0)
                ? msg.actions as AgentAction[]
                : parsed.actions
              return (
                <div key={idx} style={{
                  display: 'flex',
                  justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  animation: 'agent-msg-in 0.3s ease forwards',
                  minWidth: 0,
                }}>
                  <div style={{ maxWidth: '80%', minWidth: 0, overflow: 'hidden' }}>
                    {/* Use VoiceMessageBubble for voice messages */}
                    {msg.type === 'voice' ? (
                      <VoiceMessageBubble
                        msg={msg}
                        isAgent={msg.role === 'agent'}
                        onSpeakToggle={() => handleSpeakMessage3(msg.content, idx)}
                        isSpeaking={speakingMsgIdx3 === idx}
                        agentColor="#2563eb"
                      />
                    ) : msgText ? (
                      <div
                        className={msg.role === 'user' ? 'agent3-user-bubble' : 'agent3-agent-bubble'}
                        style={{
                          padding: '0.75rem 1rem',
                          borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                          background: msg.role === 'user'
                            ? undefined  /* handled by .agent3-user-bubble */
                            : 'rgba(255,255,255,0.06)',
                          borderLeft: msg.role === 'agent' ? '3px solid #2563eb' : 'none',
                          color: 'var(--text-primary)',
                          fontSize: '0.88rem', lineHeight: '1.55',
                          wordBreak: 'break-word' as const, overflowWrap: 'anywhere' as const,
                          maxWidth: '100%', overflow: 'hidden',
                          boxShadow: msg.role === 'user'
                            ? '0 2px 12px rgba(37,99,235,0.3), 0 0 20px rgba(212,160,23,0.1)'
                            : '0 1px 8px rgba(0,0,0,0.25)',
                        }}>
                        <div style={{ margin: 0, wordBreak: 'break-word', overflowWrap: 'anywhere' }}>{msg.role === 'agent' ? renderFormattedText(msgText) : <p style={{ margin: 0 }}>{msgText}</p>}</div>
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
                              onClick={() => handleSpeakMessage3(msg.content, idx)}
                              title="Ecouter ce message"
                              className={speakingMsgIdx3 === idx ? 'agent3-speaker-active' : ''}
                              style={{
                                background: 'none', border: 'none', cursor: 'pointer',
                                padding: '2px', display: 'flex', alignItems: 'center',
                                color: speakingMsgIdx3 === idx ? undefined : 'inherit',
                                opacity: speakingMsgIdx3 === idx ? 1 : 0.6,
                                transition: 'all 0.15s',
                              }}
                              onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                              onMouseLeave={e => { if (speakingMsgIdx3 !== idx) e.currentTarget.style.opacity = '0.6' }}
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                                <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                              </svg>
                            </button>
                          )}
                          {/* Copy button */}
                          {msg.role === 'agent' && (
                            <button
                              onClick={() => {
                                try { navigator.clipboard.writeText(msg.content) } catch {}
                                setActionToast('Message copie !')
                                setTimeout(() => setActionToast(null), 2000)
                              }}
                              title="Copier le message"
                              style={{
                                background: 'none', border: 'none', cursor: 'pointer',
                                padding: '2px', display: 'flex', alignItems: 'center',
                                color: 'inherit', opacity: 0.6, transition: 'all 0.15s',
                              }}
                              onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                              onMouseLeave={e => e.currentTarget.style.opacity = '0.6'}
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                                <rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                              </svg>
                            </button>
                          )}
                        </div>
                      </div>
                    ) : null}
                    {/* Action cards */}
                    {actions.map((action, ai) => (
                      <div key={ai} className="agent3-action-card" style={{
                        marginTop: '0.5rem', padding: '0.75rem',
                        borderRadius: '12px',
                        background: 'rgba(212,160,23,0.06)',
                        border: '1px solid rgba(212,160,23,0.2)',
                      }}>
                        {action.type === 'EMAIL' && (
                          <>
                            <div className="agent3-action-label" style={{ fontSize: '0.72rem', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
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
                                background: 'linear-gradient(135deg, #ea4335, #d93025)', color: '#fff', fontSize: '0.78rem',
                                fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
                                display: 'flex', alignItems: 'center', gap: '0.4rem',
                              }}>
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 7l-10 7L2 7"/></svg>
                                Ouvrir dans Gmail
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
                            <div className="agent3-action-label" style={{ fontSize: '0.72rem', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                              {action.data.title}
                            </div>
                            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0 0 0.5rem', lineHeight: 1.4, maxHeight: '4rem', overflow: 'hidden' }}>
                              {action.data.content?.substring(0, 200)}...
                            </p>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                              <button onClick={() => handleAction(action)} className="agent3-btn-shimmer" style={{
                                padding: '0.4rem 1rem', borderRadius: '8px', border: 'none',
                                color: '#fff',
                                fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer',
                                display: 'flex', alignItems: 'center', gap: '0.3rem',
                              }}>
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
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
                            <div className="agent3-action-label" style={{ fontSize: '0.72rem', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                              Rappel
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                              <span style={{
                                padding: '0.2rem 0.5rem', borderRadius: '6px', fontSize: '0.72rem', fontWeight: 600,
                                background: 'rgba(251,191,36,0.12)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.25)',
                              }}>
                                {action.data.date} a {action.data.time}
                              </span>
                              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                {action.data.message}
                              </span>
                            </div>
                            <button onClick={() => handleAction(action)} style={{
                              padding: '0.4rem 1rem', borderRadius: '8px', border: 'none',
                              background: '#22c55e', color: '#fff', fontSize: '0.78rem',
                              fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.3rem',
                            }}>
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                              Confirmer le rappel
                            </button>
                          </>
                        )}
                        {action.type === 'LINK' && (
                          <button onClick={() => handleAction(action)} className="agent3-small-btn" style={{
                            width: '100%', padding: '0.5rem 0.75rem', borderRadius: '8px',
                            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem',
                            transition: 'all 0.15s', textAlign: 'left',
                          }}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="agent3-text-glow">
                              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
                            </svg>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div className="agent3-text-glow" style={{ fontSize: '0.78rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {action.data.label || 'Ouvrir le lien'}
                              </div>
                              <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {action.data.url}
                              </div>
                            </div>
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="agent3-text-glow"><polyline points="9 18 15 12 9 6"/></svg>
                          </button>
                        )}
                        {action.type === 'PDF' && (
                          <>
                            <div className="agent3-action-label" style={{ fontSize: '0.72rem', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                              {action.data.title || 'Rapport PDF'}
                            </div>
                            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0 0 0.5rem' }}>
                              {action.data.sections?.length || 0} sections — Rapport complet
                            </p>
                            <a
                              href={`${import.meta.env.VITE_API_URL || ''}/api/agent3/pdf/${action.data.pdf_filename}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="agent3-btn-shimmer"
                              style={{
                                display: 'inline-flex', alignItems: 'center', gap: '0.4rem',
                                padding: '0.5rem 1.2rem', borderRadius: '8px', border: 'none',
                                color: '#fff', fontSize: '0.82rem', fontWeight: 700, cursor: 'pointer',
                                textDecoration: 'none',
                                boxShadow: '0 2px 10px rgba(212,160,23,0.3)',
                              }}
                            >
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                              Telecharger le PDF
                            </a>
                          </>
                        )}
                        {action.type === 'COPY' && (
                          <button onClick={() => handleAction(action)} style={{
                            padding: '0.4rem 1rem', borderRadius: '8px',
                            background: 'rgba(255,255,255,0.08)', color: 'var(--text-secondary)',
                            fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer',
                            border: '1px solid var(--border)',
                          }}>
                            Copier dans le presse-papier
                          </button>
                        )}
                        {action.type === 'SEARCH' && (
                          <>
                            <div className="agent3-action-label" style={{ fontSize: '0.72rem', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                              Recherche : {action.data.query || ''}
                            </div>
                            {action.data.summary && (
                              <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '0 0 0.5rem', lineHeight: 1.5 }}>
                                {action.data.summary}
                              </p>
                            )}
                            {action.data.results && Array.isArray(action.data.results) && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                                {action.data.results.slice(0, 5).map((result: any, ri: number) => (
                                  <a key={ri} href={result.url} target="_blank" rel="noopener noreferrer"
                                    className="agent3-action-card"
                                    style={{
                                      display: 'block', padding: '0.5rem 0.65rem', borderRadius: '8px',
                                      background: 'rgba(212,160,23,0.04)', border: '1px solid rgba(212,160,23,0.12)',
                                      textDecoration: 'none', transition: 'all 0.15s',
                                    }}
                                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(212,160,23,0.1)'; e.currentTarget.style.borderColor = 'rgba(212,160,23,0.3)' }}
                                    onMouseLeave={e => { e.currentTarget.style.background = 'rgba(212,160,23,0.04)'; e.currentTarget.style.borderColor = 'rgba(212,160,23,0.12)' }}
                                  >
                                    <div className="agent3-text-glow" style={{ fontSize: '0.78rem', fontWeight: 600, marginBottom: '0.15rem' }}>
                                      {result.title}
                                    </div>
                                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                                      {result.snippet?.substring(0, 150)}
                                    </div>
                                    <div className="agent3-text-glow" style={{ fontSize: '0.65rem', marginTop: '0.15rem', opacity: 0.6 }}>
                                      {result.url?.substring(0, 60)}
                                    </div>
                                  </a>
                                ))}
                              </div>
                            )}
                          </>
                        )}
                        {action.type === 'X_SEARCH' && (
                          <>
                            {/* Header X/Twitter */}
                            <div style={{ fontSize: '0.72rem', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem', color: '#a3a3a3' }}>
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>
                              Recherche X : {action.data.query || ''}
                            </div>

                            {/* Summary */}
                            {action.data.summary && (
                              <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '0 0 0.5rem', lineHeight: 1.5 }}>
                                {action.data.summary}
                              </p>
                            )}

                            {/* Error */}
                            {action.data.x_search_error && (
                              <div style={{ fontSize: '0.72rem', color: '#f59e0b', padding: '0.4rem 0.6rem', borderRadius: '6px', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)', marginBottom: '0.4rem' }}>
                                ⚠ {action.data.x_search_error}
                              </div>
                            )}

                            {/* Source badge */}
                            {action.data.x_search_source && (
                              <div className="agent3-text-glow" style={{ display: 'inline-block', fontSize: '0.6rem', background: 'rgba(212,160,23,0.1)', padding: '0.1rem 0.4rem', borderRadius: '4px', marginBottom: '0.4rem' }}>
                                via {action.data.x_search_source === 'xai_api' ? 'xAI Grok' : action.data.x_search_source === 'openclaw_cli' ? 'OpenClaw' : action.data.x_search_source}
                              </div>
                            )}

                            {/* Posts list */}
                            {action.data.posts && Array.isArray(action.data.posts) && action.data.posts.length > 0 && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                                {action.data.posts.slice(0, 10).map((post: any, pi: number) => (
                                  <a key={pi} href={post.url || `https://x.com/${(post.handle || '').replace('@', '')}`} target="_blank" rel="noopener noreferrer"
                                    style={{
                                      display: 'block', padding: '0.6rem 0.7rem', borderRadius: '10px',
                                      background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
                                      textDecoration: 'none', transition: 'all 0.15s',
                                    }}
                                    onMouseEnter={e => { e.currentTarget.style.background = 'rgba(29,155,240,0.06)'; e.currentTarget.style.borderColor = 'rgba(29,155,240,0.2)' }}
                                    onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)' }}
                                  >
                                    {/* Author line */}
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', marginBottom: '0.25rem' }}>
                                      <div style={{ width: '24px', height: '24px', borderRadius: '50%', background: 'linear-gradient(135deg, #1d9bf0, #1a8cd8)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                                        <span style={{ fontSize: '0.6rem', color: '#fff', fontWeight: 700 }}>{(post.handle || post.display_name || '?')[0].replace('@', '').toUpperCase()}</span>
                                      </div>
                                      <div style={{ minWidth: 0 }}>
                                        <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-primary)' }}>{post.display_name || post.handle || 'Inconnu'}</span>
                                        {post.handle && <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginLeft: '0.3rem' }}>{post.handle.startsWith('@') ? post.handle : `@${post.handle}`}</span>}
                                        {post.date && <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', marginLeft: '0.3rem' }}>· {post.date}</span>}
                                      </div>
                                    </div>
                                    {/* Content */}
                                    <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginLeft: '34px' }}>
                                      {(post.content || post.text || '').substring(0, 280)}
                                    </div>
                                    {/* Engagement stats */}
                                    {(post.likes > 0 || post.retweets > 0 || post.views > 0 || post.replies > 0) && (
                                      <div style={{ display: 'flex', gap: '1rem', marginTop: '0.3rem', marginLeft: '34px' }}>
                                        {post.replies > 0 && (
                                          <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.2rem' }}>
                                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                                            {post.replies >= 1000 ? `${(post.replies/1000).toFixed(1)}K` : post.replies}
                                          </span>
                                        )}
                                        {post.retweets > 0 && (
                                          <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.2rem' }}>
                                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2"><polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/></svg>
                                            {post.retweets >= 1000 ? `${(post.retweets/1000).toFixed(1)}K` : post.retweets}
                                          </span>
                                        )}
                                        {post.likes > 0 && (
                                          <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.2rem' }}>
                                            <svg width="11" height="11" viewBox="0 0 24 24" fill="#ef4444" stroke="#ef4444" strokeWidth="1"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>
                                            {post.likes >= 1000 ? `${(post.likes/1000).toFixed(1)}K` : post.likes}
                                          </span>
                                        )}
                                        {post.views > 0 && (
                                          <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.2rem' }}>
                                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                                            {post.views >= 1000000 ? `${(post.views/1000000).toFixed(1)}M` : post.views >= 1000 ? `${(post.views/1000).toFixed(1)}K` : post.views}
                                          </span>
                                        )}
                                      </div>
                                    )}
                                  </a>
                                ))}
                              </div>
                            )}

                            {/* No posts but raw content */}
                            {(!action.data.posts || action.data.posts.length === 0) && action.data.raw_content && (
                              <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', lineHeight: 1.5, padding: '0.5rem', borderRadius: '8px', background: 'rgba(255,255,255,0.03)' }}>
                                {action.data.raw_content.substring(0, 500)}
                              </div>
                            )}
                          </>
                        )}
                        {action.type === 'WEBPAGE' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#10b981', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                              {action.data.title || 'Page web'}
                            </div>
                            <a href={action.data.url} target="_blank" rel="noopener noreferrer"
                              className="agent3-text-glow" style={{ fontSize: '0.7rem', display: 'block', marginBottom: '0.35rem', opacity: 0.7, textDecoration: 'none' }}>
                              {action.data.url?.substring(0, 80)}
                            </a>
                            <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '0 0 0.5rem', lineHeight: 1.5, maxHeight: '6rem', overflow: 'hidden' }}>
                              {action.data.content?.substring(0, 400)}
                            </p>
                            {action.data.extracted_data && Object.keys(action.data.extracted_data).length > 0 && (
                              <div style={{ padding: '0.5rem', borderRadius: '6px', background: 'rgba(16,185,129,0.05)', border: '1px solid rgba(16,185,129,0.15)' }}>
                                <div style={{ fontSize: '0.68rem', color: '#10b981', fontWeight: 600, marginBottom: '0.25rem' }}>Donnees extraites</div>
                                {Object.entries(action.data.extracted_data).map(([k, v]) => (
                                  <div key={k} style={{ fontSize: '0.72rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                                    <strong>{k}:</strong> {String(v)}
                                  </div>
                                ))}
                              </div>
                            )}
                          </>
                        )}
                        {action.type === 'CODE' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#a78bfa', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
                              {action.data.filename || 'Code'} ({action.data.language || 'text'})
                            </div>
                            {action.data.description && (
                              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0 0 0.35rem' }}>
                                {action.data.description}
                              </p>
                            )}
                            <pre style={{
                              padding: '0.65rem', borderRadius: '8px',
                              background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(167,139,250,0.15)',
                              fontSize: '0.72rem', color: '#e2e8f0', lineHeight: 1.5,
                              maxHeight: '12rem', overflow: 'auto', whiteSpace: 'pre-wrap',
                              fontFamily: "'Fira Code', 'Cascadia Code', monospace",
                            }}>
                              {action.data.content?.substring(0, 2000)}
                            </pre>
                            <button onClick={() => {
                              try { navigator.clipboard.writeText(action.data.content || '') } catch {}
                              setActionToast('Code copie !')
                              setTimeout(() => setActionToast(null), 3000)
                            }} style={{
                              marginTop: '0.35rem', padding: '0.35rem 0.8rem', borderRadius: '6px',
                              background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.2)',
                              color: '#a78bfa', fontSize: '0.72rem', fontWeight: 600, cursor: 'pointer',
                            }}>
                              Copier le code
                            </button>
                          </>
                        )}
                        {action.type === 'CRON' && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <div style={{
                              width: 32, height: 32, borderRadius: '50%',
                              background: 'linear-gradient(135deg, #1e3a5f, #2563eb)',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                            }}>
                              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round">
                                <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                              </svg>
                            </div>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: '0.78rem', color: '#fbbf24', fontWeight: 600 }}>
                                Tache planifiee : {action.data.label}
                              </div>
                              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                                {action.data.cron_expr} — {action.data.instruction?.substring(0, 80)}
                              </div>
                            </div>
                            <span style={{ fontSize: '0.65rem', color: '#22c55e', fontWeight: 600 }}>Active</span>
                          </div>
                        )}
                        {action.type === 'MEMORY' && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.25rem 0' }}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d4a017" strokeWidth="2" strokeLinecap="round">
                              <path d="M12 2a10 10 0 0 1 10 10c0 5.52-4.48 10-10 10S2 17.52 2 12 6.48 2 12 2z"/>
                              <circle cx="12" cy="12" r="3"/>
                            </svg>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                              Memorise : <strong style={{ color: '#d4a017' }}>{action.data.key}</strong>
                            </span>
                          </div>
                        )}
                        {action.type === 'ERROR' && action.data.retryable && (
                          <button
                            onClick={() => {
                              // Find last user message and retry
                              const lastUserMsg = messages3.slice().reverse().find(m => m.role === 'user')
                              if (lastUserMsg) {
                                // Remove the error message first
                                setMessages3(prev => prev.filter((_, i) => i !== idx))
                                handleSend3(lastUserMsg.content)
                              }
                            }}
                            style={{
                              display: 'flex', alignItems: 'center', gap: '0.4rem',
                              padding: '0.5rem 1rem', borderRadius: '8px', border: 'none',
                              background: 'rgba(239,68,68,0.12)', color: '#ef4444',
                              fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer',
                              transition: 'all 0.15s',
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.2)'}
                            onMouseLeave={e => e.currentTarget.style.background = 'rgba(239,68,68,0.12)'}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                              <polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
                            </svg>
                            Reessayer
                          </button>
                        )}
                        {/* ── FILE_CREATE — fichier cree sur le PC ── */}
                        {action.type === 'FILE_CREATE' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#22c55e', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg>
                              Fichier cree
                            </div>
                            <div style={{
                              display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem 0.6rem',
                              borderRadius: '8px', background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.15)',
                              marginBottom: '0.35rem',
                            }}>
                              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2" strokeLinecap="round"><path d="M3 3h7l2 2h9v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/></svg>
                              <span style={{ fontSize: '0.8rem', color: '#22c55e', fontWeight: 600, fontFamily: "'Fira Code', monospace" }}>
                                {action.data.filename}
                              </span>
                            </div>
                            {action.data.content && (
                              <pre style={{
                                padding: '0.5rem', borderRadius: '6px',
                                background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(34,197,94,0.1)',
                                fontSize: '0.7rem', color: '#94a3b8', lineHeight: 1.5,
                                maxHeight: '6rem', overflow: 'auto', whiteSpace: 'pre-wrap',
                                fontFamily: "'Fira Code', 'Cascadia Code', monospace",
                              }}>
                                {action.data.content.substring(0, 500)}{action.data.content.length > 500 ? '...' : ''}
                              </pre>
                            )}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.35rem' }}>
                              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                              <span style={{ fontSize: '0.68rem', color: '#22c55e', fontWeight: 500 }}>
                                Sauvegarde dans Documents/Sylea/ via le Desktop
                              </span>
                            </div>
                          </>
                        )}
                        {/* ── EXEC_RESULT — resultat d'execution terminal ── */}
                        {action.type === 'EXEC_RESULT' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#f59e0b', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
                              Terminal
                            </div>
                            {action.data.command && (
                              <div style={{
                                padding: '0.3rem 0.5rem', borderRadius: '6px 6px 0 0',
                                background: 'rgba(245,158,11,0.08)', borderBottom: '1px solid rgba(245,158,11,0.15)',
                                fontSize: '0.72rem', color: '#f59e0b', fontFamily: "'Fira Code', monospace",
                                display: 'flex', alignItems: 'center', gap: '0.3rem',
                              }}>
                                <span style={{ color: '#22c55e' }}>$</span> {action.data.command}
                              </div>
                            )}
                            <pre style={{
                              padding: '0.6rem', borderRadius: action.data.command ? '0 0 8px 8px' : '8px',
                              background: '#0c0c14', border: '1px solid rgba(245,158,11,0.12)',
                              borderTop: action.data.command ? 'none' : undefined,
                              fontSize: '0.72rem', color: '#e2e8f0', lineHeight: 1.6,
                              maxHeight: '16rem', overflow: 'auto', whiteSpace: 'pre-wrap',
                              fontFamily: "'Fira Code', 'Cascadia Code', monospace",
                            }}>
                              {action.data.output || '(aucune sortie)'}
                            </pre>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.35rem' }}>
                              {action.data.exit_code !== undefined && (
                                <span style={{
                                  fontSize: '0.65rem', fontWeight: 600, padding: '0.15rem 0.4rem', borderRadius: '4px',
                                  background: action.data.exit_code === 0 ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                                  color: action.data.exit_code === 0 ? '#22c55e' : '#ef4444',
                                  border: `1px solid ${action.data.exit_code === 0 ? 'rgba(34,197,94,0.25)' : 'rgba(239,68,68,0.25)'}`,
                                }}>
                                  {action.data.exit_code === 0 ? '✓ Succes' : `✗ Code ${action.data.exit_code}`}
                                </span>
                              )}
                              <button onClick={() => {
                                try { navigator.clipboard.writeText(action.data.output || '') } catch {}
                                setActionToast('Sortie copiee !')
                                setTimeout(() => setActionToast(null), 3000)
                              }} style={{
                                padding: '0.2rem 0.6rem', borderRadius: '4px',
                                background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)',
                                color: 'var(--text-muted)', fontSize: '0.65rem', cursor: 'pointer',
                              }}>
                                Copier
                              </button>
                            </div>
                          </>
                        )}
                        {/* ── SCREENSHOT — capture d'ecran ── */}
                        {action.type === 'SCREENSHOT' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#06b6d4', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                              {action.data.title || 'Capture d\'ecran'}
                            </div>
                            {action.data.url && (
                              <a href={action.data.url} target="_blank" rel="noopener noreferrer"
                                style={{ fontSize: '0.68rem', color: '#06b6d4', opacity: 0.7, display: 'block', marginBottom: '0.35rem', textDecoration: 'none' }}>
                                {action.data.url.substring(0, 80)}
                              </a>
                            )}
                            {action.data.image_url && (
                              <div style={{
                                borderRadius: '8px', overflow: 'hidden',
                                border: '1px solid rgba(6,182,212,0.2)',
                                background: '#0c0c14',
                              }}>
                                <img
                                  src={action.data.image_url.startsWith('/') ? `${import.meta.env.VITE_API_URL || ''}${action.data.image_url}` : action.data.image_url}
                                  alt={action.data.title || 'Screenshot'}
                                  style={{ width: '100%', height: 'auto', display: 'block', maxHeight: '400px', objectFit: 'contain' }}
                                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                                />
                              </div>
                            )}
                            {!action.data.image_url && (
                              <div style={{
                                padding: '2rem', borderRadius: '8px', textAlign: 'center',
                                background: 'rgba(6,182,212,0.05)', border: '1px dashed rgba(6,182,212,0.2)',
                                color: 'var(--text-muted)', fontSize: '0.75rem',
                              }}>
                                Capture en cours de chargement...
                              </div>
                            )}
                          </>
                        )}
                        {/* ── IMAGE — image generee ou analysee ── */}
                        {action.type === 'IMAGE' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#ec4899', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                              {action.data.title || 'Image'}
                            </div>
                            {action.data.prompt && (
                              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: '0 0 0.35rem', fontStyle: 'italic' }}>
                                "{action.data.prompt}"
                              </p>
                            )}
                            {action.data.image_url && (
                              <div style={{
                                borderRadius: '8px', overflow: 'hidden',
                                border: '1px solid rgba(236,72,153,0.2)',
                                background: '#0c0c14',
                              }}>
                                <img
                                  src={action.data.image_url.startsWith('/') ? `${import.meta.env.VITE_API_URL || ''}${action.data.image_url}` : action.data.image_url}
                                  alt={action.data.title || action.data.prompt || 'Generated image'}
                                  style={{ width: '100%', height: 'auto', display: 'block', maxHeight: '500px', objectFit: 'contain' }}
                                  onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                                />
                              </div>
                            )}
                            {!action.data.image_url && action.data.image_error && (
                              <div style={{
                                padding: '1rem', borderRadius: '8px', textAlign: 'center',
                                background: 'rgba(239,68,68,0.05)', border: '1px dashed rgba(239,68,68,0.2)',
                                color: '#ef4444', fontSize: '0.75rem',
                              }}>
                                Erreur : {action.data.image_error}
                              </div>
                            )}
                            {!action.data.image_url && !action.data.image_error && (
                              <div style={{
                                padding: '2rem', borderRadius: '8px', textAlign: 'center',
                                background: 'rgba(236,72,153,0.05)', border: '1px dashed rgba(236,72,153,0.2)',
                                color: 'var(--text-muted)', fontSize: '0.75rem',
                              }}>
                                Image en cours de generation...
                              </div>
                            )}
                          </>
                        )}
                        {/* ── CANVAS — visualisation/diagramme ── */}
                        {action.type === 'CANVAS' && (
                          <>
                            <div style={{ fontSize: '0.72rem', color: '#8b5cf6', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
                              {action.data.title || 'Visualisation'}
                            </div>
                            {action.data.description && (
                              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: '0 0 0.35rem' }}>
                                {action.data.description}
                              </p>
                            )}
                            {action.data.type === 'html' && action.data.content ? (
                              <div style={{
                                borderRadius: '8px', overflow: 'hidden', border: '1px solid rgba(139,92,246,0.2)',
                                background: '#fff', minHeight: '200px', maxHeight: '500px',
                              }}>
                                <iframe
                                  srcDoc={action.data.content}
                                  style={{ width: '100%', height: '400px', border: 'none' }}
                                  sandbox="allow-scripts"
                                  title={action.data.title || 'Canvas'}
                                />
                              </div>
                            ) : action.data.type === 'table' && Array.isArray(action.data.content) ? (
                              <div style={{
                                borderRadius: '8px', overflow: 'auto', border: '1px solid rgba(139,92,246,0.15)',
                                maxHeight: '400px',
                              }}>
                                <table style={{ width: '100%', fontSize: '0.72rem', borderCollapse: 'collapse' }}>
                                  {action.data.content.length > 0 && (
                                    <thead>
                                      <tr>
                                        {Object.keys(action.data.content[0]).map((key: string) => (
                                          <th key={key} style={{
                                            padding: '0.4rem 0.6rem', textAlign: 'left',
                                            background: 'rgba(139,92,246,0.08)', color: '#8b5cf6',
                                            fontWeight: 600, borderBottom: '1px solid rgba(139,92,246,0.15)',
                                          }}>
                                            {key}
                                          </th>
                                        ))}
                                      </tr>
                                    </thead>
                                  )}
                                  <tbody>
                                    {action.data.content.slice(0, 50).map((row: any, ri: number) => (
                                      <tr key={ri}>
                                        {Object.values(row).map((val: any, ci: number) => (
                                          <td key={ci} style={{
                                            padding: '0.35rem 0.6rem', color: 'var(--text-secondary)',
                                            borderBottom: '1px solid rgba(255,255,255,0.05)',
                                          }}>
                                            {String(val)}
                                          </td>
                                        ))}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            ) : (
                              <pre style={{
                                padding: '0.6rem', borderRadius: '8px',
                                background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(139,92,246,0.12)',
                                fontSize: '0.72rem', color: '#e2e8f0', lineHeight: 1.5,
                                maxHeight: '12rem', overflow: 'auto', whiteSpace: 'pre-wrap',
                                fontFamily: "'Fira Code', monospace",
                              }}>
                                {typeof action.data.content === 'string' ? action.data.content.substring(0, 2000) : JSON.stringify(action.data.content, null, 2)?.substring(0, 2000)}
                              </pre>
                            )}
                          </>
                        )}
                        {/* ── SPAWN_AGENT — sous-agent lance ── */}
                        {action.type === 'SPAWN_AGENT' && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <div style={{
                              width: 32, height: 32, borderRadius: '50%',
                              background: 'linear-gradient(135deg, #7c3aed, #2563eb)',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              boxShadow: '0 2px 8px rgba(124,58,237,0.3)',
                            }}>
                              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round">
                                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
                                <path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                              </svg>
                            </div>
                            <div style={{ flex: 1 }}>
                              <div style={{ fontSize: '0.78rem', color: '#a78bfa', fontWeight: 600 }}>
                                {action.data.label || `Sous-agent : ${action.data.agent_id || 'default'}`}
                              </div>
                              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
                                {action.data.task?.substring(0, 100)}
                              </div>
                            </div>
                            <span style={{
                              fontSize: '0.65rem', fontWeight: 600, padding: '0.15rem 0.4rem', borderRadius: '4px',
                              background: action.data.spawn_success ? 'rgba(34,197,94,0.12)' : 'rgba(251,191,36,0.12)',
                              color: action.data.spawn_success ? '#22c55e' : '#fbbf24',
                            }}>
                              {action.data.spawn_success ? 'Lance' : 'En attente'}
                            </span>
                          </div>
                        )}
                        {/* ── SKILL_SEARCH — recherche de capacite ── */}
                        {action.type === 'SKILL_SEARCH' && (
                          <>
                            <div className="agent3-action-label" style={{ fontSize: '0.72rem', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                              Recherche de capacite
                            </div>
                            <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '0 0 0.3rem', lineHeight: 1.5 }}>
                              {action.data.query ? `Recherche : "${action.data.query}"` : 'Recherche en cours...'}
                            </p>
                            {action.data.results && Array.isArray(action.data.results) && action.data.results.length > 0 && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                {action.data.results.slice(0, 5).map((skill: any, si: number) => (
                                  <div key={si} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.3rem 0.5rem', borderRadius: '6px', background: 'rgba(212,160,23,0.06)', border: '1px solid rgba(212,160,23,0.12)' }}>
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#d4a017" strokeWidth="2" strokeLinecap="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/></svg>
                                    <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)' }}>{skill.name || skill.slug}</span>
                                    {skill.description && <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>— {skill.description}</span>}
                                  </div>
                                ))}
                              </div>
                            )}
                            {action.data.count !== undefined && (
                              <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', margin: '0.3rem 0 0' }}>
                                {action.data.count} skill{action.data.count > 1 ? 's' : ''} trouve{action.data.count > 1 ? 's' : ''}
                              </p>
                            )}
                          </>
                        )}
                        {/* ── SKILL_INSTALL — installation de skill ── */}
                        {action.type === 'SKILL_INSTALL' && (
                          <>
                            <div className="agent3-action-label" style={{ fontSize: '0.72rem', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                              Installation de skill
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.4rem 0.6rem', borderRadius: '8px', background: action.data.success ? 'rgba(34,197,94,0.08)' : 'rgba(212,160,23,0.06)', border: `1px solid ${action.data.success ? 'rgba(34,197,94,0.2)' : 'rgba(212,160,23,0.15)'}` }}>
                              {action.data.success ? (
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                              ) : (
                                <div style={{ width: 16, height: 16, borderRadius: '50%', border: '2px solid #d4a017', borderTopColor: 'transparent', animation: 'spin 0.8s linear infinite' }} />
                              )}
                              <div>
                                <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>{action.data.slug || action.data.name || 'Skill'}</span>
                                <span style={{ fontSize: '0.72rem', color: action.data.success ? '#22c55e' : '#d4a017', marginLeft: '0.4rem' }}>
                                  {action.data.success ? '✓ Installe' : action.data.error ? `✗ ${action.data.error}` : 'Installation...'}
                                </span>
                              </div>
                            </div>
                          </>
                        )}
                        {/* ── WORKSPACE_DOC — document workspace cree ── */}
                        {action.type === 'WORKSPACE_DOC' && (
                          <div style={{
                            display: 'flex', alignItems: 'center', gap: '0.65rem',
                            padding: '0.55rem 0.75rem', borderRadius: '10px',
                            background: 'linear-gradient(135deg, rgba(16,185,129,0.06), rgba(34,197,94,0.04))',
                            border: '1px solid rgba(16,185,129,0.18)',
                            cursor: 'default',
                            transition: 'all 0.15s ease',
                          }}
                          onMouseEnter={e => { e.currentTarget.style.background = 'linear-gradient(135deg, rgba(16,185,129,0.1), rgba(34,197,94,0.07))'; e.currentTarget.style.borderColor = 'rgba(16,185,129,0.3)' }}
                          onMouseLeave={e => { e.currentTarget.style.background = 'linear-gradient(135deg, rgba(16,185,129,0.06), rgba(34,197,94,0.04))'; e.currentTarget.style.borderColor = 'rgba(16,185,129,0.18)' }}
                          >
                            {/* File icon */}
                            <div style={{
                              width: 36, height: 36, borderRadius: '8px',
                              background: 'linear-gradient(135deg, rgba(16,185,129,0.15), rgba(34,197,94,0.1))',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              flexShrink: 0,
                            }}>
                              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                                <polyline points="14 2 14 8 20 8"/>
                                <line x1="16" y1="13" x2="8" y2="13"/>
                                <line x1="16" y1="17" x2="8" y2="17"/>
                                <polyline points="10 9 9 9 8 9"/>
                              </svg>
                            </div>
                            {/* File info */}
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{
                                fontSize: '0.82rem', fontWeight: 600, color: '#10b981',
                                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                              }}>
                                {action.data.title || 'Document'}
                              </div>
                              <div style={{
                                fontSize: '0.68rem', color: 'var(--text-muted)',
                                fontFamily: "'Fira Code', 'Cascadia Code', monospace",
                                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                marginTop: '0.1rem',
                              }}>
                                workspace/{action.data.filepath || ''}
                              </div>
                            </div>
                            {/* Badge */}
                            <div style={{
                              display: 'flex', alignItems: 'center', gap: '0.3rem',
                              padding: '0.2rem 0.5rem', borderRadius: '6px',
                              background: 'rgba(16,185,129,0.1)', flexShrink: 0,
                            }}>
                              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                              <span style={{ fontSize: '0.62rem', color: '#22c55e', fontWeight: 600, letterSpacing: '0.02em' }}>
                                Sauvegarde
                              </span>
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
            {/* ── Agent 3 Streaming Progress Panel ── */}
            {(sending3 || streamActive) && streamSteps.length > 0 && (
              <div ref={streamPanelRef3} style={{
                animation: 'agent-msg-in 0.3s ease forwards',
                borderRadius: '16px', overflow: 'hidden',
                background: 'rgba(5,8,16,0.85)',
                border: '1px solid rgba(212,160,23,0.2)',
                boxShadow: '0 4px 24px rgba(212,160,23,0.1), inset 0 1px 0 rgba(212,160,23,0.1)',
                maxWidth: '95%',
                flexShrink: 0,
                minHeight: 'fit-content',
              }}>
                {/* Header with shimmer */}
                <div className="agent3-btn-shimmer" style={{
                  padding: '0.6rem 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem',
                }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round">
                    <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
                  </svg>
                  <span style={{ color: '#fff', fontSize: '0.78rem', fontWeight: 700 }}>Agent 3 — Execution en cours</span>
                </div>

                {/* Progress bar */}
                <div style={{ padding: '0 1rem', marginBottom: '0.5rem' }}>
                  <div style={{
                    height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.06)', overflow: 'hidden',
                  }}>
                    <div style={{
                      height: '100%', borderRadius: 2,
                      background: 'linear-gradient(90deg, #1e3a5f, #2563eb, #d4a017, #fbbf24, #2563eb)',
                      backgroundSize: '200% 100%',
                      animation: 'agent3-btn-flow 2s ease-in-out infinite',
                      width: `${Math.round((streamSteps.filter(s => s.status === 'done').length / streamSteps.length) * 100)}%`,
                      transition: 'width 0.5s ease',
                    }} />
                  </div>
                  <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '0.2rem', textAlign: 'right' }}>
                    {streamSteps.filter(s => s.status === 'done').length}/{streamSteps.length} etapes
                  </div>
                </div>

                {/* Steps */}
                <div style={{ padding: '0 0.75rem 0.5rem', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
                  {streamSteps.map((step) => (
                    <div key={step.id} style={{
                      display: 'flex', alignItems: 'center', gap: '0.5rem',
                      padding: '0.35rem 0.5rem', borderRadius: '8px',
                      background: step.status === 'running' ? 'rgba(212,160,23,0.08)' : step.status === 'done' ? 'rgba(16,185,129,0.05)' : 'transparent',
                      transition: 'all 0.3s',
                    }}>
                      {/* Status icon */}
                      <div style={{ width: 18, height: 18, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                        {step.status === 'done' && (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                        )}
                        {step.status === 'running' && (
                          <div style={{
                            width: 14, height: 14, borderRadius: '50%',
                            border: '2px solid transparent',
                            borderTopColor: '#2563eb', borderRightColor: '#d4a017',
                            animation: 'spin 0.8s linear infinite',
                          }} />
                        )}
                        {step.status === 'pending' && (
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'rgba(255,255,255,0.15)' }} />
                        )}
                      </div>
                      {/* Step label */}
                      <span className={step.status === 'running' ? 'agent3-text-glow' : ''} style={{
                        fontSize: '0.75rem', fontWeight: step.status === 'running' ? 600 : 400,
                        color: step.status === 'running' ? undefined : step.status === 'done' ? '#10b981' : 'var(--text-muted)',
                        transition: 'all 0.3s',
                      }}>
                        {step.label}
                      </span>
                    </div>
                  ))}
                </div>

                {/* Tool progress — granular per-tool display */}
                {streamTools.length > 0 && (
                  <div style={{
                    borderTop: '1px solid rgba(212,160,23,0.1)',
                    padding: '0.5rem 0.75rem',
                    display: 'flex', flexDirection: 'column', gap: '0.25rem',
                  }}>
                    <div style={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.15rem' }}>
                      Outils ({streamTools.length})
                    </div>
                    {streamTools.map((t, i) => (
                      <div key={i} style={{
                        display: 'flex', alignItems: 'center', gap: '0.4rem',
                        padding: '0.2rem 0.4rem', borderRadius: '6px',
                        background: t.status === 'running' ? 'rgba(212,160,23,0.06)' : 'rgba(16,185,129,0.04)',
                        border: `1px solid ${t.status === 'running' ? 'rgba(212,160,23,0.15)' : 'rgba(16,185,129,0.1)'}`,
                      }}>
                        {t.status === 'running' ? (
                          <span className="spinner spinner-sm" style={{ width: 10, height: 10 }} />
                        ) : (
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                        )}
                        <span style={{
                          fontSize: '0.7rem', fontWeight: 500,
                          color: t.status === 'running' ? '#d4a017' : '#10b981',
                          fontFamily: "'Fira Code', monospace",
                        }}>
                          {t.tool}
                        </span>
                        <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', flex: 1 }}>
                          {t.description}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Live log (like Claude Code) */}
                {streamLogs.length > 0 && (
                  <div style={{
                    borderTop: '1px solid rgba(212,160,23,0.1)',
                    padding: '0.35rem 0.75rem', maxHeight: '5rem', overflowY: 'auto',
                    background: 'rgba(0,0,0,0.2)',
                  }}>
                    {streamLogs.slice(-4).map((log, i) => (
                      <div key={i} style={{
                        display: 'flex', alignItems: 'flex-start', gap: '0.4rem',
                        fontSize: '0.68rem', lineHeight: 1.4, padding: '0.1rem 0',
                        fontFamily: "'Fira Code', 'Cascadia Code', monospace",
                      }}>
                        <span style={{ color: 'rgba(255,255,255,0.25)', flexShrink: 0, fontSize: '0.62rem' }}>{log.time}</span>
                        <span style={{
                          color: log.type === 'success' ? '#10b981'
                            : log.type === 'tool' ? '#d4a017'
                            : log.type === 'warning' ? '#f59e0b'
                            : log.type === 'error' ? '#ef4444'
                            : 'rgba(255,255,255,0.5)',
                        }}>
                          {log.type === 'tool' && '⚡ '}{log.type === 'success' && '✓ '}{log.type === 'error' && '✗ '}{log.text}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            {/* ── Agent 3 Streaming Text (token-level) ── */}
            {streamingText && (sending3 || streamActive) && (
              <div style={{ display: 'flex', justifyContent: 'flex-start', animation: 'agent-msg-in 0.3s ease forwards', flexShrink: 0 }}>
                <div className="agent3-agent-bubble" style={{
                  padding: '0.75rem 1rem', borderRadius: '16px 16px 16px 4px',
                  background: 'rgba(255,255,255,0.06)', borderLeft: '3px solid',
                  maxWidth: '80%',
                }}>
                  <div style={{ fontSize: '0.88rem', color: 'var(--text-primary)', lineHeight: 1.55 }}>
                    {streamingText}
                    <span style={{ display: 'inline-block', width: 6, height: 14, background: '#d4a017', marginLeft: 2, animation: 'agent3-cursor-blink 0.8s step-end infinite', verticalAlign: 'text-bottom' }} />
                  </div>
                </div>
              </div>
            )}
            {/* Computer Use Live Panel */}
            {computerUseActive && (
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '0.75rem',
                padding: '1rem',
                background: 'rgba(212, 160, 23, 0.05)',
                border: '1px solid rgba(212, 160, 23, 0.2)',
                borderRadius: '12px',
                margin: '0.5rem 0',
              }}>
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%',
                      background: '#d4a017',
                      animation: 'agent3-cursor-blink 1s ease infinite',
                    }} />
                    <span style={{ color: '#d4a017', fontWeight: 600, fontSize: '0.85rem' }}>
                      Computer Use — Iteration {computerIteration.current}/{computerIteration.max}
                    </span>
                  </div>
                  <button
                    onClick={handleComputerAbort}
                    style={{
                      background: 'rgba(255, 80, 80, 0.15)',
                      border: '1px solid rgba(255, 80, 80, 0.3)',
                      borderRadius: '6px',
                      padding: '4px 12px',
                      color: '#ff5050',
                      cursor: 'pointer',
                      fontSize: '0.8rem',
                    }}
                  >
                    Arreter
                  </button>
                </div>

                {/* Live Screenshot */}
                {computerScreenshot && (
                  <div style={{
                    borderRadius: '8px',
                    overflow: 'hidden',
                    border: '1px solid rgba(255,255,255,0.1)',
                    maxHeight: '400px',
                  }}>
                    <img
                      src={`data:image/png;base64,${computerScreenshot}`}
                      alt="Ecran en direct"
                      style={{ width: '100%', height: 'auto', display: 'block' }}
                    />
                  </div>
                )}

                {/* Agent Thinking */}
                {computerThinking && (
                  <div style={{
                    padding: '0.5rem 0.75rem',
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: '8px',
                    fontSize: '0.83rem',
                    color: 'var(--text-secondary)',
                    fontStyle: 'italic',
                  }}>
                    {computerThinking}
                  </div>
                )}

                {/* Action Log */}
                {computerActions.length > 0 && (
                  <div style={{
                    maxHeight: '120px',
                    overflowY: 'auto',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '2px',
                  }}>
                    {computerActions.slice(-5).map((a, i) => (
                      <div key={i} style={{
                        fontSize: '0.75rem',
                        color: 'var(--text-tertiary)',
                        display: 'flex',
                        gap: '0.5rem',
                      }}>
                        <span style={{ color: 'rgba(212, 160, 23, 0.6)', fontFamily: 'monospace' }}>{a.time}</span>
                        <span>{a.action}</span>
                        {a.params.coordinate && <span>({a.params.coordinate.join(', ')})</span>}
                        {a.params.text && <span>"{a.params.text.slice(0, 30)}{a.params.text.length > 30 ? '...' : ''}"</span>}
                      </div>
                    ))}
                  </div>
                )}

                {/* Confirmation Dialog */}
                {computerConfirmation && (
                  <div style={{
                    padding: '0.75rem 1rem',
                    background: 'rgba(255, 160, 0, 0.1)',
                    border: '1px solid rgba(255, 160, 0, 0.3)',
                    borderRadius: '8px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.5rem',
                  }}>
                    <div style={{ fontSize: '0.85rem', color: '#ffa000', fontWeight: 600 }}>
                      Confirmation requise
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      {computerConfirmation.reason}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
                      Action: {computerConfirmation.action}
                      {computerConfirmation.params.text && ` — "${computerConfirmation.params.text.slice(0, 50)}"`}
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem' }}>
                      <button
                        onClick={() => handleComputerConfirm(true)}
                        style={{
                          flex: 1,
                          padding: '6px 12px',
                          background: 'rgba(76, 175, 80, 0.2)',
                          border: '1px solid rgba(76, 175, 80, 0.4)',
                          borderRadius: '6px',
                          color: '#4caf50',
                          cursor: 'pointer',
                          fontSize: '0.8rem',
                        }}
                      >
                        Autoriser
                      </button>
                      <button
                        onClick={() => handleComputerConfirm(false)}
                        style={{
                          flex: 1,
                          padding: '6px 12px',
                          background: 'rgba(255, 80, 80, 0.15)',
                          border: '1px solid rgba(255, 80, 80, 0.3)',
                          borderRadius: '6px',
                          color: '#ff5050',
                          cursor: 'pointer',
                          fontSize: '0.8rem',
                        }}
                      >
                        Refuser
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
            {/* Simple spinner fallback when no steps yet */}
            {sending3 && streamSteps.length === 0 && (
              <div style={{ display: 'flex', justifyContent: 'flex-start', animation: 'agent-msg-in 0.3s ease forwards', flexShrink: 0 }}>
                <div className="agent3-agent-bubble" style={{
                  padding: '0.75rem 1.25rem', borderRadius: '16px 16px 16px 4px',
                  background: 'rgba(255,255,255,0.06)', borderLeft: '3px solid',
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                }}>
                  <span className="spinner spinner-sm" />
                  <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>{t('agents.thinking')}</span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef3} />
          </div>

          {/* Input bar */}
          <div style={{
            padding: '0.75rem 1.25rem', borderTop: '1px solid var(--border)',
            background: 'rgba(3,7,15,0.6)', backdropFilter: 'blur(12px)',
            display: 'flex', alignItems: 'center', gap: '0.5rem',
            position: 'relative',
          }}>
            {/* Recording indicator with countdown */}
            {isRecording3 && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '0.4rem',
                padding: '0.3rem 0.6rem', borderRadius: '999px',
                background: 'rgba(212,160,23,0.12)', border: '1px solid rgba(212,160,23,0.3)',
                position: 'absolute', top: '-2.5rem', left: '50%', transform: 'translateX(-50%)',
                zIndex: 10,
              }}>
                <span className="agent3-recording" style={{
                  width: 8, height: 8, borderRadius: '50%',
                  animation: 'recording-dot-pulse 1s ease-in-out infinite',
                }} />
                <span className="agent3-text-glow" style={{ fontSize: '0.72rem', fontWeight: 600 }}>
                  Enregistrement... {formatRecordingTime(recordingTime3)}
                </span>
              </div>
            )}

            {/* Upload file button */}
            <input
              type="file"
              id="agent3-file-upload"
              style={{ display: 'none' }}
              accept=".pdf,.csv,.txt,.json,.md,.png,.jpg,.jpeg,.gif,.webp,.xlsx,.xls"
              onChange={async (e) => {
                const file = e.target.files?.[0]
                if (!file) return
                const formData = new FormData()
                formData.append('file', file)
                try {
                  const r = await fetch(`${API}/api/agent3/upload`, { method: 'POST', body: formData })
                  const d = await r.json()
                  if (d.success) {
                    setInputText3((prev: string) => prev + (prev ? ' ' : '') + `[Fichier: ${d.filename}]`)
                    setActionToast(`Fichier "${d.filename}" uploade`)
                    setTimeout(() => setActionToast(null), 3000)
                    // Refresh workspace info
                    if (d.workspace_filepath) {
                      const tkn = localStorage.getItem('sylea_auth_token')
                      if (tkn) {
                        fetch(`${API}/api/agent3/workspace-info`, { headers: { 'Authorization': `Bearer ${tkn}` } })
                          .then(r => r.json()).then(data => setWorkspaceInfo(data)).catch(() => {})
                      }
                    }
                  } else {
                    setActionToast(d.error || 'Erreur upload')
                    setTimeout(() => setActionToast(null), 3000)
                  }
                } catch { setActionToast('Erreur upload'); setTimeout(() => setActionToast(null), 3000) }
                e.target.value = ''
              }}
            />
            <button
              onClick={() => document.getElementById('agent3-file-upload')?.click()}
              disabled={sending3}
              title="Joindre un fichier"
              style={{
                width: 36, height: 36, borderRadius: '50%', border: 'none',
                background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)',
                cursor: sending3 ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.15s', flexShrink: 0,
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(212,160,23,0.15)'; e.currentTarget.style.color = '#d4a017' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.06)'; e.currentTarget.style.color = 'var(--text-muted)' }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
              </svg>
            </button>

            <input
              ref={inputRef3}
              type="text"
              value={inputText3}
              onChange={e => setInputText3(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend3() } }}
              placeholder={isRecording3 ? 'Parlez maintenant...' : 'Demande-moi quelque chose...'}
              disabled={isRecording3}
              style={{
                flex: 1, background: isRecording3 ? 'rgba(212,160,23,0.06)' : 'rgba(255,255,255,0.06)',
                border: isRecording3 ? '1px solid rgba(212,160,23,0.3)' : '1px solid var(--border)',
                borderRadius: '24px', padding: '0.65rem 1rem', color: 'var(--text-primary)',
                fontSize: '0.88rem', outline: 'none', transition: 'all 0.2s',
              }}
              onFocus={e => { if (!isRecording3) e.currentTarget.style.borderColor = 'rgba(212,160,23,0.5)' }}
              onBlur={e => { if (!isRecording3) e.currentTarget.style.borderColor = 'var(--border)' }}
            />

            {/* Microphone button (animated blue+gold for Agent 3) */}
            <button
              onClick={toggleRecording3}
              disabled={sending3}
              title={isRecording3 ? "Arreter l'enregistrement" : "Enregistrement vocal"}
              className={isRecording3 ? 'agent3-recording' : ''}
              style={{
                width: 40, height: 40, borderRadius: '50%', border: 'none',
                background: isRecording3 ? 'rgba(212,160,23,0.2)' : 'rgba(255,255,255,0.06)',
                color: isRecording3 ? undefined : 'var(--text-muted)',
                cursor: sending3 ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.15s', flexShrink: 0,
                animation: isRecording3 ? undefined : 'none',
              }}
              onMouseEnter={e => {
                if (!isRecording3) {
                  e.currentTarget.style.background = 'rgba(212,160,23,0.12)'
                  e.currentTarget.style.color = '#d4a017'
                }
              }}
              onMouseLeave={e => {
                if (!isRecording3) {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.06)'
                  e.currentTarget.style.color = 'var(--text-muted)'
                }
              }}
            >
              {isRecording3 ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="4" y="4" width="16" height="16" rx="2" />
                </svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="1" width="6" height="11" rx="3" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" y1="19" x2="12" y2="23" />
                  <line x1="8" y1="23" x2="16" y2="23" />
                </svg>
              )}
            </button>

            {/* Computer Use toggle */}
            <button
              onClick={() => {
                if (computerUseActive) {
                  handleComputerAbort()
                } else {
                  setComputerUseMode(prev => !prev)
                }
              }}
              title={computerUseActive ? "Arreter Computer Use" : computerUseMode ? "Mode Computer Use actif" : "Activer Computer Use"}
              style={{
                background: computerUseMode || computerUseActive ? 'rgba(212, 160, 23, 0.2)' : 'transparent',
                border: computerUseMode || computerUseActive ? '1px solid rgba(212, 160, 23, 0.5)' : '1px solid rgba(255,255,255,0.1)',
                borderRadius: '8px',
                padding: '6px 8px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                color: computerUseMode || computerUseActive ? '#d4a017' : 'var(--text-secondary)',
                fontSize: '0.8rem',
                transition: 'all 0.2s',
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
                <line x1="8" y1="21" x2="16" y2="21"/>
                <line x1="12" y1="17" x2="12" y2="21"/>
              </svg>
              {computerUseActive && <span style={{ fontSize: '0.7rem' }}>LIVE</span>}
            </button>

            {/* Send button (GOLD gradient for Agent 3) */}
            <button
              onClick={() => handleSend3()}
              disabled={!inputText3.trim() || sending3}
              style={{
                width: 40, height: 40, borderRadius: '50%', border: 'none',
                background: inputText3.trim() && !sending3
                  ? 'linear-gradient(135deg, #d4a017, #f59e0b)'
                  : 'rgba(255,255,255,0.06)',
                color: inputText3.trim() && !sending3 ? '#050810' : 'var(--text-muted)',
                cursor: inputText3.trim() && !sending3 ? 'pointer' : 'not-allowed',
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

          {/* ── Workspace reference label (permanent, no close button) ── */}
          {workspaceInfo?.exists && (
            <div style={{
              padding: '0.25rem 1.25rem 0.35rem',
              background: 'rgba(3,7,15,0.3)',
              display: 'flex', alignItems: 'center', gap: '0.35rem',
            }}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0, opacity: 0.7 }}>
                <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
              </svg>
              <span style={{
                fontSize: '0.6rem', color: 'var(--text-muted)', opacity: 0.7,
                fontFamily: "'Fira Code', monospace",
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {workspaceInfo.path}
              </span>
              <span style={{ fontSize: '0.55rem', color: 'rgba(16,185,129,0.5)' }}>
                ({workspaceInfo.file_count} fichier{(workspaceInfo.file_count || 0) > 1 ? 's' : ''})
              </span>
            </div>
          )}
        </div>

        {/* ── CRON Management Panel ── */}
        {showCronPanel && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1500, display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'agent-msg-in 0.2s ease' }}
            onClick={() => setShowCronPanel(false)}>
            <div onClick={e => e.stopPropagation()} style={{
              width: '90%', maxWidth: 520, maxHeight: '80vh', borderRadius: '16px',
              background: 'rgba(10,15,30,0.98)', border: '1px solid rgba(212,160,23,0.2)',
              boxShadow: '0 16px 48px rgba(0,0,0,0.5)', overflow: 'hidden', display: 'flex', flexDirection: 'column',
            }}>
              <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid rgba(212,160,23,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)' }}>Taches planifiees</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.06)', padding: '0.1rem 0.4rem', borderRadius: '999px' }}>{cronList.length}</span>
                </div>
                <button onClick={() => setShowCronPanel(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.2rem' }}>×</button>
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '0.75rem 1rem' }}>
                {cronLoading ? (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}><span className="spinner spinner-sm" /></div>
                ) : cronList.length === 0 ? (
                  <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem', padding: '2rem 0' }}>Aucune tache planifiee. Demande a l'Agent 3 d'en creer une !</p>
                ) : cronList.map(cron => (
                  <div key={cron.id} style={{
                    padding: '0.75rem', borderRadius: '10px', marginBottom: '0.5rem',
                    background: cron.enabled ? 'rgba(212,160,23,0.06)' : 'rgba(255,255,255,0.03)',
                    border: `1px solid ${cron.enabled ? 'rgba(212,160,23,0.15)' : 'rgba(255,255,255,0.06)'}`,
                    opacity: cron.enabled ? 1 : 0.6,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.3rem' }}>
                      <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>{cron.label}</span>
                      <div style={{ display: 'flex', gap: '0.3rem' }}>
                        <button onClick={async () => {
                          try { const r = await api.agent3RunCron(cron.id); setActionToast(r.success ? 'Tache executee !' : 'Erreur execution'); } catch { setActionToast('Erreur'); }
                          setTimeout(() => setActionToast(null), 3000)
                        }} title="Executer maintenant" style={{ width: 26, height: 26, borderRadius: '6px', border: 'none', background: 'rgba(34,197,94,0.12)', color: '#22c55e', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                        </button>
                        <button onClick={async () => {
                          try { const r = await api.agent3ToggleCron(cron.id); setCronList(prev => prev.map(c => c.id === cron.id ? { ...c, enabled: r.enabled } : c)); } catch { setActionToast('Erreur de connexion'); setTimeout(() => setActionToast(null), 4000) }
                        }} title={cron.enabled ? 'Desactiver' : 'Activer'} style={{ width: 26, height: 26, borderRadius: '6px', border: 'none', background: cron.enabled ? 'rgba(251,191,36,0.12)' : 'rgba(255,255,255,0.06)', color: cron.enabled ? '#fbbf24' : 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          {cron.enabled ? (
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                          ) : (
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                          )}
                        </button>
                        <button onClick={async () => {
                          try { await api.agent3DeleteCron(cron.id); setCronList(prev => prev.filter(c => c.id !== cron.id)); setActionToast('Tache supprimee'); } catch { setActionToast('Erreur suppression'); }
                          setTimeout(() => setActionToast(null), 3000)
                        }} title="Supprimer" style={{ width: 26, height: 26, borderRadius: '6px', border: 'none', background: 'rgba(239,68,68,0.12)', color: '#ef4444', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                      </div>
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '0.2rem' }}>{cron.instruction}</div>
                    <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                      <span style={{ background: 'rgba(251,191,36,0.1)', padding: '0.1rem 0.35rem', borderRadius: '4px', color: '#fbbf24', fontFamily: "'Fira Code', monospace" }}>{cron.cron_expr}</span>
                      {cron.last_run && <span>Derniere exec: {new Date(cron.last_run).toLocaleString('fr-FR')}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Memory Management Panel ── */}
        {showMemoryPanel && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1500, display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'agent-msg-in 0.2s ease' }}
            onClick={() => setShowMemoryPanel(false)}>
            <div onClick={e => e.stopPropagation()} style={{
              width: '90%', maxWidth: 520, maxHeight: '80vh', borderRadius: '16px',
              background: 'rgba(10,15,30,0.98)', border: '1px solid rgba(212,160,23,0.2)',
              boxShadow: '0 16px 48px rgba(0,0,0,0.5)', overflow: 'hidden', display: 'flex', flexDirection: 'column',
            }}>
              <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid rgba(212,160,23,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#d4a017" strokeWidth="2" strokeLinecap="round"><path d="M12 2a10 10 0 0 1 10 10c0 5.52-4.48 10-10 10S2 17.52 2 12 6.48 2 12 2z"/><circle cx="12" cy="12" r="3"/></svg>
                  <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)' }}>Memoires Agent 3</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.06)', padding: '0.1rem 0.4rem', borderRadius: '999px' }}>{memoryList.length}</span>
                </div>
                <button onClick={() => setShowMemoryPanel(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.2rem' }}>×</button>
              </div>
              {/* Search */}
              <div style={{ padding: '0.5rem 1rem' }}>
                <input
                  type="text" placeholder="Rechercher..." value={memorySearch}
                  onChange={e => setMemorySearch(e.target.value)}
                  style={{
                    width: '100%', padding: '0.45rem 0.75rem', borderRadius: '8px',
                    background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border)',
                    color: 'var(--text-primary)', fontSize: '0.8rem', outline: 'none',
                  }}
                />
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '0 1rem 0.75rem' }}>
                {memoryLoading ? (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}><span className="spinner spinner-sm" /></div>
                ) : memoryList.filter(m => !memorySearch || m.key.toLowerCase().includes(memorySearch.toLowerCase()) || m.value.toLowerCase().includes(memorySearch.toLowerCase())).length === 0 ? (
                  <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem', padding: '2rem 0' }}>Aucune memoire enregistree.</p>
                ) : memoryList.filter(m => !memorySearch || m.key.toLowerCase().includes(memorySearch.toLowerCase()) || m.value.toLowerCase().includes(memorySearch.toLowerCase())).map((mem, i) => (
                  <div key={i} style={{
                    padding: '0.6rem 0.75rem', borderRadius: '8px', marginBottom: '0.4rem',
                    background: 'rgba(212,160,23,0.04)', border: '1px solid rgba(212,160,23,0.1)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: '0.78rem', fontWeight: 600, color: '#d4a017' }}>{mem.key}</span>
                      <button onClick={async () => {
                        try { await api.agent3DeleteMemory(mem.key); setMemoryList(prev => prev.filter(m => m.key !== mem.key)); setActionToast('Memoire supprimee'); } catch { setActionToast('Erreur'); }
                        setTimeout(() => setActionToast(null), 3000)
                      }} style={{ width: 22, height: 22, borderRadius: '4px', border: 'none', background: 'rgba(239,68,68,0.1)', color: '#ef4444', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                      </button>
                    </div>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0.2rem 0 0', lineHeight: 1.4 }}>{mem.value}</p>
                    {mem.category && <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.04)', padding: '0.1rem 0.3rem', borderRadius: '3px', marginTop: '0.2rem', display: 'inline-block' }}>{mem.category}</span>}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Files Management Panel ── */}
        {showFilesPanel && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1500, display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'agent-msg-in 0.2s ease' }}
            onClick={() => setShowFilesPanel(false)}>
            <div onClick={e => e.stopPropagation()} style={{
              width: '90%', maxWidth: 520, maxHeight: '80vh', borderRadius: '16px',
              background: 'rgba(10,15,30,0.98)', border: '1px solid rgba(34,197,94,0.2)',
              boxShadow: '0 16px 48px rgba(0,0,0,0.5)', overflow: 'hidden', display: 'flex', flexDirection: 'column',
            }}>
              <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid rgba(34,197,94,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2" strokeLinecap="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                  <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)' }}>Fichiers uploades</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.06)', padding: '0.1rem 0.4rem', borderRadius: '999px' }}>{filesList.length}</span>
                </div>
                <button onClick={() => setShowFilesPanel(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.2rem' }}>×</button>
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '0.75rem 1rem' }}>
                {filesLoading ? (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}><span className="spinner spinner-sm" /></div>
                ) : filesList.length === 0 ? (
                  <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem', padding: '2rem 0' }}>Aucun fichier uploade.</p>
                ) : filesList.map(file => (
                  <div key={file.id} style={{
                    padding: '0.6rem 0.75rem', borderRadius: '8px', marginBottom: '0.4rem',
                    background: 'rgba(34,197,94,0.04)', border: '1px solid rgba(34,197,94,0.1)',
                    display: 'flex', alignItems: 'center', gap: '0.6rem',
                  }}>
                    <div style={{
                      width: 32, height: 32, borderRadius: '8px',
                      background: 'rgba(34,197,94,0.12)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                    }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{file.filename}</div>
                      <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>
                        {file.filetype} — {(file.filesize / 1024).toFixed(1)} Ko — {new Date(file.created_at).toLocaleDateString('fr-FR')}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Tools Diagnostics Panel ── */}
        {showToolsPanel && (
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 1500, display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'agent-msg-in 0.2s ease' }}
            onClick={() => setShowToolsPanel(false)}>
            <div onClick={e => e.stopPropagation()} style={{
              width: '90%', maxWidth: 560, maxHeight: '80vh', borderRadius: '16px',
              background: 'rgba(10,15,30,0.98)', border: '1px solid rgba(167,139,250,0.2)',
              boxShadow: '0 16px 48px rgba(0,0,0,0.5)', overflow: 'hidden', display: 'flex', flexDirection: 'column',
            }}>
              <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid rgba(167,139,250,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" strokeWidth="2" strokeLinecap="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
                  <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)' }}>Diagnostics outils</span>
                </div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                  <button onClick={() => { setToolsLoading(true); api.agent3TestTools().then(setToolsResult).catch(() => { setActionToast('Erreur de connexion'); setTimeout(() => setActionToast(null), 4000) }).finally(() => setToolsLoading(false)) }}
                    style={{ padding: '0.3rem 0.6rem', borderRadius: '6px', border: 'none', background: 'rgba(167,139,250,0.15)', color: '#a78bfa', fontSize: '0.72rem', fontWeight: 600, cursor: 'pointer' }}>
                    Relancer
                  </button>
                  <button onClick={() => setShowToolsPanel(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.2rem' }}>×</button>
                </div>
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '0.75rem 1rem' }}>
                {toolsLoading ? (
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '2rem', gap: '0.5rem' }}>
                    <span className="spinner spinner-sm" />
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Test des outils en cours...</span>
                  </div>
                ) : !toolsResult ? (
                  <p style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem', padding: '2rem 0' }}>Aucun resultat.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                    {/* Summary */}
                    {toolsResult.summary && (
                      <div style={{ padding: '0.5rem 0.75rem', borderRadius: '8px', background: 'rgba(212,160,23,0.06)', border: '1px solid rgba(212,160,23,0.12)', marginBottom: '0.3rem' }}>
                        <span style={{ fontSize: '0.8rem', fontWeight: 700, color: toolsResult.all_working ? '#22c55e' : '#f59e0b' }}>{toolsResult.summary}</span>
                      </div>
                    )}
                    {/* Tools list */}
                    {toolsResult.tools && Object.entries(toolsResult.tools).map(([tool, result]: [string, any]) => (
                      <div key={tool} style={{
                        padding: '0.5rem 0.75rem', borderRadius: '8px',
                        background: result?.working ? 'rgba(34,197,94,0.05)' : 'rgba(239,68,68,0.05)',
                        border: `1px solid ${result?.working ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)'}`,
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                      }}>
                        {result?.working ? (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                        ) : (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="3" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        )}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <span style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-primary)', fontFamily: "'Fira Code', monospace" }}>{tool}</span>
                            {result?.label && <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>— {result.label}</span>}
                            {result?.version && <span className="agent3-text-glow" style={{ fontSize: '0.62rem', background: 'rgba(212,160,23,0.1)', padding: '0.05rem 0.3rem', borderRadius: '3px' }}>{result.version}</span>}
                          </div>
                          {result?.error && !result?.working && (
                            <div style={{ fontSize: '0.65rem', color: '#ef4444', marginTop: '0.15rem', opacity: 0.8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {String(result.error).substring(0, 80)}
                            </div>
                          )}
                        </div>
                        <span style={{ fontSize: '0.7rem', fontWeight: 600, color: result?.working ? '#22c55e' : '#ef4444', flexShrink: 0 }}>
                          {result?.working ? 'OK' : 'Echec'}
                        </span>
                      </div>
                    ))}
                    {/* Circuit breaker */}
                    {toolsResult.circuit_breaker && (
                      <div style={{ marginTop: '0.5rem', padding: '0.5rem 0.75rem', borderRadius: '8px', background: 'rgba(212,160,23,0.06)', border: '1px solid rgba(212,160,23,0.15)' }}>
                        <div className="agent3-text-glow" style={{ fontSize: '0.72rem', fontWeight: 600, marginBottom: '0.2rem' }}>Circuit Breaker</div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          Etat: <strong style={{ color: toolsResult.circuit_breaker.state === 'closed' ? '#22c55e' : '#ef4444' }}>{toolsResult.circuit_breaker.state}</strong>
                          {' — '}Echecs: {toolsResult.circuit_breaker.failure_count}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

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

  // ── Agent 2 Chat view ────────────────────────────────────────────────────
  if (AGENT2_ENABLED && chat2Open) {
    return (
      <div className="page animate-fade-in" style={{ flex: 1, height: 'calc(100vh - 3.5rem - 3rem)', minHeight: 0, maxHeight: 'calc(100vh - 3.5rem - 3rem)', overflow: 'hidden' }}>
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
          @keyframes toast-in {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
          }
        `}</style>
        <div className="container" style={{ maxWidth: 680, margin: '0 auto', padding: '0', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
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

            {/* Voice auto-play toggle */}
            {isTTSSupported() && (
              <button
                onClick={() => setVoiceEnabled2(v => !v)}
                title={voiceEnabled2 ? 'Desactiver la voix automatique' : 'Activer la voix automatique'}
                style={{
                  display: 'flex', alignItems: 'center', gap: '0.35rem',
                  padding: '0.3rem 0.65rem', borderRadius: '999px',
                  border: voiceEnabled2 ? '1px solid rgba(239,68,68,0.4)' : '1px solid var(--border)',
                  background: voiceEnabled2 ? 'rgba(239,68,68,0.12)' : 'rgba(255,255,255,0.04)',
                  color: voiceEnabled2 ? '#f87171' : 'var(--text-muted)',
                  cursor: 'pointer', fontSize: '0.72rem', fontWeight: 600,
                  transition: 'all 0.2s',
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                  {voiceEnabled2 ? (
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

            {/* Voice call button */}
            <button
              onClick={() => { setChat2Open(false); setInCall(true) }}
              title="Appeler l'Agent Sylea 2"
              style={{
                display: 'flex', alignItems: 'center', gap: '0.35rem',
                padding: '0.3rem 0.65rem', borderRadius: '999px',
                border: '1px solid rgba(239,68,68,0.3)',
                background: 'rgba(239,68,68,0.08)',
                color: '#f87171',
                cursor: 'pointer', fontSize: '0.72rem', fontWeight: 600,
                transition: 'all 0.2s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.15)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'rgba(239,68,68,0.08)' }}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2z" />
              </svg>
              Appeler
            </button>
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
              // Use pre-parsed actions from backend if available, otherwise parse from content
              const parsed = msg.role === 'agent' ? parseActions(msg.content) : { text: msg.content, actions: [] }
              const msgText = parsed.text
              const actions = (msg.actions && msg.actions.length > 0)
                ? msg.actions as AgentAction[]
                : parsed.actions
              return (
                <div key={idx} style={{
                  display: 'flex',
                  justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  animation: 'agent-msg-in 0.3s ease forwards',
                }}>
                  <div style={{ maxWidth: '80%' }}>
                    {/* Use VoiceMessageBubble for voice messages */}
                    {msg.type === 'voice' ? (
                      <VoiceMessageBubble
                        msg={msg}
                        isAgent={msg.role === 'agent'}
                        onSpeakToggle={() => handleSpeakMessage2(msg.content, idx)}
                        isSpeaking={speakingMsgIdx2 === idx}
                        agentColor="#ef4444"
                      />
                    ) : msgText ? (
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
                        <div style={{ margin: 0 }}>{msg.role === 'agent' ? renderFormattedText(msgText) : <p style={{ margin: 0 }}>{msgText}</p>}</div>
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
                              onClick={() => handleSpeakMessage2(msg.content, idx)}
                              title="Ecouter ce message"
                              style={{
                                background: 'none', border: 'none', cursor: 'pointer',
                                padding: '2px', display: 'flex', alignItems: 'center',
                                color: speakingMsgIdx2 === idx ? '#f87171' : 'inherit',
                                opacity: speakingMsgIdx2 === idx ? 1 : 0.6,
                                transition: 'all 0.15s',
                              }}
                              onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                              onMouseLeave={e => { if (speakingMsgIdx2 !== idx) e.currentTarget.style.opacity = '0.6' }}
                            >
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                                <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                              </svg>
                            </button>
                          )}
                        </div>
                      </div>
                    ) : null}
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
                                background: 'linear-gradient(135deg, #ea4335, #d93025)', color: '#fff', fontSize: '0.78rem',
                                fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
                                display: 'flex', alignItems: 'center', gap: '0.4rem',
                              }}>
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 7l-10 7L2 7"/></svg>
                                Ouvrir dans Gmail
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
                            <div style={{ fontSize: '0.72rem', color: '#f87171', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                              {action.data.title}
                            </div>
                            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: '0 0 0.5rem', lineHeight: 1.4, maxHeight: '4rem', overflow: 'hidden' }}>
                              {action.data.content?.substring(0, 200)}...
                            </p>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                              <button onClick={() => handleAction(action)} style={{
                                padding: '0.4rem 1rem', borderRadius: '8px', border: 'none',
                                background: 'linear-gradient(135deg, #b91c1c, #ef4444)', color: '#fff',
                                fontSize: '0.78rem', fontWeight: 600, cursor: 'pointer',
                                display: 'flex', alignItems: 'center', gap: '0.3rem',
                              }}>
                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
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
                            <div style={{ fontSize: '0.72rem', color: '#f87171', fontWeight: 700, marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                              Rappel
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                              <span style={{
                                padding: '0.2rem 0.5rem', borderRadius: '6px', fontSize: '0.72rem', fontWeight: 600,
                                background: 'rgba(251,191,36,0.12)', color: '#fbbf24', border: '1px solid rgba(251,191,36,0.25)',
                              }}>
                                {action.data.date} a {action.data.time}
                              </span>
                              <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                {action.data.message}
                              </span>
                            </div>
                            <button onClick={() => handleAction(action)} style={{
                              padding: '0.4rem 1rem', borderRadius: '8px', border: 'none',
                              background: '#22c55e', color: '#fff', fontSize: '0.78rem',
                              fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.3rem',
                            }}>
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>
                              Confirmer le rappel
                            </button>
                          </>
                        )}
                        {action.type === 'LINK' && (
                          <button onClick={() => handleAction(action)} style={{
                            width: '100%', padding: '0.5rem 0.75rem', borderRadius: '8px',
                            background: 'rgba(37,99,235,0.08)', border: '1px solid rgba(59,130,246,0.2)',
                            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem',
                            transition: 'all 0.15s', textAlign: 'left',
                          }}
                          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(37,99,235,0.15)' }}
                          onMouseLeave={e => { e.currentTarget.style.background = 'rgba(37,99,235,0.08)' }}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" strokeWidth="2" strokeLinecap="round">
                              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
                            </svg>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontSize: '0.78rem', color: '#60a5fa', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {action.data.label || 'Ouvrir le lien'}
                              </div>
                              <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {action.data.url}
                              </div>
                            </div>
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" strokeWidth="2.5" strokeLinecap="round"><polyline points="9 18 15 12 9 6"/></svg>
                          </button>
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
            position: 'relative',
          }}>
            {/* Recording indicator with countdown */}
            {isRecording2 && (
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
                  Enregistrement... {formatRecordingTime(recordingTime2)}
                </span>
              </div>
            )}

            <input
              ref={inputRef2}
              type="text"
              value={inputText2}
              onChange={e => setInputText2(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend2() } }}
              placeholder={isRecording2 ? 'Parlez maintenant...' : 'Demande-moi quelque chose...'}
              disabled={isRecording2}
              style={{
                flex: 1, background: isRecording2 ? 'rgba(239,68,68,0.06)' : 'rgba(255,255,255,0.06)',
                border: isRecording2 ? '1px solid rgba(239,68,68,0.3)' : '1px solid var(--border)',
                borderRadius: '24px', padding: '0.65rem 1rem', color: 'var(--text-primary)',
                fontSize: '0.88rem', outline: 'none', transition: 'all 0.2s',
              }}
              onFocus={e => { if (!isRecording2) e.currentTarget.style.borderColor = 'rgba(239,68,68,0.5)' }}
              onBlur={e => { if (!isRecording2) e.currentTarget.style.borderColor = 'var(--border)' }}
            />

            {/* Microphone button (RED for Agent 2) */}
            <button
              onClick={toggleRecording2}
              disabled={sending2}
              title={isRecording2 ? "Arreter l'enregistrement" : "Enregistrement vocal"}
              style={{
                width: 40, height: 40, borderRadius: '50%', border: 'none',
                background: isRecording2 ? 'rgba(239,68,68,0.2)' : 'rgba(255,255,255,0.06)',
                color: isRecording2 ? '#ef4444' : 'var(--text-muted)',
                cursor: sending2 ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.15s', flexShrink: 0,
                animation: isRecording2 ? 'recording-pulse 1.5s ease-in-out infinite' : 'none',
              }}
              onMouseEnter={e => {
                if (!isRecording2) {
                  e.currentTarget.style.background = 'rgba(239,68,68,0.15)'
                  e.currentTarget.style.color = '#f87171'
                }
              }}
              onMouseLeave={e => {
                if (!isRecording2) {
                  e.currentTarget.style.background = 'rgba(255,255,255,0.06)'
                  e.currentTarget.style.color = 'var(--text-muted)'
                }
              }}
            >
              {isRecording2 ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="4" y="4" width="16" height="16" rx="2" />
                </svg>
              ) : (
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
      <div className="page animate-fade-in" style={{ flex: 1, height: 'calc(100vh - 3.5rem - 3rem)', minHeight: 0, maxHeight: 'calc(100vh - 3.5rem - 3rem)', overflow: 'hidden' }}>
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
        <div className="container" style={{ maxWidth: 680, margin: '0 auto', padding: '0', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
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
                      <div style={{ margin: 0 }}>{msg.role === 'agent' ? renderFormattedText(msg.content) : <p style={{ margin: 0 }}>{msg.content}</p>}</div>
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

        {/* Agent 2 — horizontal card (hidden when AGENT2_ENABLED is false) */}
        {AGENT2_ENABLED && <div style={{
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
                <filter id="agent2-red-blur" x="-50%" y="-50%" width="200%" height="200%">
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
        </div>}

        {/* Agent 3 — horizontal card (blue & gold shimmering) */}
        <style>{`
          .agent3-title-shimmer {
            background: linear-gradient(90deg, #2563eb, #d4a017, #fbbf24, #2563eb, #1e3a5f, #2563eb);
            background-size: 300% 100%;
            -webkit-background-clip: text !important;
            background-clip: text !important;
            -webkit-text-fill-color: transparent !important;
            color: transparent !important;
            animation: agent3-name-flow 3s ease-in-out infinite;
          }
          @keyframes agent3-name-flow {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
          }
          .agent3-btn-shimmer {
            background: linear-gradient(90deg, #1e3a5f, #2563eb, #d4a017, #fbbf24, #2563eb, #1e3a5f) !important;
            background-size: 300% 100% !important;
            animation: agent3-btn-flow 3s ease-in-out infinite;
          }
          @keyframes agent3-btn-flow {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
          }
          /* ── Agent 3 animated message bubbles ── */
          .agent3-user-bubble {
            background: linear-gradient(135deg, #1e3a5f, #2563eb, #d4a017, #1e3a5f) !important;
            background-size: 300% 300% !important;
            animation: agent3-bubble-flow 4s ease-in-out infinite;
          }
          @keyframes agent3-bubble-flow {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
          }
          .agent3-agent-bubble {
            border-image: linear-gradient(180deg, #2563eb, #d4a017, #fbbf24, #2563eb) 1 !important;
            border-left: 3px solid !important;
            animation: agent3-border-glow 3s ease-in-out infinite;
          }
          @keyframes agent3-border-glow {
            0% { border-image: linear-gradient(180deg, #2563eb, #d4a017, #fbbf24, #2563eb) 1; }
            33% { border-image: linear-gradient(180deg, #fbbf24, #2563eb, #d4a017, #fbbf24) 1; }
            66% { border-image: linear-gradient(180deg, #d4a017, #fbbf24, #2563eb, #d4a017) 1; }
            100% { border-image: linear-gradient(180deg, #2563eb, #d4a017, #fbbf24, #2563eb) 1; }
          }
          .agent3-action-card {
            border: 1px solid transparent !important;
            background-clip: padding-box !important;
            position: relative !important;
          }
          .agent3-action-card::before {
            content: '';
            position: absolute; inset: -1px;
            border-radius: 13px;
            background: linear-gradient(135deg, #2563eb, #d4a017, #fbbf24, #2563eb);
            background-size: 300% 300%;
            animation: agent3-bubble-flow 4s ease-in-out infinite;
            z-index: -1;
            opacity: 0.4;
          }
          .agent3-voice-user {
            background: linear-gradient(135deg, #1e3a5f, #2563eb, #d4a017, #1e3a5f) !important;
            background-size: 300% 300% !important;
            animation: agent3-bubble-flow 4s ease-in-out infinite;
          }
          .agent3-voice-agent {
            border-left: 3px solid transparent !important;
            border-image: linear-gradient(180deg, #2563eb, #d4a017, #fbbf24, #2563eb) 1 !important;
            animation: agent3-border-glow 3s ease-in-out infinite;
          }
          .agent3-action-label {
            background: linear-gradient(90deg, #60a5fa, #d4a017, #fbbf24, #60a5fa);
            background-size: 300% 100%;
            -webkit-background-clip: text !important;
            background-clip: text !important;
            -webkit-text-fill-color: transparent !important;
            animation: agent3-name-flow 3s ease-in-out infinite;
          }
          .agent3-speaker-active {
            animation: agent3-speaker-pulse 1.5s ease-in-out infinite;
          }
          @keyframes agent3-speaker-pulse {
            0%,100% { color: #2563eb; }
            50% { color: #fbbf24; }
          }
          /* ── Agent 3 — animated waveform bars ── */
          .agent3-bar {
            animation: agent3-bar-color 3s ease-in-out infinite !important;
            transition: none !important;
          }
          .agent3-bar-dim {
            animation: agent3-bar-dim-color 3s ease-in-out infinite !important;
            transition: none !important;
          }
          @keyframes agent3-bar-color {
            0%,100% { background: #2563eb !important; }
            33% { background: #d4a017 !important; }
            66% { background: #fbbf24 !important; }
          }
          @keyframes agent3-bar-dim-color {
            0%,100% { background: rgba(37,99,235,0.25) !important; }
            33% { background: rgba(212,160,23,0.25) !important; }
            66% { background: rgba(251,191,36,0.25) !important; }
          }
          /* ── Agent 3 — animated play button ── */
          .agent3-play-btn {
            animation: agent3-play-bg 3s ease-in-out infinite !important;
          }
          @keyframes agent3-play-bg {
            0%,100% { background: #2563eb !important; }
            50% { background: #d4a017 !important; }
          }
          /* ── Agent 3 — animated text color ── */
          .agent3-text-glow {
            animation: agent3-text-color 3s ease-in-out infinite;
          }
          @keyframes agent3-text-color {
            0%,100% { color: #60a5fa; }
            50% { color: #fbbf24; }
          }
          /* ── Agent 3 — animated border ── */
          .agent3-border-glow {
            animation: agent3-border-color 3s ease-in-out infinite;
          }
          @keyframes agent3-border-color {
            0%,100% { border-color: rgba(37,99,235,0.3); }
            50% { border-color: rgba(212,160,23,0.3); }
          }
          /* ── Agent 3 — animated bg subtle ── */
          .agent3-bg-subtle {
            animation: agent3-bg-sub 3s ease-in-out infinite;
          }
          @keyframes agent3-bg-sub {
            0%,100% { background: rgba(37,99,235,0.08); }
            50% { background: rgba(212,160,23,0.08); }
          }
          /* ── Agent 3 — animated small btn ── */
          .agent3-small-btn {
            border: 1px solid rgba(37,99,235,0.3);
            background: rgba(37,99,235,0.08);
            animation: agent3-small-btn-anim 3s ease-in-out infinite;
          }
          @keyframes agent3-small-btn-anim {
            0%,100% { border-color: rgba(37,99,235,0.3); background: rgba(37,99,235,0.08); }
            50% { border-color: rgba(212,160,23,0.3); background: rgba(212,160,23,0.08); }
          }
          .agent3-small-btn:hover {
            border-color: rgba(251,191,36,0.5) !important;
            background: rgba(212,160,23,0.15) !important;
          }
          /* ── Agent 3 — animated card border ── */
          .agent3-card-active {
            animation: agent3-card-border 3s ease-in-out infinite;
          }
          @keyframes agent3-card-border {
            0%,100% {
              border-color: rgba(37,99,235,0.3);
              box-shadow: 0 2px 20px rgba(37,99,235,0.1);
            }
            50% {
              border-color: rgba(212,160,23,0.3);
              box-shadow: 0 2px 20px rgba(212,160,23,0.1);
            }
          }
          /* ── Agent 3 — animated recording ── */
          .agent3-recording {
            animation: agent3-rec 1.5s ease-in-out infinite;
          }
          @keyframes agent3-rec {
            0%,100% { color: #2563eb; }
            50% { color: #d4a017; }
          }
          /* ── Agent 3 — animated input focus ── */
          .agent3-input-focus:focus {
            border-color: rgba(212,160,23,0.5) !important;
            box-shadow: 0 0 0 2px rgba(37,99,235,0.15), 0 0 0 4px rgba(212,160,23,0.08) !important;
          }
        `}</style>
        <div className={active3 ? 'agent3-card-active' : ''} style={{
          display: 'flex', alignItems: 'center', gap: '1rem',
          background: active3
            ? 'linear-gradient(135deg, rgba(37,99,235,0.08), rgba(212,160,23,0.03), var(--bg-surface))'
            : 'var(--bg-surface)',
          border: active3 ? '1px solid rgba(37,99,235,0.3)' : '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          padding: '1rem 1.25rem',
          boxShadow: active3 ? '0 2px 20px rgba(37,99,235,0.1)' : '0 1px 8px rgba(0,0,0,0.15)',
          transition: 'all 0.3s',
          marginBottom: '0.75rem',
        }}>
          {/* Logo — blue+gold shimmering */}
          <div style={{ flexShrink: 0 }}>
            <svg width={48} height={48} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
              <defs>
                <linearGradient id="agent3-card-g" x1="0%" y1="100%" x2="100%" y2="0%">
                  <stop offset="0%">
                    <animate attributeName="stop-color" values="#1e3a5f;#d4a017;#1e3a5f" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="35%">
                    <animate attributeName="stop-color" values="#2563eb;#fbbf24;#2563eb" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="65%">
                    <animate attributeName="stop-color" values="#d4a017;#2563eb;#d4a017" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="100%">
                    <animate attributeName="stop-color" values="#fbbf24;#1e3a5f;#fbbf24" dur="3s" repeatCount="indefinite" />
                  </stop>
                </linearGradient>
                <linearGradient id="agent3-card-glow" x1="0%" y1="100%" x2="100%" y2="0%">
                  <stop offset="0%">
                    <animate attributeName="stop-color" values="#1e3a5f;#d4a017;#1e3a5f" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="50%">
                    <animate attributeName="stop-color" values="#2563eb;#fbbf24;#2563eb" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="100%">
                    <animate attributeName="stop-color" values="#fbbf24;#1e3a5f;#fbbf24" dur="3s" repeatCount="indefinite" />
                  </stop>
                </linearGradient>
                <linearGradient id="agent3-card-shine" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%">
                    <animate attributeName="stop-color" values="rgba(255,230,200,0.6);rgba(200,220,255,0.3);rgba(255,230,200,0.6)" dur="3s" repeatCount="indefinite" />
                  </stop>
                  <stop offset="100%">
                    <animate attributeName="stop-color" values="rgba(200,220,255,0.3);rgba(255,230,200,0.6);rgba(200,220,255,0.3)" dur="3s" repeatCount="indefinite" />
                  </stop>
                </linearGradient>
                <filter id="agent3-blur" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="20" />
                </filter>
              </defs>
              <path d={S_PATH} stroke="url(#agent3-card-glow)" strokeWidth="90" fill="none" strokeLinecap="round"
                style={{ filter: 'url(#agent3-blur)', opacity: 0.22 }} />
              <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
              <path d={S_PATH} stroke="url(#agent3-card-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
              <path d={S_PATH} stroke="url(#agent3-card-shine)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
            </svg>
          </div>

          {/* Text center */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.15rem' }}>
              <h3 className="agent3-title-shimmer" style={{
                fontSize: '1rem', fontWeight: 700, margin: 0,
              }}>
                Agent Sylea 3
              </h3>
              {/* OpenClaw status dot */}
              {active3 && (
                <span title={openclawConnected ? 'OpenClaw connecte' : 'OpenClaw deconnecte'} style={{
                  width: 7, height: 7, borderRadius: '50%',
                  background: openclawConnected ? '#4ade80' : '#ef4444',
                  display: 'inline-block', flexShrink: 0,
                  boxShadow: openclawConnected ? '0 0 6px rgba(74,222,128,0.5)' : '0 0 6px rgba(239,68,68,0.5)',
                }} />
              )}
            </div>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', margin: '0 0 0.25rem', lineHeight: 1.3 }}>
              Agent d'elite
            </p>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
              Execution de taches complexes, recherche approfondie, analyses detaillees, multi-tache.
            </p>
            {active3 && (
              <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', margin: '0.2rem 0 0', fontStyle: 'italic', opacity: 0.7 }}>
                {lastInteraction3}
              </p>
            )}
          </div>

          {/* Status + buttons right */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '0.4rem', flexShrink: 0 }}>
            {/* Status badge */}
            {active3 ? (
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
            {active3 ? (
              <>
                <div style={{ display: 'flex', gap: '0.4rem' }}>
                  <button
                    className="agent3-btn-shimmer"
                    onClick={openChat3}
                    style={{
                      padding: '0.55rem 1rem', borderRadius: 'var(--radius-md)',
                      border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.82rem',
                      color: '#fff', transition: 'all 0.2s', whiteSpace: 'nowrap',
                      boxShadow: '0 2px 10px rgba(212,160,23,0.3)',
                    }}
                    onMouseEnter={e => e.currentTarget.style.transform = 'translateY(-1px)'}
                    onMouseLeave={e => e.currentTarget.style.transform = 'translateY(0)'}
                  >
                    Discuter
                  </button>
                  <button
                    onClick={() => setInCall3(true)}
                    className="agent3-btn-shimmer"
                    style={{
                      padding: '0.55rem 0.8rem', borderRadius: 'var(--radius-md)',
                      border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.82rem',
                      color: '#fff', transition: 'all 0.2s', whiteSpace: 'nowrap',
                      boxShadow: '0 2px 10px rgba(212,160,23,0.3)',
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
                  onClick={() => setShowDeactivateModal3(true)}
                  className="agent3-small-btn agent3-text-glow"
                  style={{
                    borderRadius: 'var(--radius-md)', cursor: 'pointer',
                    fontSize: '0.78rem', fontWeight: 600,
                    padding: '0.4rem 1rem',
                    transition: 'all 0.15s', whiteSpace: 'nowrap',
                  }}
                >
                  Desactiver cet agent
                </button>
              </>
            ) : (
              <button
                className="agent3-btn-shimmer"
                onClick={() => setShowActivateModal3(true)}
                style={{
                  padding: '0.55rem 1.4rem', borderRadius: 'var(--radius-md)',
                  border: 'none', cursor: 'pointer', fontWeight: 700, fontSize: '0.85rem',
                  color: '#fff', transition: 'all 0.2s', whiteSpace: 'nowrap',
                  boxShadow: '0 2px 10px rgba(212,160,23,0.3)',
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
      {AGENT2_ENABLED && inCall && (
        <VoiceCall
          onEndCall={() => setInCall(false)}
          onMessage={handleVoiceCallMessage}
          agentColor="#ef4444"
          agentName="Agent Sylea 2"
          chatEndpoint={agent2ChatEndpoint}
        />
      )}

      {/* ── Voice Call overlay (Agent 3) ── */}
      {inCall3 && (
        <VoiceCall
          onEndCall={() => setInCall3(false)}
          onMessage={handleVoiceCallMessage3}
          agentColor="#2563eb"
          agentName="Agent Sylea 3"
          chatEndpoint={agent3ChatEndpoint}
        />
      )}

      {/* ── Activation modal ── */}
      {/* Modale conflit : un seul agent actif à la fois */}
      {conflictModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1100,
          background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{
            background: 'var(--bg-surface)', borderRadius: 'var(--radius-lg)',
            border: '1px solid rgba(239,68,68,0.3)', padding: '2rem',
            maxWidth: 420, width: '90%', textAlign: 'center',
          }}>
            <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>⚠️</div>
            <h3 style={{ color: 'var(--text-primary)', marginBottom: '0.75rem', fontSize: '1.1rem' }}>
              Un agent est deja actif
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem', lineHeight: 1.5, marginBottom: '1.5rem' }}>
              {conflictModal} est actuellement actif. Vous ne pouvez activer qu'un seul agent a la fois.
              Desactivez-le d'abord avant d'en activer un autre.
            </p>
            <button
              onClick={() => setConflictModal(null)}
              style={{
                padding: '0.6rem 1.5rem', borderRadius: 'var(--radius-md)',
                background: 'linear-gradient(135deg, #ef4444, #dc2626)', border: 'none',
                color: 'white', cursor: 'pointer', fontSize: '0.88rem', fontWeight: 600,
              }}
            >
              Compris
            </button>
          </div>
        </div>
      )}

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
      {AGENT2_ENABLED && showActivateModal2 && (
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
      {AGENT2_ENABLED && showDeactivateModal2 && (
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

      {/* ── Agent 3 Activation modal ── */}
      {showActivateModal3 && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          animation: 'fadeInScale 0.2s ease',
        }}
          onClick={() => setShowActivateModal3(false)}
        >
          <div className="agent3-border-glow" style={{
            background: 'var(--bg-card)', border: '1px solid rgba(212,160,23,0.25)',
            borderRadius: 'var(--radius-lg)', padding: '2rem', maxWidth: 420, width: '90%',
            boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          }}
            onClick={e => e.stopPropagation()}
          >
            <h3 className="agent3-title-shimmer" style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '0.75rem' }}>
              Activer l'Agent Sylea 3
            </h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: '1.5rem' }}>
              L'Agent Sylea 3 est votre agent d'elite capable d'executer des taches complexes :
              recherche approfondie, analyses detaillees et multi-tache avec OpenClaw.
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowActivateModal3(false)} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border)',
                color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.85rem',
                transition: 'all 0.15s',
              }}>
                {t('common.annuler')}
              </button>
              <button onClick={handleActivate3} className="agent3-btn-shimmer" style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                border: 'none',
                color: '#fff', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600,
                transition: 'all 0.15s',
              }}>
                Activer
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Agent 3 Setup Wizard ── */}
      {showSetupWizard3 && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1100,
          background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(10px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          animation: 'fadeInScale 0.3s ease',
        }}>
          <div style={{
            background: 'var(--bg-card)', border: '1px solid rgba(212,160,23,0.3)',
            borderRadius: '1.25rem', padding: '2rem 2.25rem', maxWidth: 520, width: '92%',
            boxShadow: '0 12px 60px rgba(212,160,23,0.15), 0 0 40px rgba(37,99,235,0.08)',
            position: 'relative', overflow: 'hidden',
          }}>
            {/* Shimmer bar at top */}
            <div style={{
              position: 'absolute', top: 0, left: 0, right: 0, height: 3,
              background: 'linear-gradient(90deg, #1e3a5f, #2563eb, #d4a017, #fbbf24, #2563eb, #1e3a5f)',
              backgroundSize: '300% 100%',
              animation: 'agent3-btn-flow 3s ease-in-out infinite',
            }} />

            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.5rem' }}>
              <div style={{
                width: 42, height: 42, borderRadius: '50%',
                background: 'linear-gradient(135deg, #1e3a5f, #2563eb)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: '0 0 20px rgba(212,160,23,0.3)',
              }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" strokeWidth="2">
                  <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
                </svg>
              </div>
              <div>
                <h3 className="agent3-title-shimmer" style={{ fontSize: '1.15rem', fontWeight: 700, margin: 0 }}>
                  Installation Agent Sylea 3
                </h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', margin: 0 }}>
                  Configuration automatique d'OpenClaw
                </p>
              </div>
              <button onClick={() => setShowSetupWizard3(false)} style={{
                marginLeft: 'auto', background: 'none', border: 'none',
                color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.3rem', padding: '0.25rem',
              }}>×</button>
            </div>

            {/* Progress bar global */}
            <div style={{
              background: 'rgba(255,255,255,0.06)', borderRadius: 99, height: 6,
              marginBottom: '1.75rem', overflow: 'hidden',
            }}>
              <div style={{
                height: '100%', borderRadius: 99, transition: 'width 0.6s ease',
                width: `${setupStep === 0 ? 5 : setupStep === 1 ? 30 : setupStep === 2 ? 60 : setupStep === 3 ? 85 : 100}%`,
                background: 'linear-gradient(90deg, #2563eb, #d4a017, #fbbf24)',
                boxShadow: '0 0 12px rgba(212,160,23,0.5)',
              }} />
            </div>

            {/* Steps indicator */}
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1.5rem', padding: '0 0.25rem' }}>
              {['Verification', 'Installation', 'Configuration', 'Connexion'].map((label, i) => (
                <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.35rem', flex: 1 }}>
                  <div style={{
                    width: 28, height: 28, borderRadius: '50%',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '0.75rem', fontWeight: 700, transition: 'all 0.4s',
                    background: i < setupStep ? 'linear-gradient(135deg, #2563eb, #d4a017)'
                      : i === setupStep ? 'linear-gradient(135deg, #1e3a5f, #2563eb)'
                      : 'rgba(255,255,255,0.06)',
                    color: i <= setupStep ? '#fff' : 'var(--text-muted)',
                    border: i === setupStep ? '2px solid #fbbf24' : '2px solid transparent',
                    boxShadow: i === setupStep ? '0 0 12px rgba(251,191,36,0.4)' : 'none',
                  }}>
                    {i < setupStep ? '✓' : i + 1}
                  </div>
                  <span style={{
                    fontSize: '0.65rem', color: i <= setupStep ? '#d4a017' : 'var(--text-muted)',
                    fontWeight: i === setupStep ? 600 : 400, textAlign: 'center',
                  }}>{label}</span>
                </div>
              ))}
            </div>

            {/* Step content */}
            <div style={{
              background: 'rgba(255,255,255,0.03)', borderRadius: '0.75rem',
              padding: '1.25rem', marginBottom: '1.25rem', minHeight: 140,
              border: '1px solid rgba(212,160,23,0.1)',
            }}>
              {/* Step 0: Verification */}
              {setupStep === 0 && (
                <div>
                  <p style={{ fontSize: '0.9rem', color: 'var(--text-primary)', fontWeight: 600, marginBottom: '1rem' }}>
                    Verification de votre systeme...
                  </p>
                  {setupStatus.node_installed !== undefined ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                        <span style={{ color: setupStatus.node_installed ? '#22c55e' : '#ef4444' }}>
                          {setupStatus.node_installed ? '✅' : '❌'}
                        </span>
                        <span style={{ color: 'var(--text-secondary)' }}>
                          Node.js {setupStatus.node_installed ? setupStatus.node_version : '— Non installe'}
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                        <span style={{ color: setupStatus.openclaw_installed ? '#22c55e' : '#f59e0b' }}>
                          {setupStatus.openclaw_installed ? '✅' : '⏳'}
                        </span>
                        <span style={{ color: 'var(--text-secondary)' }}>
                          OpenClaw {setupStatus.openclaw_installed ? setupStatus.openclaw_version || 'installe' : '— A installer'}
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                        <span style={{ color: setupStatus.gateway_running ? '#22c55e' : '#f59e0b' }}>
                          {setupStatus.gateway_running ? '✅' : '⏳'}
                        </span>
                        <span style={{ color: 'var(--text-secondary)' }}>
                          Gateway {setupStatus.gateway_running ? 'en cours d\'execution' : '— A demarrer'}
                        </span>
                      </div>
                      {!setupStatus.node_installed && (
                        <div style={{
                          marginTop: '0.75rem', padding: '0.75rem', borderRadius: '0.5rem',
                          background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)',
                        }}>
                          <p style={{ fontSize: '0.8rem', color: '#fca5a5', margin: 0 }}>
                            Node.js est requis. <a href="https://nodejs.org" target="_blank" rel="noopener"
                              style={{ color: '#d4a017', textDecoration: 'underline' }}>
                              Telecharger Node.js
                            </a> puis relancez la verification.
                          </p>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <div style={{
                        width: 20, height: 20, borderRadius: '50%',
                        border: '2px solid #d4a017', borderTopColor: 'transparent',
                        animation: 'spin 0.8s linear infinite',
                      }} />
                      <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Analyse en cours...</span>
                    </div>
                  )}
                </div>
              )}

              {/* Step 1: Installation */}
              {setupStep === 1 && (
                <div>
                  <p style={{ fontSize: '0.9rem', color: 'var(--text-primary)', fontWeight: 600, marginBottom: '1rem' }}>
                    {setupStatus.openclaw_installed ? 'OpenClaw est deja installe !' : 'Installation d\'OpenClaw...'}
                  </p>
                  {setupStatus.openclaw_installed ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                      <span style={{ color: '#22c55e' }}>✅</span>
                      <span style={{ color: 'var(--text-secondary)' }}>
                        OpenClaw {setupStatus.openclaw_version || ''} pret
                      </span>
                    </div>
                  ) : setupLoading ? (
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem' }}>
                        <div style={{
                          width: 20, height: 20, borderRadius: '50%',
                          border: '2px solid #d4a017', borderTopColor: 'transparent',
                          animation: 'spin 0.8s linear infinite',
                        }} />
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                          Installation en cours... Cela peut prendre 1-2 minutes.
                        </span>
                      </div>
                      <div style={{
                        background: 'rgba(255,255,255,0.06)', borderRadius: 99, height: 4, overflow: 'hidden',
                      }}>
                        <div style={{
                          height: '100%', borderRadius: 99,
                          background: 'linear-gradient(90deg, #2563eb, #fbbf24)',
                          animation: 'agent3-btn-flow 2s ease-in-out infinite',
                          width: '60%',
                        }} />
                      </div>
                    </div>
                  ) : (
                    <div>
                      <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '0.75rem' }}>
                        Cliquez sur le bouton ci-dessous pour installer OpenClaw automatiquement :
                      </p>
                      <button
                        onClick={async () => {
                          setSetupLoading(true)
                          setSetupError('')
                          try {
                            const r = await fetch(`${API}/api/agent3/setup/install`, { method: 'POST' })
                            const d = await r.json()
                            if (d.success) {
                              setSetupStatus((s: Record<string, any>) => ({ ...s, openclaw_installed: true }))
                            } else {
                              setSetupError(d.error || 'Echec de l\'installation')
                            }
                          } catch (e: any) {
                            setSetupError(e.message)
                          }
                          setSetupLoading(false)
                        }}
                        className="agent3-btn-shimmer"
                        style={{
                          padding: '0.65rem 1.5rem', borderRadius: 'var(--radius-md)',
                          border: 'none', color: '#fff', cursor: 'pointer',
                          fontSize: '0.85rem', fontWeight: 600,
                        }}
                      >
                        Installer OpenClaw
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Step 2: Configuration */}
              {setupStep === 2 && (
                <div>
                  <p style={{ fontSize: '0.9rem', color: 'var(--text-primary)', fontWeight: 600, marginBottom: '1rem' }}>
                    Configuration automatique...
                  </p>
                  {setupLoading ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <div style={{
                          width: 20, height: 20, borderRadius: '50%',
                          border: '2px solid #fbbf24', borderTopColor: 'transparent',
                          animation: 'spin 0.8s linear infinite',
                        }} />
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                          Configuration des parametres optimaux...
                        </span>
                      </div>
                      <div style={{
                        background: 'rgba(255,255,255,0.06)', borderRadius: 99, height: 4, overflow: 'hidden',
                      }}>
                        <div style={{
                          height: '100%', borderRadius: 99,
                          background: 'linear-gradient(90deg, #d4a017, #2563eb, #fbbf24)',
                          animation: 'agent3-btn-flow 1.5s ease-in-out infinite',
                          width: '75%',
                        }} />
                      </div>
                    </div>
                  ) : setupStatus.config_done ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                        <span style={{ color: '#22c55e' }}>✅</span>
                        <span style={{ color: 'var(--text-secondary)' }}>Endpoint HTTP active</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                        <span style={{ color: '#22c55e' }}>✅</span>
                        <span style={{ color: 'var(--text-secondary)' }}>Port 18789 configure</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                        <span style={{ color: '#22c55e' }}>✅</span>
                        <span style={{ color: 'var(--text-secondary)' }}>Token securise</span>
                      </div>
                    </div>
                  ) : (
                    <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                      La configuration se lancera automatiquement...
                    </p>
                  )}
                </div>
              )}

              {/* Step 3: Connexion */}
              {setupStep === 3 && (
                <div>
                  <p style={{ fontSize: '0.9rem', color: 'var(--text-primary)', fontWeight: 600, marginBottom: '1rem' }}>
                    Demarrage du Gateway...
                  </p>
                  {setupLoading ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                      <div style={{
                        width: 24, height: 24, borderRadius: '50%',
                        border: '2px solid #22c55e', borderTopColor: 'transparent',
                        animation: 'spin 0.8s linear infinite',
                      }} />
                      <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                        Connexion au Gateway OpenClaw...
                      </span>
                    </div>
                  ) : setupStatus.connected ? (
                    <div style={{
                      textAlign: 'center', padding: '0.75rem 0',
                    }}>
                      <div style={{ fontSize: '2.5rem', marginBottom: '0.5rem' }}>🚀</div>
                      <p className="agent3-title-shimmer" style={{
                        fontSize: '1.1rem', fontWeight: 700, margin: '0 0 0.5rem',
                      }}>
                        Agent Sylea 3 pret !
                      </p>
                      <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', margin: 0 }}>
                        OpenClaw est connecte. Votre agent d'elite est operationnel.
                      </p>
                    </div>
                  ) : (
                    <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                      Demarrage en cours...
                    </p>
                  )}
                </div>
              )}

              {/* Error display */}
              {setupError && (
                <div style={{
                  marginTop: '0.75rem', padding: '0.65rem 0.75rem', borderRadius: '0.5rem',
                  background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)',
                }}>
                  <p style={{ fontSize: '0.8rem', color: '#fca5a5', margin: 0 }}>{setupError}</p>
                </div>
              )}
            </div>

            {/* Action buttons */}
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowSetupWizard3(false)} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border)',
                color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.85rem',
              }}>
                Annuler
              </button>

              {/* Re-check button for step 0 */}
              {setupStep === 0 && (
                <button
                  disabled={setupLoading}
                  onClick={async () => {
                    setSetupLoading(true)
                    setSetupError('')
                    try {
                      const r = await fetch(`${API}/api/agent3/setup/check`)
                      const data = await r.json()
                      setSetupStatus(data)
                      if (data.ready) {
                        // Already ready — skip to end
                        setSetupStep(3)
                        setSetupStatus((s: Record<string, any>) => ({ ...s, connected: true }))
                      }
                    } catch (e: any) {
                      setSetupError(e.message)
                    }
                    setSetupLoading(false)
                  }}
                  style={{
                    padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                    background: 'rgba(212,160,23,0.15)', border: '1px solid rgba(212,160,23,0.3)',
                    color: '#d4a017', cursor: 'pointer', fontSize: '0.85rem',
                  }}
                >
                  Reverifier
                </button>
              )}

              {/* Next / action button */}
              <button
                disabled={setupLoading || (setupStep === 0 && !setupStatus.node_installed)}
                className="agent3-btn-shimmer"
                onClick={async () => {
                  setSetupError('')
                  if (setupStep === 0) {
                    // Move to step 1
                    setSetupStep(1)
                    // If already installed, auto-advance
                    if (setupStatus.openclaw_installed) {
                      setSetupStep(2)
                      // Auto-configure
                      setSetupLoading(true)
                      try {
                        const r = await fetch(`${API}/api/agent3/setup/configure`, { method: 'POST' })
                        const d = await r.json()
                        if (d.token) {
                          await fetch(`${API}/api/agent3/setup/save-token`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ token: d.token }),
                          })
                        }
                        setSetupStatus((s: Record<string, any>) => ({ ...s, config_done: true }))
                        // Move to step 3 — start gateway
                        setTimeout(async () => {
                          setSetupStep(3)
                          try {
                            const r2 = await fetch(`${API}/api/agent3/setup/start`, { method: 'POST' })
                            const d2 = await r2.json()
                            if (d2.success) {
                              setSetupStatus((s: Record<string, any>) => ({ ...s, connected: true }))
                            } else {
                              setSetupError(d2.error || 'Echec du demarrage')
                            }
                          } catch (e: any) {
                            setSetupError(e.message)
                          }
                          setSetupLoading(false)
                        }, 1500)
                      } catch (e: any) {
                        setSetupError(e.message)
                        setSetupLoading(false)
                      }
                    }
                  } else if (setupStep === 1) {
                    // Move to configure
                    setSetupStep(2)
                    setSetupLoading(true)
                    try {
                      const r = await fetch(`${API}/api/agent3/setup/configure`, { method: 'POST' })
                      const d = await r.json()
                      if (d.token) {
                        await fetch(`${API}/api/agent3/setup/save-token`, {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ token: d.token }),
                        })
                      }
                      setSetupStatus((s: Record<string, any>) => ({ ...s, config_done: true }))
                      // Auto-advance to step 3
                      setTimeout(async () => {
                        setSetupStep(3)
                        try {
                          const r2 = await fetch(`${API}/api/agent3/setup/start`, { method: 'POST' })
                          const d2 = await r2.json()
                          if (d2.success) {
                            setSetupStatus((s: Record<string, any>) => ({ ...s, connected: true }))
                          } else {
                            setSetupError(d2.error || 'Echec du demarrage')
                          }
                        } catch (e: any) {
                          setSetupError(e.message)
                        }
                        setSetupLoading(false)
                      }, 1500)
                    } catch (e: any) {
                      setSetupError(e.message)
                      setSetupLoading(false)
                    }
                  } else if (setupStep === 2) {
                    // Move to start gateway
                    setSetupStep(3)
                    setSetupLoading(true)
                    try {
                      const r = await fetch(`${API}/api/agent3/setup/start`, { method: 'POST' })
                      const d = await r.json()
                      if (d.success) {
                        setSetupStatus((s: Record<string, any>) => ({ ...s, connected: true }))
                      } else {
                        setSetupError(d.error || 'Echec du demarrage')
                      }
                    } catch (e: any) {
                      setSetupError(e.message)
                    }
                    setSetupLoading(false)
                  } else if (setupStep === 3 && setupStatus.connected) {
                    // Done — activate agent
                    setShowSetupWizard3(false)
                    setActive3(true)
                    if ('Notification' in window && Notification.permission === 'default') {
                      Notification.requestPermission()
                    }
                  }
                }}
                style={{
                  padding: '0.6rem 1.5rem', borderRadius: 'var(--radius-md)',
                  border: 'none', color: '#fff', cursor: 'pointer',
                  fontSize: '0.85rem', fontWeight: 600,
                  opacity: (setupLoading || (setupStep === 0 && !setupStatus.node_installed)) ? 0.5 : 1,
                }}
              >
                {setupStep === 3 && setupStatus.connected ? 'Commencer !'
                  : setupStep === 0 ? 'Suivant'
                  : setupLoading ? 'En cours...'
                  : 'Suivant'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Agent 3 Deactivation modal ── */}
      {showDeactivateModal3 && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          animation: 'fadeInScale 0.2s ease',
        }}
          onClick={() => setShowDeactivateModal3(false)}
        >
          <div className="agent3-border-glow" style={{
            background: 'var(--bg-card)', border: '1px solid rgba(212,160,23,0.25)',
            borderRadius: 'var(--radius-lg)', padding: '2rem', maxWidth: 420, width: '90%',
            boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
          }}
            onClick={e => e.stopPropagation()}
          >
            <h3 className="agent3-title-shimmer" style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '0.75rem' }}>
              Desactiver l'Agent Sylea 3
            </h3>
            <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', lineHeight: '1.6', marginBottom: '1.5rem' }}>
              Votre Agent Sylea 3 sera mis en pause. Il ne pourra plus executer de taches complexes
              ni se connecter a OpenClaw.
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setShowDeactivateModal3(false)} style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border)',
                color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.85rem',
                transition: 'all 0.15s',
              }}>
                {t('common.annuler')}
              </button>
              <button onClick={handleDeactivate3} className="agent3-btn-shimmer" style={{
                padding: '0.6rem 1.25rem', borderRadius: 'var(--radius-md)',
                border: 'none',
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
      {AGENT2_ENABLED && actionToast && (
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
