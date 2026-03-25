// Page Enregistrer un événement — Saisie texte/vocale + analyse IA

import { useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { deltaFromImpact } from '../utils/duration'
import { useT } from '../i18n/LanguageContext'
import { useDeviceContext } from '../contexts/DeviceContext'
import type { AnalyseEvenement } from '../types'

type Phase = 'form' | 'loading' | 'result' | 'done'

// ── Agent Sylea Logo (gold S) ────────────────────────────────────────────────
const CX = 190, CY = 170
const S_PATH = `M ${CX} ${CY-105} C ${CX+90} ${CY-105}, ${CX+90} ${CY-28}, ${CX} ${CY} C ${CX-90} ${CY+28}, ${CX-90} ${CY+105}, ${CX} ${CY+105}`

function AgentSyleaLogo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id="evt-agent-gold-g" x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%" stopColor="#d4a017" />
          <stop offset="40%" stopColor="#f59e0b" />
          <stop offset="100%" stopColor="#fbbf24" />
        </linearGradient>
        <filter id="evt-agent-gold-blur">
          <feGaussianBlur stdDeviation="20" />
        </filter>
      </defs>
      <path d={S_PATH} stroke="url(#evt-agent-gold-g)" strokeWidth="90" fill="none" strokeLinecap="round"
        style={{ filter: 'url(#evt-agent-gold-blur)', opacity: 0.18 }} />
      <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke="url(#evt-agent-gold-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke="#050810" strokeWidth="18" fill="none" strokeLinecap="butt" />
      <path d={S_PATH} stroke="rgba(255,230,150,0.5)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  )
}

