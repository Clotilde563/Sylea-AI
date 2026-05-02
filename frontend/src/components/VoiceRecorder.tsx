import { useState, useRef, useEffect } from 'react'
import { api } from '../api/client'

/**
 * Composant d'enregistrement vocal qui utilise le backend Whisper
 * (plus precis que le SpeechRecognition browser natif, surtout en francais).
 *
 * Props :
 *   - onTranscription(text, audioBlob) : callback quand la transcription est prete
 *   - disabled : desactive le bouton
 *   - language : code langue pour Whisper (defaut 'fr')
 *   - compact : mode bouton seul (sans waveform visible)
 */
export default function VoiceRecorder({
  onTranscription,
  disabled = false,
  language = 'fr',
  compact = false,
}: {
  onTranscription: (text: string, audioBlob?: Blob) => void
  disabled?: boolean
  language?: string
  compact?: boolean
}) {
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [duration, setDuration] = useState(0)
  const [error, setError] = useState('')

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const durationIntervalRef = useRef<number | null>(null)

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(t => t.stop())
      }
      if (durationIntervalRef.current) {
        window.clearInterval(durationIntervalRef.current)
      }
    }
  }, [])

  const start = async () => {
    setError('')
    setDuration(0)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      // Choose mime type (prefer webm audio/opus, fallback to default)
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : 'audio/mp4'

      const mr = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = mr
      chunksRef.current = []

      mr.ondataavailable = e => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      mr.onstop = async () => {
        // Stop mic
        if (streamRef.current) {
          streamRef.current.getTracks().forEach(t => t.stop())
          streamRef.current = null
        }
        if (durationIntervalRef.current) {
          window.clearInterval(durationIntervalRef.current)
          durationIntervalRef.current = null
        }
        if (chunksRef.current.length === 0) return

        const audioBlob = new Blob(chunksRef.current, { type: mimeType })

        // Transcribe via Whisper backend
        setTranscribing(true)
        try {
          const r = await api.voiceTranscribe(audioBlob, language)
          if (r.error) {
            setError(r.error)
          } else if (r.text) {
            onTranscription(r.text, audioBlob)
          } else {
            setError('Transcription vide')
          }
        } catch (e: any) {
          setError(e?.message || 'Erreur transcription')
        } finally {
          setTranscribing(false)
        }
      }

      mr.start()
      setRecording(true)
      durationIntervalRef.current = window.setInterval(() => {
        setDuration(d => d + 1)
      }, 1000)
    } catch (e: any) {
      setError(e?.message || 'Micro refuse')
    }
  }

  const stop = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
      setRecording(false)
    }
  }

  const cancel = () => {
    chunksRef.current = []
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }
    if (durationIntervalRef.current) {
      window.clearInterval(durationIntervalRef.current)
      durationIntervalRef.current = null
    }
    setRecording(false)
    setDuration(0)
  }

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  if (transcribing) {
    return (
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: compact ? 0 : '6px 12px',
        color: 'var(--accent-violet-light)', fontSize: '0.85rem',
      }}>
        <span className="spinner spinner-sm" style={{ width: 14, height: 14 }} />
        <span>Transcription…</span>
      </div>
    )
  }

  if (recording) {
    return (
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 8,
        padding: compact ? '4px' : '6px 12px',
        background: 'rgba(239,68,68,0.12)',
        border: '1px solid rgba(239,68,68,0.4)',
        borderRadius: 20,
      }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%', background: '#ef4444',
          animation: 'pulse 1s ease-in-out infinite',
        }} />
        {!compact && (
          <span style={{ fontSize: '0.8rem', color: '#ef4444', fontFamily: 'monospace' }}>
            {formatTime(duration)}
          </span>
        )}
        <button
          onClick={stop}
          title="Arrêter et transcrire"
          style={{
            background: 'var(--accent-violet)', color: '#fff',
            border: 'none', borderRadius: 12, padding: '2px 10px',
            cursor: 'pointer', fontSize: '0.75rem', fontWeight: 600,
          }}
        >
          ✓
        </button>
        <button
          onClick={cancel}
          title="Annuler"
          style={{
            background: 'transparent', color: 'var(--text-muted)',
            border: 'none', cursor: 'pointer', fontSize: '0.9rem', padding: 0,
          }}
        >
          ✕
        </button>
      </div>
    )
  }

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', gap: 4 }}>
      <button
        onClick={start}
        disabled={disabled}
        title="Enregistrer un message vocal (Whisper)"
        style={{
          width: compact ? 32 : 36,
          height: compact ? 32 : 36,
          borderRadius: '50%',
          background: disabled ? 'var(--bg-elevated)' : 'var(--accent-violet)',
          color: '#fff',
          border: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.5 : 1,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'transform 0.1s',
        }}
        onMouseEnter={e => { if (!disabled) e.currentTarget.style.transform = 'scale(1.08)' }}
        onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)' }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" y1="19" x2="12" y2="23"/>
          <line x1="8" y1="23" x2="16" y2="23"/>
        </svg>
      </button>
      {error && !compact && (
        <div style={{ fontSize: '0.7rem', color: '#ef4444', marginTop: 2 }}>
          {error.slice(0, 60)}
        </div>
      )}
    </div>
  )
}
