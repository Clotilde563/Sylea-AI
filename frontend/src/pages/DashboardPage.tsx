// Page Tableau de bord — Vue principale de Syléa.AI

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ProbabilityGauge } from '../components/ProbabilityGauge'
import { SyleaLogo } from '../components/SyleaLogo'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { dureeFromProb } from '../utils/duration'
import type { ProbabiliteResult, SousObjectif, TachesQuotidiennes, TacheItem } from '../types'

export function DashboardPage() {
  const navigate = useNavigate()
  const { profil, setProfil, probCalculee, setProbCalculee } = useStore()
  const [loading, setLoading] = useState(false)
  const [calcResult, setCalcResult] = useState<ProbabiliteResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [bilanFait, setBilanFait] = useState(true)
  const [personnalite, setPersonnalite] = useState<string | null>(null)
  const [sousObjectifs, setSousObjectifs] = useState<SousObjectif[]>([])
  const [tachesData, setTachesData] = useState<TachesQuotidiennes | null>(null)
  const [tachesExist, setTachesExist] = useState(false)
  const [loadingTaches, setLoadingTaches] = useState(false)
  const [loadingSO, setLoadingSO] = useState(false)

  useEffect(() => {
    api.getProfil()
      .then(setProfil)
      .catch(() => navigate('/profil'))
    api.checkBilanAujourdhui()
      .then(res => setBilanFait(res.exists))
      .catch(() => setBilanFait(true))
    api.getPersonnalite()
      .then(res => setPersonnalite(res.phrase))
      .catch(() => {})
    api.getSousObjectifs()
      .then(setSousObjectifs)
      .catch(() => {})
    api.checkTachesAujourdhui()
      .then(res => {
        setTachesExist(res.exists)
        if (res.taches) setTachesData(res.taches)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (profil && !probCalculee && (profil.objectif?.probabilite_calculee ?? 0) === 0 && profil.objectif) {
      handleCalcProb()
    }
  }, [profil, probCalculee])

  const handleCalcProb = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.recalculerProbabilite()
      setCalcResult(res)
      setProbCalculee(true)
      const updated = await api.getProfil()
      setProfil(updated)
      if (sousObjectifs.length === 0) {
        setLoadingSO(true)
        try {
          const so = await api.genererSousObjectifs()
          setSousObjectifs(so)
        } catch {}
        setLoadingSO(false)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Erreur de calcul')
    } finally {
      setLoading(false)
    }
  }

  const handleGenererTaches = async () => {
    setLoadingTaches(true)
    try {
      const res = await api.genererTaches()
      setTachesData(res)
      setTachesExist(true)
    } catch (e: unknown) {
      if (e instanceof Error && e.message.includes('409')) {
        const check = await api.checkTachesAujourdhui()
        if (check.taches) {
          setTachesData(check.taches)
          setTachesExist(true)
        }
      }
    } finally {
      setLoadingTaches(false)
    }
  }

  const handleCompleterTache = async (tacheId: string) => {
    try {
      const res = await api.completerTache(tacheId)
      if (tachesData) {
        const updatedTaches = tachesData.taches.map(t =>
          t.id === tacheId ? { ...t, completee: true } : t
        )
        const allDone = updatedTaches.every(t => t.completee)
        setTachesData({
          ...tachesData,
          taches: updatedTaches,
          statut: allDone ? 'terminee' : 'en_cours',
        })
      }
      const updated = await api.getProfil()
      setProfil(updated)
      if (res.impacts_sous_objectifs.length > 0) {
        setSousObjectifs(prev =>
          prev.map(so => {
            const impact = res.impacts_sous_objectifs.find(i => i.id === so.id)
            return impact ? { ...so, progression: impact.progression } : so
          })
        )
      }
    } catch (err) { console.error('completerTache error:', err) }
  }

  const handleAbandonner = async () => {
    try {
      await api.abandonnerTaches()
      if (tachesData) {
        setTachesData({ ...tachesData, statut: 'abandonnee' })
      }
    } catch {}
  }

  if (!profil) {
    return (
      <div className="loading-center">
        <div className="spinner" />
        <p style={{ color: 'var(--text-muted)' }}>Chargement…</p>
      </div>
    )
  }

  const prob = profil.probabilite_actuelle
  const probCalculeeVal = profil.objectif?.probabilite_calculee ?? 0
  const probGauge = 0.1 + prob
  const probTemps = probCalculeeVal + prob
  const duree = dureeFromProb(probTemps)
  const rawDesc = profil.objectif?.description || ''
  const objectifDesc = (rawDesc.split('\n\n--- Contexte personnalisé ---\n')[0].trim()) || 'Aucun objectif défini'

  const deadlineStr = tachesData?.deadline
    ? new Date(tachesData.deadline).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
    : null
  const tachesEnCours = tachesData?.statut === 'en_cours'
  const tachesCompletes = tachesData?.taches.filter(t => t.completee).length ?? 0
  const tachesTotal = tachesData?.taches.length ?? 0

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* En-tête chaleureux */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
          <div>
            <p style={{ color: 'var(--accent-violet-light)', fontSize: '0.82rem', letterSpacing: '0.06em', marginBottom: '0.35rem', opacity: 0.85 }}>Bon retour parmi nous</p>
            <h1 style={{ fontSize: '2rem', fontWeight: 700, marginBottom: '0.3rem', background: 'linear-gradient(135deg, var(--accent-silver), var(--accent-violet-light))', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>{profil.nom}</h1>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ color: 'var(--accent-violet-light)' }}>{'\u25c6'}</span> {profil.profession}
              <span style={{ color: 'var(--text-muted)', opacity: 0.4 }}>|</span>
              <span style={{ color: 'var(--accent-gold)' }}>{'\u25c7'}</span> {profil.ville}
            </p>
          </div>
          <SyleaLogo size={52} animated={false} />
        </div>

        {/* Compétences */}
        {profil.competences && profil.competences.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem', marginBottom: '0.5rem', marginTop: '0.35rem' }}>
            {profil.competences.map((c, i) => (
              <span key={i} className="badge badge-violet" style={{ borderRadius: '12px', fontSize: '0.72rem', padding: '0.2rem 0.65rem' }}>{c}</span>
            ))}
          </div>
        )}

        {/* Phrase personnalité IA (scintillante) */}
        {personnalite && (
          <p className="animate-fade-in shimmer-text" style={{ fontSize: '0.82rem', fontStyle: 'italic', textAlign: 'left', marginBottom: '2rem' }}>
            {'\u00ab'} {personnalite} {'\u00bb'}
          </p>
        )}

        {/* Bandeau bilan quotidien */}
        {!bilanFait && (
          <button onClick={() => navigate('/bilan')} className="animate-fade-in"
            style={{ width: '100%', background: 'linear-gradient(135deg, rgba(251,191,36,0.1), rgba(251,191,36,0.03))', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 'var(--radius-lg)', padding: '1.25rem 1.5rem', marginBottom: '1rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '1rem', textAlign: 'left', transition: 'all 0.2s' }}>
            <span style={{ fontSize: '1.75rem' }}>{'\u2600'}</span>
            <div style={{ flex: 1 }}>
              <p style={{ fontWeight: 600, color: 'var(--accent-gold)', fontSize: '0.95rem', marginBottom: '0.25rem' }}>Bilan du jour</p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>Comment vous sentez-vous aujourd'hui ?</p>
            </div>
            <span style={{ color: 'var(--accent-gold)', fontSize: '1.2rem', fontWeight: 300 }}>{'\u203a'}</span>
          </button>
        )}

        {/* Bandeau tâches en cours */}
        {tachesEnCours && (
          <div className="animate-fade-in"
            style={{ width: '100%', background: 'linear-gradient(135deg, rgba(251,146,60,0.12), rgba(251,146,60,0.03))', border: '1px solid rgba(251,146,60,0.35)', borderRadius: 'var(--radius-lg)', padding: '1rem 1.5rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <span style={{ fontSize: '1.25rem' }}>{'\u23f3'}</span>
            <div style={{ flex: 1 }}>
              <p style={{ fontWeight: 600, color: '#fb923c', fontSize: '0.85rem', marginBottom: '0.15rem' }}>{tachesCompletes}/{tachesTotal} tâches complétées</p>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Deadline : {deadlineStr || 'ce soir'}</p>
            </div>
          </div>
        )}

        {/* Jauge principale */}
        <div className="card animate-fade-in-scale"
          style={{ background: 'linear-gradient(135deg, var(--bg-surface), #0b1525)', border: '1px solid var(--border)', marginBottom: '1.5rem', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '2rem', gap: '1rem' }}>
          <div style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', color: 'var(--accent-violet-light)', textTransform: 'uppercase', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>{'\u25c8'}</span> Temps estimé
          </div>
          <ProbabilityGauge value={probGauge} size={200} showDuration={true} showPercent={false} durationOverride={probTemps} />
          <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', letterSpacing: '0.06em', textAlign: 'center' }}>
            pour atteindre votre objectif — {duree.label}
          </p>
          <div style={{ textAlign: 'center', maxWidth: '440px' }}>
            <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', fontStyle: 'italic', lineHeight: '1.5', marginBottom: '0.75rem' }}>{objectifDesc}</p>
            {profil.objectif?.categorie && <span className="badge badge-violet">{profil.objectif.categorie}</span>}
          </div>
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', color: 'var(--text-muted)' }}>
              <div className="spinner spinner-sm" />
              <span style={{ fontSize: '0.875rem' }}>Analyse en cours…</span>
            </div>
          )}
          {error && <p style={{ color: 'var(--danger)', fontSize: '0.875rem' }}>{'\u26a0'} {error}</p>}
          <button className="btn btn-outline btn-sm" onClick={handleCalcProb} disabled={loading}>
            {loading ? 'Calcul…' : '\u21bb Recalculer la probabilité'}
          </button>
        </div>

        {/* Sous-objectifs séquentiels */}
        {sousObjectifs.length > 0 && (() => {
          const activeIdx = sousObjectifs.findIndex(so => so.progression < 100)
          return (
            <div className="card animate-fade-in" style={{ marginBottom: '1.5rem', padding: '1.25rem' }}>
              <h3 style={{ fontSize: '0.75rem', fontWeight: 700, letterSpacing: '0.1em', color: 'var(--accent-violet-light)', textTransform: 'uppercase', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span>{'\u25c7'}</span> Sous-objectifs
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {sousObjectifs.map((so, idx) => {
                  const isCompleted = so.progression >= 100
                  const isActive = idx === activeIdx
                  const isLocked = !isCompleted && !isActive
                  const barColor = isCompleted ? 'linear-gradient(90deg, #22c55e, #16a34a)' : isActive ? 'linear-gradient(90deg, #60a5fa, #818cf8)' : 'rgba(255,255,255,0.1)'
                  const textColor = isCompleted ? '#4ade80' : isActive ? 'var(--text-secondary)' : 'var(--text-muted)'
                  const tempsLabel = so.temps_estime > 0 ? (so.temps_estime >= 365 ? `${Math.round(so.temps_estime / 365)} an${so.temps_estime >= 730 ? 's' : ''}` : so.temps_estime >= 30 ? `${Math.round(so.temps_estime / 30)} mois` : `${Math.round(so.temps_estime)} j`) : null
                  return (
                    <div key={so.id} style={{ opacity: isLocked ? 0.4 : 1, transition: 'opacity 0.3s' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.3rem' }}>
                        <span style={{ fontSize: '0.82rem', color: textColor, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          {isCompleted && <span style={{ color: '#22c55e' }}>{'\u2713'}</span>}
                          {isActive && <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#60a5fa', boxShadow: '0 0 8px rgba(96,165,250,0.6)', animation: 'pulse 2s infinite' }} />}
                          {isLocked && <span style={{ fontSize: '0.7rem', opacity: 0.7 }}>{'🔒'}</span>}
                          {so.titre}
                        </span>
                        <span style={{ fontSize: '0.72rem', color: isCompleted ? '#4ade80' : 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          {isActive && tempsLabel && <span style={{ color: 'var(--accent-violet-light)', fontSize: '0.68rem' }}>~{tempsLabel}</span>}
                          {so.progression.toFixed(0)}%
                        </span>
                      </div>
                      <div style={{ height: '6px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${Math.min(100, so.progression)}%`, background: barColor, borderRadius: '3px', transition: 'width 0.5s ease', boxShadow: isActive ? '0 0 8px rgba(96,165,250,0.4)' : 'none' }} />
                      </div>
                    </div>
                  )
                })}
              </div>
              {loadingSO && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.75rem', color: 'var(--text-muted)' }}>
                  <div className="spinner spinner-sm" />
                  <span style={{ fontSize: '0.8rem' }}>Génération des sous-objectifs…</span>
                </div>
              )}
            </div>
          )
        })()}

        {/* Résultat d'analyse IA */}
        {calcResult && (
          <div className="card card-gold animate-fade-in" style={{ marginBottom: '1.5rem' }}>
            <h3 style={{ color: 'var(--accent-gold)', marginBottom: '1rem', fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{'\u25c8'} Analyse Syléa.AI</h3>
            <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem', lineHeight: '1.6', fontStyle: 'italic' }}>{calcResult.resume}</p>
            {(calcResult.points_forts.length > 0 || calcResult.points_faibles.length > 0) && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
                {calcResult.points_forts.length > 0 && (
                  <div>
                    <p style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--success)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{'\u25c6'} Points forts</p>
                    {calcResult.points_forts.map((p, i) => <p key={i} style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>{'\u2022'} {p}</p>)}
                  </div>
                )}
                {calcResult.points_faibles.length > 0 && (
                  <div>
                    <p style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--danger)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{'\u25c7'} Points faibles</p>
                    {calcResult.points_faibles.map((p, i) => <p key={i} style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>{'\u2022'} {p}</p>)}
                  </div>
                )}
              </div>
            )}
            {calcResult.conseil_prioritaire && (
              <div style={{ background: 'rgba(26,111,216,0.07)', border: '1px solid var(--border-gold)', borderRadius: 'var(--radius-md)', padding: '0.875rem', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                <span style={{ fontSize: '1rem', flexShrink: 0 }}>{'\u2605'}</span>
                <div>
                  <p style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-gold)', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Action prioritaire recommandée</p>
                  <p style={{ fontSize: '0.875rem', color: 'var(--text-primary)', lineHeight: '1.5' }}>{calcResult.conseil_prioritaire}</p>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Menu d'actions */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
          <ActionCard emoji={'\u27e1'} title="Analyser un choix" desc="Soumettez un dilemme et recevez une analyse IA pros/cons" onClick={() => navigate('/dilemme')} highlight />
          <ActionCard emoji={'\u25eb'} title="Statistiques" desc="Visualisez vos décisions passées et votre courbe de progression" onClick={() => navigate('/statistiques')} />
          <ActionCard emoji={'\u25c9'} title="Enregistrer un événement" desc="Notifiez un événement et découvrez son impact sur votre objectif" onClick={() => navigate('/evenement')} />
          {tachesEnCours ? (
            <TaskCard taches={tachesData!.taches} deadline={deadlineStr || '23:59'} onComplete={handleCompleterTache} onAbandon={handleAbandonner} />
          ) : (
            <ActionCard emoji={'\u2726'} title="Que faire ?" desc={tachesData && tachesData.statut !== 'en_cours' ? (tachesData.statut === 'terminee' ? "Tâches terminées pour aujourd'hui" : "Tâches abandonnées pour aujourd'hui") : "Générez votre plan d'action quotidien par l'IA"} onClick={handleGenererTaches} orange={!tachesData || tachesData.statut === 'en_cours'} disabled={loadingTaches || (tachesExist && !tachesEnCours)} loading={loadingTaches} />
          )}
        </div>
      </div>
    </div>
  )
}

function TaskCard({ taches, deadline, onComplete, onAbandon }: { taches: TacheItem[]; deadline: string; onComplete: (id: string) => void; onAbandon: () => void }) {
  return (
    <div style={{ background: 'linear-gradient(135deg, rgba(251,146,60,0.15), rgba(251,146,60,0.04))', border: '1px solid rgba(251,146,60,0.4)', borderRadius: 'var(--radius-lg)', padding: '1.25rem', gridColumn: '1 / -1' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#fb923c' }}>{'\u2726'} Que faire aujourd'hui ?</h3>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', background: 'rgba(251,146,60,0.15)', padding: '0.2rem 0.6rem', borderRadius: '12px' }}>{'\u23f0'} {deadline}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', marginBottom: '1rem' }}>
        {taches.map(t => (
          <div key={t.id} onClick={() => !t.completee && onComplete(t.id)}
            style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', cursor: t.completee ? 'default' : 'pointer', opacity: t.completee ? 0.5 : 1, transition: 'opacity 0.3s', userSelect: 'none' }}>
            <span style={{ marginTop: '0.1rem', fontSize: '1rem', lineHeight: '1', flexShrink: 0 }}>{t.completee ? '\u2611\uFE0F' : '\u2B1C'}</span>
            <span style={{ fontSize: '0.85rem', color: t.completee ? 'var(--text-muted)' : 'var(--text-secondary)', textDecoration: t.completee ? 'line-through' : 'none', lineHeight: '1.4' }}>{t.description}</span>
          </div>
        ))}
      </div>
      <button onClick={onAbandon}
        style={{ background: 'transparent', border: '1px solid rgba(251,146,60,0.3)', color: 'rgba(251,146,60,0.7)', fontSize: '0.75rem', padding: '0.4rem 1rem', borderRadius: 'var(--radius-md)', cursor: 'pointer', transition: 'all 0.2s' }}
        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(251,146,60,0.1)'; e.currentTarget.style.color = '#fb923c' }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'rgba(251,146,60,0.7)' }}>
        Abandonner ces tâches
      </button>
    </div>
  )
}

function ActionCard({ emoji, title, desc, onClick, highlight, orange, disabled, loading }: { emoji: string; title: string; desc: string; onClick: () => void; highlight?: boolean; orange?: boolean; disabled?: boolean; loading?: boolean }) {
  const bg = orange ? 'linear-gradient(135deg, rgba(251,146,60,0.18), rgba(251,146,60,0.06))' : highlight ? 'linear-gradient(135deg, rgba(26,111,216,0.18), rgba(26,111,216,0.06))' : 'var(--bg-surface)'
  const borderColor = orange ? 'rgba(251,146,60,0.4)' : highlight ? 'var(--accent-violet-dim)' : 'var(--border)'
  const shadowStyle = orange ? '0 0 24px rgba(251,146,60,0.3)' : highlight ? 'var(--shadow-violet)' : 'var(--shadow-card)'
  const emojiColor = orange ? '#fb923c' : highlight ? 'var(--accent-violet-light)' : 'var(--accent-gold)'
  return (
    <button onClick={onClick} disabled={disabled}
      style={{ background: bg, border: `1px solid ${borderColor}`, borderRadius: 'var(--radius-lg)', padding: '1.25rem', textAlign: 'left', cursor: disabled ? 'not-allowed' : 'pointer', transition: 'all 0.2s', boxShadow: shadowStyle, opacity: disabled ? 0.5 : 1 }}
      onMouseEnter={e => { if (!disabled) { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = orange ? '0 0 36px rgba(251,146,60,0.5)' : highlight ? '0 0 32px rgba(26,111,216,0.45)' : '0 8px 32px rgba(0,0,0,0.55)' } }}
      onMouseLeave={e => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = shadowStyle }}>
      <div style={{ fontSize: '1.5rem', marginBottom: '0.625rem', color: emojiColor }}>{loading ? <span className="spinner spinner-sm" /> : emoji}</div>
      <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.375rem' }}>{title}</h3>
      <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: '1.4' }}>{desc}</p>
    </button>
  )
}