export function EvenementPage() {
  const navigate = useNavigate()
  const t = useT()
  const { ctx: deviceCtx } = useDeviceContext()
  const { profil, setProfil, refreshSousObjectifs } = useStore()

  const [phase, setPhase]         = useState<Phase>('form')
  const [description, setDescription] = useState('')
  const [analyse, setAnalyse]     = useState<AnalyseEvenement | null>(null)
  const [error, setError]         = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [sousObjectifImpacte, setSousObjectifImpacte] = useState<string | null>(null)
  const recognitionRef = useRef<any>(null)

  // Context-gathering state
  const [contextNeeded, setContextNeeded] = useState(false)
  const [contextQuestion, setContextQuestion] = useState<string | null>(null)
  const [contextInput, setContextInput] = useState('')
  const [contextProvided, setContextProvided] = useState(false)
  const [contextLoading, setContextLoading] = useState(false)
  const [contextFeedback, setContextFeedback] = useState<string | null>(null)
  const [isListeningCtx, setIsListeningCtx] = useState(false)
  const recognitionCtxRef = useRef<any>(null)

  // -- Load profil on mount --------------------------------------------------
  useEffect(() => {
    if (!profil) {
      api.getProfil().then(setProfil).catch(() => navigate('/profil'))
    }
  }, [])

  // -- Voice input ----------------------------------------------------------
  const toggleVoice = useCallback(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) {
      setError(t('evenement.vocal_indisponible'))
      return
    }

    if (isListening && recognitionRef.current) {
      recognitionRef.current.stop()
      setIsListening(false)
      return
    }

    const r = new SR()
    r.lang = 'fr-FR'
    r.continuous = false
    r.interimResults = false
    recognitionRef.current = r

    r.onresult = (e: any) => {
      const text = e.results[0][0].transcript
      setDescription((prev) => (prev ? prev + ' ' + text : text))
      setIsListening(false)
    }
    r.onerror = () => setIsListening(false)
    r.onend = () => setIsListening(false)

    r.start()
    setIsListening(true)
  }, [isListening])

  // Voice input for context panel
  const toggleVoiceCtx = useCallback(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) return

    if (isListeningCtx && recognitionCtxRef.current) {
      recognitionCtxRef.current.stop()
      setIsListeningCtx(false)
      return
    }

    const r = new SR()
    r.lang = 'fr-FR'
    r.continuous = false
    r.interimResults = false
    recognitionCtxRef.current = r

    r.onresult = (e: any) => {
      const text = e.results[0][0].transcript
      setContextInput((prev) => (prev ? prev + ' ' + text : text))
      setIsListeningCtx(false)
    }
    r.onerror = () => setIsListeningCtx(false)
    r.onend = () => setIsListeningCtx(false)

    r.start()
    setIsListeningCtx(true)
  }, [isListeningCtx])

  const handleSendContext = async (text: string) => {
    if (!text.trim()) return
    setContextLoading(true)
    setContextFeedback(null)
    try {
      const result = await api.agentSaveContext(
        text.trim(),
        `evenement: ${description.trim().slice(0, 50)}`,
        'evenement',
        description.trim(),
      )
      setContextInput('')
      if (result.sufficient) {
        setContextProvided(true)
        setContextNeeded(false)
      } else {
        // Context insufficient — show feedback as a new question
        setContextFeedback(result.feedback)
        if (result.feedback) {
          setContextQuestion(result.feedback)
        }
      }
    } catch {
      setContextProvided(true)
      setContextNeeded(false)
    } finally {
      setContextLoading(false)
    }
  }

  // -- Handlers -------------------------------------------------------------
  const handleAnalyser = async () => {
    if (!description.trim() || description.trim().length < 5) {
      setError(t('evenement.min_caracteres'))
      return
    }

    // Check context before analyzing (only if not already provided)
    if (!contextProvided) {
      setContextLoading(true)
      try {
        const ctxResult = await api.agentCheckContext(
          'evenement',
          description.trim(),
          undefined,
          deviceCtx ?? undefined,
        )
        if (ctxResult.needs_context) {
          setContextNeeded(true)
          setContextQuestion(ctxResult.agent_question)
          setContextLoading(false)
          return
        }
      } catch {
        // If check fails, proceed with analysis anyway
      }
      setContextLoading(false)
    }

    setError(null)
    setPhase('loading')
    try {
      const result = await api.analyserEvenement(description.trim(), deviceCtx ?? undefined)
      setAnalyse(result)
      setPhase('result')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('evenement.erreur_analyse'))
      setPhase('form')
    }
  }

  const handleConfirmer = async () => {
    if (!analyse) return
    setSubmitting(true)
    setError(null)
    try {
      const confirmResult = await api.confirmerEvenement({
        description: description.trim(),
        impact_probabilite: analyse.impact_probabilite,
        resume: analyse.resume,
        contexte_appareil: deviceCtx ?? undefined,
      })
      if (confirmResult?.sous_objectif_impacte) {
        setSousObjectifImpacte(confirmResult.sous_objectif_impacte)
      }
      const updated = await api.getProfil()
      setProfil(updated)
      await refreshSousObjectifs()
      setPhase('done')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('evenement.erreur_enregistrement'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleReset = () => {
    setDescription('')
    setAnalyse(null)
    setError(null)
    setSousObjectifImpacte(null)
    setContextNeeded(false)
    setContextQuestion(null)
    setContextInput('')
    setContextProvided(false)
    setContextFeedback(null)
    setPhase('form')
  }

  // -- Guard ----------------------------------------------------------------
  if (!profil) {
    return (
      <div className="page">
        <div className="container page-content" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem' }}>
          <p style={{ color: 'var(--text-muted)' }}>{t('evenement.chargement_profil')}</p>
          <div className="spinner" />
        </div>
      </div>
    )
  }

  const probActuelle = profil.probabilite_actuelle
  const probCalculeeVal = profil.objectif?.probabilite_calculee ?? 0
  const probTemps = probCalculeeVal + probActuelle

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* En-tête */}
        <div style={{ marginBottom: '2rem' }}>
          <h2 style={{ color: 'var(--accent-silver)', marginBottom: '0.375rem' }}>
            {t('evenement.titre')}
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            {t('evenement.subtitle')}
          </p>
        </div>

        {/* Phase : Formulaire */}
        {phase === 'form' && (
          <div className="card animate-fade-in-scale" style={{ maxWidth: '600px', margin: '0 auto' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              <div className="input-group">
                <label className="input-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>
                    {t('evenement.description_label')} <span style={{ color: 'var(--accent-gold)' }}>*</span>
                  </span>
                  <button
                    type="button"
                    onClick={toggleVoice}
                    style={{
                      background: isListening
                        ? 'linear-gradient(135deg, #ef4444, #dc2626)'
                        : 'linear-gradient(135deg, rgba(26,111,216,0.18), rgba(26,111,216,0.06))',
                      border: `1px solid ${isListening ? '#ef4444' : 'var(--accent-violet-dim)'}`,
                      borderRadius: 'var(--radius-md)',
                      padding: '0.35rem 0.75rem',
                      cursor: 'pointer',
                      color: isListening ? 'white' : 'var(--accent-violet-light)',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      letterSpacing: '0.06em',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.4rem',
                      transition: 'all 0.2s',
                    }}
                  >
                    {isListening ? (
                      <>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'white', animation: 'pulse 1s infinite' }} />
                        {t('evenement.arreter')}
                      </>
                    ) : (
                      <>{t('evenement.dicter')}</>
                    )}
                  </button>
                </label>
                <textarea
                  className="input"
                  rows={4}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={t('evenement.description_placeholder')}
                  style={{ resize: 'vertical' }}
                />
              </div>

              {/* Context-gathering panel */}
              {contextNeeded && contextQuestion && (
                <div
                  className="animate-fade-in"
                  style={{
                    background: 'linear-gradient(135deg, rgba(212,160,23,0.08), rgba(245,158,11,0.04))',
                    border: '1px solid rgba(212,160,23,0.3)',
                    borderRadius: 'var(--radius-lg)',
                    padding: '1.25rem',
                  }}
                >
                  {/* Agent header */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.75rem' }}>
                    <AgentSyleaLogo size={24} />
                    <span style={{
                      fontWeight: 700, fontSize: '0.85rem',
                      background: 'linear-gradient(135deg, #d4a017, #f59e0b, #fbbf24)',
                      WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                    }}>
                      Agent Sylea 1
                    </span>
                  </div>

                  {/* Question bubble */}
                  <div style={{
                    background: 'rgba(255,255,255,0.04)',
                    borderRadius: 'var(--radius-md)',
                    padding: '0.85rem 1rem',
                    marginBottom: '0.85rem',
                    borderLeft: '3px solid #d4a017',
                  }}>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', lineHeight: 1.5, margin: 0 }}>
                      {contextQuestion}
                    </p>
                  </div>

                  {/* Text input + mic + send */}
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <input
                      type="text"
                      className="input"
                      value={contextInput}
                      onChange={(e) => setContextInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleSendContext(contextInput) }}
                      placeholder="Ta reponse..."
                      style={{ flex: 1 }}
                      disabled={contextLoading}
                    />
                    <button
                      type="button"
                      onClick={toggleVoiceCtx}
                      style={{
                        background: isListeningCtx
                          ? 'linear-gradient(135deg, #ef4444, #dc2626)'
                          : 'rgba(212,160,23,0.15)',
                        border: `1px solid ${isListeningCtx ? '#ef4444' : 'rgba(212,160,23,0.4)'}`,
                        borderRadius: 'var(--radius-md)',
                        padding: '0.5rem 0.65rem',
                        cursor: 'pointer',
                        color: isListeningCtx ? 'white' : '#fbbf24',
                        fontSize: '1rem',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                      title="Dicter"
                    >
                      {isListeningCtx ? (
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'white', animation: 'pulse 1s infinite', display: 'inline-block' }} />
                      ) : (
                        '\uD83C\uDFA4'
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSendContext(contextInput)}
                      disabled={!contextInput.trim() || contextLoading}
                      style={{
                        background: contextInput.trim()
                          ? 'linear-gradient(135deg, #d4a017, #f59e0b)'
                          : 'rgba(255,255,255,0.05)',
                        border: '1px solid rgba(212,160,23,0.4)',
                        borderRadius: 'var(--radius-md)',
                        padding: '0.5rem 0.85rem',
                        cursor: contextInput.trim() ? 'pointer' : 'default',
                        color: contextInput.trim() ? '#0d0d14' : 'var(--text-muted)',
                        fontWeight: 600, fontSize: '0.82rem',
                      }}
                    >
                      {contextLoading ? '...' : 'Envoyer'}
                    </button>
                  </div>

                  {/* Insufficient context warning */}
                  {contextFeedback && (
                    <div
                      className="animate-fade-in"
                      style={{
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.55rem 0.85rem',
                        background: 'rgba(245,158,11,0.08)',
                        border: '1px solid rgba(245,158,11,0.3)',
                        borderRadius: 'var(--radius-md)',
                        color: '#f59e0b',
                        fontSize: '0.82rem', fontWeight: 500,
                        marginTop: '0.5rem',
                      }}
                    >
                      <span style={{ fontSize: '1rem' }}>{'\u26A0'}</span>
                      Contexte insuffisant : {contextFeedback}
                    </div>
                  )}
                </div>
              )}

              {/* Context provided confirmation */}
              {contextProvided && (
                <div
                  className="animate-fade-in"
                  style={{
                    display: 'flex', alignItems: 'center', gap: '0.5rem',
                    padding: '0.65rem 1rem',
                    background: 'rgba(34,197,94,0.08)',
                    border: '1px solid rgba(34,197,94,0.3)',
                    borderRadius: 'var(--radius-md)',
                    color: '#4ade80',
                    fontSize: '0.85rem', fontWeight: 600,
                  }}
                >
                  <span style={{ fontSize: '1.1rem' }}>{'\u2713'}</span>
                  Contexte enrichi — Vous pouvez maintenant analyser
                </div>
              )}

              {error && (
                <p style={{ color: 'var(--danger)', fontSize: '0.875rem' }}>{'\u26A0'} {error}</p>
              )}

              <button
                className="btn btn-primary btn-full"
                onClick={handleAnalyser}
                disabled={!description.trim() || description.trim().length < 5 || contextNeeded || contextLoading}
              >
                {contextLoading ? 'Verification du contexte...' : t('evenement.analyser')}
              </button>
            </div>
          </div>
        )}

        {/* Phase : Chargement */}
        {phase === 'loading' && (
          <div className="loading-center">
            <div
              style={{
                width: '64px',
                height: '64px',
                borderRadius: '50%',
                border: '3px solid var(--accent-violet-dim)',
                borderTop: '3px solid var(--accent-violet)',
                animation: 'spin 0.8s linear infinite',
              }}
            />
            <div style={{ textAlign: 'center' }}>
              <p style={{ color: 'var(--accent-silver)', fontWeight: 600, marginBottom: '0.375rem' }}>
                {t('evenement.analyse_cours')}
              </p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
                {t('evenement.calcul_impact')}
              </p>
            </div>
          </div>
        )}

        {/* Phase : Résultat */}
        {phase === 'result' && analyse && (
          <div className="animate-fade-in" style={{ maxWidth: '600px', margin: '0 auto' }}>

            {/* Card impact */}
            <div
              className="card"
              style={{
                background: analyse.impact_probabilite >= 0
                  ? 'linear-gradient(135deg, rgba(34,197,94,0.08), rgba(34,197,94,0.02))'
                  : 'linear-gradient(135deg, rgba(239,68,68,0.08), rgba(239,68,68,0.02))',
                border: `1px solid ${analyse.impact_probabilite >= 0 ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
                marginBottom: '1.5rem',
              }}
            >
              {/* Impact header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
                <div style={{
                  fontSize: '1.8rem',
                  fontWeight: 700,
                  color: analyse.impact_probabilite >= 0 ? '#22c55e' : '#ef4444',
                  fontFamily: 'Inter, system-ui, sans-serif',
                }}>
                  {deltaFromImpact(probTemps, analyse.impact_probabilite)}
                </div>
                <div>
                  <p style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    {t('evenement.impact_temps')}
                  </p>
                  <p style={{
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    color: analyse.impact_probabilite >= 0 ? '#4ade80' : '#fca5a5',
                  }}>
                    {analyse.impact_probabilite >= 0 ? '+' : ''}{analyse.impact_probabilite.toFixed(1)}%
                  </p>
                </div>
              </div>

              {/* Analyse */}
              <p style={{ color: 'var(--text-secondary)', lineHeight: '1.5', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
                {analyse.explication}
              </p>

              {/* Conseil */}
              <p style={{ fontSize: '0.8rem', color: 'var(--accent-gold)', fontStyle: 'italic' }}>
                {'\u2605'} {analyse.conseil}
              </p>
            </div>

            {error && (
              <p style={{ color: 'var(--danger)', fontSize: '0.875rem', marginBottom: '1rem' }}>{'\u26A0'} {error}</p>
            )}

            {/* Actions */}
            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button className="btn btn-outline" onClick={handleReset}>
                {t('evenement.nouvel_evenement')}
              </button>
              <button
                className="btn btn-gold"
                onClick={handleConfirmer}
                disabled={submitting}
              >
                {submitting ? t('evenement.enregistrement') : t('evenement.confirmer_evenement')}
              </button>
            </div>
          </div>
        )}

        {/* Phase : Confirmation */}
        {phase === 'done' && (
          <div
            className="card animate-fade-in-scale"
            style={{
              maxWidth: '480px',
              margin: '0 auto',
              textAlign: 'center',
              padding: '2.5rem',
              border: '1px solid var(--success)',
              boxShadow: '0 0 32px rgba(34,197,94,0.15)',
            }}
          >
            <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>{'\u2713'}</div>
            <h3 style={{ color: 'var(--success)', marginBottom: '0.75rem' }}>{t('evenement.evenement_enregistre')}</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '1rem', lineHeight: '1.5' }}>
              {t('evenement.evenement_sauvegarde')}
            </p>
            {sousObjectifImpacte && (
              <div style={{ background: 'rgba(96,165,250,0.08)', border: '1px solid rgba(96,165,250,0.25)', borderRadius: 'var(--radius-md)', padding: '0.6rem 1rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: '#60a5fa', fontSize: '0.8rem' }}>{'\u21B3'}</span>
                <span style={{ color: '#93c5fd', fontSize: '0.82rem' }}>{t('evenement.sous_objectif_impacte')} <strong>{sousObjectifImpacte}</strong></span>
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
              <button className="btn btn-outline btn-sm" onClick={handleReset}>
                {t('evenement.nouvel_evenement')}
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => navigate('/')}>
                {t('evenement.tableau_bord')}
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
