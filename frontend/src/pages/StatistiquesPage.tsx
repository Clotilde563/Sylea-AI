// Page Statistiques — Deux graphiques
// Graphique 1 (théorique) : X = temps restant (10a → 0), Y = probabilité % (0→100%)
// Graphique 2 (réel)      : X = temps réel écoulé depuis le début (→ aujourd'hui), Y = probabilité %

import { useEffect, useState, useId } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { dureeFromProb, buildTimeTicks } from '../utils/duration'
import type { Decision, Profil, SousObjectif } from '../types'
import { ConfirmDeleteModal } from '../components/ConfirmDeleteModal'
import { useT } from '../i18n/LanguageContext'

// ── Dimensions partagées ──────────────────────────────────────────────────────
const W   = 620
const H   = 300
const PAD = { top: 24, right: 24, bottom: 52, left: 58 }

// ── Helpers coordonnées ───────────────────────────────────────────────────────
const innerW = (w = W) => w - PAD.left - PAD.right
const innerH = (h = H) => h - PAD.top  - PAD.bottom

/** X depuis un temps réel elapsed (ms) sur total elapsed */
function xFromElapsed(elapsedMs: number, totalMs: number): number {
  return PAD.left + Math.min(elapsedMs / totalMs, 1) * innerW()
}

// Constantes chart 1 (Y fixe, X dynamique selon duree estimee)
const Y_TICKS = [0, 25, 50, 75, 100]

