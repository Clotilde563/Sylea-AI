// Page Dilemme — Analyse IA d'un choix de vie (N options)

import { useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { OptionCard } from '../components/OptionCard'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { useT } from '../i18n/LanguageContext'
import { useDeviceContext } from '../contexts/DeviceContext'
import type { AnalyseDilemme, Decision } from '../types'

type Phase = 'form' | 'loading' | 'result' | 'done'

// ── Agent Sylea Logo (gold S) ────────────────────────────────────────────────
const CX = 190, CY = 170
const S_PATH = `M ${CX} ${CY-105} C ${CX+90} ${CY-105}, ${CX+90} ${CY-28}, ${CX} ${CY} C ${CX-90} ${CY+28}, ${CX-90} ${CY+105}, ${CX} ${CY+105}`

function AgentSyleaLogo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 380 380" style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id="ctx-agent-gold-g" x1="50%" y1="100%" x2="50%" y2="0%">
          <stop offset="0%" stopColor="#d4a017" />
          <stop offset="40%" stopColor="#f59e0b" />
          <stop offset="100%" stopColor="#fbbf24" />
        </linearGradient>
        <filter id="ctx-agent-gold-blur">
          <feGaussianBlur stdDeviation="20" />
        </filter>
      </defs>
      <path d={S_PATH} stroke="url(#ctx-agent-gold-g)" strokeWidth="90" fill="none" strokeLinecap="round"
        style={{ filter: 'url(#ctx-agent-gold-blur)', opacity: 0.18 }} />
      <path d={S_PATH} stroke="rgba(2,4,16,0.98)" strokeWidth="58" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke="url(#ctx-agent-gold-g)" strokeWidth="46" fill="none" strokeLinecap="round" />
      <path d={S_PATH} stroke="#050810" strokeWidth="18" fill="none" strokeLinecap="butt" />
      <path d={S_PATH} stroke="rgba(255,230,150,0.5)" strokeWidth="2.5" fill="none" strokeLinecap="round" />
    </svg>
  )
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
  const [choixSelectionne, setChoixSelectionne] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [sousObjectifImpacte, setSousObjectifImpacte] = useState<string | null>(null)
  const [impactTemporel, setImpactTemporel] = useState<string>('1_mois')
  const [customYears, setCustomYears] = useState(0)
  const [customMonths, setCustomMonths] = useState(0)
  const [customDays, setCustomDays] = useState(0)

  // Context-gathering state
  const [contextNeeded, setContextNeeded] = useState(false)
  const [contextQuestion, setContextQuestion] = useState<string | null>(null)
  const [contextChoices, setContextChoices] = useState<string[] | null>(null)
  const [contextInput, setContextInput] = useState('')
  const [contextProvided, setContextProvided] = useState(false)
  const [contextLoading, setContextLoading] = useState(false)
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

  const contextCascadeRef = useRef(0)
  const contextAnswersRef = useRef<string[]>([])

  const handleSendContext = async (text: string) => {
    if (!text.trim()) return
    setContextLoading(true)
    try {
      const questionAuto = `${options.map(o => o.trim()).join(' vs ')}`
      await api.agentSaveContext(text.trim(), `dilemme: ${questionAuto}`)
      setContextInput('')
      // Après 1 réponse → débloquer directement l'analyse
      setContextProvided(true)
      setContextNeeded(false)
    } catch {
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
          setContextChoices(ctxResult.choices)
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

  const handleChoisir = async () => {
    if (!analyse || !choixSelectionne) return
    setSubmitting(true)
    setError(null)
    try {
      const choixResult = await api.choisirOption({
        question: analyse.question,
        options: analyse.options,
        choix: choixSelectionne,
        impact_temporel_jours: getImpactDays(),
        contexte_appareil: deviceCtx ?? undefined,
      })
      if (choixResult?.sous_objectif_impacte) {
        setSousObjectifImpacte(choixResult.sous_objectif_impacte)
      }
      // Recharger le profil pour la probabilité mise à jour
      const updated = await api.getProfil()
      setProfil(updated)
      await refreshSousObjectifs()
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
    setChoixSelectionne(null)
    setAnalyse(null)
    setError(null)
    setSousObjectifImpacte(null)
    setImpactTemporel('1_mois')
    setCustomYears(0)
    setCustomMonths(0)
    setCustomDays(0)
    setContextNeeded(false)
    setContextQuestion(null)
    setContextChoices(null)
    setContextInput('')
    setContextProvided(false)
    setPhase('form')
  }

  const addOption = () => {
    if (options.length < MAX_OPTIONS) {
      setOptions([...options, ''])
    }
  }

  const removeOption = (index: number) => {
    if (options.length > MIN_OPTIONS) {
      setOptions(options.filter((_, i) => i !== index))
    }
  }

  const updateOption = (index: number, value: string) => {
    const next = [...options]
    next[index] = value
    setOptions(next)
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

        {/* En-tête */}
        <div style={{ marginBottom: '2rem' }}>
          <h2 style={{ color: 'var(--accent-silver)', marginBottom: '0.375rem' }}>
            {t('dilemme.analyser_choix')}
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
            {t('dilemme.analyser_desc')}
          </p>
        </div>

        {/* Phase : Formulaire */}
        {phase === 'form' && (
          <div className="card animate-fade-in-scale" style={{ maxWidth: '680px', margin: '0 auto' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
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
                  <div style={{ display: 'flex', gap: '0.5rem', marginBottom: contextChoices ? '0.75rem' : 0 }}>
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

                  {/* QCM choices */}
                  {contextChoices && contextChoices.length > 0 && (
                    <div>
                      <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '0.4rem' }}>
                        ou repondre rapidement :
                      </p>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
                        {contextChoices.map((choice, i) => (
                          <button
                            key={i}
                            type="button"
                            onClick={() => handleSendContext(choice)}
                            disabled={contextLoading}
                            style={{
                              background: 'rgba(212,160,23,0.12)',
                              border: '1px solid rgba(212,160,23,0.35)',
                              borderRadius: '999px',
                              padding: '0.4rem 0.85rem',
                              color: '#fbbf24',
                              cursor: 'pointer',
                              fontSize: '0.8rem',
                              fontWeight: 500,
                              transition: 'all 0.15s',
                            }}
                          >
                            {choice}
                          </button>
                        ))}
                      </div>
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
                disabled={options.some(o => !o.trim()) || contextNeeded || contextLoading}
              >
                {contextLoading ? 'Verification du contexte...' : t('dilemme.analyser')}
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
                {t('dilemme.analyse_en_cours')}
              </p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
                {t('dilemme.calcul_impact')}
              </p>
            </div>
          </div>
        )}

        {/* Phase : Résultat */}
        {phase === 'result' && analyse && (
          <div className="animate-fade-in">
            {/* Options */}
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
              {analyse.options.map((opt) => (
                <OptionCard
                  key={opt.lettre}
                  lettre={opt.lettre}
                  option={opt}
                  recommandee={analyse.option_recommandee === opt.lettre}
                  selected={choixSelectionne === opt.lettre}
                  onSelect={() => setChoixSelectionne(choixSelectionne === opt.lettre ? null : opt.lettre)}
                  probActuelle={(profil.objectif?.probabilite_calculee ?? 0) + profil.probabilite_actuelle}
                  impactTemporelJours={getImpactDays()}
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

            {/* Actions */}
            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
              <button className="btn btn-outline" onClick={handleReset}>
                {'\u2190'} {t('dilemme.nouveau_dilemme')}
              </button>
              <button
                className="btn btn-gold"
                onClick={handleChoisir}
                disabled={!choixSelectionne || submitting}
              >
                {submitting
                  ? t('dilemme.enregistrement')
                  : choixSelectionne
                  ? `\u2713 ${t('dilemme.valider_option')} ${choixSelectionne}`
                  : t('dilemme.selectionnez_option')}
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
            <h3 style={{ color: 'var(--success)', marginBottom: '0.75rem' }}>{t('dilemme.decision_enregistree')}</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '1rem', lineHeight: '1.5' }}>
              {t('dilemme.choix_sauvegarde')}
            </p>
            {sousObjectifImpacte && (
              <div style={{ background: 'rgba(96,165,250,0.08)', border: '1px solid rgba(96,165,250,0.25)', borderRadius: 'var(--radius-md)', padding: '0.6rem 1rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: '#60a5fa', fontSize: '0.8rem' }}>{'\u21B3'}</span>
                <span style={{ color: '#93c5fd', fontSize: '0.82rem' }}>{t('dilemme.sous_objectif_impacte')} : <strong>{sousObjectifImpacte}</strong></span>
              </div>
            )}
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
              <button className="btn btn-outline btn-sm" onClick={handleReset}>
                {t('dilemme.nouveau_dilemme')}
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => navigate('/')}>
                {t('dilemme.tableau_de_bord')}
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
