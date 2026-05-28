// Page de validation finale d'un tracking : récap pondéré + impact prévu
// + bouton "Valider et appliquer" qui déclenche /tracking/:id/validate

import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useStore } from '../store/useStore'
import type { TrackingRecap, TrackingItem } from '../types'

export function TrackingRecapPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { setProfil, refreshSousObjectifs } = useStore()
  const [tracking, setTracking] = useState<TrackingItem | null>(null)
  const [recap, setRecap] = useState<TrackingRecap | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [validatedResult, setValidatedResult] = useState<{
    impact: number
    delta: number
    so: { titre: string; progression_avant: number; progression_apres: number; est_cible: boolean }[]
  } | null>(null)

  useEffect(() => {
    if (!id) return
    Promise.all([api.trackingGet(id), api.trackingRecap(id)])
      .then(([t, r]) => {
        setTracking(t.tracking)
        setRecap(r)
      })
      .catch(e => setError(e instanceof Error ? e.message : 'Erreur de chargement'))
      .finally(() => setLoading(false))
  }, [id])

  const handleValidate = async () => {
    if (!id) return
    setSubmitting(true)
    setError(null)
    try {
      const r = await api.trackingValidate(id)
      setValidatedResult({
        impact: r.impact_jours_applique,
        delta: r.delta_probabilite,
        so: r.so_impactes || [],
      })
      // Refresh profil + SOs pour repercuter dans le store
      const profil = await api.getProfil()
      setProfil(profil)
      await refreshSousObjectifs()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erreur de validation')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="page animate-fade-in">
        <div className="container page-content">
          <div className="loading-center" style={{ padding: '4rem 1rem' }}>
            <div style={{
              width: '52px', height: '52px', borderRadius: '50%',
              border: '3px solid var(--accent-violet-dim)',
              borderTop: '3px solid var(--accent-violet)',
              animation: 'spin 0.8s linear infinite',
            }} />
            <p style={{ color: 'var(--text-muted)', marginTop: '1rem' }}>Chargement du récap…</p>
          </div>
        </div>
      </div>
    )
  }

  if (error || !tracking || !recap) {
    return (
      <div className="page animate-fade-in">
        <div className="container page-content">
          <div style={{
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.3)',
            padding: '1rem',
            borderRadius: 'var(--radius-md)',
            color: '#fca5a5',
          }}>
            {error || 'Récap introuvable'}
          </div>
          <button className="btn btn-outline" onClick={() => navigate('/tracking')} style={{ marginTop: '1rem' }}>
            ← Retour à mes dilemmes
          </button>
        </div>
      </div>
    )
  }

  // Phase 'validated' : impact appliqué, on affiche le résultat avec graphe SO
  if (validatedResult) {
    return (
      <div className="page animate-fade-in">
        <div className="container page-content">
          <div className="card animate-fade-in-scale" style={{
            maxWidth: '640px',
            margin: '0 auto',
            padding: '2.5rem 2rem',
            border: '1px solid rgba(34,197,94,0.4)',
            boxShadow: '0 0 32px rgba(34,197,94,0.15)',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: '3rem', marginBottom: '0.75rem' }}>{'◇'}</div>
            <h2 style={{ color: 'var(--success)', marginBottom: '0.75rem' }}>
              Suivi validé
            </h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', marginBottom: '1.5rem', lineHeight: 1.5 }}>
              L'impact réel de vos actions a été appliqué à votre objectif.
            </p>

            {/* Impact métrique */}
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1.5rem',
            }}>
              <div style={{
                padding: '1rem',
                background: validatedResult.impact >= 0 ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                border: `1px solid ${validatedResult.impact >= 0 ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
                borderRadius: 'var(--radius-md)',
              }}>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Impact en jours
                </p>
                <p style={{ fontSize: '1.4rem', fontWeight: 700, color: validatedResult.impact >= 0 ? '#4ade80' : '#fca5a5' }}>
                  {validatedResult.impact >= 0 ? '+' : ''}{validatedResult.impact.toFixed(1)} j
                </p>
              </div>
              <div style={{
                padding: '1rem',
                background: validatedResult.delta >= 0 ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                border: `1px solid ${validatedResult.delta >= 0 ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
                borderRadius: 'var(--radius-md)',
              }}>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Probabilité
                </p>
                <p style={{ fontSize: '1.4rem', fontWeight: 700, color: validatedResult.delta >= 0 ? '#4ade80' : '#fca5a5' }}>
                  {validatedResult.delta >= 0 ? '+' : ''}{validatedResult.delta.toFixed(2)}%
                </p>
              </div>
            </div>

            {/* SOs impactés */}
            {validatedResult.so.length > 0 && (
              <div style={{
                background: 'rgba(124,58,237,0.04)',
                border: '1px solid rgba(124,58,237,0.2)',
                borderRadius: 'var(--radius-md)',
                padding: '1rem',
                marginBottom: '1.5rem',
                textAlign: 'left',
              }}>
                <p style={{ fontSize: '0.72rem', color: 'var(--accent-violet-light)', marginBottom: '0.6rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
                  ◇ Sous-objectifs impactés
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                  {validatedResult.so.map((s, i) => {
                    const delta = s.progression_apres - s.progression_avant
                    return (
                      <div key={i} style={{
                        background: s.est_cible ? 'rgba(245,158,11,0.08)' : 'rgba(255,255,255,0.02)',
                        border: s.est_cible ? '1px solid rgba(245,158,11,0.3)' : '1px solid rgba(255,255,255,0.05)',
                        borderRadius: '6px',
                        padding: '0.6rem 0.85rem',
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem' }}>
                          <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)', fontWeight: s.est_cible ? 600 : 400 }}>
                            {s.est_cible && <span style={{ color: '#fbbf24', marginRight: '0.4rem' }}>★</span>}
                            {s.titre}
                          </span>
                          <span style={{
                            fontSize: '0.85rem',
                            fontWeight: 700,
                            color: delta >= 0 ? '#4ade80' : '#fca5a5',
                          }}>
                            {s.progression_avant.toFixed(1)}% → {s.progression_apres.toFixed(1)}% ({delta >= 0 ? '+' : ''}{delta.toFixed(1)}%)
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'center' }}>
              <button className="btn btn-outline btn-sm" onClick={() => navigate('/tracking')}>
                Mes dilemmes
              </button>
              <button className="btn btn-primary btn-sm" onClick={() => navigate('/')}>
                Tableau de bord
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // Phase normale : récap pondéré + bouton valider
  const totalChoices = recap.recap.breakdown.reduce((s, b) => s + b.nb_clicks, 0)
  return (
    <div className="page animate-fade-in">
      <div className="container page-content">
        <button
          className="btn btn-outline btn-sm"
          onClick={() => navigate('/tracking')}
          style={{ marginBottom: '1rem' }}
        >
          ← Retour
        </button>

        <h1 className="page-title" style={{ marginBottom: '0.35rem' }}>
          Récap du suivi
        </h1>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem', marginBottom: '1.5rem' }}>
          {tracking.question}
        </p>

        {/* Cards breakdown */}
        <div className="card" style={{ marginBottom: '1.5rem', padding: '1.5rem' }}>
          <h3 style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--accent-violet-light)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '1rem' }}>
            ◈ Pondération de l'impact
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', marginBottom: '1.25rem' }}>
            {recap.recap.breakdown.map((b, i) => {
              const isNone = b.option === 'none'
              const isPositive = b.impact_pondere > 0
              const isNegative = b.impact_pondere < 0
              return (
                <div key={i} style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr auto auto',
                  gap: '0.75rem',
                  alignItems: 'center',
                  padding: '0.65rem 0.85rem',
                  background: isNone ? 'rgba(148,163,184,0.05)' : 'rgba(124,58,237,0.05)',
                  border: `1px solid ${isNone ? 'rgba(148,163,184,0.15)' : 'rgba(124,58,237,0.18)'}`,
                  borderRadius: '6px',
                }}>
                  <div>
                    <p style={{ fontSize: '0.88rem', color: 'var(--text-primary)', fontWeight: 500, marginBottom: '0.15rem' }}>
                      {b.label}
                    </p>
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {b.nb_clicks} fois sur {recap.recap.nb_periodes} ({b.percentage}%)
                    </p>
                  </div>
                  {/* Mini barre visuelle */}
                  <div style={{ width: '80px', height: '6px', background: 'rgba(255,255,255,0.05)', borderRadius: '3px', overflow: 'hidden' }}>
                    <div style={{
                      height: '100%',
                      width: `${b.percentage}%`,
                      background: isNone ? '#94a3b8' : 'linear-gradient(90deg, var(--accent-violet), var(--accent-violet-light))',
                    }} />
                  </div>
                  <div style={{
                    minWidth: '70px',
                    textAlign: 'right',
                    fontSize: '0.95rem',
                    fontWeight: 700,
                    color: isPositive ? '#4ade80' : isNegative ? '#fca5a5' : 'var(--text-muted)',
                    fontFamily: 'var(--font-mono)',
                  }}>
                    {isPositive ? '+' : ''}{b.impact_pondere.toFixed(1)} j
                  </div>
                </div>
              )
            })}
          </div>

          {/* Total */}
          <div style={{
            borderTop: '1px solid var(--border)',
            paddingTop: '1rem',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <div>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.2rem' }}>
                Impact total appliqué à votre objectif
              </p>
              <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                {totalChoices} réponses sur {recap.recap.nb_periodes} périodes
              </p>
            </div>
            <div style={{ textAlign: 'right' }}>
              <p style={{
                fontSize: '1.6rem',
                fontWeight: 800,
                fontFamily: 'var(--font-mono)',
                color: recap.recap.impact_total_jours >= 0 ? '#4ade80' : '#fca5a5',
                lineHeight: 1,
              }}>
                {recap.recap.impact_total_jours >= 0 ? '+' : ''}{recap.recap.impact_total_jours.toFixed(1)} j
              </p>
              <p style={{
                fontSize: '0.8rem',
                color: recap.delta_probabilite_preview >= 0 ? '#4ade80' : '#fca5a5',
                marginTop: '0.2rem',
              }}>
                ≈ {recap.delta_probabilite_preview >= 0 ? '+' : ''}{recap.delta_probabilite_preview.toFixed(2)}% de probabilité
              </p>
            </div>
          </div>
        </div>

        {error && (
          <div style={{
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.3)',
            padding: '0.85rem 1rem',
            borderRadius: 'var(--radius-md)',
            color: '#fca5a5',
            marginBottom: '1rem',
            fontSize: '0.85rem',
          }}>
            {'⚠'} {error}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
          <button className="btn btn-outline" onClick={() => navigate('/tracking')}>
            Retour
          </button>
          <button
            className="btn btn-gold"
            onClick={handleValidate}
            disabled={submitting}
          >
            {submitting ? 'Application en cours…' : '✓ Valider et appliquer l\'impact'}
          </button>
        </div>
      </div>
    </div>
  )
}