// ── Composant principal ───────────────────────────────────────────────────────
export function StatistiquesPage() {
  const t        = useT()
  const uid      = useId().replace(/\W/g, '')
  const navigate = useNavigate()
  const { profil, setProfil, refreshSousObjectifs, sousObjectifs } = useStore()
  const [decisions, setDecisions] = useState<Decision[]>([])

  const handleDeleteDecision = async (id: string) => {
    try {
      await api.deleteDecision(id)
      setDecisions((prev) => prev.filter((d) => d.id !== id))
      // Re-fetch profil pour obtenir probabilite_actuelle mise à jour
      const updatedProfil = await api.getProfil()
      setProfil(updatedProfil)
      await refreshSousObjectifs()
    } catch {
      // silently fail
    }
    setDeleteTarget(null)
  }
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [loading, setLoading]     = useState(true)
  const [zoomChart1, setZoomChart1] = useState<'7j' | '30j' | '90j' | 'max'>('max')
  const [smoothChart1, setSmoothChart1] = useState(true)
  const [zoomChart2, setZoomChart2] = useState<'7j' | '30j' | '90j' | 'max'>('max')
  const [smoothChart2, setSmoothChart2] = useState(true)

  useEffect(() => {
    // Toujours recharger le profil depuis l'API
    api.getProfil().then(setProfil).catch(() => navigate('/profil'))
    api.getHistorique(100)
      .then(setDecisions)
      .catch(() => setDecisions([]))
      .finally(() => setLoading(false))
    refreshSousObjectifs()
  }, [])

  // ── Stats résumées ────────────────────────────────────────────────────────
  const probActuelle  = profil?.probabilite_actuelle ?? 0
  const probCalculee  = profil?.objectif?.probabilite_calculee ?? 0
  const probTemps     = probCalculee + probActuelle
  const gainTotal     = decisions.reduce((acc, d) => acc + (d.impact_net ?? 0), 0)
  const probInitiale  = Math.max(0, Math.min(100, probActuelle - gainTotal))
  const dureeActuelle = dureeFromProb(probTemps)
  const dureeInitiale = dureeFromProb(probCalculee + probInitiale)
  const tempsGagne    = Math.max(0, dureeInitiale.totalJours - dureeActuelle.totalJours)
  const tgAns         = Math.floor(tempsGagne / 365)
  const tgMois        = Math.floor((tempsGagne % 365) / 30)

  // ── Données chart 2 (courbe réelle) ──────────────────────────────────────
  const { histPoints, totalElapsedMs } = buildHistoricalPoints(profil, decisions)

  return (
    <div className="page animate-fade-in">
      <div className="container page-content">

        {/* ── En-tête ── */}
        <div style={{ marginBottom: '2rem' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', marginBottom: '0.25rem' }}>
            {t('stats.dashboard_avance')}
          </p>
          <h1 style={{ fontSize: '1.75rem', color: 'var(--accent-silver)', marginBottom: '0.25rem' }}>
            {t('stats.titre')}
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            {t('stats.evolution_proba')}
          </p>
        </div>

        {/* ── Cartes stats ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem', marginBottom: '1.75rem' }}>
          <StatCard label={t('stats.decisions_prises')} value={String(decisions.length)} sub={t('stats.depuis_debut')} color="var(--accent-violet-light)" />
          <StatCard label={t('stats.gain_proba')} value={gainTotal >= 0 ? `+${gainTotal.toFixed(1)} %` : `${gainTotal.toFixed(1)} %`} sub={t('stats.total_cumule')} color={gainTotal >= 0 ? '#22c55e' : '#ef4444'} />
          <StatCard label={t('stats.temps_economise')} value={tempsGagne > 0 ? (tgAns > 0 ? `${tgAns}a${tgMois > 0 ? ` ${tgMois}m` : ''}` : `${tgMois}m`) : '—'} sub={t('stats.vers_objectif')} color="#4090f0" />
          <StatCard label={t('stats.temps_restant')} value={dureeActuelle.ligne1} sub={dureeActuelle.ligne2 || t('stats.pour_atteindre')} color="var(--accent-silver)" />
        </div>

        {/* ── Card contenant les deux graphiques ── */}
        <div
          className="card"
          style={{ background: 'linear-gradient(135deg, var(--bg-surface), #0b1525)', border: '1px solid var(--border)', padding: '1.5rem', marginBottom: '1.5rem', overflowX: 'auto' }}
        >
          {/* ── Graphique 1 : progression des sous-objectifs ── */}
          <div style={{ marginBottom: '0.6rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', color: 'var(--accent-violet-light)', textTransform: 'uppercase' }}>
              {'\u25C8'} PROGRESSION DES SOUS-OBJECTIFS
            </span>
            <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
              <button
                onClick={() => setSmoothChart1(v => !v)}
                style={{
                  padding: '0.25rem 0.625rem',
                  borderRadius: '999px',
                  fontSize: '0.65rem',
                  fontWeight: 600,
                  letterSpacing: '0.06em',
                  border: smoothChart1 ? '1px solid #8b5cf6' : '1px solid var(--border)',
                  background: smoothChart1 ? 'rgba(139,92,246,0.15)' : 'transparent',
                  color: smoothChart1 ? '#a78bfa' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {t('stats.dynamique')}
              </button>
              <div style={{ width: 1, height: 16, background: 'var(--border)', margin: '0 0.15rem' }} />
              {(['7j', '30j', '90j', 'max'] as const).map((period) => (
                <button
                  key={period}
                  onClick={() => setZoomChart1(period)}
                  style={{
                    padding: '0.25rem 0.625rem',
                    borderRadius: '999px',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    letterSpacing: '0.06em',
                    border: zoomChart1 === period ? '1px solid #8b5cf6' : '1px solid var(--border)',
                    background: zoomChart1 === period ? 'rgba(139,92,246,0.15)' : 'transparent',
                    color: zoomChart1 === period ? '#a78bfa' : 'var(--text-muted)',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                    textTransform: 'uppercase',
                  }}
                >
                  {period === 'max' ? 'MAX' : period.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {profil && (
            <ChartSousObjectifs
              uid={uid}
              profil={profil}
              sousObjectifs={sousObjectifs}
              decisions={decisions}
              histPoints={histPoints}
              totalElapsedMs={totalElapsedMs}
              loading={loading}
              zoomPeriod={zoomChart1}
              smooth={smoothChart1}
            />
          )}

          {/* Legende chart 1 — sous-objectifs */}
          <div style={{ display: 'flex', gap: '1.25rem', marginTop: '0.75rem', marginBottom: '2rem', flexWrap: 'wrap' }}>
            {sousObjectifs.map((so, idx) => {
              const colors = ['#3b82f6', '#8b5cf6', '#f59e0b', '#10b981']
              const color = colors[idx % colors.length]
              const isActive = idx === sousObjectifs.findIndex(s => s.progression < 100)
              return (
                <div key={so.id} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span style={{
                    width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block',
                    boxShadow: isActive ? `0 0 8px ${color}` : 'none',
                    border: isActive ? `2px solid ${color}` : 'none',
                  }} />
                  <span style={{ fontSize: '0.72rem', color: isActive ? 'var(--text-primary)' : 'var(--text-muted)', fontWeight: isActive ? 600 : 400 }}>
                    {so.titre}{isActive ? ' *' : ''}
                  </span>
                </div>
              )
            })}
          </div>

          {/* Séparateur */}
          <div style={{ borderTop: '1px solid var(--border)', marginBottom: '1.5rem' }}/>

          {/* ── Graphique 2 : progression réelle dans le temps ── */}
          <div style={{ marginBottom: '0.6rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', color: '#f87171', textTransform: 'uppercase' }}>
              ◈ {t('stats.progression_reelle')}
            </span>
            <div style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
              <button
                onClick={() => setSmoothChart2(v => !v)}
                style={{
                  padding: '0.25rem 0.625rem',
                  borderRadius: '999px',
                  fontSize: '0.65rem',
                  fontWeight: 600,
                  letterSpacing: '0.06em',
                  border: smoothChart2 ? '1px solid #f59e0b' : '1px solid var(--border)',
                  background: smoothChart2 ? 'rgba(245,158,11,0.15)' : 'transparent',
                  color: smoothChart2 ? '#fbbf24' : 'var(--text-muted)',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {t('stats.dynamique')}
              </button>
              <div style={{ width: 1, height: 16, background: 'var(--border)', margin: '0 0.15rem' }} />
              {(['7j', '30j', '90j', 'max'] as const).map((period) => (
                <button
                  key={period}
                  onClick={() => setZoomChart2(period)}
                  style={{
                    padding: '0.25rem 0.625rem',
                    borderRadius: '999px',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    letterSpacing: '0.06em',
                    border: zoomChart2 === period ? '1px solid #ef4444' : '1px solid var(--border)',
                    background: zoomChart2 === period ? 'rgba(239,68,68,0.15)' : 'transparent',
                    color: zoomChart2 === period ? '#f87171' : 'var(--text-muted)',
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                    textTransform: 'uppercase',
                  }}
                >
                  {period === 'max' ? 'MAX' : period.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {profil && (
            <Chart2
              uid={uid}
              profil={profil}
              histPoints={histPoints}
              totalElapsedMs={totalElapsedMs}
              probActuelle={probActuelle}
              loading={loading}
              zoomPeriod={zoomChart2}
              smooth={smoothChart2}
            />
          )}

          {/* Légende chart 2 */}
          <div style={{ display: 'flex', gap: '1.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
            <LegendItem colorLine="#ef4444" label={t('stats.progression_reelle_legende')} />
          </div>
        </div>

        {/* ── Tableau historique ── */}
        {!loading && decisions.length > 0 && (
          <div className="card" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <h3 style={{ fontSize: '0.8rem', fontWeight: 700, letterSpacing: '0.1em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '1rem' }}>
              ◈ {t('stats.historique_decisions')}
            </h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {[t('stats.question_col'), t('stats.choix_col'), t('stats.impact_col'), t('stats.date_col'), ''].map((h) => (
                      <th key={h} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.06em', fontSize: '0.72rem' }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {decisions.slice(0, 10).map((d, i) => {
                    const impact = d.impact_net ?? 0
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                        <td style={{ padding: '0.625rem 0.75rem', color: 'var(--text-secondary)', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {d.question}
                        </td>
                        <td style={{ padding: '0.625rem 0.75rem', color: 'var(--text-primary)', fontSize: '0.8rem' }}>
                          {d.option_choisie_description || '—'}
                        </td>
                        <td style={{ padding: '0.625rem 0.75rem' }}>
                          <span style={{ color: impact >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600, fontSize: '0.8rem' }}>
                            {impact >= 0 ? '+' : ''}{impact.toFixed(1)}%
                          </span>
                        </td>
                        <td style={{ padding: '0.625rem 0.75rem', color: 'var(--text-muted)', fontSize: '0.75rem' }}>
                          {d.cree_le ? new Date(d.cree_le).toLocaleDateString('fr-FR') : '—'}
                        </td>
                        <td style={{ padding: '0.375rem 0.5rem', textAlign: 'center' }}>
                          <button
                            onClick={() => setDeleteTarget(d.id)}
                            title={t('stats.supprimer')}
                            style={{
                              background: 'none',
                              border: 'none',
                              cursor: 'pointer',
                              fontSize: '0.85rem',
                              padding: '0.2rem',
                              color: '#ef4444',
                              opacity: 0.6,
                              transition: 'opacity 0.15s',
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.opacity = '1')}
                            onMouseLeave={(e) => (e.currentTarget.style.opacity = '0.6')}
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <ConfirmDeleteModal
        visible={deleteTarget !== null}
        onConfirm={() => deleteTarget && handleDeleteDecision(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
      />

      {!loading && decisions.length === 0 && (
          <div className="card" style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
            <p style={{ fontSize: '1.5rem', marginBottom: '0.5rem', opacity: 0.4 }}>⊙</p>
            <p>{t('stats.aucune_decision')}</p>
            <p style={{ fontSize: '0.8rem', marginTop: '0.5rem' }}>{t('stats.aucune_decision_desc')}</p>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Graphique 1 (progression des sous-objectifs) ─────────────────────────────
const SO_COLORS = ['#3b82f6', '#8b5cf6', '#f59e0b', '#10b981']

function ChartSousObjectifs({
  uid, profil, sousObjectifs, decisions, histPoints, totalElapsedMs, loading, zoomPeriod = 'max', smooth = false,
}: {
  uid: string
  profil: Profil
  sousObjectifs: SousObjectif[]
  decisions: Decision[]
  histPoints: { elapsedMs: number; prob: number }[]
  totalElapsedMs: number
  loading: boolean
  zoomPeriod?: '7j' | '30j' | '90j' | 'max'
  smooth?: boolean
}) {
  const t = useT()
  const [hover, setHover] = useState<{ x: number; soData: { soId: string; titre: string; prog: number; color: string }[] } | null>(null)

  const MS_DAY = 24 * 60 * 60 * 1000
  const cutoffMs = zoomPeriod === '7j' ? 7 * MS_DAY
                 : zoomPeriod === '30j' ? 30 * MS_DAY
                 : zoomPeriod === '90j' ? 90 * MS_DAY
                 : totalElapsedMs
  const windowStartMs = Math.max(0, totalElapsedMs - cutoffMs)
  const isZoomed = zoomPeriod !== 'max'
  const windowMs = isZoomed ? cutoffMs : totalElapsedMs

  const elapsedDays = windowMs / MS_DAY
  const xTicks = buildTimeTicks(elapsedDays)

  // Active SO index
  const activeIdx = sousObjectifs.findIndex(so => so.progression < 100)

  // Build per-SO progression timeline from decisions
  // Each decision with sous_objectif_impacte tells us which SO was impacted
  const soTimelines = (() => {
    if (sousObjectifs.length === 0) return []

    const sorted = [...decisions]
      .filter(d => d.cree_le)
      .sort((a, b) => new Date(a.cree_le).getTime() - new Date(b.cree_le).getTime())

    const oml = profil.objectif_modifie_le
    const refDate = oml
      ? oml
      : (sorted.length === 0 ? new Date().toISOString() : profil.cree_le)
    const t0 = new Date(refDate).getTime()

    // Build progression timeline per SO
    // We know the current progression of each SO. We reconstruct history by
    // working backwards from current state using decisions that have sous_objectif_impacte.
    // However, since impact_net is the main probability impact, not the SO progression delta,
    // we use a simpler approach: accumulate SO progression from decisions.

    // Build a lookup from SO titre → SO id (sous_objectif_impacte stores the titre)
    const titreToId: Record<string, string> = {}
    for (const so of sousObjectifs) {
      titreToId[so.titre] = so.id
    }

    // Start all SOs at 0%
    const soProgression: Record<string, number> = {}
    for (const so of sousObjectifs) {
      soProgression[so.id] = 0
    }

    // Build points per SO: start at 0
    const timelines: Map<string, { elapsedMs: number; prog: number }[]> = new Map()
    for (const so of sousObjectifs) {
      timelines.set(so.id, [{ elapsedMs: 0, prog: 0 }])
    }

    // Process decisions in chronological order
    for (const d of sorted) {
      if (!d.sous_objectif_impacte) continue
      // sous_objectif_impacte contains the SO titre, not the SO id
      const soId = titreToId[d.sous_objectif_impacte]
      if (!soId || !timelines.has(soId)) continue

      const tMs = Math.max(0, new Date(d.cree_le).getTime() - t0)
      const impact = Math.abs(d.impact_net ?? 0)
      // Each decision adds some progression to the impacted SO
      // Use impact_net as a proxy for progression increment (scaled)
      soProgression[soId] = Math.min(100, soProgression[soId] + impact * 2)
      timelines.get(soId)!.push({ elapsedMs: tMs, prog: soProgression[soId] })
    }

    // Adjust final points to match actual current progression
    for (const so of sousObjectifs) {
      const timeline = timelines.get(so.id)!
      const lastProg = timeline[timeline.length - 1].prog
      const currentProg = so.progression

      // If we have decision-based data, scale to match current progression
      if (timeline.length > 1 && lastProg > 0) {
        const scale = currentProg / lastProg
        for (let i = 1; i < timeline.length; i++) {
          timeline[i].prog = Math.min(100, timeline[i].prog * scale)
        }
      }

      // Add final point at current time with current progression
      timeline.push({ elapsedMs: totalElapsedMs, prog: currentProg })
    }

    // Apply zoom filtering
    return sousObjectifs.map((so, idx) => {
      let pts = timelines.get(so.id) || [{ elapsedMs: 0, prog: 0 }]

      if (isZoomed) {
        const inWindow = pts.filter(p => p.elapsedMs >= windowStartMs)
        if (inWindow.length === 0 && pts.length > 0) {
          inWindow.push(pts[pts.length - 1])
        }
        if (inWindow.length > 0 && inWindow[0].elapsedMs > windowStartMs && pts.length > 0) {
          // Interpolate start point
          let startProg = 0
          for (const p of pts) {
            if (p.elapsedMs <= windowStartMs) startProg = p.prog
            else break
          }
          inWindow.unshift({ elapsedMs: windowStartMs, prog: startProg })
        }
        pts = inWindow.map(p => ({ ...p, elapsedMs: p.elapsedMs - windowStartMs }))
      }

      return {
        soId: so.id,
        titre: so.titre,
        color: SO_COLORS[idx % SO_COLORS.length],
        isActive: idx === activeIdx,
        points: pts,
      }
    })
  })()

  // Y: progression 0-100%
  const Y_PROG_TICKS = [0, 25, 50, 75, 100]
  function yProg(prog: number): number {
    const clamped = Math.max(0, Math.min(100, prog))
    return PAD.top + innerH() * (1 - clamped / 100)
  }

  // Build paths — même logique sigmoïde que Chart2 pour un lissage identique
  const soPaths = soTimelines.map(so => {
    if (so.points.length < 2) return { ...so, pathD: '' }

    let pathD: string
    if (smooth && so.points.length >= 2) {
      // Mode lisse : somme de sigmoïdes + échantillonnage uniforme (identique à Chart2)
      const baseProg = so.points[0].prog
      const totalRange = windowMs || 1
      const avgGap = so.points.length > 1
        ? (so.points[so.points.length - 1].elapsedMs - so.points[0].elapsedMs) / (so.points.length - 1)
        : totalRange
      const transWidth = Math.max(avgGap * 0.6, totalRange * 0.06)

      function smoothProg(ems: number): number {
        let prog = baseProg
        for (let i = 1; i < so.points.length; i++) {
          const delta = so.points[i].prog - so.points[i - 1].prog
          const center = so.points[i].elapsedMs
          const x = (ems - center) / transWidth
          const sig = 1 / (1 + Math.exp(-3 * x))
          prog += delta * sig
        }
        return prog
      }

      const numSamples = 150
      const startEms = so.points[0].elapsedMs
      const endEms = so.points[so.points.length - 1].elapsedMs
      const rangeEms = endEms - startEms || 1

      const pts: { x: number; y: number }[] = []
      for (let s = 0; s <= numSamples; s++) {
        const ems = startEms + (rangeEms * s) / numSamples
        const prog = smoothProg(ems)
        pts.push({
          x: xFromElapsed(ems, windowMs),
          y: yProg(prog),
        })
      }
      pathD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
    } else {
      // Step path (same as Chart2 non-smooth)
      pathD = so.points.map((p, i) => {
        const x = xFromElapsed(p.elapsedMs, windowMs)
        const y = yProg(p.prog)
        if (i === 0) return `M ${x.toFixed(1)} ${y.toFixed(1)}`
        return `H ${x.toFixed(1)} V ${y.toFixed(1)}`
      }).join(' ')
    }

    return { ...so, pathD }
  })

  return (
    <svg
      width={W} height={H}
      viewBox={`0 0 ${W} ${H}`}
      style={{ display: 'block', maxWidth: '100%', overflow: 'visible' }}
      onMouseMove={(e) => {
        const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
        const scaleX = W / rect.width
        const mx = (e.clientX - rect.left) * scaleX
        if (mx < PAD.left || mx > W - PAD.right) { setHover(null); return }
        const frac = (mx - PAD.left) / innerW()
        const ems = frac * windowMs

        // Find progression value for each SO at this time
        const soData = soTimelines.map(so => {
          let prog = 0
          for (const p of so.points) {
            if (p.elapsedMs <= ems) prog = p.prog
            else break
          }
          return { soId: so.soId, titre: so.titre, prog, color: so.color }
        })

        setHover({ x: PAD.left + frac * innerW(), soData })
      }}
      onMouseLeave={() => setHover(null)}
    >
      <defs>
        <filter id={`sg1-glow-${uid}`}>
          <feGaussianBlur stdDeviation="2" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>

      {/* Grille Y (progression %) */}
      {Y_PROG_TICKS.map((p) => {
        const yy = yProg(p)
        return (
          <g key={p}>
            <line x1={PAD.left} y1={yy} x2={W - PAD.right} y2={yy}
              stroke="rgba(255,255,255,0.05)" strokeWidth="1"
              strokeDasharray={p === 0 || p === 100 ? '' : '4 4'}/>
            <text x={PAD.left - 6} y={yy} textAnchor="end" dominantBaseline="middle"
              fontSize="10" fill="rgba(232,232,240,0.35)"
              fontFamily="Inter, system-ui, sans-serif">
              {p}%
            </text>
          </g>
        )
      })}

      {/* Grille X (temps reel) */}
      {xTicks.map(({ valueDays, label }, ti) => {
        const xx = xFromElapsed(valueDays * 24 * 60 * 60 * 1000, windowMs)
        if (xx < PAD.left - 1 || xx > W - PAD.right + 1) return null
        return (
          <g key={`xt-${ti}`}>
            <line x1={xx} y1={PAD.top} x2={xx} y2={H - PAD.bottom}
              stroke="rgba(255,255,255,0.05)" strokeWidth="1"
              strokeDasharray={ti === 0 ? '' : '4 4'}/>
            <text x={xx} y={H - PAD.bottom + 14} textAnchor="middle"
              fontSize="10" fill="rgba(232,232,240,0.35)"
              fontFamily="Inter, system-ui, sans-serif">
              {label}
            </text>
          </g>
        )
      })}

      {/* Labels axes */}
      <text x={PAD.left + innerW() / 2} y={H - 4} textAnchor="middle"
        fontSize="10" fill="rgba(232,232,240,0.4)"
        fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.08em">
        {t('stats.temps_ecoule')}
      </text>
      <text x={10} y={PAD.top + innerH() / 2} textAnchor="middle"
        fontSize="10" fill="rgba(232,232,240,0.4)"
        fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.08em"
        transform={`rotate(-90, 10, ${PAD.top + innerH() / 2})`}>
        Progression
      </text>

      {/* Lines per SO */}
      {!loading && soPaths.map(so => so.pathD ? (
        <path key={so.soId} d={so.pathD} fill="none" stroke={so.color}
          strokeWidth={so.isActive ? 3 : 2}
          strokeLinecap="round" strokeLinejoin="round"
          opacity={so.isActive ? 1 : 0.7}
          style={{ filter: so.isActive ? `url(#sg1-glow-${uid})` : undefined }}/>
      ) : null)}

      {/* End dots per SO (current progression) */}
      {!loading && !smooth && soPaths.map(so => {
        if (so.points.length === 0) return null
        const last = so.points[so.points.length - 1]
        const px = xFromElapsed(last.elapsedMs, windowMs)
        const py = yProg(last.prog)
        return (
          <circle key={`dot-${so.soId}`} cx={px} cy={py} r={so.isActive ? 6 : 4}
            fill={so.color} stroke="#020509" strokeWidth="2"
            style={{ filter: so.isActive ? `drop-shadow(0 0 6px ${so.color})` : undefined }}/>
        )
      })}

      {/* Tooltip */}
      {hover && hover.soData.length > 0 && (() => {
        const tipW = 155
        const tipH = 14 + hover.soData.length * 16 + 6
        const tipX = hover.x > W - PAD.right - tipW - 10 ? hover.x - tipW - 10 : hover.x + 10
        const tipY = Math.min(PAD.top + 10, H - PAD.bottom - tipH - 10)
        return (
          <g>
            <line x1={hover.x} y1={PAD.top} x2={hover.x} y2={H - PAD.bottom}
              stroke="rgba(255,255,255,0.13)" strokeWidth="1" strokeDasharray="3 3"/>
            <rect x={tipX} y={tipY} width={tipW} height={tipH} rx={6}
              fill="#13131f" stroke="rgba(139,92,246,0.4)" strokeWidth="1"/>
            {hover.soData.map((so, i) => (
              <g key={so.soId}>
                <circle cx={tipX + 10} cy={tipY + 14 + i * 16} r={3} fill={so.color}/>
                <text x={tipX + 18} y={tipY + 14 + i * 16 + 1} dominantBaseline="middle"
                  fontSize="9" fill="rgba(232,232,240,0.7)"
                  fontFamily="Inter, system-ui, sans-serif">
                  {so.titre.length > 12 ? so.titre.slice(0, 12) + '..' : so.titre}
                </text>
                <text x={tipX + tipW - 8} y={tipY + 14 + i * 16 + 1} textAnchor="end" dominantBaseline="middle"
                  fontSize="10" fontWeight="700" fill={so.color}
                  fontFamily="Inter, system-ui, sans-serif">
                  {so.prog.toFixed(0)}%
                </text>
              </g>
            ))}
          </g>
        )
      })()}
    </svg>
  )
}

// ── Graphique 2 (courbe réelle rouge) ─────────────────────────────────────────
/** Monotone cubic Hermite spline — courbe lisse passant par tous les points sans oscillation */
function buildSmoothPath(pts: { x: number; y: number }[]): string {
  const n = pts.length
  if (n < 2) return ''
  if (n === 2) return `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)} L ${pts[1].x.toFixed(1)} ${pts[1].y.toFixed(1)}`

  // 1. Calculer les pentes (differences)
  const dx: number[] = []
  const dy: number[] = []
  const m: number[] = []
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1].x - pts[i].x)
    dy.push(pts[i + 1].y - pts[i].y)
    m.push(dx[i] === 0 ? 0 : dy[i] / dx[i])
  }

  // 2. Tangentes monotones (Fritsch-Carlson)
  const t: number[] = [m[0]]
  for (let i = 1; i < n - 1; i++) {
    if (m[i - 1] * m[i] <= 0) {
      t.push(0)
    } else {
      t.push((m[i - 1] + m[i]) / 2)
    }
  }
  t.push(m[n - 2])

  // 3. Ajuster pour monotonie
  for (let i = 0; i < n - 1; i++) {
    if (Math.abs(m[i]) < 1e-10) { t[i] = 0; t[i + 1] = 0; continue }
    const a = t[i] / m[i]
    const b = t[i + 1] / m[i]
    const s = a * a + b * b
    if (s > 9) {
      const tau = 3 / Math.sqrt(s)
      t[i] = tau * a * m[i]
      t[i + 1] = tau * b * m[i]
    }
  }

  // 4. Generer le path SVG avec des courbes cubiques
  let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`
  for (let i = 0; i < n - 1; i++) {
    const dxi = dx[i] / 3
    const cp1x = pts[i].x + dxi
    const cp1y = pts[i].y + t[i] * dxi
    const cp2x = pts[i + 1].x - dxi
    const cp2y = pts[i + 1].y - t[i + 1] * dxi
    d += ` C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${pts[i + 1].x.toFixed(1)} ${pts[i + 1].y.toFixed(1)}`
  }
  return d
}

function Chart2({
  uid, profil, histPoints, totalElapsedMs, probActuelle, loading, zoomPeriod = 'max', smooth = false,
}: {
  uid: string
  profil: Profil
  histPoints: { elapsedMs: number; prob: number }[]
  totalElapsedMs: number
  probActuelle: number
  loading: boolean
  zoomPeriod?: '7j' | '30j' | '90j' | 'max'
  smooth?: boolean
}) {
  const t = useT()
  const [hover, setHover] = useState<{ x: number; y: number; prob: number; elapsedMs: number } | null>(null)

  // ── Zoom : filtrer les points par période ───────────────────────────────────────
  const MS_DAY = 24 * 60 * 60 * 1000
  const cutoffMs = zoomPeriod === '7j' ? 7 * MS_DAY
                 : zoomPeriod === '30j' ? 30 * MS_DAY
                 : zoomPeriod === '90j' ? 90 * MS_DAY
                 : totalElapsedMs
  const windowStartMs = Math.max(0, totalElapsedMs - cutoffMs)
  const isZoomed = zoomPeriod !== 'max'

  // Filtrer + recentrer les points dans la fenêtre de zoom
  const zoomedPoints = (() => {
    if (!isZoomed) return histPoints
    // Trouver les points dans la fenêtre
    const inWindow = histPoints.filter(p => p.elapsedMs >= windowStartMs)
    if (inWindow.length === 0) return histPoints.length > 0 ? [histPoints[histPoints.length - 1]] : []
    // Interpoler le point de début si nécessaire
    const first = inWindow[0]
    if (first.elapsedMs > windowStartMs && histPoints.length > 0) {
      const probAtStart = interpolateProb(histPoints, windowStartMs)
      inWindow.unshift({ elapsedMs: windowStartMs, prob: probAtStart })
    }
    // Recentrer : elapsedMs relatif à windowStart
    return inWindow.map(p => ({ ...p, elapsedMs: p.elapsedMs - windowStartMs }))
  })()

  const windowMs = isZoomed ? cutoffMs : totalElapsedMs
  const elapsedDays = windowMs / MS_DAY
  const xTicks      = buildTimeTicks(elapsedDays)

  // ── Auto-scale Y pour les modes zoomés ────────────────────────────────────
  const allProbs = zoomedPoints.map(p => p.prob)
  const rawMin = allProbs.length > 0 ? Math.min(...allProbs) : 0
  const rawMax = allProbs.length > 0 ? Math.max(...allProbs) : 100
  const yProbMin = isZoomed ? Math.max(0, Math.floor(rawMin - 2)) : 0
  const yProbMax = isZoomed ? Math.min(100, Math.ceil(rawMax + 2)) : 100
  const yRange = Math.max(1, yProbMax - yProbMin)

  // Y from prob pour zoom (avec bornes dynamiques)
  function yZoomed(prob: number): number {
    const clamped = Math.max(yProbMin, Math.min(yProbMax, prob))
    return PAD.top + innerH() * (1 - (clamped - yProbMin) / yRange)
  }

  // Ticks Y pour le mode zoomé
  const yTicksZoomed = (() => {
    if (!isZoomed) return Y_TICKS
    const step = yRange <= 5 ? 1 : yRange <= 15 ? 2 : yRange <= 30 ? 5 : 10
    const ticks: number[] = []
    const start = Math.ceil(yProbMin / step) * step
    for (let v = start; v <= yProbMax; v += step) ticks.push(v)
    if (ticks.length < 2) { ticks.push(yProbMin); ticks.push(yProbMax) }
    return [...new Set(ticks)].sort((a, b) => a - b)
  })()

  // Couleurs conditionnelles selon le mode
  const lineColor = smooth ? '#f59e0b' : '#ef4444'
  const glowColor = smooth ? 'rgba(245,158,11,0.9)' : 'rgba(239,68,68,0.9)'
  const dotColor  = smooth ? '#fcd34d' : '#fca5a5'

  // Path de la courbe (escalier ou lisse selon le mode)
  const pathD = zoomedPoints.length >= 2
    ? smooth
      ? (() => {
          // Mode lisse : fonction continue globale
          // prob(t) = prob_initiale + Σ delta_i × sigmoid((t - t_i) / largeur)
          // Échantillonnage uniforme → courbe parfaitement lisse sans aucun angle

          // Collecter les décisions (moments + deltas de probabilité)
          const decisions: { ems: number; prob: number }[] = []
          for (let i = 0; i < zoomedPoints.length; i++) {
            decisions.push({ ems: zoomedPoints[i].elapsedMs, prob: zoomedPoints[i].prob })
          }
          if (decisions.length < 2) return ''

          const baseProb = decisions[0].prob
          // Largeur de transition : large pour un lissage visible
          // Utiliser l'écart moyen entre décisions × 1.5 pour que les transitions se chevauchent
          const totalRange = windowMs || 1
          const avgGap = decisions.length > 1
            ? (decisions[decisions.length - 1].ems - decisions[0].ems) / (decisions.length - 1)
            : totalRange
          const transWidth = Math.max(avgGap * 0.6, totalRange * 0.06)

          // Fonction continue : à l'instant ems, quelle est la proba lissée ?
          function smoothProb(ems: number): number {
            let prob = baseProb
            for (let i = 1; i < decisions.length; i++) {
              const delta = decisions[i].prob - decisions[i - 1].prob
              const center = decisions[i].ems
              // Sigmoïde très douce : k=3 pour une transition large et progressive
              const x = (ems - center) / transWidth
              const sig = 1 / (1 + Math.exp(-3 * x))
              prob += delta * sig
            }
            return prob
          }

          // Échantillonner uniformément 150 points sur toute la timeline
          const numSamples = 150
          const startEms = decisions[0].ems
          const endEms = decisions[decisions.length - 1].ems
          const rangeEms = endEms - startEms || 1

          const pts: { x: number; y: number }[] = []
          for (let s = 0; s <= numSamples; s++) {
            const ems = startEms + (rangeEms * s) / numSamples
            const prob = smoothProb(ems)
            pts.push({
              x: xFromElapsed(ems, windowMs),
              y: yZoomed(prob),
            })
          }

          // Construire le path SVG directement avec des lignes (les 150 points font une courbe lisse)
          return pts.map((p, i) =>
            i === 0 ? `M ${p.x.toFixed(1)} ${p.y.toFixed(1)}` : `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`
          ).join(' ')
        })()
      : zoomedPoints.map((p, i) => {
          const x = xFromElapsed(p.elapsedMs, windowMs)
          const y = yZoomed(p.prob)
          if (i === 0) return `M ${x.toFixed(1)} ${y.toFixed(1)}`
          return `H ${x.toFixed(1)} V ${y.toFixed(1)}`
        }).join(' ')
    : ''

  // Aire sous la courbe rouge
  const areaD = pathD && zoomedPoints.length >= 2 ? (() => {
    const last  = zoomedPoints[zoomedPoints.length - 1]
    const first = zoomedPoints[0]
    return pathD +
      ` L ${xFromElapsed(last.elapsedMs, windowMs).toFixed(1)} ${(H - PAD.bottom).toFixed(1)}` +
      ` L ${xFromElapsed(first.elapsedMs, windowMs).toFixed(1)} ${(H - PAD.bottom).toFixed(1)} Z`
  })() : ''

  return (
    <svg
      width={W} height={H}
      viewBox={`0 0 ${W} ${H}`}
      style={{ display: 'block', maxWidth: '100%', overflow: 'visible' }}
      onMouseMove={(e) => {
        const rect  = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
        const scaleX = W / rect.width
        const mx    = (e.clientX - rect.left) * scaleX
        if (mx < PAD.left || mx > W - PAD.right) { setHover(null); return }
        const frac     = (mx - PAD.left) / innerW()
        const ems      = frac * windowMs
        // interpoler la proba depuis les points zoomés
        const prob     = interpolateProb(zoomedPoints, ems)
        setHover({ x: PAD.left + frac * innerW(), y: yZoomed(prob), prob, elapsedMs: ems + windowStartMs })
      }}
      onMouseLeave={() => setHover(null)}
    >
      <defs>
        <linearGradient id={`sg2-area-${uid}`} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%"   stopColor={lineColor} stopOpacity="0.15"/>
          <stop offset="100%" stopColor={lineColor} stopOpacity="0.01"/>
        </linearGradient>
        <filter id={`sg2-glow-${uid}`}>
          <feGaussianBlur stdDeviation="2" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>

      {/* Grille Y (probabilités — auto-scale en mode zoom) */}
      {yTicksZoomed.map((p) => {
        const yy = yZoomed(p)
        return (
          <g key={p}>
            <line x1={PAD.left} y1={yy} x2={W - PAD.right} y2={yy}
              stroke="rgba(255,255,255,0.05)" strokeWidth="1"
              strokeDasharray={p === yProbMin || p === yProbMax ? '' : '4 4'}/>
            <text x={PAD.left - 6} y={yy} textAnchor="end" dominantBaseline="middle"
              fontSize="10" fill="rgba(232,232,240,0.35)"
              fontFamily="Inter, system-ui, sans-serif">
              {p}%
            </text>
          </g>
        )
      })}

      {/* Grille X (temps réel) */}
      {xTicks.map(({ valueDays, label }, ti) => {
        const xx = xFromElapsed(valueDays * 24 * 60 * 60 * 1000, windowMs)
        if (xx < PAD.left - 1 || xx > W - PAD.right + 1) return null
        return (
          <g key={`xt-${ti}`}>
            <line x1={xx} y1={PAD.top} x2={xx} y2={H - PAD.bottom}
              stroke="rgba(255,255,255,0.05)" strokeWidth="1"
              strokeDasharray={ti === 0 ? '' : '4 4'}/>
            <text x={xx} y={H - PAD.bottom + 14} textAnchor="middle"
              fontSize="10" fill="rgba(232,232,240,0.35)"
              fontFamily="Inter, system-ui, sans-serif">
              {label}
            </text>
          </g>
        )
      })}

      {/* Labels axes */}
      <text x={PAD.left + innerW() / 2} y={H - 4} textAnchor="middle"
        fontSize="10" fill="rgba(232,232,240,0.4)"
        fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.08em">
        {t('stats.temps_ecoule')}
      </text>
      <text x={10} y={PAD.top + innerH() / 2} textAnchor="middle"
        fontSize="10" fill="rgba(232,232,240,0.4)"
        fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.08em"
        transform={`rotate(-90, 10, ${PAD.top + innerH() / 2})`}>
        {t('stats.probabilite_label')}
      </text>

      {/* Aire + courbe rouge */}
      {!loading && areaD && <path d={areaD} fill={`url(#sg2-area-${uid})`}/>}
      {!loading && pathD && (
        <path d={pathD} fill="none" stroke={lineColor} strokeWidth="2.5"
          strokeLinecap="round" strokeLinejoin="round"
          style={{ filter: `url(#sg2-glow-${uid})` }}/>
      )}

      {/* Points de décision (masqués en mode lisse) */}
      {/* Point initial */}
            {!loading && !smooth && zoomedPoints.length > 0 && (() => {
              const first = zoomedPoints[0]
              const fx = xFromElapsed(first.elapsedMs, windowMs)
              const fy = yZoomed(first.prob)
              return (
                <circle cx={fx} cy={fy} r={5}
                  fill={dotColor} stroke="#020509" strokeWidth="2"
                  style={{ filter: `drop-shadow(0 0 4px ${glowColor})` }}/>
              )
            })()}
            {!loading && !smooth && zoomedPoints.filter((_, i) => i > 0 && i < zoomedPoints.length - 1).map((hp, i) => {
        const hx = xFromElapsed(hp.elapsedMs, windowMs)
        const hy = yZoomed(hp.prob)
        return (
          <circle key={i} cx={hx} cy={hy} r={5}
            fill={dotColor} stroke="#020509" strokeWidth="2"
            style={{ filter: `drop-shadow(0 0 4px ${glowColor})` }}/>
        )
      })}

      {/* Point "Maintenant" (extrémité droite) */}
      {!loading && zoomedPoints.length > 0 && (() => {
        const last = zoomedPoints[zoomedPoints.length - 1]
        const px   = xFromElapsed(last.elapsedMs, windowMs)
        const py   = yZoomed(last.prob)
        return (
          <g>
            {!smooth && <circle cx={px} cy={py} r={7}
              fill={lineColor} stroke="#020509" strokeWidth="2"
              style={{ filter: `drop-shadow(0 0 8px ${glowColor})` }}/>}
            {!smooth && <circle cx={px} cy={py} r={3} fill="#020509"/>}
            <text x={px} y={py - 13} textAnchor="middle"
              fontSize="9" fill={smooth ? 'rgba(251,191,36,0.9)' : 'rgba(248,113,113,0.9)'}
              fontFamily="Inter, system-ui, sans-serif"
              fontWeight="600" letterSpacing="0.06em">
              {t('stats.maintenant')}
            </text>
          </g>
        )
      })()}

      {/* Tooltip survol chart 2 */}
      {hover && (() => {
        const tipX = hover.x > W - PAD.right - 130 ? hover.x - 130 : hover.x + 10
        const tipY = hover.y < PAD.top + 55 ? hover.y + 10 : hover.y - 55
        const elapsedDaysH = hover.elapsedMs / MS_DAY
        const ticks = buildTimeTicks(elapsedDaysH)
        const timeLabel = ticks.length > 0 ? ticks[ticks.length - 1].label : '—'
        return (
          <g>
            <line x1={hover.x} y1={PAD.top} x2={hover.x} y2={H - PAD.bottom}
              stroke="rgba(255,255,255,0.13)" strokeWidth="1" strokeDasharray="3 3"/>
            <circle cx={hover.x} cy={hover.y} r={4} fill="white" opacity={0.8}
              style={{ filter: 'drop-shadow(0 0 3px white)' }}/>
            <rect x={tipX} y={tipY} width={118} height={46} rx={6}
              fill="#13131f" stroke={smooth ? 'rgba(245,158,11,0.4)' : 'rgba(239,68,68,0.4)'} strokeWidth="1"/>
            <text x={tipX + 8} y={tipY + 15}
              fontSize="9" fill="rgba(232,232,240,0.5)"
              fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.06em">
              T+{timeLabel}
            </text>
            <text x={tipX + 8} y={tipY + 31}
              fontSize="12" fontWeight="700" fill={smooth ? '#fbbf24' : '#f87171'}
              fontFamily="Inter, system-ui, sans-serif">
              {hover.prob.toFixed(1)} % {t('stats.reussite')}
            </text>
          </g>
        )
      })()}
    </svg>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Construit les points de la courbe réelle à partir du profil + décisions */
function buildHistoricalPoints(
  profil: Profil | null,
  decisions: Decision[],
): { histPoints: { elapsedMs: number; prob: number }[]; totalElapsedMs: number } {
  if (!profil) return { histPoints: [], totalElapsedMs: 1 }

  // t0 = date du dernier reset de l'objectif
  // Si pas de date de reset ET pas de decisions : J+0 (depart propre = maintenant)
  // Si pas de date de reset MAIS des decisions : fallback cree_le (historique ancien)
  // Trier les décisions par date croissante
  const sorted = [...decisions]
    .filter((d) => d.cree_le)
    .sort((a, b) => new Date(a.cree_le).getTime() - new Date(b.cree_le).getTime())
  const oml = profil.objectif_modifie_le
  const refDate = oml
    ? oml
    : (sorted.length === 0 ? new Date().toISOString() : profil.cree_le)
  const t0 = new Date(refDate).getTime()
  const tNow       = Date.now()
  const totalMs    = Math.max(tNow - t0, 1)
  const probActuel = profil.probabilite_actuelle


  const points: { elapsedMs: number; prob: number }[] = []

  // Point de départ : prob initiale à t=0
  // Si aucune décision (ex: après reset), partir de 0
  const probInitiale = sorted.length > 0
    ? sorted[0].probabilite_avant
    : probActuel  // pas de decisions -> partir de la proba actuelle
  points.push({ elapsedMs: 0, prob: probInitiale })

  // Chaque décision ajoute deux points (avant → après)
  for (const d of sorted) {
    const tMs = new Date(d.cree_le).getTime() - t0
    if (tMs <= 0) continue
    if (d.probabilite_avant !== undefined) {
      points.push({ elapsedMs: tMs - 1, prob: d.probabilite_avant })
    }
    if (d.probabilite_apres !== null && d.probabilite_apres !== undefined) {
      points.push({ elapsedMs: tMs, prob: d.probabilite_apres })
    }
  }

  // Point final : aujourd'hui
  points.push({ elapsedMs: totalMs, prob: probActuel })

  return { histPoints: points, totalElapsedMs: totalMs }
}

/** Interpolation en palier : retourne la dernière probabilité connue (pas d'interpolation linéaire) */
function interpolateProb(
  points: { elapsedMs: number; prob: number }[],
  ems: number,
): number {
  if (points.length === 0) return 0
  // Trouver le dernier point dont le temps est <= ems
  let result = points[0].prob
  for (const p of points) {
    if (p.elapsedMs <= ems) result = p.prob
    else break
  }
  return result
}

// ── Composants locaux ─────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }: { label: string; value: string; sub: string; color: string }) {
  return (
    <div className="card" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', padding: '1.1rem 1.25rem' }}>
      <p style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.4rem' }}>{label}</p>
      <p style={{ fontSize: '1.35rem', fontWeight: 700, color, letterSpacing: '0.02em', marginBottom: '0.2rem' }}>{value}</p>
      <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{sub}</p>
    </div>
  )
}

function LegendItem({ colorLine, colorDot, label }: { colorLine?: string; colorDot?: string; label: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      {colorDot
        ? <span style={{ width: 10, height: 10, borderRadius: '50%', background: colorDot, display: 'inline-block', boxShadow: `0 0 6px ${colorDot}` }}/>
        : <span style={{ width: 22, height: 3, background: colorLine, borderRadius: 2, display: 'inline-block' }}/>
      }
      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{label}</span>
    </div>
  )
}
