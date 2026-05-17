// Page Enregistrer un événement — Saisie texte/vocale + analyse IA

import { useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { formatImpactJours } from '../utils/duration'
import { useT } from '../i18n/LanguageContext'
import { useDeviceContext } from '../contexts/DeviceContext'
import { AgentSyleaLogo } from '../components/AgentSyleaLogo'
import { AGENT_COLORS } from '../constants/agentColors'
import type { AnalyseEvenement } from '../types'

type Phase = 'form' | 'loading' | 'result' | 'done'

// ── Active agent detection ───────────────────────────────────────────────────
function getActiveAgent(): { id: 1 | 2 | 3; name: string; colors: { primary: string; gradient: string; bg: string; border: string; btnBg: string; btnColor: string } } | null {
  const a1 = localStorage.getItem('sylea_agent1_active') === 'true'
  const a2 = localStorage.getItem('sylea_agent2_active') === 'true'
  const a3 = localStorage.getItem('sylea_agent3_active') === 'true'
  if (a3) return {
    id: 3, name: 'Agent Sylea 3',
    colors: { primary: AGENT_COLORS.agent3.primary, gradient: 'linear-gradient(135deg, #1e3a5f, #2563eb, #d4a017, #fbbf24)', bg: 'rgba(37,99,235,0.08)', border: 'rgba(37,99,235,0.3)', btnBg: 'linear-gradient(135deg, #2563eb, #d4a017)', btnColor: 'white' },
  }
  if (a2) return {
    id: 2, name: 'Agent Sylea 2',
    colors: { primary: AGENT_COLORS.agent2.primary, gradient: 'linear-gradient(135deg, #b91c1c, #ef4444, #f87171)', bg: 'rgba(239,68,68,0.08)', border: 'rgba(239,68,68,0.3)', btnBg: 'linear-gradient(135deg, #b91c1c, #ef4444)', btnColor: 'white' },
  }
  if (a1) return {
    id: 1, name: 'Agent Sylea 1',
    colors: { primary: AGENT_COLORS.agent1.primary, gradient: 'linear-gradient(135deg, #d4a017, #f59e0b, #fbbf24)', bg: 'rgba(212,160,23,0.08)', border: 'rgba(212,160,23,0.3)', btnBg: 'linear-gradient(135deg, #d4a017, #f59e0b)', btnColor: '#0d0d14' },
  }
  return null
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
  // Detail du cascade : tous les SOs impactes (cible + ceux affectes par overflow)
  const [cascadeImpacts, setCascadeImpacts] = useState<Array<{
    so_id: string
    titre: string
    progression_avant: number
    progression_apres: number
    delta_pct: number
    est_cible: boolean
    est_complete: boolean
  }> | null>(null)
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
        impact_jours: analyse.impact_jours ?? 0,
        resume: analyse.resume,
        contexte_appareil: deviceCtx ?? undefined,
      })
      if (confirmResult?.sous_objectif_impacte) {
        setSousObjectifImpacte(confirmResult.sous_objectif_impacte)
      }
      // Capture la liste cascade : si l'event a debordé du SO ciblé, on
      // affiche aussi les autres SOs impactes pour la transparence.
      const cascade = (confirmResult as any)?.sous_objectifs_impactes
      if (Array.isArray(cascade) && cascade.length > 0) {
        setCascadeImpacts(cascade)
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
    setCascadeImpacts(null)
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

  const _probActuelle = profil.probabilite_actuelle

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
              {/* Block if no agent is active */}
              {!getActiveAgent() && (
                <div style={{
                  padding: '1.5rem', borderRadius: 'var(--radius-lg)',
                  background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.2)',
                  textAlign: 'center',
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.75rem',
                }}>
                  <AgentSyleaLogo size={36} />
                  <p style={{ color: 'var(--text-primary)', fontSize: '0.88rem', fontWeight: 600, margin: 0 }}>
                    Activez un Agent Sylea pour enregistrer des evenements
                  </p>
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', margin: 0, maxWidth: 400 }}>
                    L'agent enrichit le contexte de vos analyses pour des recommandations plus precises et personnalisees.
                  </p>
                  <button
                    className="btn btn-primary"
                    style={{ marginTop: '0.25rem', padding: '0.55rem 1.5rem', fontSize: '0.82rem' }}
                    onClick={() => navigate('/agents')}
                  >
                    Activer un Agent
                  </button>
                </div>
              )}
              {getActiveAgent() && (<>
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
              {contextNeeded && contextQuestion && (() => {
                const ag = getActiveAgent()
                const c = ag?.colors || { primary: '#d4a017', gradient: 'linear-gradient(135deg, #d4a017, #f59e0b, #fbbf24)', bg: 'rgba(212,160,23,0.08)', border: 'rgba(212,160,23,0.3)', btnBg: 'linear-gradient(135deg, #d4a017, #f59e0b)', btnColor: '#0d0d14' }
                return (
                <div
                  className="animate-fade-in"
                  style={{
                    background: `linear-gradient(135deg, ${c.bg}, transparent)`,
                    border: `1px solid ${c.border}`,
                    borderRadius: 'var(--radius-lg)',
                    padding: '1.25rem',
                  }}
                >
                  {/* Agent header */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.75rem' }}>
                    <AgentSyleaLogo size={24} color={c.primary} />
                    <span style={{
                      fontWeight: 700, fontSize: '0.85rem',
                      background: c.gradient,
                      WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                    }}>
                      {ag?.name || 'Agent Sylea 1'}
                    </span>
                  </div>

                  {/* Question bubble */}
                  <div style={{
                    background: 'rgba(255,255,255,0.04)',
                    borderRadius: 'var(--radius-md)',
                    padding: '0.85rem 1rem',
                    marginBottom: '0.85rem',
                    borderLeft: `3px solid ${c.primary}`,
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
                          : `${c.primary}26`,
                        border: `1px solid ${isListeningCtx ? '#ef4444' : `${c.primary}66`}`,
                        borderRadius: 'var(--radius-md)',
                        padding: '0.5rem 0.65rem',
                        cursor: 'pointer',
                        color: isListeningCtx ? 'white' : c.primary,
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
                          ? c.btnBg
                          : 'rgba(255,255,255,0.05)',
                        border: `1px solid ${c.primary}66`,
                        borderRadius: 'var(--radius-md)',
                        padding: '0.5rem 0.85rem',
                        cursor: contextInput.trim() ? 'pointer' : 'default',
                        color: contextInput.trim() ? c.btnColor : 'var(--text-muted)',
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
                )
              })()}

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
              </>)}
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
                background: (analyse.impact_jours ?? analyse.impact_probabilite) >= 0
                  ? 'linear-gradient(135deg, rgba(34,197,94,0.08), rgba(34,197,94,0.02))'
                  : 'linear-gradient(135deg, rgba(239,68,68,0.08), rgba(239,68,68,0.02))',
                border: `1px solid ${(analyse.impact_jours ?? analyse.impact_probabilite) >= 0 ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
                marginBottom: '1.5rem',
              }}
            >
              {/* Impact header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
                <div style={{
                  fontSize: '1.8rem',
                  fontWeight: 700,
                  color: (analyse.impact_jours ?? analyse.impact_probabilite) >= 0 ? '#22c55e' : '#ef4444',
                  fontFamily: 'Inter, system-ui, sans-serif',
                }}>
                  {formatImpactJours(analyse.impact_jours ?? 0)}
                </div>
                <div>
                  <p style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    {t('evenement.impact_temps')}
                  </p>
                  <p style={{
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    color: (analyse.impact_jours ?? analyse.impact_probabilite) >= 0 ? '#4ade80' : '#fca5a5',
                  }}>
                    {(analyse.impact_jours ?? 0) >= 0 ? 'temps gagne' : 'temps perdu'}
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
            {/* Mode "cascade detaille" : si on a la liste complete des SOs impactes,
                on l'affiche entiere (cible + cascade overflow) pour la transparence.
                Sinon fallback sur le simple nom du SO cible. */}
            {cascadeImpacts && cascadeImpacts.length > 0 ? (
              <div style={{ background: 'rgba(96,165,250,0.06)', border: '1px solid rgba(96,165,250,0.2)', borderRadius: 'var(--radius-md)', padding: '0.85rem 1rem', marginBottom: '1.5rem', textAlign: 'left' }}>
                <div style={{ color: '#93c5fd', fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.6rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span>{'\u21B3'}</span> Sous-objectifs impact\u00E9s ({cascadeImpacts.length})
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                  {cascadeImpacts.map((item) => (
                    <div key={item.so_id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.78rem' }}>
                      <span style={{
                        flexShrink: 0,
                        fontSize: '0.65rem',
                        padding: '0.1rem 0.4rem',
                        borderRadius: '4px',
                        background: item.est_cible ? 'rgba(34,211,238,0.18)' : 'rgba(139,92,246,0.12)',
                        color: item.est_cible ? '#22d3ee' : '#a78bfa',
                        fontWeight: 600,
                        minWidth: '52px',
                        textAlign: 'center',
                      }}>
                        {item.est_cible ? 'CIBLE' : 'CASCADE'}
                      </span>
                      <span style={{ color: '#cbd5e1', flex: 1 }}>{item.titre}</span>
                      <span style={{ color: '#94a3b8', fontSize: '0.72rem', whiteSpace: 'nowrap' }}>
                        {item.progression_avant.toFixed(1)}% \u2192 <strong style={{ color: item.est_complete ? '#22c55e' : '#cbd5e1' }}>{item.progression_apres.toFixed(1)}%</strong>
                        {' '}<span style={{ color: '#22c55e' }}>(+{item.delta_pct.toFixed(1)})</span>
                      </span>
                    </div>
                  ))}
                </div>
                {cascadeImpacts.some(i => !i.est_cible) && (
                  <div style={{ marginTop: '0.6rem', paddingTop: '0.5rem', borderTop: '1px solid rgba(96,165,250,0.15)', fontSize: '0.7rem', color: '#94a3b8', lineHeight: 1.45 }}>
                    L'impact d\u00E9passait la capacit\u00E9 du SO cibl\u00E9 \u2014 l'exc\u00E9dent a \u00E9t\u00E9 redistribu\u00E9 proportionnellement sur les autres SOs pour pr\u00E9server la coh\u00E9rence (impact total = somme).
                  </div>
                )}
              </div>
            ) : sousObjectifImpacte ? (
              <div style={{ background: 'rgba(96,165,250,0.08)', border: '1px solid rgba(96,165,250,0.25)', borderRadius: 'var(--radius-md)', padding: '0.6rem 1rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: '#60a5fa', fontSize: '0.8rem' }}>{'\u21B3'}</span>
                <span style={{ color: '#93c5fd', fontSize: '0.82rem' }}>{t('evenement.sous_objectif_impacte')} <strong>{sousObjectifImpacte}</strong></span>
              </div>
            ) : null}
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
