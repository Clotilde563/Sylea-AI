// Page Dilemme — Analyse IA d'un choix de vie (N options)

import { useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { OptionCard } from '../components/OptionCard'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { useT } from '../i18n/LanguageContext'
import { useDeviceContext } from '../contexts/DeviceContext'
import { AgentSyleaLogo } from '../components/AgentSyleaLogo'
import { AGENT_COLORS } from '../constants/agentColors'
import type { AnalyseDilemme, Decision, TrackingItem } from '../types'

type Phase = 'form' | 'loading' | 'result' | 'done'

// ── Active agent detection ───────────────────────────────────────────────────
function getActiveAgent(): { id: 1 | 2; name: string; colors: { primary: string; gradient: string; bg: string; border: string; btnBg: string; btnColor: string } } | null {
  const a1 = localStorage.getItem('sylea_agent1_active') === 'true'
  const a2 = localStorage.getItem('sylea_agent2_active') === 'true'
  if (a2) return {
    id: 2, name: 'Agent Syléa 2',
    colors: { primary: AGENT_COLORS.agent2.primary, gradient: 'linear-gradient(135deg, #b91c1c, #ef4444, #f87171)', bg: 'rgba(239,68,68,0.08)', border: 'rgba(239,68,68,0.3)', btnBg: 'linear-gradient(135deg, #b91c1c, #ef4444)', btnColor: 'white' },
  }
  if (a1) return {
    id: 1, name: 'Agent Syléa 1',
    colors: { primary: AGENT_COLORS.agent1.primary, gradient: 'linear-gradient(135deg, #d4a017, #f59e0b, #fbbf24)', bg: 'rgba(212,160,23,0.08)', border: 'rgba(212,160,23,0.3)', btnBg: 'linear-gradient(135deg, #d4a017, #f59e0b)', btnColor: '#0d0d14' },
  }
  return null
}

const MAX_OPTIONS = 5
const MIN_OPTIONS = 2

// Couleurs pour les pastilles d'options
const OPTION_COLORS = [
  'linear-gradient(135deg, var(--accent-violet), #5b21b6)',
  'linear-gradient(135deg, #d4a017, #b8860b)',
  'linear-gradient(135deg, #059669, #047857)',
  'linear-gradient(135deg, #dc2626, #b91c1c)',
  'linear-gradient(135deg, #2563eb, #1d4ed8)',
]
const OPTION_TEXT_COLORS = ['white', '#0d0d14', 'white', 'white', 'white']

export function DilemmePage() {
  const t = useT()
  const navigate = useNavigate()
  const { profil, analyse, setAnalyse, setProfil, refreshSousObjectifs } = useStore()
  const { ctx: deviceCtx } = useDeviceContext()

  const [phase, setPhase] = useState<Phase>(analyse ? 'result' : 'form')
  const [options, setOptions] = useState<string[]>(['', ''])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // Phase 'done' : tracking cree, on affiche l'ID + nb_periodes pour rassurer
  // l'user que les notifs vont arriver.
  const [trackingCree, setTrackingCree] = useState<TrackingItem | null>(null)
  const [impactTemporel, setImpactTemporel] = useState<string>('1_mois')
  const [customYears, setCustomYears] = useState(0)
  const [customMonths, setCustomMonths] = useState(0)
  const [customDays, setCustomDays] = useState(0)

  // Context-gathering state
  const [contextNeeded, setContextNeeded] = useState(false)
  const [contextQuestion, setContextQuestion] = useState<string | null>(null)
  const [contextInput, setContextInput] = useState('')
  const [contextProvided, setContextProvided] = useState(false)
  const [contextLoading, setContextLoading] = useState(false)
  const [contextFeedback, setContextFeedback] = useState<string | null>(null)
  // Compteur de tentatives pour le contexte. Au-dela de MAX_CONTEXT_ATTEMPTS (3),
  // on force-pass meme si Claude juge insuffisant -> evite la boucle infinie
  // ou l'user reste prisonnier du panel. Le backend a aussi son propre cap.
  const [contextAttempts, setContextAttempts] = useState(0)
  const MAX_CONTEXT_ATTEMPTS = 3
  const [isListeningCtx, setIsListeningCtx] = useState(false)
  const recognitionCtxRef = useRef<any>(null)

  const TEMPORAL_OPTIONS = [
    { value: '1_jour', label: t('dilemme.jour') },
    { value: '1_semaine', label: t('dilemme.semaine') },
    { value: '1_mois', label: t('dilemme.mois_label') },
    { value: '1_an', label: t('dilemme.an_label') },
    { value: 'long_terme', label: t('dilemme.long_terme') },
    { value: 'personnalise', label: t('dilemme.personnalise') },
  ]

  const getTemporalLabel = () => {
    const map: Record<string, string> = {
      '1_jour': "aujourd'hui",
      '1_semaine': 'cette semaine',
      '1_mois': 'ce mois-ci',
      '1_an': "cette année",
      'long_terme': "sur toute la durée de l'objectif",
    }
    if (impactTemporel === 'personnalise') {
      const parts = []
      if (customYears > 0) parts.push(`${customYears} an(s)`)
      if (customMonths > 0) parts.push(`${customMonths} mois`)
      if (customDays > 0) parts.push(`${customDays} jour(s)`)
      return parts.length > 0 ? `dans ${parts.join(' ')}` : "aujourd'hui"
    }
    return map[impactTemporel] || 'ce mois-ci'
  }

  // Durée max = durée restante de l'objectif
  const objectifMaxDays = (() => {
    if (profil?.objectif?.deadline) {
      const d = new Date(profil.objectif.deadline)
      const now = new Date()
      return Math.max(1, Math.ceil((d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)))
    }
    return 3650
  })()

  const getImpactDays = (): number => {
    switch (impactTemporel) {
      case '1_jour': return 1
      case '1_semaine': return 7
      case '1_mois': return 30
      case '1_an': return 365
      case 'long_terme': return objectifMaxDays
      case 'personnalise':
        return Math.max(1, Math.min(objectifMaxDays, customYears * 365 + customMonths * 30 + customDays))
      default: return 30
    }
  }

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
    const newAttempt = contextAttempts + 1
    setContextAttempts(newAttempt)
    try {
      const questionAuto = `${options.map(o => o.trim()).join(' vs ')}`
      const result = await api.agentSaveContext(
        text.trim(),
        `dilemme: ${questionAuto}`,
        'dilemme',
        questionAuto,
        options.map(o => o.trim()),
        newAttempt,
      )
      setContextInput('')
      // Force-pass apres MAX_CONTEXT_ATTEMPTS pour ne JAMAIS piéger l'user.
      // Le backend a sa propre garde a >=3 attempts, mais on duplique cote
      // front pour gerer aussi le cas API down.
      if (result.sufficient || newAttempt >= MAX_CONTEXT_ATTEMPTS) {
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
      // En cas d'erreur reseau, on est indulgent : on avance
      setContextProvided(true)
      setContextNeeded(false)
    } finally {
      setContextLoading(false)
    }
  }

  const handleAnalyser = async () => {
    if (options.some(o => !o.trim())) {
      setError(t('dilemme.remplir_champs'))
      return
    }
    if (impactTemporel === 'personnalise' && customYears === 0 && customMonths === 0 && customDays === 0) {
      setError(t('dilemme.duree_personnalisee_vide'))
      return
    }
    if (impactTemporel === 'personnalise' && (customYears * 365 + customMonths * 30 + customDays) > objectifMaxDays) {
      setError(`La duree ne peut pas depasser celle de votre objectif (~${Math.floor(objectifMaxDays / 365)}a ${Math.floor((objectifMaxDays % 365) / 30)}m).`)
      return
    }

    // Check context before analyzing (only if not already provided)
    if (!contextProvided) {
      setContextLoading(true)
      try {
        const questionAuto = `${options.map(o => o.trim()).join(' vs ')}`
        const ctxResult = await api.agentCheckContext(
          'dilemme',
          questionAuto,
          options.map(o => o.trim()),
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
      const questionAuto = `${options.map(o => o.trim()).join(' vs ')} (impact temporel: ${getTemporalLabel()})`
      const result = await api.analyserDilemme({
        question: questionAuto,
        options: options.map(o => o.trim()),
        impact_temporel_jours: getImpactDays(),
        contexte_appareil: deviceCtx ?? undefined,
      })
      setAnalyse(result)
      setPhase('result')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('dilemme.erreur_analyse'))
      setPhase('form')
    }
  }

  // NOUVEAU FLOW (commit 2/3 tracking) : au lieu de choisir une option et
  // d'appliquer l'impact immediatement, on demarre un TRACKING. L'utilisateur
  // ne choisit PAS de A/B/C maintenant — c'est via les notifs periodiques
  // (J+30, J+60, ...) qu'on lui demande ce qu'il a REELLEMENT fait. A la fin
  // du tracking, un recap pondere applique l'impact reel.
  const handleConfirmer = async () => {
    if (!analyse) return
    setSubmitting(true)
    setError(null)
    try {
      const impactJours = getImpactDays() || 30
      // Timezone du device (Europe/Paris, America/New_York, ...)
      const deviceTz = (() => {
        try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' } catch { return 'UTC' }
      })()
      const r = await api.trackingCreate({
        question: analyse.question,
        options: analyse.options.map(o => ({
          lettre: o.lettre,
          description: o.description,
          impact_jours: o.impact_jours,
          pros: o.pros,
          cons: o.cons,
          resume: o.resume,
        })),
        impact_temporel_jours: impactJours,
        verdict: analyse.verdict,
        etude_scientifique: analyse.etude_scientifique || '',
        device_tz: deviceTz,
      })
      setTrackingCree(r.tracking)
      setAnalyse(null)
      setPhase('done')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('dilemme.erreur_enregistrement'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleReset = () => {
    setOptions(['', ''])
    setAnalyse(null)
    setError(null)
    setTrackingCree(null)
    setImpactTemporel('1_mois')
    setCustomYears(0)
    setCustomMonths(0)
    setCustomDays(0)
    setContextNeeded(false)
    setContextQuestion(null)
    setContextInput('')
    setContextProvided(false)
    setContextFeedback(null)
    setContextAttempts(0)
    setPhase('form')
  }

  // Helper : invalide le contexte fourni quand l'user modifie ses options.
  // Sinon on garderait un contexte stale (ex: contexte donne pour "Marc vs Paul"
  // mais l'user a maintenant tape "Sarah vs Lucas" -> faut re-checker).
  const invalidateContext = () => {
    if (contextProvided) {
      setContextProvided(false)
      setContextAttempts(0)
    }
  }

  const addOption = () => {
    if (options.length < MAX_OPTIONS) {
      setOptions([...options, ''])
      invalidateContext()
    }
  }

  const removeOption = (index: number) => {
    if (options.length > MIN_OPTIONS) {
      setOptions(options.filter((_, i) => i !== index))
      invalidateContext()
    }
  }

  const updateOption = (index: number, value: string) => {
    const next = [...options]
    next[index] = value
    setOptions(next)
    invalidateContext()
  }

  if (!profil) {
    return (
      <div className="page">
        <div className="container page-content" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem' }}>
          <p style={{ color: 'var(--text-muted)' }}>{t('dilemme.creer_profil_msg')}</p>
          <button className="btn btn-primary" onClick={() => navigate('/profil')}>
            {t('dilemme.creer_profil')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* En-tête — Linear style */}
        <div style={{ marginBottom: 'var(--space-8)' }}>
          <h1 style={{
            fontSize: 'var(--fs-3xl)',
            fontWeight: 700,
            letterSpacing: 'var(--tracking-tight)',
            color: 'var(--text-primary)',
            marginBottom: 'var(--space-2)',
            lineHeight: 1.15,
          }}>
            {t('dilemme.analyser_choix')}
          </h1>
          <p style={{
            color: 'var(--text-muted)',
            fontSize: 'var(--fs-md)',
            lineHeight: 1.55,
            maxWidth: 600,
          }}>
            {t('dilemme.analyser_desc')}
          </p>
        </div>

        {/* Phase : Formulaire */}
        {phase === 'form' && (
          <div className="card animate-fade-in-scale" style={{ maxWidth: '680px', margin: '0 auto' }}>
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
                    Activez un Agent Sylea pour analyser vos choix
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
              {/* Formulaire masque si aucun agent actif */}
              {getActiveAgent() && (<>
              {/* Sélecteur d'impact temporel */}
              <div className="input-group">
                <label className="input-label">
                  {t('dilemme.impact_temporel')} <span style={{ color: 'var(--accent-gold)' }}>*</span>
                </label>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '0.5rem' }}>
                  {t('dilemme.impact_temporel_desc')}
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
                  {TEMPORAL_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setImpactTemporel(opt.value)}
                      style={{
                        padding: '0.6rem 0.5rem',
                        borderRadius: 'var(--radius-md)',
                        border: impactTemporel === opt.value
                          ? '2px solid var(--accent-violet)'
                          : '1px solid var(--border)',
                        background: impactTemporel === opt.value
                          ? 'rgba(124,58,237,0.15)'
                          : 'rgba(255,255,255,0.03)',
                        color: impactTemporel === opt.value
                          ? 'var(--accent-violet-light)'
                          : 'var(--text-secondary)',
                        cursor: 'pointer',
                        fontSize: '0.85rem',
                        fontWeight: impactTemporel === opt.value ? 600 : 400,
                        transition: 'all 0.15s',
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
                {impactTemporel === 'personnalise' && (
                  <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.75rem' }}>
                    <div style={{ flex: 1 }}>
                      <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{t('dilemme.annees')}</label>
                      <input
                        type="number"
                        className="input"
                        min={0}
                        max={50}
                        value={customYears}
                        onChange={(e) => setCustomYears(Math.max(0, parseInt(e.target.value) || 0))}
                        style={{ textAlign: 'center' }}
                      />
                    </div>
                    <div style={{ flex: 1 }}>
                      <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{t('dilemme.mois')}</label>
                      <input
                        type="number"
                        className="input"
                        min={0}
                        max={11}
                        value={customMonths}
                        onChange={(e) => setCustomMonths(Math.max(0, parseInt(e.target.value) || 0))}
                        style={{ textAlign: 'center' }}
                      />
                    </div>
                    <div style={{ flex: 1 }}>
                      <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{t('dilemme.jours')}</label>
                      <input
                        type="number"
                        className="input"
                        min={0}
                        max={30}
                        value={customDays}
                        onChange={(e) => setCustomDays(Math.max(0, parseInt(e.target.value) || 0))}
                        style={{ textAlign: 'center' }}
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Options dynamiques */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {options.map((opt, i) => {
                  const lettre = String.fromCharCode(65 + i)
                  return (
                    <div key={i} className="input-group">
                      <label className="input-label" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span
                          style={{
                            width: '20px',
                            height: '20px',
                            borderRadius: '50%',
                            background: OPTION_COLORS[i % OPTION_COLORS.length],
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '0.7rem',
                            fontWeight: 700,
                            color: OPTION_TEXT_COLORS[i % OPTION_TEXT_COLORS.length],
                            flexShrink: 0,
                          }}
                        >
                          {lettre}
                        </span>
                        {t('dilemme.option')} {lettre} <span style={{ color: 'var(--accent-gold)' }}>*</span>
                        {options.length > MIN_OPTIONS && (
                          <button
                            type="button"
                            onClick={() => removeOption(i)}
                            style={{
                              marginLeft: 'auto',
                              background: 'none',
                              border: '1px solid var(--border)',
                              borderRadius: '4px',
                              color: 'var(--text-muted)',
                              cursor: 'pointer',
                              fontSize: '0.75rem',
                              padding: '0.15rem 0.5rem',
                              transition: 'all 0.15s',
                            }}
                            title={t('dilemme.supprimer_option')}
                          >
                            ×
                          </button>
                        )}
                      </label>
                      <textarea
                        className="input"
                        rows={2}
                        value={opt}
                        onChange={(e) => updateOption(i, e.target.value)}
                        placeholder={`Ex: ${i === 0 ? 'Quitter mon CDI et lancer ma startup' : i === 1 ? 'Rester en CDI et développer en parallèle' : 'Une autre approche...'}`}
                      />
                    </div>
                  )
                })}
              </div>

              {/* Bouton ajouter option */}
              {options.length < MAX_OPTIONS && (
                <button
                  type="button"
                  onClick={addOption}
                  style={{
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px dashed var(--border)',
                    borderRadius: 'var(--radius-md)',
                    padding: '0.75rem',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    fontSize: '0.875rem',
                    transition: 'all 0.15s',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.5rem',
                  }}
                >
                  <span style={{ fontSize: '1.2rem', fontWeight: 300 }}>+</span>
                  {t('dilemme.ajouter_option')} ({options.length}/{MAX_OPTIONS})
                </button>
              )}

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
                      placeholder={t('common.ta_reponse_placeholder')}
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
                disabled={options.some(o => !o.trim()) || contextNeeded || contextLoading}
              >
                {contextLoading ? 'Verification du contexte...' : t('dilemme.analyser')}
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
                {t('dilemme.analyse_en_cours')}
              </p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
                {t('dilemme.calcul_impact')}
              </p>
            </div>
          </div>
        )}

        {/* Phase : Résultat */}
        {phase === 'result' && analyse && (() => {
          // NOUVEAU FLOW : OptionCards DISPLAY-ONLY (pas de choix immediat).
          // L'utilisateur ne sait pas a l'avance ce qu'il fera reellement →
          // on lui demandera periode par periode via les notifs (J+30 etc).
          //
          // Le badge "Recommande" est masque si l'option dite recommandee a
          // un impact_jours NEGATIF : dire "Recommande" alors que Claude
          // estime le choix destructeur est trompeur. Dans ce cas, le verdict
          // explique la nuance ("moins pire des deux", etc).
          const recommandee = analyse.options.find(o => o.lettre === analyse.option_recommandee)
          const recommandedHasPositiveImpact = (recommandee?.impact_jours ?? 0) > 0
          return (
          <div className="animate-fade-in">
            {/* Options - display only */}
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
              {analyse.options.map((opt) => (
                <OptionCard
                  key={opt.lettre}
                  lettre={opt.lettre}
                  option={opt}
                  recommandee={recommandedHasPositiveImpact && analyse.option_recommandee === opt.lettre}
                  selected={false}
                  onSelect={undefined /* display-only */}
                />
              ))}
            </div>

            {/* Verdict */}
            <div
              className="card"
              style={{
                background: 'linear-gradient(135deg, rgba(124,58,237,0.08), rgba(212,160,23,0.04))',
                border: '1px solid var(--accent-violet-dim)',
                marginBottom: '1.5rem',
              }}
            >
              <p style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent-violet-light)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.625rem' }}>
                {'\u25C8'} {t('dilemme.verdict_sylea')}
              </p>
              <p style={{ color: 'var(--text-secondary)', lineHeight: '1.6', fontSize: '0.925rem' }}>
                {analyse.verdict}
              </p>
            </div>

            {/* Étude scientifique */}
            {analyse.etude_scientifique && (
              <div
                className="card"
                style={{
                  background: 'linear-gradient(135deg, rgba(59,130,246,0.06), rgba(16,185,129,0.04))',
                  border: '1px solid rgba(59,130,246,0.2)',
                  marginBottom: '1.5rem',
                }}
              >
                <p style={{ fontSize: '0.75rem', fontWeight: 700, color: '#60a5fa', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.625rem' }}>
                  {t('dilemme.etude_scientifique')}
                </p>
                <p style={{ color: 'var(--text-secondary)', lineHeight: '1.6', fontSize: '0.875rem', fontStyle: 'italic' }}>
                  {analyse.etude_scientifique}
                </p>
              </div>
            )}

            {error && (
              <p style={{ color: 'var(--danger)', fontSize: '0.875rem', marginBottom: '1rem' }}>{'\u26A0'} {error}</p>
            )}

            {/* Explication tracking pour rassurer l'user */}
            <div
              style={{
                background: 'rgba(96,165,250,0.06)',
                border: '1px solid rgba(96,165,250,0.2)',
                borderRadius: 'var(--radius-md)',
                padding: '0.85rem 1rem',
                marginBottom: '1.25rem',
                fontSize: '0.85rem',
                color: '#93c5fd',
                lineHeight: 1.5,
              }}
            >
              <strong style={{ color: '#60a5fa' }}>{'\u25C8'} Suivi sur la dur\u00E9e&nbsp;: </strong>
              Sylea ne vous demande pas de choisir maintenant. En confirmant,
              vous d\u00E9marrez un suivi qui vous demandera p\u00E9riodiquement
              (par notification) ce que vous avez <em>r\u00E9ellement</em> fait.
              L'impact sur votre objectif sera calcul\u00E9 \u00E0 la fin, en fonction
              de vos vraies actions.
            </div>

            {/* Actions : Confirmer (demarre tracking) | Nouveau dilemme */}
            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button className="btn btn-outline" onClick={handleReset}>
                {'\u2190'} {t('dilemme.nouveau_dilemme')}
              </button>
              <button
                className="btn btn-gold"
                onClick={handleConfirmer}
                disabled={submitting}
              >
                {submitting ? t('dilemme.enregistrement') : `\u2713 Confirmer et d\u00E9marrer le suivi`}
              </button>
            </div>
          </div>
          )
        })()}

        {/* Phase : Confirmation (tracking demarre) */}
        {phase === 'done' && trackingCree && (() => {
          // Calcule la date de la 1ere notif au format lisible
          const nextNotif = trackingCree.next_notif_at
            ? new Date(trackingCree.next_notif_at).toLocaleString('fr-FR', {
                day: '2-digit', month: 'long', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
              })
            : '\u2014'
          const nbPeriodes = trackingCree.nb_periodes
          const dureeJours = trackingCree.impact_temporel_jours
          const cadence = dureeJours <= 30 ? '1 notification \u00E0 la fin' : `${nbPeriodes} notifications mensuelles`
          return (
          <div
            className="card animate-fade-in-scale"
            style={{
              maxWidth: '540px',
              margin: '0 auto',
              padding: '2.25rem 2rem',
              border: '1px solid var(--success)',
              boxShadow: '0 0 32px rgba(34,197,94,0.15)',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: '3rem', marginBottom: '0.75rem' }}>{'\u25C7'}</div>
            <h3 style={{ color: 'var(--success)', marginBottom: '0.5rem' }}>
              Suivi d\u00E9marr\u00E9
            </h3>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', marginBottom: '1.5rem', lineHeight: 1.55 }}>
              Aucun impact appliqu\u00E9 pour l'instant. Sylea vous notifiera
              <strong style={{ color: '#fbbf24' }}> {cadence}</strong> pour
              vous demander ce que vous avez r\u00E9ellement fait.
            </p>
            <div style={{
              background: 'rgba(96,165,250,0.08)',
              border: '1px solid rgba(96,165,250,0.25)',
              borderRadius: 'var(--radius-md)',
              padding: '0.85rem 1rem',
              marginBottom: '1.5rem',
              textAlign: 'left',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: '#93c5fd', marginBottom: '0.35rem' }}>
                <span>Dur\u00E9e du suivi&nbsp;:</span>
                <strong>{dureeJours} jours</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: '#93c5fd', marginBottom: '0.35rem' }}>
                <span>Nombre de p\u00E9riodes&nbsp;:</span>
                <strong>{nbPeriodes}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: '#93c5fd' }}>
                <span>Premi\u00E8re notification&nbsp;:</span>
                <strong>{nextNotif}</strong>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
              <button className="btn btn-outline btn-sm" onClick={handleReset}>
                {t('dilemme.nouveau_dilemme')}
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => navigate('/')}>
                {t('dilemme.tableau_de_bord')}
              </button>
            </div>
          </div>
          )
        })()}

      </div>
    </div>
  )
}
