// Page Statistiques — Deux graphiques
// Graphique 1 (théorique) : X = temps restant (10a → 0), Y = probabilité % (0→100%)
// Graphique 2 (réel)      : X = temps réel écoulé depuis le début (→ aujourd'hui), Y = probabilité %

import { useEffect, useState, useId } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store/useStore'
import { api } from '../api/client'
import { dureeFromProb, probFromJours, buildTimeTicks } from '../utils/duration'
import type { Decision, Profil } from '../types'
import { ConfirmDeleteModal } from '../components/ConfirmDeleteModal'

// ── Dimensions partagées ──────────────────────────────────────────────────────
const W   = 620
const H   = 300
const PAD = { top: 24, right: 24, bottom: 52, left: 58 }

// ── Helpers coordonnées ───────────────────────────────────────────────────────
const innerW = (w = W) => w - PAD.left - PAD.right
const innerH = (h = H) => h - PAD.top  - PAD.bottom

/**
 * X depuis des jours restants (graphique 1) — axe INVERSÉ :
 * days=MAX_DAYS (beaucoup de temps restant) → gauche (PAD.left)
 * days=0        (objectif atteint)          → droite (W - PAD.right)
 */
function xFromDays(days: number, maxDays: number): number {
  return PAD.left + (1 - Math.min(days / maxDays, 1)) * innerW()
}
/** Y depuis une probabilité % (0→bas, 100→haut) */
function yFromProb(prob: number): number {
  return PAD.top + innerH() * (1 - Math.max(0, Math.min(100, prob)) / 100)
}
/** X depuis un temps réel elapsed (ms) sur total elapsed */
function xFromElapsed(elapsedMs: number, totalMs: number): number {
  return PAD.left + Math.min(elapsedMs / totalMs, 1) * innerW()
}

// Constantes chart 1 (Y fixe, X dynamique selon duree estimee)
const Y_TICKS = [0, 25, 50, 75, 100]

/** Genere des ticks annees pour l axe X du chart 1 */
function buildChartYearTicks(maxAns: number): number[] {
  const r = Math.ceil(maxAns)
  if (r <= 2)   return [0, 1, 2].filter(v => v <= r)
  if (r <= 5)   return [0, 1, 2, 3, 4, 5].filter(v => v <= r)
  if (r <= 10)  return [0, 2, 5, 10].filter(v => v <= r)
  if (r <= 20)  return [0, 5, 10, 15, 20].filter(v => v <= r)
  if (r <= 40)  return [0, 5, 10, 20, 30, 40].filter(v => v <= r)
  if (r <= 60)  return [0, 10, 20, 30, 40, 50, 60].filter(v => v <= r)
  if (r <= 100) return [0, 25, 50, 75, 100].filter(v => v <= r)
  return [0, 25, 50, 75, 100, 150, 200].filter(v => v <= r)
}

