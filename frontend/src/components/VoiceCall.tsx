// VoiceCall.tsx — Full-screen voice call overlay for Agent Sylea 2
import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'

// ── Red variant of the Sylea logo SVG ──────────────────────────────────────
const CX = 190, CY = 170
const S_PATH = `M ${CX} ${CY - 105} C ${CX + 90} ${CY - 105}, ${CX + 90} ${CY - 28}, ${CX} ${CY} C ${CX - 90} ${CY + 28}, ${CX - 90} ${CY + 105}, ${CX} ${CY + 105}`

function AgentRedLogo({ size = 120 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id="call-red-g" x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%" stopColor="#b91c1c" />
          <stop offset="40%" stopColor="#ef4444" />
          <stop offset="100%" stopColor="#f87171" />
        </linearGradient>
        <filter id="call-red-blur">
          <feGaussianBlur stdDeviation="20" />
        </filter>
      </defs>
      {/* Halo */}
      <path d={S_PATH} stroke="url(#call-red-g)" strokeWidth="90" fill="none" strokeLinecap="round"
        style={{ filter: 'url(#call-red-blur)', opacity: 0.18 }} />
      {/* Outer border */}
      <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
      {/* Red body */}
      <path d={S_PATH} stroke="url(#call-red-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
      {/* Inner hollow */}
      <path d={S_PATH} stroke="#050810" strokeWidth="18" fill="none" strokeLinecap="butt" />
      {/* Specular highlight */}
      <path d={S_PATH} stroke="rgba(255,150,150,0.5)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  )
}

// ── Types ──────────────────────────────────────────────────────────────────
interface VoiceCallProps {
  onEndCall: () => void
  onMessage: (userText: string, agentText: string) => void
  agentColor: string
  agentName: string
  chatEndpoint: (messages: Array<{ role: string; content: string }>, deviceCtx?: any) => Promise<{ message: string; audioData?: string }>
}

type SpeakingState = 'user' | 'agent' | 'idle'

// ── Component ─────────────────────────────────────────────────────────────
const VoiceCall: React.FC<VoiceCallProps> = ({ onEndCall, onMessage, agentColor, agentName, chatEndpoint }) => {
  const [callDuration, setCallDuration] = useState(0)
  const [isSpeaking, setIsSpeaking] = useState<SpeakingState>('idle')
  const [transcript, setTranscript] = useState('')
  const [isMuted, setIsMuted] = useState(false)
  const [speakerOn, setSpeakerOn] = useState(true)
  const [fadeIn, setFadeIn] = useState(false)

  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const conversationRef = useRef<Array<{ role: string; content: string }>>([])
  const callTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const activeRef = useRef(true)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const finalTranscriptRef = useRef('')

  // Fade in on mount
  useEffect(() => {
    requestAnimationFrame(() => setFadeIn(true))
  }, [])

  // Call duration timer
  useEffect(() => {
    callTimerRef.current = setInterval(() => {
      setCallDuration(prev => prev + 1)
    }, 1000)
    return () => {
      if (callTimerRef.current) clearInterval(callTimerRef.current)
    }
  }, [])

  // Format duration as MM:SS
  const formatDuration = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }

  // ── Stop recognition ──────────────────────────────────────────────────
  const stopRecognition = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }
    if (recognitionRef.current) {
      try { recognitionRef.current.abort() } catch { /* ignore */ }
      recognitionRef.current = null
    }
  }, [])

  // ── Start listening ───────────────────────────────────────────────────
  const startListening = useCallback(() => {
    if (!activeRef.current || isMuted) return

    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) return

    // Clean up any existing instance
    stopRecognition()

    const recognition = new SR() as SpeechRecognition
    recognition.lang = 'fr-FR'
    recognition.continuous = true
    recognition.interimResults = true

    finalTranscriptRef.current = ''

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      if (!activeRef.current) return

      let interim = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          finalTranscriptRef.current += event.results[i][0].transcript + ' '
        } else {
          interim = event.results[i][0].transcript
        }
      }
      setTranscript(finalTranscriptRef.current + interim)
      setIsSpeaking('user')

      // Reset silence timer
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = setTimeout(() => {
        // 2 seconds of silence -- send to agent
        const text = finalTranscriptRef.current.trim()
        if (text && activeRef.current) {
          handleUserFinishedSpeaking(text)
          finalTranscriptRef.current = ''
          setTranscript('')
        }
      }, 2000)
    }

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      // Restart on transient errors if still active
      if (activeRef.current && event.error !== 'aborted' && event.error !== 'not-allowed') {
        setTimeout(() => {
          if (activeRef.current) startListening()
        }, 500)
      }
    }

    recognition.onend = () => {
      // Auto-restart if still active (browser may stop recognition)
      if (activeRef.current && recognitionRef.current === recognition) {
        setTimeout(() => {
          if (activeRef.current) startListening()
        }, 300)
      }
    }

    recognitionRef.current = recognition
    try {
      recognition.start()
      setIsSpeaking('idle')
    } catch {
      // Already started or error — retry
      setTimeout(() => {
        if (activeRef.current) startListening()
      }, 500)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMuted, stopRecognition])

  // ── Handle user finished speaking ─────────────────────────────────────
  const handleUserFinishedSpeaking = useCallback(async (text: string) => {
    if (!activeRef.current) return

    // Stop recognition while agent is responding
    stopRecognition()
    setIsSpeaking('agent')

    // Add to conversation history
    conversationRef.current.push({ role: 'user', content: text })

    try {
      // Call agent endpoint
      const res = await chatEndpoint(conversationRef.current)
      if (!activeRef.current) return

      conversationRef.current.push({ role: 'assistant', content: res.message })

      // Save to chat history
      onMessage(text, res.message)

      // Play TTS
      if (speakerOn) {
        if (res.audioData) {
          const audio = new Audio(`data:audio/mp3;base64,${res.audioData}`)
          audioRef.current = audio
          audio.onended = () => {
            audioRef.current = null
            if (activeRef.current) {
              setIsSpeaking('idle')
              startListening()
            }
          }
          audio.onerror = () => {
            audioRef.current = null
            if (activeRef.current) {
              setIsSpeaking('idle')
              startListening()
            }
          }
          await audio.play()
        } else {
          // Fallback to browser TTS
          const synth = window.speechSynthesis
          synth.cancel()
          const utterance = new SpeechSynthesisUtterance(res.message)
          utterance.lang = 'fr-FR'
          utterance.rate = 0.95
          utterance.pitch = 1.05

          const voices = synth.getVoices()
          const frenchVoice =
            voices.find(v => v.lang.startsWith('fr') && v.name.includes('Denise') && v.name.includes('Online'))
            || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Online') && v.name.includes('Natural'))
            || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Denise'))
            || voices.find(v => v.lang.startsWith('fr') && v.name.includes('Google'))
            || voices.find(v => v.lang.startsWith('fr'))
          if (frenchVoice) utterance.voice = frenchVoice

          utterance.onend = () => {
            if (activeRef.current) {
              setIsSpeaking('idle')
              startListening()
            }
          }
          utterance.onerror = () => {
            if (activeRef.current) {
              setIsSpeaking('idle')
              startListening()
            }
          }
          synth.speak(utterance)
        }
      } else {
        // Speaker off — just resume listening
        setIsSpeaking('idle')
        startListening()
      }
    } catch {
      if (activeRef.current) {
        setIsSpeaking('idle')
        startListening()
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatEndpoint, onMessage, speakerOn, stopRecognition, startListening])

  // ── Start listening on mount ──────────────────────────────────────────
  useEffect(() => {
    // Small delay to allow mic permissions
    const timer = setTimeout(() => {
      if (activeRef.current) startListening()
    }, 500)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Handle mute toggle ────────────────────────────────────────────────
  useEffect(() => {
    if (isMuted) {
      stopRecognition()
      setIsSpeaking('idle')
      setTranscript('')
      finalTranscriptRef.current = ''
    } else if (isSpeaking !== 'agent') {
      startListening()
    }
  }, [isMuted, stopRecognition, startListening, isSpeaking])

  // ── End call ──────────────────────────────────────────────────────────
  const handleEndCall = useCallback(() => {
    activeRef.current = false
    stopRecognition()
    window.speechSynthesis.cancel()
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    if (callTimerRef.current) {
      clearInterval(callTimerRef.current)
      callTimerRef.current = null
    }
    onEndCall()
  }, [stopRecognition, onEndCall])

  // ── Cleanup on unmount ────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      activeRef.current = false
      if (recognitionRef.current) {
        try { recognitionRef.current.abort() } catch { /* ignore */ }
      }
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      if (callTimerRef.current) clearInterval(callTimerRef.current)
      if (audioRef.current) audioRef.current.pause()
      window.speechSynthesis.cancel()
    }
  }, [])

  // ── Speaking indicator dots ───────────────────────────────────────────
  const speakingColor = isSpeaking === 'user' ? '#3b82f6' : isSpeaking === 'agent' ? agentColor : 'rgba(255,255,255,0.2)'
  const speakingLabel = isSpeaking === 'user' ? 'Vous parlez...' : isSpeaking === 'agent' ? 'Agent repond...' : 'En attente...'

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 2000,
      background: 'radial-gradient(ellipse at center, rgba(30,5,5,0.95) 0%, rgba(5,8,16,0.98) 70%)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      opacity: fadeIn ? 1 : 0,
      transition: 'opacity 0.4s ease',
    }}>
      <style>{`
        @keyframes vc-pulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.3); opacity: 0.5; }
        }
        @keyframes vc-glow {
          0%, 100% { box-shadow: 0 0 40px rgba(239,68,68,0.15); }
          50% { box-shadow: 0 0 80px rgba(239,68,68,0.3); }
        }
        @keyframes vc-ring {
          0% { transform: scale(0.8); opacity: 0.6; }
          50% { transform: scale(1.2); opacity: 0; }
          100% { transform: scale(0.8); opacity: 0; }
        }
      `}</style>

      {/* Background glow ring when agent is speaking */}
      {isSpeaking === 'agent' && (
        <div style={{
          position: 'absolute',
          width: 220, height: 220, borderRadius: '50%',
          border: `2px solid ${agentColor}`,
          animation: 'vc-ring 2s ease-in-out infinite',
          top: '50%', left: '50%',
          marginTop: -200, marginLeft: -110,
        }} />
      )}

      {/* Agent logo */}
      <div style={{
        marginBottom: '1.5rem',
        animation: isSpeaking === 'agent' ? 'vc-glow 2s ease-in-out infinite' : 'none',
        borderRadius: '50%',
        padding: '1rem',
      }}>
        <AgentRedLogo size={120} />
      </div>

      {/* Agent name */}
      <h2 style={{
        fontSize: '1.4rem', fontWeight: 700, margin: '0 0 0.5rem',
        background: `linear-gradient(135deg, ${agentColor}, #f87171)`,
        WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
      }}>
        {agentName}
      </h2>

      {/* Call duration */}
      <p style={{
        fontSize: '2rem', fontWeight: 300, color: 'rgba(255,255,255,0.7)',
        margin: '0 0 2rem', fontVariantNumeric: 'tabular-nums',
        letterSpacing: '0.1em',
      }}>
        {formatDuration(callDuration)}
      </p>

      {/* Speaking indicator */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0.75rem',
        marginBottom: '3rem',
      }}>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {[0, 1, 2].map(i => (
            <div key={i} style={{
              width: 10, height: 10, borderRadius: '50%',
              background: speakingColor,
              animation: isSpeaking !== 'idle' ? `vc-pulse 1.2s ease-in-out ${i * 0.2}s infinite` : 'none',
              opacity: isSpeaking === 'idle' ? 0.3 : 1,
              transition: 'background 0.3s, opacity 0.3s',
            }} />
          ))}
        </div>
        <span style={{
          fontSize: '0.85rem', color: 'rgba(255,255,255,0.5)',
          fontWeight: 500,
        }}>
          {speakingLabel}
        </span>
      </div>

      {/* Live transcript (subtle, small) */}
      {transcript && isSpeaking === 'user' && (
        <div style={{
          position: 'absolute', bottom: 160, left: '50%', transform: 'translateX(-50%)',
          maxWidth: '80%', textAlign: 'center',
          padding: '0.5rem 1rem', borderRadius: '12px',
          background: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.1)',
        }}>
          <p style={{
            fontSize: '0.8rem', color: 'rgba(255,255,255,0.5)',
            margin: 0, fontStyle: 'italic',
          }}>
            {transcript}
          </p>
        </div>
      )}

      {/* Bottom controls */}
      <div style={{
        position: 'absolute', bottom: 60,
        display: 'flex', alignItems: 'center', gap: '2rem',
      }}>
        {/* Mute button */}
        <button
          onClick={() => setIsMuted(m => !m)}
          style={{
            width: 56, height: 56, borderRadius: '50%',
            background: isMuted ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.08)',
            border: isMuted ? '2px solid rgba(255,255,255,0.3)' : '1px solid rgba(255,255,255,0.12)',
            color: isMuted ? '#fff' : 'rgba(255,255,255,0.7)',
            cursor: 'pointer',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            gap: '2px', transition: 'all 0.2s',
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="1" width="6" height="11" rx="3" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
            {isMuted && <line x1="1" y1="1" x2="23" y2="23" />}
          </svg>
          <span style={{ fontSize: '0.55rem', fontWeight: 600 }}>
            {isMuted ? 'Unmute' : 'Muet'}
          </span>
        </button>

        {/* End call button */}
        <button
          onClick={handleEndCall}
          style={{
            width: 72, height: 72, borderRadius: '50%',
            background: '#ef4444',
            border: 'none',
            color: '#fff',
            cursor: 'pointer',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            gap: '2px',
            boxShadow: '0 4px 24px rgba(239,68,68,0.4)',
            transition: 'all 0.2s',
          }}
          onMouseEnter={e => { e.currentTarget.style.transform = 'scale(1.05)'; e.currentTarget.style.boxShadow = '0 6px 32px rgba(239,68,68,0.6)' }}
          onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)'; e.currentTarget.style.boxShadow = '0 4px 24px rgba(239,68,68,0.4)' }}
        >
          {/* Phone down icon */}
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.68 13.31a16 16 0 0 0 3.41 2.6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7 2 2 0 0 1 1.72 2v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91" />
            <line x1="23" y1="1" x2="1" y2="23" />
          </svg>
          <span style={{ fontSize: '0.6rem', fontWeight: 700 }}>Raccrocher</span>
        </button>

        {/* Speaker button */}
        <button
          onClick={() => setSpeakerOn(s => !s)}
          style={{
            width: 56, height: 56, borderRadius: '50%',
            background: speakerOn ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.15)',
            border: !speakerOn ? '2px solid rgba(255,255,255,0.3)' : '1px solid rgba(255,255,255,0.12)',
            color: !speakerOn ? '#fff' : 'rgba(255,255,255,0.7)',
            cursor: 'pointer',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            gap: '2px', transition: 'all 0.2s',
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
            {speakerOn ? (
              <>
                <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
                <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
              </>
            ) : (
              <line x1="23" y1="9" x2="17" y2="15" />
            )}
          </svg>
          <span style={{ fontSize: '0.55rem', fontWeight: 600 }}>
            {speakerOn ? 'HP' : 'HP off'}
          </span>
        </button>
      </div>
    </div>
  )
}

export default VoiceCall
