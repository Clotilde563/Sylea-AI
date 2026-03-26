// VoiceCall.tsx — Full-screen voice call overlay
import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '../api/client'

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
        <filter id="call-red-blur"><feGaussianBlur stdDeviation="20" /></filter>
      </defs>
      <path d={S_PATH} stroke="url(#call-red-g)" strokeWidth="90" fill="none" strokeLinecap="round" style={{ filter: 'url(#call-red-blur)', opacity: 0.18 }} />
      <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke="url(#call-red-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke="#050810" strokeWidth="18" fill="none" strokeLinecap="butt" />
      <path d={S_PATH} stroke="rgba(255,150,150,0.5)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  )
}

interface VoiceCallProps {
  onEndCall: () => void
  onMessage: (userText: string, agentText: string) => void
  agentColor: string
  agentName: string
  chatEndpoint: (messages: Array<{ role: string; content: string }>, deviceCtx?: any) => Promise<{ message: string; audioData?: string }>
}

const VoiceCall: React.FC<VoiceCallProps> = ({ onEndCall, onMessage, agentColor, agentName, chatEndpoint }) => {
  const [callDuration, setCallDuration] = useState(0)
  const [isSpeaking, setIsSpeaking] = useState<'user' | 'agent' | 'idle'>('idle')
  const [transcript, setTranscript] = useState('')
  const [isMuted, setIsMuted] = useState(false)
  const [speakerOn, setSpeakerOn] = useState(true)
  const [fadeIn, setFadeIn] = useState(false)
  const [callStarted, setCallStarted] = useState(false)
  const [status, setStatus] = useState('Appuyez pour commencer')

  const activeRef = useRef(true)
  const conversationRef = useRef<Array<{ role: string; content: string }>>([])
  const callTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const recognitionRef = useRef<any>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const finalTranscriptRef = useRef('')

  useEffect(() => {
    requestAnimationFrame(() => setFadeIn(true))
    return () => {
      activeRef.current = false
      if (callTimerRef.current) clearInterval(callTimerRef.current)
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      if (recognitionRef.current) try { recognitionRef.current.abort() } catch { /* */ }
      if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
      window.speechSynthesis.cancel()
    }
  }, [])

  const formatDuration = (secs: number) => {
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
  }

  // Send user text to agent and play response
  const sendToAgent = useCallback(async (text: string) => {
    if (!activeRef.current) return
    setIsSpeaking('agent')
    setStatus('Agent reflechit...')

    conversationRef.current.push({ role: 'user', content: text })

    try {
      const res = await chatEndpoint(conversationRef.current)
      if (!activeRef.current) return

      conversationRef.current.push({ role: 'assistant', content: res.message })
      onMessage(text, res.message)

      // Play TTS
      if (speakerOn && res.audioData) {
        setStatus('Agent parle...')
        const audio = new Audio(`data:audio/mp3;base64,${res.audioData}`)
        audioRef.current = audio
        audio.onended = () => {
          audioRef.current = null
          if (activeRef.current) {
            setIsSpeaking('idle')
            setStatus('A ton tour...')
            startRecognition()
          }
        }
        audio.onerror = () => {
          audioRef.current = null
          if (activeRef.current) {
            setIsSpeaking('idle')
            setStatus('A ton tour...')
            startRecognition()
          }
        }
        await audio.play()
      } else if (speakerOn) {
        // Fallback browser TTS
        setStatus('Agent parle...')
        const synth = window.speechSynthesis
        const utterance = new SpeechSynthesisUtterance(res.message)
        utterance.lang = 'fr-FR'
        utterance.rate = 0.95
        const voices = synth.getVoices()
        const frVoice = voices.find(v => v.lang.startsWith('fr') && v.name.includes('Google'))
          || voices.find(v => v.lang.startsWith('fr'))
        if (frVoice) utterance.voice = frVoice
        utterance.onend = () => {
          if (activeRef.current) {
            setIsSpeaking('idle')
            setStatus('A ton tour...')
            startRecognition()
          }
        }
        synth.speak(utterance)
      } else {
        setIsSpeaking('idle')
        setStatus('A ton tour...')
        startRecognition()
      }
    } catch {
      if (activeRef.current) {
        setIsSpeaking('idle')
        setStatus('Erreur — reessaye')
        startRecognition()
      }
    }
  }, [chatEndpoint, onMessage, speakerOn])

  // Start speech recognition
  const startRecognition = useCallback(() => {
    if (!activeRef.current || isMuted) return

    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) { setStatus('Reconnaissance vocale non supportee'); return }

    // Clean up existing
    if (recognitionRef.current) {
      try { recognitionRef.current.abort() } catch { /* */ }
    }

    const recognition = new SR()
    recognition.lang = 'fr-FR'
    recognition.continuous = true
    recognition.interimResults = true
    finalTranscriptRef.current = ''

    recognition.onstart = () => {
      console.log('[VoiceCall] Recognition started')
      setStatus('Parle maintenant...')
    }

    recognition.onresult = (event: any) => {
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
      setStatus('Ecoute...')

      // Reset silence timer
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = setTimeout(() => {
        const text = finalTranscriptRef.current.trim()
        if (text && activeRef.current) {
          // Stop recognition before sending
          if (recognitionRef.current) {
            try { recognitionRef.current.abort() } catch { /* */ }
            recognitionRef.current = null
          }
          finalTranscriptRef.current = ''
          setTranscript('')
          sendToAgent(text)
        }
      }, 2500) // 2.5 seconds of silence
    }

    recognition.onerror = (event: any) => {
      console.log('[VoiceCall] Recognition error:', event.error)
      if (activeRef.current && event.error !== 'aborted' && event.error !== 'not-allowed') {
        setTimeout(() => { if (activeRef.current) startRecognition() }, 1000)
      }
    }

    recognition.onend = () => {
      console.log('[VoiceCall] Recognition ended')
      // Auto-restart if still active and not during agent response
      if (activeRef.current && recognitionRef.current === recognition) {
        setTimeout(() => { if (activeRef.current) startRecognition() }, 500)
      }
    }

    recognitionRef.current = recognition
    try {
      recognition.start()
    } catch (e) {
      console.log('[VoiceCall] Start error:', e)
      setTimeout(() => { if (activeRef.current) startRecognition() }, 1000)
    }
  }, [isMuted, sendToAgent])

  // Handle "Commencer l'appel" click
  const handleStartCall = useCallback(() => {
    setCallStarted(true)
    setStatus('Demarrage...')

    // Start call timer
    callTimerRef.current = setInterval(() => {
      setCallDuration(prev => prev + 1)
    }, 1000)

    // Request mic permission then start recognition
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then((stream) => {
        stream.getTracks().forEach(t => t.stop())
        console.log('[VoiceCall] Mic permission granted')
        startRecognition()
      })
      .catch((err) => {
        console.log('[VoiceCall] Mic error:', err)
        setStatus('Permission micro requise')
        // Try anyway
        startRecognition()
      })
  }, [startRecognition])

  // Handle end call
  const handleEndCall = useCallback(() => {
    activeRef.current = false
    if (recognitionRef.current) try { recognitionRef.current.abort() } catch { /* */ }
    if (audioRef.current) { audioRef.current.pause(); audioRef.current = null }
    if (callTimerRef.current) clearInterval(callTimerRef.current)
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
    window.speechSynthesis.cancel()
    onEndCall()
  }, [onEndCall])

  // Mute toggle
  useEffect(() => {
    if (isMuted && recognitionRef.current) {
      try { recognitionRef.current.abort() } catch { /* */ }
      recognitionRef.current = null
      setTranscript('')
      finalTranscriptRef.current = ''
      setStatus('Micro coupe')
    } else if (!isMuted && callStarted && isSpeaking !== 'agent') {
      startRecognition()
    }
  }, [isMuted, callStarted, isSpeaking, startRecognition])

  const speakingColor = isSpeaking === 'user' ? '#60a5fa' : isSpeaking === 'agent' ? agentColor : 'rgba(255,255,255,0.3)'

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 2000,
      background: 'radial-gradient(ellipse at center, rgba(20,0,0,0.95), #050510)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      opacity: fadeIn ? 1 : 0, transition: 'opacity 0.5s ease',
    }}>
      <style>{`
        @keyframes vc-pulse { 0%,100% { transform: scale(1); opacity: 0.7; } 50% { transform: scale(1.15); opacity: 1; } }
      `}</style>

      {/* Glow */}
      <div style={{
        position: 'absolute', top: '20%', width: 300, height: 300, borderRadius: '50%',
        background: `radial-gradient(circle, ${agentColor}22, transparent 70%)`,
        filter: 'blur(60px)', pointerEvents: 'none',
      }} />

      <AgentRedLogo size={140} />
      <h2 style={{ color: agentColor, fontSize: '1.4rem', fontWeight: 700, margin: '1.5rem 0 0.5rem' }}>{agentName}</h2>
      <p style={{ fontSize: '2rem', fontWeight: 300, color: 'rgba(255,255,255,0.7)', margin: '0 0 1rem', letterSpacing: '0.1em' }}>
        {callStarted ? formatDuration(callDuration) : '00:00'}
      </p>

      {/* Status */}
      <p style={{ fontSize: '0.9rem', color: 'rgba(255,255,255,0.5)', margin: '0 0 1rem' }}>{status}</p>

      {/* Start button */}
      {!callStarted && (
        <button onClick={handleStartCall} style={{
          padding: '1rem 2.5rem', borderRadius: '999px',
          background: `linear-gradient(135deg, ${agentColor}, ${agentColor}cc)`,
          border: 'none', color: 'white', fontSize: '1.1rem', fontWeight: 700,
          cursor: 'pointer', marginBottom: '2rem',
          boxShadow: `0 0 30px ${agentColor}66`,
          animation: 'vc-pulse 2s ease-in-out infinite',
        }}>
          🎙️ Commencer l'appel
        </button>
      )}

      {/* Speaking indicator */}
      {callStarted && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', gap: 6 }}>
            {[0, 1, 2].map(i => (
              <div key={i} style={{
                width: 10, height: 10, borderRadius: '50%', background: speakingColor,
                animation: isSpeaking !== 'idle' ? `vc-pulse 1.2s ease-in-out ${i * 0.2}s infinite` : 'none',
                opacity: isSpeaking === 'idle' ? 0.3 : 1,
              }} />
            ))}
          </div>
        </div>
      )}

      {/* Transcript */}
      {transcript && isSpeaking === 'user' && (
        <div style={{
          maxWidth: 400, padding: '0.75rem 1.25rem', borderRadius: 12,
          background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
          marginBottom: '2rem',
        }}>
          <p style={{ color: 'rgba(255,255,255,0.6)', fontSize: '0.85rem', margin: 0, fontStyle: 'italic' }}>
            {transcript}
          </p>
        </div>
      )}

      {/* Bottom controls */}
      <div style={{ display: 'flex', gap: '2rem', alignItems: 'center' }}>
        <button onClick={() => setIsMuted(!isMuted)} style={{
          width: 56, height: 56, borderRadius: '50%',
          background: isMuted ? 'rgba(239,68,68,0.2)' : 'rgba(255,255,255,0.1)',
          border: `1px solid ${isMuted ? '#ef4444' : 'rgba(255,255,255,0.2)'}`,
          color: isMuted ? '#ef4444' : 'white', cursor: 'pointer',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          fontSize: '1.2rem',
        }}>
          {isMuted ? '🔇' : '🎤'}
          <span style={{ fontSize: '0.55rem', marginTop: 2 }}>{isMuted ? 'Muet' : 'Micro'}</span>
        </button>

        <button onClick={handleEndCall} style={{
          width: 72, height: 72, borderRadius: '50%',
          background: 'linear-gradient(135deg, #ef4444, #dc2626)',
          border: 'none', color: 'white', cursor: 'pointer',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          fontSize: '1.5rem', boxShadow: '0 0 20px rgba(239,68,68,0.4)',
        }}>
          ✕
          <span style={{ fontSize: '0.6rem', marginTop: 2 }}>Raccrocher</span>
        </button>

        <button onClick={() => setSpeakerOn(!speakerOn)} style={{
          width: 56, height: 56, borderRadius: '50%',
          background: speakerOn ? 'rgba(255,255,255,0.1)' : 'rgba(239,68,68,0.2)',
          border: `1px solid ${speakerOn ? 'rgba(255,255,255,0.2)' : '#ef4444'}`,
          color: speakerOn ? 'white' : '#ef4444', cursor: 'pointer',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          fontSize: '1.2rem',
        }}>
          {speakerOn ? '🔊' : '🔈'}
          <span style={{ fontSize: '0.55rem', marginTop: 2 }}>HP</span>
        </button>
      </div>
    </div>
  )
}

export default VoiceCall
