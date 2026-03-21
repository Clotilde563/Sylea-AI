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

  // -- Handlers -------------------------------------------------------------
  const handleAnalyser = async () => {
    if (!description.trim() || description.trim().length < 5) {
      setError(t('evenement.min_caracteres'))
      return
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

              {error && (
                <p style={{ color: 'var(--danger)', fontSize: '0.875rem' }}>⚠ {error}</p>
              )}

              <button
                className="btn btn-primary btn-full"
                onClick={handleAnalyser}
                disabled={!description.trim() || description.trim().length < 5}
              >
                {t('evenement.analyser')}
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
                ★ {analyse.conseil}
              </p>
            </div>

            {error && (
              <p style={{ color: 'var(--danger)', fontSize: '0.875rem', marginBottom: '1rem' }}>⚠ {error}</p>
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
            <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>✓</div>
            <h3 style={{ color: 'var(--success)', marginBottom: '0.75rem' }}>{t('evenement.evenement_enregistre')}</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginBottom: '1rem', lineHeight: '1.5' }}>
              {t('evenement.evenement_sauvegarde')}
            </p>
            {sousObjectifImpacte && (
              <div style={{ background: 'rgba(96,165,250,0.08)', border: '1px solid rgba(96,165,250,0.25)', borderRadius: 'var(--radius-md)', padding: '0.6rem 1rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: '#60a5fa', fontSize: '0.8rem' }}>{'↳'}</span>
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
