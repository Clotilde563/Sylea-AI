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

function AgentBlueLogo({ size = 120 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id="call-blue-g" x1="0%" y1="100%" x2="100%" y2="0%">
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
        <linearGradient id="call-blue-shine" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%">
            <animate attributeName="stop-color" values="rgba(255,230,200,0.6);rgba(200,220,255,0.3);rgba(255,230,200,0.6)" dur="3s" repeatCount="indefinite" />
          </stop>
          <stop offset="100%">
            <animate attributeName="stop-color" values="rgba(200,220,255,0.3);rgba(255,230,200,0.6);rgba(200,220,255,0.3)" dur="3s" repeatCount="indefinite" />
          </stop>
        </linearGradient>
        <filter id="call-blue-blur"><feGaussianBlur stdDeviation="20" /></filter>
        <linearGradient id="call-blue-glow" x1="0%" y1="100%" x2="100%" y2="0%">
          <stop offset="0%">
            <animate attributeName="stop-color" values="#1e3a5f;#d4a017;#1e3a5f" dur="3s" repeatCount="indefinite" />
          </stop>
          <stop offset="100%">
            <animate attributeName="stop-color" values="#2563eb;#fbbf24;#2563eb" dur="3s" repeatCount="indefinite" />
          </stop>
        </linearGradient>
      </defs>
      <path d={S_PATH} stroke="url(#call-blue-glow)" strokeWidth="90" fill="none" strokeLinecap="round" style={{ filter: 'url(#call-blue-blur)', opacity: 0.22 }} />
      <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke="url(#call-blue-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke="#050810" strokeWidth="18" fill="none" strokeLinecap="butt" />
      <path d={S_PATH} stroke="url(#call-blue-shine)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
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
  const [interimTranscript, setInterimTranscript] = useState('')
  const [isMuted, setIsMuted] = useState(false)
  const [speakerOn, setSpeakerOn] = useState(true)
  const [fadeIn, setFadeIn] = useState(true)  // Show immediately
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
        await audio.play().catch(() => {
          // Blocked by Chrome — fallback to browser TTS
          console.log('[VoiceCall] audio.play blocked in sendToAgent, using TTS')
          const synth = window.speechSynthesis
          synth.cancel()
          const u = new SpeechSynthesisUtterance(res.message)
          u.lang = 'fr-FR'; u.rate = 0.95
          u.onend = () => { if (activeRef.current) { setIsSpeaking('idle'); setStatus('A ton tour...'); startRecognition() } }
          synth.speak(u)
        })
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

  // Start speech recognition (continuous mode with silence detection)
  const startRecognition = useCallback(() => {
    if (!activeRef.current || isMuted) return

    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) { setStatus('Reconnaissance vocale non supportee'); return }

    // Clean up existing
    if (recognitionRef.current) {
      try { recognitionRef.current.abort() } catch { /* */ }
    }
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null }
    finalTranscriptRef.current = ''
    setInterimTranscript('')

    const recognition = new SR()
    recognition.lang = 'fr-FR'
    recognition.continuous = true
    recognition.interimResults = true

    console.log('[VoiceCall] Creating continuous recognition instance...')

    recognition.onstart = () => {
      console.log('[VoiceCall] Recognition STARTED (continuous) — speak now')
      setStatus('Parle maintenant...')
      setIsSpeaking('idle')
    }

    recognition.onresult = (event: any) => {
      if (!activeRef.current) return

      let finalText = ''
      let interimText = ''

      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i]
        if (result.isFinal) {
          finalText += result[0].transcript
        } else {
          interimText += result[0].transcript
        }
      }

      // Update the accumulated final transcript
      if (finalText) {
        finalTranscriptRef.current = finalText.trim()
        setTranscript(finalTranscriptRef.current)
        setIsSpeaking('user')
      }

      // Show interim results
      setInterimTranscript(interimText.trim())
      if (interimText.trim()) {
        setIsSpeaking('user')
      }

      console.log('[VoiceCall] final:', finalTranscriptRef.current, '| interim:', interimText.trim())

      // Reset silence timer — user is still speaking
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)

      const hasContent = finalTranscriptRef.current || interimText.trim()
      if (hasContent) {
        silenceTimerRef.current = setTimeout(() => {
          if (!activeRef.current) return
          const textToSend = finalTranscriptRef.current || interimText.trim()
          if (textToSend) {
            console.log('[VoiceCall] Silence timeout — sending:', textToSend)
            // Stop recognition before sending to agent
            if (recognitionRef.current) {
              try { recognitionRef.current.abort() } catch { /* */ }
              recognitionRef.current = null
            }
            setInterimTranscript('')
            setTranscript(textToSend)
            finalTranscriptRef.current = ''
            sendToAgentRef.current(textToSend)
          }
        }, 1500)
      }
    }

    recognition.onerror = (event: any) => {
      console.log('[VoiceCall] Recognition error:', event.error)
      if (event.error === 'no-speech') {
        // No speech detected — just restart
        if (activeRef.current) {
          console.log('[VoiceCall] No speech, restarting...')
          setTimeout(() => { if (activeRef.current) startRecognitionRef.current() }, 300)
        }
      } else if (event.error === 'aborted') {
        // Intentionally stopped — do nothing
      } else if (event.error === 'not-allowed') {
        setStatus('Permission micro refusee')
      } else {
        if (activeRef.current) {
          setTimeout(() => { if (activeRef.current) startRecognitionRef.current() }, 1000)
        }
      }
    }

    recognition.onend = () => {
      console.log('[VoiceCall] Recognition ended')
      // Auto-restart if the call is still active and we're not in agent-speaking mode
      // (browser may auto-stop continuous recognition after a while)
      if (activeRef.current && !silenceTimerRef.current) {
        // Only restart if we didn't just trigger a silence timeout (which means sendToAgent is handling it)
        const speaking = document.querySelector('[data-voice-speaking]')?.getAttribute('data-voice-speaking')
        // Use a small delay to avoid rapid restart loops
        setTimeout(() => {
          if (activeRef.current && recognitionRef.current === null) {
            console.log('[VoiceCall] Auto-restarting recognition after browser stop')
            startRecognitionRef.current()
          }
        }, 300)
      }
    }

    recognitionRef.current = recognition
    try {
      recognition.start()
      console.log('[VoiceCall] recognition.start() called (continuous)')
    } catch (e) {
      console.log('[VoiceCall] Start error:', e)
      setTimeout(() => { if (activeRef.current) startRecognitionRef.current() }, 1000)
    }
  }, [isMuted])

  // Use refs to avoid stale closures
  const startRecognitionRef = useRef(startRecognition)
  startRecognitionRef.current = startRecognition
  const sendToAgentRef = useRef(sendToAgent)
  sendToAgentRef.current = sendToAgent
  const chatEndpointRef = useRef(chatEndpoint)
  chatEndpointRef.current = chatEndpoint
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  // Handle "Commencer l'appel" click
  const handleStartCall = useCallback(() => {
    activeRef.current = true  // Ensure active flag is set
    setCallStarted(true)
    setStatus('Demarrage...')

    // Start call timer
    callTimerRef.current = setInterval(() => {
      setCallDuration(prev => prev + 1)
    }, 1000)

    // Unlock AudioContext with user gesture (critical for Chrome autoplay policy)
    const audioCtx = new AudioContext()
    audioCtx.resume().then(() => console.log('[VoiceCall] AudioContext unlocked'))

    // Also play a tiny silent sound to unlock audio playback
    const silentAudio = new Audio('data:audio/mp3;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4Ljc2LjEwMAAAAAAAAAAAAAAA//tQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAABhgC7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7u7v/////////////////////////////////')
    silentAudio.volume = 0.01
    silentAudio.play().catch(() => {})

    // Request mic permission
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then((stream) => {
        stream.getTracks().forEach(t => t.stop())
        console.log('[VoiceCall] Mic permission granted')
        setStatus('Agent decroche...')
        setIsSpeaking('agent')
        console.log('[VoiceCall] Calling chatEndpoint for greeting...')
        const greetMsgs = [{ role: 'user', content: '[APPEL VOCAL] L utilisateur vient de lancer un appel vocal avec toi. Decroche et dis-lui bonjour naturellement en 1 phrase.' }]
        chatEndpointRef.current(greetMsgs)
          .then((res) => {
            console.log('[VoiceCall] Greeting received:', res.message?.substring(0, 50))
            console.log('[VoiceCall] Has audioData:', !!res.audioData)
            // Don't check activeRef here — the greeting must always play

            console.log('[VoiceCall] Step 1 - about to play TTS')

            // Play greeting — use browser TTS directly (most reliable)
            console.log('[VoiceCall] Starting TTS playback...')
            const synth = window.speechSynthesis
            synth.cancel()
            const utt = new SpeechSynthesisUtterance(res.message)
            utt.lang = 'fr-FR'
            utt.rate = 0.95
            const voices = synth.getVoices()
            const frVoice = voices.find((v: SpeechSynthesisVoice) => v.lang.startsWith('fr') && v.name.includes('Google'))
              || voices.find((v: SpeechSynthesisVoice) => v.lang.startsWith('fr'))
            if (frVoice) utt.voice = frVoice
            utt.onstart = () => console.log('[VoiceCall] TTS speaking...')
            utt.onend = () => {
              console.log('[VoiceCall] TTS ended, starting recognition')
              if (activeRef.current) {
                setIsSpeaking('idle')
                setStatus('A ton tour...')
                startRecognitionRef.current()
              }
            }
            utt.onerror = (e) => {
              console.log('[VoiceCall] TTS error:', e)
              if (activeRef.current) startRecognitionRef.current()
            }
            synth.speak(utt)
            console.log('[VoiceCall] TTS queued')
          })
          .catch((e) => {
            console.log('[VoiceCall] Greeting error:', e)
            startRecognitionRef.current()
          })
      })
      .catch((err) => {
        console.log('[VoiceCall] Mic error:', err)
        setStatus('Permission micro requise')
      })
  }, [])

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
      if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null }
      setTranscript('')
      setInterimTranscript('')
      finalTranscriptRef.current = ''
      setStatus('Micro coupe')
    } else if (!isMuted && callStarted && isSpeaking !== 'agent') {
      startRecognition()
    }
  }, [isMuted, callStarted, isSpeaking, startRecognition])

  const isBlue = agentColor.includes('2563eb')
  const speakingColor = isSpeaking === 'user' ? '#60a5fa' : isSpeaking === 'agent' ? (isBlue ? '#d4a017' : agentColor) : 'rgba(255,255,255,0.3)'

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: isBlue
        ? 'radial-gradient(ellipse at center, rgba(5,5,25,0.98), #050510)'
        : 'radial-gradient(ellipse at center, rgba(20,0,0,0.98), #050510)',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      opacity: fadeIn ? 1 : 0, transition: 'opacity 0.5s ease',
    }}>
      <style>{`
        @keyframes vc-pulse { 0%,100% { transform: scale(1); opacity: 0.7; } 50% { transform: scale(1.15); opacity: 1; } }
        @keyframes vc-blue-title {
          0% { color: #2563eb; text-shadow: 0 0 20px rgba(37,99,235,0.4); }
          50% { color: #fbbf24; text-shadow: 0 0 20px rgba(251,191,36,0.4); }
          100% { color: #2563eb; text-shadow: 0 0 20px rgba(37,99,235,0.4); }
        }
        @keyframes vc-blue-glow {
          0% { background: radial-gradient(circle, rgba(37,99,235,0.12), transparent 70%); }
          50% { background: radial-gradient(circle, rgba(212,160,23,0.12), transparent 70%); }
          100% { background: radial-gradient(circle, rgba(37,99,235,0.12), transparent 70%); }
        }
      `}</style>

      {/* Glow */}
      <div style={{
        position: 'absolute', top: '20%', width: 300, height: 300, borderRadius: '50%',
        background: isBlue
          ? 'radial-gradient(circle, rgba(37,99,235,0.12), transparent 70%)'
          : `radial-gradient(circle, ${agentColor}22, transparent 70%)`,
        filter: 'blur(60px)', pointerEvents: 'none',
        animation: isBlue ? 'vc-blue-glow 3s ease-in-out infinite' : 'none',
      }} />

      {isBlue ? <AgentBlueLogo size={140} /> : <AgentRedLogo size={140} />}
      <h2 style={{
        fontSize: '1.4rem', fontWeight: 700, margin: '1.5rem 0 0.5rem',
        ...(isBlue
          ? { animation: 'vc-blue-title 3s ease-in-out infinite' }
          : { color: agentColor }
        ),
      }}>{agentName}</h2>
      <p style={{ fontSize: '2rem', fontWeight: 300, color: 'rgba(255,255,255,0.7)', margin: '0 0 1rem', letterSpacing: '0.1em' }}>
        {callStarted ? formatDuration(callDuration) : '00:00'}
      </p>

      {/* Status */}
      <p style={{ fontSize: '0.9rem', color: 'rgba(255,255,255,0.5)', margin: '0 0 1rem' }}>{status}</p>

      {/* Start button */}
      {!callStarted && (
        <button onClick={handleStartCall} style={{
          padding: '1rem 2.5rem', borderRadius: '999px',
          background: isBlue
            ? 'linear-gradient(90deg, #1e3a5f, #2563eb, #d4a017, #fbbf24, #2563eb, #1e3a5f)'
            : `linear-gradient(135deg, ${agentColor}, ${agentColor}cc)`,
          backgroundSize: isBlue ? '300% 100%' : 'auto',
          border: 'none', color: 'white', fontSize: '1.1rem', fontWeight: 700,
          cursor: 'pointer', marginBottom: '2rem',
          boxShadow: isBlue
            ? '0 0 30px rgba(37,99,235,0.4), 0 0 60px rgba(212,160,23,0.15)'
            : `0 0 30px ${agentColor}66`,
          animation: isBlue ? 'vc-pulse 2s ease-in-out infinite, vc-btn-flow 3s ease-in-out infinite' : 'vc-pulse 2s ease-in-out infinite',
        }}>
          <style>{`
            @keyframes vc-btn-flow {
              0% { background-position: 0% 50%; }
              50% { background-position: 100% 50%; }
              100% { background-position: 0% 50%; }
            }
          `}</style>
          🎙️ Commencer l'appel
        </button>
      )}

      {/* Speaking indicator */}
      {callStarted && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.5rem' }}>
          <div style={{ display: 'flex', gap: 6 }}>
            {[0, 1, 2].map(i => {
              const dotColors = isBlue && isSpeaking === 'agent'
                ? ['#2563eb', '#d4a017', '#fbbf24']
                : [speakingColor, speakingColor, speakingColor]
              return (
                <div key={i} style={{
                  width: 10, height: 10, borderRadius: '50%', background: dotColors[i],
                  animation: isSpeaking !== 'idle' ? `vc-pulse 1.2s ease-in-out ${i * 0.2}s infinite` : 'none',
                  opacity: isSpeaking === 'idle' ? 0.3 : 1,
                  boxShadow: isBlue && isSpeaking === 'agent' ? `0 0 8px ${dotColors[i]}88` : 'none',
                }} />
              )
            })}
          </div>
        </div>
      )}

      {/* Transcript */}
      {(transcript || interimTranscript) && isSpeaking === 'user' && (
        <div style={{
          maxWidth: 400, padding: '0.75rem 1.25rem', borderRadius: 12,
          background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
          marginBottom: '2rem',
        }}>
          {transcript && (
            <span style={{ color: 'rgba(255,255,255,0.7)', fontSize: '0.85rem' }}>
              {transcript}
            </span>
          )}
          {interimTranscript && (
            <span style={{ color: 'rgba(255,255,255,0.35)', fontSize: '0.85rem', fontStyle: 'italic' }}>
              {transcript ? ' ' : ''}{interimTranscript}
            </span>
          )}
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