// ── Composant principal ───────────────────────────────────────────────────────
export function StatistiquesPage() {
  const uid      = useId().replace(/\W/g, '')
  const navigate = useNavigate()
  const { profil, setProfil } = useStore()
  const [decisions, setDecisions] = useState<Decision[]>([])

  const handleDeleteDecision = async (id: string) => {
    try {
      await api.deleteDecision(id)
      setDecisions((prev) => prev.filter((d) => d.id !== id))
      // Re-fetch profil pour obtenir probabilite_actuelle mise à jour
      const updatedProfil = await api.getProfil()
      setProfil(updatedProfil)
    } catch {
      // silently fail
    }
    setDeleteTarget(null)
  }
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [loading, setLoading]     = useState(true)
  const [hover1, setHover1]       = useState<{ days: number; x: number; y: number } | null>(null)
  const [zoomChart2, setZoomChart2] = useState<'7j' | '30j' | '90j' | 'max'>('max')

  useEffect(() => {
    // Toujours recharger le profil depuis l'API
    api.getProfil().then(setProfil).catch(() => navigate('/profil'))
    api.getHistorique(100)
      .then(setDecisions)
      .catch(() => setDecisions([]))
      .finally(() => setLoading(false))
  }, [])

  // ── Stats résumées ────────────────────────────────────────────────────────
  const probActuelle  = profil?.probabilite_actuelle ?? 0
  const probCalculee  = profil?.objectif?.probabilite_calculee ?? 0
  const probTemps     = probCalculee + probActuelle
  const gainTotal     = decisions.reduce((acc, d) => acc + (d.impact_net ?? 0), 0)
  const probInitiale  = Math.max(0, Math.min(100, probActuelle - gainTotal))
  const dureeActuelle = dureeFromProb(probTemps)
  const dureeInitiale = dureeFromProb(probCalculee + probInitiale)
  // Chart 1 FIXE : axe X = duree estimee initiale (ne change JAMAIS)
  const maxDaysChart1 = Math.max(Math.round(dureeInitiale.totalJours * 1.05), 365)
  const maxAnsChart1  = Math.ceil(maxDaysChart1 / 365)
  const xTicks1       = buildChartYearTicks(maxAnsChart1)
  // Normalisation : la courbe theorique doit demarrer a 0% en Y
  const probBase  = probFromJours(maxDaysChart1)   // proba brute au bord gauche (~24%)
  const normProb  = (rawP: number) => Math.max(0, Math.min(100, (rawP - probBase) / (100 - probBase) * 100))
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
            Tableau de bord avancé
          </p>
          <h1 style={{ fontSize: '1.75rem', color: 'var(--accent-silver)', marginBottom: '0.25rem' }}>
            Statistiques
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            Évolution de votre probabilité de réussite
          </p>
        </div>

        {/* ── Cartes stats ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem', marginBottom: '1.75rem' }}>
          <StatCard label="Décisions prises"     value={String(decisions.length)} sub="depuis le début"              color="var(--accent-violet-light)" />
          <StatCard label="Gain probabilité"     value={gainTotal >= 0 ? `+${gainTotal.toFixed(1)} %` : `${gainTotal.toFixed(1)} %`} sub="total cumulé" color={gainTotal >= 0 ? '#22c55e' : '#ef4444'} />
          <StatCard label="Temps économisé"      value={tempsGagne > 0 ? (tgAns > 0 ? `${tgAns}a${tgMois > 0 ? ` ${tgMois}m` : ''}` : `${tgMois}m`) : '—'} sub="vers votre objectif" color="#4090f0" />
          <StatCard label="Temps restant estimé" value={dureeActuelle.ligne1} sub={dureeActuelle.ligne2 || 'pour atteindre l\'objectif'} color="var(--accent-silver)" />
        </div>

        {/* ── Card contenant les deux graphiques ── */}
        <div
          className="card"
          style={{ background: 'linear-gradient(135deg, var(--bg-surface), #0b1525)', border: '1px solid var(--border)', padding: '1.5rem', marginBottom: '1.5rem', overflowX: 'auto' }}
        >
          {/* ── Graphique 1 : courbe théorique ── */}
          <div style={{ marginBottom: '0.6rem' }}>
            <span style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', color: 'var(--accent-violet-light)', textTransform: 'uppercase' }}>
              ◈ Probabilité théorique selon le temps restant estimé
            </span>
          </div>

          <svg
            width={W} height={H}
            viewBox={`0 0 ${W} ${H}`}
            style={{ display: 'block', maxWidth: '100%', overflow: 'visible' }}
            onMouseMove={(e) => {
              const rect   = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
              const scaleX = W / rect.width
              const mx     = (e.clientX - rect.left) * scaleX
              if (mx < PAD.left || mx > W - PAD.right) { setHover1(null); return }
              // Axe X inversé : frac=0 (gauche) → MAX_DAYS, frac=1 (droite) → 0
              const frac = (mx - PAD.left) / innerW()
              const d    = Math.max(0, Math.min(maxDaysChart1, Math.round((1 - frac) * maxDaysChart1)))
              setHover1({ days: d, x: xFromDays(d, maxDaysChart1), y: yFromProb(normProb(probFromJours(d))) })
            }}
            onMouseLeave={() => setHover1(null)}
          >
            <defs>
              <linearGradient id={`sg1-line-${uid}`} x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%"   stopColor="#5520b8"/>
                <stop offset="50%"  stopColor="#0090e0"/>
                <stop offset="100%" stopColor="#00c8ff"/>
              </linearGradient>
              <linearGradient id={`sg1-area-${uid}`} x1="0%" y1="0%" x2="0%" y2="100%">
                <stop offset="0%"   stopColor="#0090e0" stopOpacity="0.15"/>
                <stop offset="100%" stopColor="#0090e0" stopOpacity="0.01"/>
              </linearGradient>
              <filter id={`sg1-glow-${uid}`}>
                <feGaussianBlur stdDeviation="2" result="b"/>
                <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
            </defs>

            {/* Grille Y (probabilités) */}
            {Y_TICKS.map((p) => {
              const yy = yFromProb(p)
              return (
                <g key={p}>
                  <line x1={PAD.left} y1={yy} x2={W - PAD.right} y2={yy}
                    stroke="rgba(255,255,255,0.05)" strokeWidth="1"
                    strokeDasharray={p === 0 || p === 100 ? '' : '4 4'} />
                  <text x={PAD.left - 6} y={yy} textAnchor="end" dominantBaseline="middle"
                    fontSize="10" fill="rgba(232,232,240,0.35)"
                    fontFamily="Inter, system-ui, sans-serif">
                    {p}%
                  </text>
                </g>
              )
            })}

            {/* Grille X (années — axe inversé : 10a gauche → 0 droite) */}
            {xTicks1.map((ans) => {
              // avec xFromDays inversé : ans=MAX_ANS → gauche, ans=0 → droite
              const xx = xFromDays(ans * 365, maxDaysChart1)
              return (
                <g key={ans}>
                  <line x1={xx} y1={PAD.top} x2={xx} y2={H - PAD.bottom}
                    stroke="rgba(255,255,255,0.05)" strokeWidth="1"
                    strokeDasharray={ans === 0 || ans === maxAnsChart1 ? '' : '4 4'} />
                  <text x={xx} y={H - PAD.bottom + 14} textAnchor="middle"
                    fontSize="10" fill="rgba(232,232,240,0.35)"
                    fontFamily="Inter, system-ui, sans-serif">
                    {ans === 0 ? '0' : `${ans}a`}
                  </text>
                </g>
              )
            })}

            {/* Labels axes */}
            <text x={PAD.left + innerW() / 2} y={H - 4} textAnchor="middle"
              fontSize="10" fill="rgba(232,232,240,0.4)"
              fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.08em">
              TEMPS RESTANT ESTIMÉ
            </text>
            <text x={10} y={PAD.top + innerH() / 2} textAnchor="middle"
              fontSize="10" fill="rgba(232,232,240,0.4)"
              fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.08em"
              transform={`rotate(-90, 10, ${PAD.top + innerH() / 2})`}>
              PROBABILITÉ
            </text>

            {/* Aire + courbe théorique */}
            {(() => {
              // On génère les pts de gauche (MAX_DAYS) vers droite (0) pour suivre l'axe
              const pts = []
              for (let d = maxDaysChart1; d >= 0; d -= 18) {
                pts.push({ x: xFromDays(d, maxDaysChart1), y: yFromProb(normProb(probFromJours(d))) })
              }
              // Premier pt = gauche, bas (MAX_DAYS, 0%) — Dernier pt = droite, haut (0, 100%)
              const lineD = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
              // Aire : fermer vers bas-droite puis Z remonte au premier pt (bas-gauche)
              const areaD = lineD +
                ` L ${(W - PAD.right).toFixed(1)} ${(H - PAD.bottom).toFixed(1)}` +
                ` L ${PAD.left.toFixed(1)} ${(H - PAD.bottom).toFixed(1)} Z`
              return (
                <>
                  <path d={areaD} fill={`url(#sg1-area-${uid})`}/>
                  <path d={lineD} fill="none" stroke={`url(#sg1-line-${uid})`}
                    strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                    style={{ filter: `url(#sg1-glow-${uid})` }}/>
                </>
              )
            })()}

            {/* Point position actuelle sur la courbe théorique */}
            {profil && (() => {
              // Le curseur démarre au bord gauche (0%) et avance uniquement
              // grâce au temps économisé par les décisions réelles.
              const cursorDays = Math.max(0, maxDaysChart1 - tempsGagne)
              const px = xFromDays(cursorDays, maxDaysChart1)
              const py = yFromProb(normProb(probFromJours(cursorDays)))
              return (
                <g>
                  <line x1={px} y1={PAD.top} x2={px} y2={H - PAD.bottom}
                    stroke="rgba(0,200,255,0.2)" strokeWidth="1" strokeDasharray="3 3"/>
                  <circle cx={px} cy={py} r={7}
                    fill="#00c8ff" stroke="#020509" strokeWidth="2"
                    style={{ filter: 'drop-shadow(0 0 8px rgba(0,200,255,0.9))' }}/>
                  <circle cx={px} cy={py} r={3} fill="#020509"/>
                  <text x={px} y={py - 13} textAnchor="middle"
                    fontSize="9" fill="rgba(0,200,255,0.85)"
                    fontFamily="Inter, system-ui, sans-serif"
                    fontWeight="600" letterSpacing="0.06em">
                    MAINTENANT
                  </text>
                </g>
              )
            })()}

            {/* Tooltip survol chart 1 */}
            {hover1 && (() => {
              const rawProb = probFromJours(hover1.days)
              const prob    = normProb(rawProb)
              const duree   = dureeFromProb(rawProb)
              const tipX   = hover1.x > W - PAD.right - 130 ? hover1.x - 130 : hover1.x + 10
              const tipY   = hover1.y < PAD.top + 55 ? hover1.y + 10 : hover1.y - 55
              return (
                <g>
                  <line x1={hover1.x} y1={PAD.top} x2={hover1.x} y2={H - PAD.bottom}
                    stroke="rgba(255,255,255,0.13)" strokeWidth="1" strokeDasharray="3 3"/>
                  <circle cx={hover1.x} cy={hover1.y} r={4} fill="white" opacity={0.8}
                    style={{ filter: 'drop-shadow(0 0 3px white)' }}/>
                  <rect x={tipX} y={tipY} width={122} height={46} rx={6}
                    fill="#13131f" stroke="rgba(64,144,240,0.4)" strokeWidth="1"/>
                  <text x={tipX + 8} y={tipY + 15}
                    fontSize="9" fill="rgba(232,232,240,0.5)"
                    fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.06em">
                    TEMPS : {duree.ligne1}{duree.ligne2 ? ` ${duree.ligne2}` : ''}
                  </text>
                  <text x={tipX + 8} y={tipY + 31}
                    fontSize="12" fontWeight="700" fill="#4090f0"
                    fontFamily="Inter, system-ui, sans-serif">
                    {prob.toFixed(1)} % de réussite
                  </text>
                </g>
              )
            })()}
          </svg>

          {/* Légende chart 1 */}
          <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '2rem', flexWrap: 'wrap' }}>
            <LegendItem colorLine="#4090f0" label="Courbe théorique" />
            <LegendItem colorDot="#00c8ff" label="Position actuelle" />
          </div>

          {/* Séparateur */}
          <div style={{ borderTop: '1px solid var(--border)', marginBottom: '1.5rem' }}/>

          {/* ── Graphique 2 : progression réelle dans le temps ── */}
          <div style={{ marginBottom: '0.6rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
            <span style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.12em', color: '#f87171', textTransform: 'uppercase' }}>
              ◈ Progression réelle depuis le début
            </span>
            <div style={{ display: 'flex', gap: '0.25rem' }}>
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
            />
          )}

          {/* Légende chart 2 */}
          <div style={{ display: 'flex', gap: '1.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
            <LegendItem colorLine="#ef4444" label="Progression réelle" />
          </div>
        </div>

        {/* ── Tableau historique ── */}
        {!loading && decisions.length > 0 && (
          <div className="card" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)' }}>
            <h3 style={{ fontSize: '0.8rem', fontWeight: 700, letterSpacing: '0.1em', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '1rem' }}>
              ◈ Historique des décisions
            </h3>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    {['Question', 'Choix', 'Impact', 'Date', ''].map((h) => (
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
                            title="Supprimer cette décision"
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
            <p>Aucune décision enregistrée pour l'instant.</p>
            <p style={{ fontSize: '0.8rem', marginTop: '0.5rem' }}>Analysez un dilemme pour commencer à alimenter vos statistiques.</p>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Graphique 2 (courbe réelle rouge) ─────────────────────────────────────────
function Chart2({
  uid, profil, histPoints, totalElapsedMs, probActuelle, loading, zoomPeriod = 'max',
}: {
  uid: string
  profil: Profil
  histPoints: { elapsedMs: number; prob: number }[]
  totalElapsedMs: number
  probActuelle: number
  loading: boolean
  zoomPeriod?: '7j' | '30j' | '90j' | 'max'
}) {
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

  // Path de la courbe rouge (utilise zoomedPoints + windowMs)
  const pathD = zoomedPoints.length >= 2
    ? zoomedPoints.map((p, i) => {
        const x = xFromElapsed(p.elapsedMs, windowMs)
        const y = yZoomed(p.prob)
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
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
          <stop offset="0%"   stopColor="#ef4444" stopOpacity="0.15"/>
          <stop offset="100%" stopColor="#ef4444" stopOpacity="0.01"/>
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
        TEMPS ÉCOULÉ DEPUIS LE DÉBUT
      </text>
      <text x={10} y={PAD.top + innerH() / 2} textAnchor="middle"
        fontSize="10" fill="rgba(232,232,240,0.4)"
        fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.08em"
        transform={`rotate(-90, 10, ${PAD.top + innerH() / 2})`}>
        PROBABILITÉ
      </text>

      {/* Aire + courbe rouge */}
      {!loading && areaD && <path d={areaD} fill={`url(#sg2-area-${uid})`}/>}
      {!loading && pathD && (
        <path d={pathD} fill="none" stroke="#ef4444" strokeWidth="2.5"
          strokeLinecap="round" strokeLinejoin="round"
          style={{ filter: `url(#sg2-glow-${uid})` }}/>
      )}

      {/* Points de décision */}
      {/* Point initial */}
            {!loading && zoomedPoints.length > 0 && (() => {
              const first = zoomedPoints[0]
              const fx = xFromElapsed(first.elapsedMs, windowMs)
              const fy = yZoomed(first.prob)
              return (
                <circle cx={fx} cy={fy} r={5}
                  fill="#fca5a5" stroke="#020509" strokeWidth="2"
                  style={{ filter: 'drop-shadow(0 0 4px rgba(239,68,68,0.8))' }}/>
              )
            })()}
            {!loading && zoomedPoints.filter((_, i) => i > 0 && i < zoomedPoints.length - 1).map((hp, i) => {
        const hx = xFromElapsed(hp.elapsedMs, windowMs)
        const hy = yZoomed(hp.prob)
        return (
          <circle key={i} cx={hx} cy={hy} r={5}
            fill="#fca5a5" stroke="#020509" strokeWidth="2"
            style={{ filter: 'drop-shadow(0 0 4px rgba(239,68,68,0.8))' }}/>
        )
      })}

      {/* Point "Maintenant" (extrémité droite) */}
      {!loading && zoomedPoints.length > 0 && (() => {
        const last = zoomedPoints[zoomedPoints.length - 1]
        const px   = xFromElapsed(last.elapsedMs, windowMs)
        const py   = yZoomed(last.prob)
        return (
          <g>
            <circle cx={px} cy={py} r={7}
              fill="#ef4444" stroke="#020509" strokeWidth="2"
              style={{ filter: 'drop-shadow(0 0 8px rgba(239,68,68,0.9))' }}/>
            <circle cx={px} cy={py} r={3} fill="#020509"/>
            <text x={px} y={py - 13} textAnchor="middle"
              fontSize="9" fill="rgba(248,113,113,0.9)"
              fontFamily="Inter, system-ui, sans-serif"
              fontWeight="600" letterSpacing="0.06em">
              MAINTENANT
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
              fill="#13131f" stroke="rgba(239,68,68,0.4)" strokeWidth="1"/>
            <text x={tipX + 8} y={tipY + 15}
              fontSize="9" fill="rgba(232,232,240,0.5)"
              fontFamily="Inter, system-ui, sans-serif" letterSpacing="0.06em">
              T+{timeLabel}
            </text>
            <text x={tipX + 8} y={tipY + 31}
              fontSize="12" fontWeight="700" fill="#f87171"
              fontFamily="Inter, system-ui, sans-serif">
              {hover.prob.toFixed(1)} % de réussite
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

/** Interpolation linéaire de la probabilité pour un instant donné (en ms) */
function interpolateProb(
  points: { elapsedMs: number; prob: number }[],
  ems: number,
): number {
  if (points.length === 0) return 0
  if (points.length === 1) return points[0].prob
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i], b = points[i + 1]
    if (ems >= a.elapsedMs && ems <= b.elapsedMs) {
      const t = (ems - a.elapsedMs) / (b.elapsedMs - a.elapsedMs)
      return a.prob + t * (b.prob - a.prob)
    }
  }
  return points[points.length - 1].prob
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
